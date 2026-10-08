"""Local operator console. One managed worker; read-only replay of retained runs."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from precedent.console.state import reconstruct, safe_child, shot_path
from precedent.worker.events import RUNS, new_run_id, read_events

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "src/precedent/apps/static"
TEMPLATES = Jinja2Templates(directory=Path(__file__).with_name("templates"))


class RunManager:
    def __init__(self, root: Path, apps_url: str, launcher=None):
        self.root, self.apps_url = root.resolve(), apps_url.rstrip("/")
        self.launcher = launcher or subprocess.Popen
        self.processes: dict[str, subprocess.Popen] = {}
        self.lock = asyncio.Lock()

    def active(self, run_id: str) -> bool:
        process = self.processes.get(run_id)
        return process is not None and process.poll() is None

    async def company(self):
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(self.apps_url + "/workspace.json")
                response.raise_for_status()
                data = response.json()
                if not isinstance(data.get("seed"), int) or not data.get("name"):
                    raise ValueError("Invalid company identity")
                return data
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                503, "Company apps unavailable. Start the apps, then reload."
            ) from exc

    async def start(self, request: str, seed: int):
        async with self.lock:
            if any(self.active(run_id) for run_id in self.processes):
                raise HTTPException(
                    409, "Ava is already working. This console supports one active run."
                )
            company = await self.company()
            if company["seed"] != seed:
                raise HTTPException(409, "The company server changed. Reload before starting work.")
            run_id = new_run_id()
            directory = safe_child(self.root, run_id)
            directory.mkdir(parents=True)
            launch = {
                "request": request,
                "seed": seed,
                "company": company,
                "apps_url": self.apps_url,
                "human_answers": True,
            }
            (directory / "launch.json").write_text(json.dumps(launch))
            env = {
                **os.environ,
                "PRECEDENT_APPS_URL": self.apps_url,
                "PRECEDENT_RUN_ID": run_id,
                "PRECEDENT_RUNS_ROOT": str(self.root),
                "PRECEDENT_HUMAN_CHANNEL": "console",
            }
            try:
                with (directory / "process.log").open("ab") as output:
                    process = self.launcher(
                        [
                            sys.executable,
                            "-m",
                            "precedent.cli",
                            "run",
                            "--seed",
                            str(seed),
                            "--task",
                            request,
                        ],
                        cwd=REPO,
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=output,
                        start_new_session=True,
                    )
                self.processes[run_id] = process
            except OSError as exc:
                (directory / "launch-error.txt").write_text(str(exc))
                raise HTTPException(
                    503, "Worker could not start. See the retained launch error."
                ) from exc
            return run_id

    def close(self):
        for process in self.processes.values():
            if process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)


def create_app(root: Path = RUNS, apps_url: str | None = None, launcher=None) -> FastAPI:
    manager = RunManager(
        root, apps_url or os.getenv("PRECEDENT_APPS_URL", "http://localhost:8100"), launcher
    )

    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(manager.close)

    app = FastAPI(title="Precedent", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.manager = manager
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
        return await call_next(request)

    def directory(run_id):
        try:
            path = safe_child(manager.root, run_id)
        except ValueError as exc:
            raise HTTPException(404, "Run not found") from exc
        if not (path / "events.jsonl").exists() and not (path / "launch.json").exists():
            raise HTTPException(404, "Run not found")
        return path

    def state(run_id, at: int | None = None):
        path = directory(run_id)
        events = [e for e in read_events(path / "events.jsonl") if e.run_id == run_id]
        all_events = events
        if at is not None:
            if not any(e.seq == at and e.type == "observation" for e in events):
                raise HTTPException(400, "Choose a recorded observation")
            events = [e for e in events if e.seq <= at]
        data = reconstruct(events, manager.active(run_id) if at is None else False)
        if at is not None:
            data["status"] = "Recorded step"
            data["mode"] = "Replay · saved view" + (
                " · Scripted validation" if data.get("validation") else ""
            )
            data["captures"] = reconstruct(all_events)["captures"]
        launch = (
            json.loads((path / "launch.json").read_text())
            if (path / "launch.json").exists()
            else {}
        )
        data["run_id"] = run_id
        data["company"] = launch.get("company") or data.get("company")
        data["apps_url"] = launch.get("apps_url", manager.apps_url)
        data["can_answer"] = data["can_answer"] and launch.get("human_answers", False)
        if not events and launch:
            data["request"] = launch["request"]
            data["seed"] = launch["seed"]
        for capture in data["captures"] + ([data["capture"]] if data.get("capture") else []):
            name = str(capture.get("screenshot", "")).removeprefix("shots/")
            valid = shot_path(path, name)
            capture["href"] = f"/runs/{run_id}/shots/{name}" if valid else None
        # Independent grading is explicitly separate, never used as worker verification.
        grade = path / "grade.json"
        data["grade"] = json.loads(grade.read_text()) if grade.exists() and at is None else None
        question = data.get("question")
        data["answer_submitted"] = bool(
            at is None
            and question
            and (path / "answers" / f"{question['question_id']}.json").exists()
        )
        if data["answer_submitted"]:
            data["can_answer"] = False
        data["has_receipt_file"] = at is None and (path / "receipt.md").is_file()
        return data

    @app.get("/")
    async def home(request: Request):
        error, company = None, None
        try:
            company = await manager.company()
        except HTTPException as exc:
            error = exc.detail
        runs = []
        if manager.root.exists():
            for path in sorted(manager.root.iterdir(), reverse=True):
                if path.is_dir():
                    try:
                        runs.append(state(path.name))
                    except (HTTPException, ValueError):
                        continue
        runs.sort(key=lambda run: run.get("started_at", ""), reverse=True)
        return TEMPLATES.TemplateResponse(
            request,
            "home.html",
            {
                "company": company,
                "error": error,
                "runs": runs,
                "apps_url": manager.apps_url,
                "busy": any(manager.active(r) for r in manager.processes),
            },
        )

    @app.get("/workspace-status")
    def workspace_status(seed: int):
        candidates = []
        if manager.root.exists():
            for path in sorted(manager.root.iterdir(), reverse=True):
                if not path.is_dir():
                    continue
                try:
                    data = state(path.name)
                except (HTTPException, ValueError):
                    continue
                if data["seed"] == seed and not data.get("validation"):
                    candidates.append(data)
        latest = next(
            (d for d in candidates if manager.active(d["run_id"])),
            candidates[0] if candidates else None,
        )
        return {
            "seed": seed,
            "run": (
                {k: latest[k] for k in ("run_id", "request", "status", "mode")} if latest else None
            ),
        }

    @app.post("/runs")
    async def start(request: Request):
        form = await request.form()
        task = str(form.get("request", "")).strip()
        if not task or len(task) > 8000:
            raise HTTPException(400, "Enter a request of 1 to 8,000 characters.")
        try:
            seed = int(str(form.get("seed")))
        except ValueError as exc:
            raise HTTPException(400, "Invalid company seed") from exc
        run_id = await manager.start(task, seed)
        return RedirectResponse(f"/runs/{run_id}", status_code=303)

    @app.get("/runs/{run_id}")
    def run_page(request: Request, run_id: str):
        return TEMPLATES.TemplateResponse(request, "run.html", {"state": state(run_id)})

    @app.get("/runs/{run_id}/state")
    def run_state(run_id: str, at: int | None = None):
        return state(run_id, at)

    @app.get("/runs/{run_id}/events")
    async def events(request: Request, run_id: str):
        directory(run_id)

        async def stream():
            # Always send a complete reconstruction on reconnect, including process status.
            previous = None
            while not await request.is_disconnected():
                current = state(run_id)
                payload = json.dumps(current, default=str)
                if payload != previous:
                    yield {"id": str(current["last_seq"]), "event": "state", "data": payload}
                    previous = payload
                if not manager.active(run_id):
                    break
                await asyncio.sleep(0.8)

        return EventSourceResponse(stream(), ping=10)

    @app.get("/runs/{run_id}/shots/{name}")
    def shot(run_id: str, name: str):
        path = directory(run_id)
        # Serve only captures referenced by this run's own observation log.
        allowed = {
            str(e.data.get("screenshot", "")).removeprefix("shots/")
            for e in read_events(path / "events.jsonl")
            if e.run_id == run_id and e.type == "observation"
        }
        target = shot_path(path, name) if name in allowed else None
        if target is None:
            raise HTTPException(404, "Capture not found")
        return FileResponse(target, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/runs/{run_id}/answer")
    async def answer(request: Request, run_id: str):
        current = state(run_id)
        if not current["can_answer"]:
            raise HTTPException(409, "This run has no answerable question.")
        form = await request.form()
        question = current["question"]
        key = str(form.get("question_id", ""))
        text = str(form.get("choice") or form.get("answer", "")).strip()
        if key != question["question_id"] or not text or len(text) > 4000:
            raise HTTPException(400, "Answer the current question with 1 to 4,000 characters.")
        if not re_safe_question(key):
            raise HTTPException(400, "Invalid question identifier")
        path = directory(run_id) / "answers"
        path.mkdir(exist_ok=True)
        try:
            with (path / f"{key}.json").open("x") as output:
                json.dump({"question_id": key, "text": text, "by": "human"}, output)
        except FileExistsError as exc:
            raise HTTPException(409, "An answer was already submitted.") from exc
        return RedirectResponse(f"/runs/{run_id}", status_code=303)

    @app.get("/runs/{run_id}/receipt.md")
    def receipt(run_id: str):
        path = directory(run_id) / "receipt.md"
        if path.is_symlink() or not path.is_file():
            raise HTTPException(404, "No evidence receipt available")
        return FileResponse(path, media_type="text/markdown", filename="receipt.md")

    return app


def re_safe_question(key: str) -> bool:
    return key.startswith("q") and key[1:].isdigit()

"""Local operator console. One managed worker; read-only replay of retained runs."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from precedent import companion
from precedent.console.guide import evidence_runs, load_evidence, load_guide
from precedent.console.state import reconstruct, safe_child, shot_path
from precedent.learning.recall import index_entries
from precedent.learning.store import Store, root_for, scope_for
from precedent.worker.events import RUNS, new_run_id, read_events

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "src/precedent/apps/static"
TEMPLATES = Jinja2Templates(directory=Path(__file__).with_name("templates"))
TEMPLATES.env.globals.update(
    ava_dock=companion.dock,
    ava_art=companion.art,
    connections_url=os.getenv("PRECEDENT_CONNECTIONS_URL", "http://localhost:8126"),
)


class RunManager:
    def __init__(self, root: Path, apps_url: str, launcher=None, *, headed: bool = False):
        self.root, self.apps_url = root.resolve(), apps_url.rstrip("/")
        self.headed = headed
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
                "headed": self.headed,
            }
            (directory / "launch.json").write_text(json.dumps(launch))
            env = {
                **os.environ,
                "PRECEDENT_APPS_URL": self.apps_url,
                "PRECEDENT_RUN_ID": run_id,
                "PRECEDENT_RUNS_ROOT": str(self.root),
                "PRECEDENT_HUMAN_CHANNEL": "console",
                "PRECEDENT_WATCH": "1",
            }
            command = [
                sys.executable,
                "-m",
                "precedent.cli",
                "run",
                "--seed",
                str(seed),
                "--task",
                request,
            ]
            if self.headed:
                command.append("--headed")
            try:
                with (directory / "process.log").open("ab") as output:
                    process = self.launcher(
                        command,
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


def create_app(
    root: Path = RUNS, apps_url: str | None = None, launcher=None, *, headed: bool = False
) -> FastAPI:
    manager = RunManager(
        root,
        apps_url or os.getenv("PRECEDENT_APPS_URL", "http://localhost:8100"),
        launcher,
        headed=headed,
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
        data["sandbox"] = any(
            n.get("kind") == "skill_selected" and n.get("validation") for n in data["notes"]
        )
        if data["sandbox"]:
            data["mode"] = "Sandbox trial · " + (
                "Saved evidence" if data["finished"] else "Execution"
            )
        data["company"] = launch.get("company") or data.get("company")
        data["apps_url"] = launch.get("apps_url", manager.apps_url)
        data["headed"] = bool(launch.get("headed", False))
        if data["sandbox"]:
            data["headed"] = manager.headed
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
        if data["finished"] and (data["grade"] or {}).get("overall") == "pass":
            data["status"] = "Completed · independent grade"
        question = data.get("question")
        data["answer_submitted"] = bool(
            at is None
            and question
            and (path / "answers" / f"{question['question_id']}.json").exists()
        )
        if data["answer_submitted"]:
            data["can_answer"] = False
        data["has_receipt_file"] = at is None and (path / "receipt.md").is_file()
        data["tribunal_link"] = True  # every run can be heard, native Google runs included
        data["learning_href"] = "/mind?tab=skills" if data["sandbox"] else "/mind"
        learning_path = path / "learning.json"
        if learning_path.exists() and not data["sandbox"]:
            try:
                learning = json.loads(learning_path.read_text())
                data["learning_href"] = "/mind?entry=" + learning["episode_id"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
        # Link only records actually observed/acknowledged, never a model's invented URL.
        observed = " ".join(
            str(e.data.get("url", ""))
            if e.type == "observation"
            else str(e.data.get("path", ""))
            if e.type == "note" and e.data.get("kind") == "app_effect"
            else str(e.data.get("evidence", ""))
            if e.type == "check"
            else ""
            for e in events
        )
        data["artifacts"] = [
            {"label": f"Bill {key}", "path": f"/books/bills/{key}"}
            for key in dict.fromkeys(re.findall(r"/books/bills/(INV-[A-Za-z0-9_-]+)", observed))
        ][-3:]
        if data["artifacts"]:
            bill_path = data["artifacts"][-1]["path"]
            data["artifacts"].extend(
                [
                    {"label": "Approval routing", "path": bill_path + "#approvals"},
                    {"label": "Attached invoice", "path": bill_path + "#attachment"},
                ]
            )
        native = [
            {
                "label": "Gmail draft" if e.data.get("app") == "gmail" else "Calendar event",
                "href": e.data["link"],
            }
            for e in events
            if e.type == "note"
            and e.data.get("kind") == "native_artifact"
            and str(e.data.get("link", "")).startswith(
                (
                    "https://mail.google.com/",
                    "https://www.google.com/calendar/",
                    "https://calendar.google.com/",
                )
            )
        ]
        if native:  # native Google work: link the real draft and event, not company records
            data["artifacts"] = native
        for event in events:
            if event.type == "note" and event.data.get("kind") == "meeting_artifacts":
                data["artifacts"] = [
                    item
                    for item in event.data.get("artifacts", [])
                    if re.match(
                        r"^/(mail/drafts/draft-[a-f0-9]+|calendar/(events/event-[a-f0-9]+|availability\?))",
                        str(item.get("path", "")),
                    )
                ]
        if data["sandbox"]:
            # Trial records belong to a disposable company, never the reviewer's live one.
            data["artifacts"] = []
        data["companion"] = companion.pose_for(data)
        return data

    async def render_home(request: Request, draft: dict | None = None):
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
                "headed": manager.headed,
                "draft": draft,
            },
        )

    @app.get("/mind")
    async def mind(
        request: Request, tab: str = "memory", q: str = "", entry: str = "", error: str = ""
    ):
        if request.headers.get("x-precedent-agent"):
            raise HTTPException(404)
        company, entries, selected, all_entries = None, [], None, []
        try:
            company = await manager.company()
            store = Store(root_for(manager.root))
            scope = scope_for(company)
            all_entries = store.list(scope)
            entries = [
                item
                for item in store.list(scope, q[:200])
                if (item["kind"] == "skill") == (tab == "skills")
            ]
            entries.sort(key=lambda item: item["kind"] != "episode")
            if entry:
                selected = store.get(scope, entry)
            elif entries:
                selected = entries[0]
        except KeyError as exc:
            raise HTTPException(404, "Learning not found in this workspace") from exc
        except Exception:
            error = "Learning is unavailable right now. Your tasks remain available."
        return TEMPLATES.TemplateResponse(
            request,
            "mind.html",
            {
                "company": company,
                "apps_url": manager.apps_url,
                "entries": entries,
                "selected": selected,
                "tab": tab,
                "query": q[:200],
                "error": error[:300],
                "validating": any(i["status"] == "validating" for i in all_entries),
                "counts": {
                    "memory": sum(i["kind"] != "skill" for i in all_entries),
                    "skills": sum(i["kind"] == "skill" for i in all_entries),
                },
            },
        )

    @app.post("/mind/{entry_id}/{action}")
    async def mind_action(request: Request, entry_id: str, action: str):
        if request.headers.get("x-precedent-agent"):
            raise HTTPException(403)
        company = await manager.company()
        scope = scope_for(company)
        store = Store(root_for(manager.root))
        try:
            item = store.get(scope, entry_id)
            if action == "draft":
                item = store.draft_skill(scope, entry_id)
            elif action == "activate":
                item = store.activate(scope, entry_id)
            elif action == "deactivate" and item["kind"] == "skill":
                item = store.revise(scope, entry_id, status="inactive")
            elif action == "archive" and item["kind"] != "skill":
                item = store.revise(scope, entry_id, status="archived")
            elif action == "correct" and item["kind"] != "skill":
                form = await request.form()
                correction = str(form.get("correction", "")).strip()
                if not correction:
                    raise ValueError("Write a correction first")
                item = store.revise(scope, entry_id, correction=correction)
            elif action == "validate" and item["kind"] == "skill":
                async with manager.lock:
                    if any(manager.active(r) for r in manager.processes):
                        raise ValueError(
                            "Let the current task finish before starting a sandbox trial"
                        )
                    if item["payload"].get("missing_coverage") or item["status"] not in (
                        "draft",
                        "validation_failed",
                        "inactive",
                    ):
                        raise ValueError("This skill is not ready for validation")
                    run_id = new_run_id()
                    run_dir = safe_child(manager.root, run_id)
                    run_dir.mkdir(parents=True)
                    payload = {**item["payload"], "validation": None, "validation_run_id": run_id}
                    item = store.revise(scope, entry_id, status="validating", payload=payload)
                    command = [
                        sys.executable,
                        "-m",
                        "precedent.learning.validate",
                        "--root",
                        str(store.root),
                        "--scope",
                        scope,
                        "--skill",
                        entry_id,
                        "--runs",
                        str(manager.root),
                        "--run-id",
                        run_id,
                        "--seed",
                        str(company["seed"]),
                        "--template",
                        company["template"],
                    ]
                    if manager.headed:
                        command.append("--headed")
                    try:
                        with (run_dir / "process.log").open("ab") as output:
                            manager.processes[run_id] = manager.launcher(
                                command,
                                cwd=REPO,
                                env=os.environ.copy(),
                                stdin=subprocess.DEVNULL,
                                stdout=output,
                                stderr=output,
                                start_new_session=True,
                            )
                    except OSError:
                        store.revise(scope, entry_id, status="validation_failed")
                        raise
            else:
                raise ValueError("That action is unavailable")
        except KeyError as exc:
            raise HTTPException(404, "Learning not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        # Archived/corrected entries are excluded by registry status even if an index is stale.
        if item["kind"] != "skill":
            try:
                await index_entries(store, scope, [item])
            except Exception:
                pass
        return RedirectResponse(
            "/mind?tab="
            + ("skills" if item["kind"] == "skill" else "memory")
            + "&entry="
            + item["id"],
            status_code=303,
        )

    @app.get("/")
    async def home(request: Request):
        return await render_home(request)

    @app.get("/compose")
    async def compose(request: Request, handoff: str = ""):
        """Open a draft Ava's companion handed over from the company apps. The draft is
        fetched server-to-server from this console's own configured company URL, bound to
        that company's identity, and only prefills the composer: nothing is assigned."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", handoff):
            return await render_home(request, {"error": "That draft link is not valid."})
        try:
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                response = await client.get(f"{manager.apps_url}/ava/handoff/{handoff}")
            entry = response.json() if response.status_code == 200 else None
            current = await manager.company()
        except (httpx.HTTPError, ValueError, HTTPException):
            return await render_home(
                request,
                {"error": "The company apps are unavailable, so the draft could not be read."},
            )
        if not entry or not isinstance(entry.get("text"), str):
            return await render_home(
                request, {"error": "That draft was already opened or has expired."}
            )
        if not entry.get("instance_id") or entry.get("instance_id") != current.get("instance_id"):
            return await render_home(
                request,
                {"error": "That draft came from a different company than this workspace serves."},
            )
        return await render_home(
            request,
            {
                "text": entry["text"][:2000],
                "context": companion.clean_context(entry.get("context")),
            },
        )

    @app.get("/guide")
    def guide(request: Request):
        active = next((r for r in manager.processes if manager.active(r)), None)
        evidence = load_evidence()
        installed = set()
        for run_id in evidence_runs(evidence):
            with contextlib.suppress(HTTPException):
                directory(run_id)
                installed.add(run_id)
        proof = None
        with contextlib.suppress(HTTPException, ValueError, KeyError):
            proof = state(evidence["hero"]["run_id"])
        return TEMPLATES.TemplateResponse(
            request,
            "guide.html",
            {
                "guide": load_guide(STATIC),
                "evidence": evidence,
                "installed": installed,
                "active_url": f"/runs/{active}" if active else None,
                "apps_url": manager.apps_url,
                "proof": proof,
                "asset_version": max(
                    int((STATIC / name).stat().st_mtime)
                    for name in ("guide.css", "guide.js", "loki/loki.css")
                ),
            },
        )

    @app.get("/guide/research")
    def guide_research():
        return FileResponse(
            REPO / "docs/memory_skills_research.md", media_type="text/plain; charset=utf-8"
        )

    @app.get("/watch")
    def watch(request: Request):
        return TEMPLATES.TemplateResponse(request, "watch.html", {"apps_url": manager.apps_url})

    @app.get("/watch/state")
    def watch_state():
        # Follow this console's managed task, never an unrelated run or old replay.
        for run_id in list(manager.processes):
            if manager.active(run_id):
                current = state(run_id)
                if not current["finished"]:
                    return JSONResponse(
                        {
                            "run_url": f"/runs/{run_id}",
                            "request": current["request"],
                            "status": current["status"],
                            "companion": current["companion"],
                        },
                        headers={"Cache-Control": "no-store"},
                    )
        return JSONResponse({"run_url": None}, headers={"Cache-Control": "no-store"})

    @app.get("/workspace-status")
    def workspace_status(seed: int, instance_id: str | None = None):
        candidates = []
        if manager.root.exists():
            for path in sorted(manager.root.iterdir(), reverse=True):
                if not path.is_dir():
                    continue
                try:
                    data = state(path.name)
                except (HTTPException, ValueError):
                    continue
                identity = (data.get("company") or {}).get("instance_id")
                # A seed alone does not identify a company; bind to the instance when known.
                if instance_id and identity != instance_id:
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
                {
                    **{k: latest[k] for k in ("run_id", "request", "status", "mode", "companion")},
                    "active": manager.active(latest["run_id"]) and not latest["finished"],
                    "run_url": f"/runs/{latest['run_id']}",
                }
                if latest
                else None
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

    @app.get("/runs/{run_id}/workspace")
    def live_workspace(request: Request, run_id: str):
        return TEMPLATES.TemplateResponse(request, "live.html", {"state": state(run_id)})

    @app.get("/runs/{run_id}/screen")
    async def live_screen(run_id: str):
        current = state(run_id)
        if not manager.active(run_id) or current["finished"] or not current.get("screen"):
            raise HTTPException(409, "This run has no active browser stream.")
        # The stream source comes only from this managed run, never a request parameter.
        source = urlsplit(current["screen"])
        if (
            source.scheme != "http"
            or source.hostname != "127.0.0.1"
            or source.path != "/screen.mjpg"
            or not source.port
            or source.username
            or source.password
            or source.query
            or source.fragment
        ):
            raise HTTPException(502, "Invalid browser stream endpoint.")
        client = httpx.AsyncClient(timeout=httpx.Timeout(10, connect=3), trust_env=False)
        try:
            response = await client.send(
                client.build_request("GET", current["screen"]), stream=True
            )
        except httpx.HTTPError as exc:
            await client.aclose()
            raise HTTPException(503, "Browser stream is reconnecting.") from exc
        content_type = response.headers.get("content-type", "")
        if response.status_code != 200 or not content_type.startswith("multipart/x-mixed-replace;"):
            await response.aclose()
            await client.aclose()
            raise HTTPException(503, "Browser stream is unavailable.")

        async def frames():
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            except httpx.HTTPError:
                return  # The viewer reconnects; never substitute saved captures.
            finally:
                await response.aclose()
                await client.aclose()

        return StreamingResponse(
            frames(),
            headers={
                "Content-Type": content_type,
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/runs/{run_id}/state")
    def run_state(run_id: str, at: int | None = None):
        return state(run_id, at)

    @app.post("/runs/{run_id}/focus")
    async def focus_browser(run_id: str):
        current = state(run_id)
        if not manager.active(run_id) or current["finished"] or not current["headed"]:
            raise HTTPException(409, "This task has no active native browser.")
        source = urlsplit(current.get("browser_focus") or "")
        if (
            source.scheme != "http"
            or source.hostname != "127.0.0.1"
            or not source.port
            or not source.path.startswith("/focus/")
            or source.username
            or source.password
            or source.query
            or source.fragment
        ):
            raise HTTPException(409, "Ava’s browser is still starting or is unavailable.")
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                response = await client.post(current["browser_focus"])
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(
                503, "The browser is unavailable. Follow the task here for updates."
            ) from exc
        return {"focused": True}

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

    # ------------------------------------------------------------- Teach Ava
    def teach_scope():
        from precedent.learning import teach

        return teach, root_for(manager.root)

    async def demonstration(demo_id: str):
        teach, learning = teach_scope()
        company = await manager.company()
        try:
            path = teach.directory(learning, demo_id)
        except KeyError as exc:
            raise HTTPException(404, "Demonstration not found") from exc
        meta = teach.read_meta(path)
        if meta.get("scope") != scope_for(company):
            raise HTTPException(404, "Demonstration not found in this workspace")
        return teach, path, meta, company

    @app.get("/teach")
    async def teach_home(request: Request, error: str = ""):
        teach, learning = teach_scope()
        company = await manager.company()
        scope = scope_for(company)
        demos = []
        for path in sorted(teach.root(learning).iterdir(), reverse=True):
            try:
                meta = teach.read_meta(path)
            except (OSError, ValueError):
                continue
            if meta.get("scope") == scope:
                demos.append(meta)
        demos.sort(key=lambda m: m.get("created", ""), reverse=True)
        return TEMPLATES.TemplateResponse(
            request,
            "teach.html",
            {
                "company": company,
                "apps_url": manager.apps_url,
                "demos": demos[:20],
                "error": error[:300],
            },  # fmt: skip
        )

    @app.post("/teach")
    async def teach_upload(request: Request):
        import tempfile

        teach, learning = teach_scope()
        company = await manager.company()
        form = await request.form()
        title = str(form.get("title", "")).strip()
        procedure = str(form.get("procedure", "")).strip()
        upload = form.get("video")
        has_video = bool(getattr(upload, "filename", ""))
        if not title or (not has_video and not procedure):
            return RedirectResponse("/teach?error=Give+a+title+and+a+recording+or+procedure", 303)
        try:
            if has_video:
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    size = 0
                    while chunk := await upload.read(1 << 20):
                        size += len(chunk)
                        if size > 300 * (1 << 20):
                            raise ValueError("Keep recordings under 300 MB")
                        tmp.write(chunk)
                meta = teach.create(learning, scope_for(company), title, video=Path(tmp.name),
                                    filename=upload.filename)  # fmt: skip
            else:
                meta = teach.create(learning, scope_for(company), title, procedure=procedure)
        except ValueError as exc:
            return RedirectResponse(f"/teach?error={quote(str(exc))}", 303)
        teach.start(teach.directory(learning, meta["id"]), manager.apps_url)
        return RedirectResponse(f"/teach/{meta['id']}", 303)

    @app.get("/teach/{demo_id}")
    async def teach_watch(request: Request, demo_id: str):
        teach, path, meta, company = await demonstration(demo_id)
        return TEMPLATES.TemplateResponse(
            request,
            "teach_watch.html",
            {
                "company": company,
                "apps_url": manager.apps_url,
                "meta": meta,
                "asset_version": int((STATIC / "teach" / "teach.js").stat().st_mtime),
            },  # fmt: skip
        )

    @app.get("/teach/{demo_id}/state")
    async def teach_state(demo_id: str):
        teach, path, meta, _ = await demonstration(demo_id)
        skill = (path / "SKILL.md").read_text() if (path / "SKILL.md").is_file() else None
        return {"meta": meta, "notes": teach.read_notes(path), "skill_md": skill}

    @app.get("/teach/{demo_id}/video")
    async def teach_video(demo_id: str):
        teach, path, meta, _ = await demonstration(demo_id)
        name = meta.get("original")
        target = path / name if name else None
        if target is None or target.is_symlink() or not target.is_file():
            raise HTTPException(404, "No recording")
        media = teach.VIDEO_TYPES.get(target.suffix.lower(), "application/octet-stream")
        return FileResponse(target, media_type=media)

    @app.get("/teach/{demo_id}/frames/{name}")
    async def teach_frame(demo_id: str, name: str):
        teach, path, _, _ = await demonstration(demo_id)
        if not re.fullmatch(r"step-\d{2,3}\.jpg", name):
            raise HTTPException(404, "Frame not found")
        target = path / "frames" / name
        if target.is_symlink() or not target.is_file():
            raise HTTPException(404, "Frame not found")
        return FileResponse(target, media_type="image/jpeg")

    @app.post("/teach/{demo_id}/save")
    async def teach_save(request: Request, demo_id: str):
        teach, path, meta, company = await demonstration(demo_id)
        form = await request.form()
        try:
            item = teach.save_skill(Store(root_for(manager.root)), scope_for(company), path,
                                    str(form.get("trial_request", "")))  # fmt: skip
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f"/mind?tab=skills&entry={item['id']}", 303)

    # ------------------------------------------------------------- the Tribunal
    hearings: dict[str, threading.Thread] = {}
    hearings_lock = threading.Lock()

    def hearing(run_id: str) -> bool:
        thread = hearings.get(run_id)
        return thread is not None and thread.is_alive()

    @app.get("/runs/{run_id}/tribunal")
    def tribunal_page(request: Request, run_id: str):
        current = state(run_id)
        return TEMPLATES.TemplateResponse(
            request,
            "tribunal.html",
            {
                "run_id": run_id,
                "task": current.get("request", ""),
                "company": (current.get("company") or {}).get("name"),
                "apps_url": current.get("apps_url") or manager.apps_url,
                "finished": bool(current["finished"]) and not manager.active(run_id),
                "asset_version": max(
                    int((STATIC / name).stat().st_mtime)
                    for name in ("tribunal/tribunal.css", "tribunal/tribunal.js", "loki/loki.css")
                ),
            },
        )

    @app.get("/runs/{run_id}/tribunal/state")
    def tribunal_state(run_id: str, before: bool = False):
        from precedent.tribunal.court import read_record

        # While Ava's run is active the in-run hearing (and any remand) may still be writing.
        live = hearing(run_id) or manager.active(run_id)
        path = directory(run_id)
        # The grader may run after the hearing; show its current result, kept separate.
        grade = None
        if (path / "grade.json").is_file():
            try:
                grade = json.loads((path / "grade.json").read_text()).get("overall")
            except (OSError, ValueError, AttributeError):
                grade = None
        # Ava's own verification and any remand, from her run log (shown, never used to rule).
        checks, remanded, claims = {}, [], {}
        for event in read_events(path / "events.jsonl"):
            if event.run_id != run_id:
                continue
            if event.type == "check":
                checks[str(event.data.get("condition_id"))] = event.data.get("result")
            elif event.type == "note" and event.data.get("kind") == "goal_progress":
                claims[str(event.data.get("condition_id"))] = event.data.get("evidence")
            elif event.type == "note" and event.data.get("kind") == "remand":
                remanded = list(event.data.get("charges") or [])
        ava = {k: list(checks.values()).count(k) for k in ("pass", "fail", "unknown")}
        return {
            # The first hearing of a remanded run is kept; it shows the branches as caught.
            "events": read_record(path, "tribunal-before-remand" if before else "tribunal"),
            "has_before": (path / "tribunal-before-remand" / "events.jsonl").is_file(),
            "hearing": live,
            "grade": grade,
            "ava": ava,
            "remanded": remanded,
            "claims": claims,
        }

    @app.post("/runs/{run_id}/tribunal")
    def convene_tribunal(run_id: str):
        from precedent.tribunal.court import convene

        path = directory(run_id)
        current = state(run_id)
        if not current["finished"] or manager.active(run_id):
            raise HTTPException(409, "The Tribunal hears a task once Ava has finished it.")
        with hearings_lock:
            if any(hearing(r) for r in hearings):
                raise HTTPException(409, "The Tribunal is already in session.")
            apps_url = current.get("apps_url") or manager.apps_url
            thread = threading.Thread(
                target=convene, args=(path,), kwargs={"apps_url": apps_url}, daemon=True
            )
            hearings[run_id] = thread
            thread.start()
        return {"convened": True}

    @app.get("/runs/{run_id}/tribunal/exhibits/{name}")
    def tribunal_exhibit(run_id: str, name: str, before: bool = False):
        if not re.fullmatch(r"E\d{1,3}\.png", name):
            raise HTTPException(404, "Exhibit not found")
        folder = "tribunal-before-remand" if before else "tribunal"
        target = directory(run_id) / folder / name
        if target.is_symlink() or not target.is_file():
            raise HTTPException(404, "Exhibit not found")
        return FileResponse(target, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/runs/{run_id}/receipt.md")
    def receipt(run_id: str):
        path = directory(run_id) / "receipt.md"
        if path.is_symlink() or not path.is_file():
            raise HTTPException(404, "No evidence receipt available")
        return FileResponse(path, media_type="text/markdown", filename="receipt.md")

    return app


def re_safe_question(key: str) -> bool:
    return key.startswith("q") and key[1:].isdigit()

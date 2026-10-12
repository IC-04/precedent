"""Local owner UI plus a separately exposable OAuth callback-only application."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from precedent import companion
from precedent.connected.google import GoogleService, event_authorized
from precedent.connected.providers import GOOGLE_SCOPES, ProviderError, Providers
from precedent.connected.service import Service
from precedent.connected.store import Vault

COOKIE = "precedent_connected_owner"
REPO = Path(__file__).resolve().parents[3]
TEMPLATES = Jinja2Templates(directory=REPO / "src/precedent/apps/templates")
TEMPLATES.env.globals.update(ava_art=companion.art, ava_dock=companion.dock)


def configuration():
    config = {
        provider: {
            key: os.getenv(f"PRECEDENT_{prefix}_{env}", "")
            for key, env in (
                ("client_id", "CLIENT_ID"),
                ("client_secret", "CLIENT_SECRET"),
                ("redirect_uri", "REDIRECT_URI"),
            )
        }
        for provider, prefix in (("gmail", "GMAIL"), ("slack", "SLACK"))
    }
    credential_file = Path(
        os.getenv(
            "PRECEDENT_GOOGLE_CLIENT_FILE",
            str(Path.home() / ".local/share/precedent/google-oauth.json"),
        )
    ).expanduser()
    if credential_file.exists():
        if credential_file.stat().st_mode & 0o077:
            raise ValueError("Google client file must have 0600 permissions")
        raw = json.loads(credential_file.read_text())
        client = raw.get("web", {})
        if not client:
            raise ValueError("This local web workspace requires a Web application OAuth client")
        config["gmail"].update(
            client_id=client["client_id"],
            client_secret=client["client_secret"],
            redirect_uri=os.getenv("PRECEDENT_GOOGLE_REDIRECT_URI", client["redirect_uris"][0]),
        )
    for key in ("client_id", "client_secret", "redirect_uri"):
        value = os.getenv("PRECEDENT_GOOGLE_" + key.upper())
        if value:
            config["gmail"][key] = value
    config["gmail"]["scope"] = " ".join(sorted(GOOGLE_SCOPES))
    return config


def make_service(root: Path | None = None):
    root = root or Path(os.getenv("PRECEDENT_CONNECTED_ROOT", ".connected"))
    key = Path(
        os.getenv(
            "PRECEDENT_CONNECTED_KEY_FILE",
            str(Path.home() / ".local/share/precedent/connected.key"),
        )
    )
    return GoogleService(Vault(root, key), Providers(configuration()))


def callback_app(service: Service):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/oauth/{provider}/callback", response_class=HTMLResponse)
    async def callback(request: Request, provider: str):
        if provider not in ("gmail", "slack"):
            raise HTTPException(404)
        try:
            await service.callback(
                provider,
                request.query_params.get("state", ""),
                request.query_params.get("code", ""),
                bool(request.query_params.get("error")),
            )
            message = "Account connected. Return to the Precedent window and choose your sources."
        except (ValueError, ProviderError) as exc:
            message = str(exc)
        # No code/state/token is echoed, including in the redirect destination.
        from html import escape

        return HTMLResponse(
            "<!doctype html><title>Precedent authorization</title>"
            "<meta name='referrer' content='no-referrer'>"
            "<script>history.replaceState(null,'','/oauth/complete')</script>"
            "<h1>Precedent</h1><p>" + escape(message) + "</p>",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    return app


def create_app(service: Service | None = None, *, base_url="http://localhost:8250"):
    service = service or make_service()
    vault = service.vault
    processes: dict = {}
    run_lock = asyncio.Lock()
    runs_root = vault.root / "runs"
    runs_root.mkdir(exist_ok=True, mode=0o700)

    def purge_expired_evidence():
        import shutil

        for directory in runs_root.iterdir():
            if not directory.is_dir():
                continue
            meta = vault.get("run:" + directory.name)
            if meta and meta.get("expires", 0) < time.time():
                shutil.rmtree(directory)
                vault.delete("run:" + directory.name)

    purge_expired_evidence()

    @asynccontextmanager
    async def lifespan(app):
        async def retention():
            while True:
                await asyncio.sleep(300)
                purge_expired_evidence()

        retention_task = asyncio.create_task(retention())
        yield
        retention_task.cancel()
        for process in processes.values():
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        await service.providers.client.aclose()

    app = FastAPI(
        title="Precedent connected workspace",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.service, app.state.processes = service, processes
    app.mount("/static", StaticFiles(directory=REPO / "src/precedent/apps/static"), name="static")

    def render(request, page="connections", **ctx):
        return TEMPLATES.TemplateResponse(
            request,
            "connected/google.html"
            if isinstance(service, GoogleService)
            else "connected/workspace.html",
            dict(
                page=page,
                connections=service.public_connections(),
                workspace=vault.identity(),
                agent=bool(request.state.worker or request.headers.get("x-precedent-agent")),
                error="",
                notice="",
                csrf_token=hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest(),
                google_mode=isinstance(service, GoogleService),
                guide_url=os.getenv("PRECEDENT_PROJECT_GUIDE_URL", ""),
                account={
                    k: v
                    for k, v in (vault.get("connection:gmail") or {}).items()
                    if k in ("label", "email", "status", "selection", "calendar_id")
                },
                capabilities=service.capabilities() if isinstance(service, GoogleService) else [],
            )
            | ctx,
        )

    def stop_runs():
        for process in processes.values():
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)

    @app.middleware("http")
    async def owner_boundary(request, call_next):
        path = request.url.path
        owner = vault.authenticated(request.cookies.get(COOKIE))
        token = request.headers.get("x-precedent-connected", "")
        grant = vault.get("worker:" + hashlib.sha256(token.encode()).hexdigest()) if token else None
        worker = bool(
            grant and grant["expires"] > time.time() and grant["workspace"] == vault.identity()
        )
        request.state.worker = worker
        request.state.worker_grant = grant if worker else None
        public = path.startswith("/static/") or path == "/unlock"
        if not public and not (owner or worker):
            return HTMLResponse(
                "<h1>Open your connected workspace</h1>"
                "<p>Use the local launcher to open an owner session.</p>",
                401,
            )
        if worker and not (
            path in ("/", "/workspace.json", "/workspace", "/artifacts", "/artifacts/new")
            or path.startswith(
                ("/sources", "/artifacts/", "/static/", "/mail", "/calendar", "/native/")
            )
        ):
            return HTMLResponse("Not available to Ava", 403)
        if request.method == "POST" and not worker:
            if (
                request.headers.get("origin") != base_url
                or request.headers.get("sec-fetch-site") == "cross-site"
            ):
                return HTMLResponse("Cross-origin action refused", 403)
            await request.body()
            form = await request.form()
            csrf = request.cookies.get(COOKIE, "")
            if not csrf or not secrets.compare_digest(
                str(form.get("csrf", "")), hashlib.sha256(csrf.encode()).hexdigest()
            ):
                return HTMLResponse("Owner action expired. Reload this page.", 403)
        from precedent.connected.google import ACTIVITY

        activity_token = ACTIVITY.set(
            runs_root / grant["run_id"] / "provider-activity.jsonl"
            if worker and grant.get("run_id") and (runs_root / grant["run_id"]).is_dir()
            else None
        )
        try:
            response = await call_next(request)
        finally:
            ACTIVITY.reset(activity_token)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(ProviderError)
    async def provider_failure(request: Request, exc: ProviderError):
        response = render(request, "workspace", artifacts=service.artifacts(), error=str(exc))
        response.status_code = 409 if exc.reconnect else 503
        return response

    @app.get("/unlock")
    def unlock(ticket: str = ""):
        if not vault.consume("ticket:" + ticket):
            raise HTTPException(403, "This opening link expired or was already used.")
        response = RedirectResponse("/connections", 303)
        response.set_cookie(
            COOKIE,
            vault.get("owner")["session"],
            httponly=True,
            samesite="lax",
            secure=base_url.startswith("https://"),
            max_age=86400,
        )
        return response

    @app.get("/")
    def home(request: Request):
        return RedirectResponse("/workspace" if request.state.worker else "/connections", 303)

    @app.get("/connections")
    async def connections(request: Request):
        return render(request)

    @app.get("/setup")
    def setup(request: Request):
        return render(request, "setup")

    @app.post("/connections/{provider}/{action}")
    async def connection_action(request: Request, provider: str, action: str):
        if provider not in ("gmail", "slack"):
            raise HTTPException(404)
        try:
            if action == "connect":
                if provider == "gmail" and isinstance(service, GoogleService):
                    form = await request.form()
                    return RedirectResponse(
                        service.begin_google(request.cookies[COOKIE], form.getlist("features")), 303
                    )
                return RedirectResponse(service.begin(provider, request.cookies[COOKIE]), 303)
            if action == "disconnect":
                stop_runs()
                notice = await service.disconnect(provider)
                return render(request, notice=notice)
            if action == "refresh":
                await service.fetch(provider, fresh=True)
                return RedirectResponse("/sources/" + provider, 303)
            if action == "select":
                form = await request.form()
                stop_runs()
                if isinstance(service, GoogleService):
                    await service.select(
                        provider,
                        form.getlist("ids"),
                        int(form.get("days", "3")),
                        str(form.get("subject", "")),
                    )
                else:
                    await service.select(provider, form.getlist("ids"), int(form.get("days", "3")))
                return RedirectResponse("/connections", 303)
        except (ProviderError, ValueError) as exc:
            return render(request, error=str(exc))
        raise HTTPException(404)

    @app.get("/connections/{provider}/select")
    async def selection(request: Request, provider: str):
        if provider not in ("gmail", "slack"):
            raise HTTPException(404)
        try:
            grant = await service.grant(provider)
            choices = await service.providers.choices(provider, grant["token"]["access_token"])
            return render(request, "selection", provider=provider, choices=choices, grant=grant)
        except ProviderError as exc:
            return render(request, error=str(exc))

    @app.post("/forget")
    def forget():
        stop_runs()
        service.forget()
        # This directory is exclusively connected-run evidence, never the existing demo runs.
        import shutil

        for path in runs_root.iterdir():
            if path.is_dir():
                shutil.rmtree(path)
        return RedirectResponse("/connections", 303)

    @app.get("/workspace.json")
    def identity():
        if isinstance(service, GoogleService):
            grant = vault.get("connection:gmail") or {}
            from zoneinfo import ZoneInfo

            zone = grant.get("calendar_timezone", "UTC")
            return dict(
                mode="connected",
                connector="google",
                name="Google workspace",
                instance_id=vault.identity(),
                memory_id=service.stable_id(),
                generated=False,
                date=datetime.now(ZoneInfo(zone)).isoformat(),
                timezone=zone,
                capabilities=service.capabilities(),
                inference=["Google Vertex AI"],
                ready=bool(grant.get("selection") or grant.get("calendar_id")),
            )
        return dict(
            mode="connected",
            name="Connected workspace",
            instance_id=vault.identity(),
            generated=False,
            date=datetime.now(UTC).isoformat(),
            capabilities=["contextual_preparation"],
            inference=["Google Vertex AI"],
            ready=all(c["status"] == "Ready" for c in service.public_connections()),
        )

    @app.get("/workspace")
    def workspace(request: Request):
        return render(request, "workspace", artifacts=service.artifacts())

    @app.get("/sources/{provider}")
    async def sources(request: Request, provider: str):
        if provider not in ("gmail", "slack"):
            raise HTTPException(404)
        try:
            result = await service.fetch(provider)
            return render(request, "sources", provider=provider, result=result)
        except ProviderError as exc:
            return render(request, "workspace", artifacts=service.artifacts(), error=str(exc))

    @app.get("/sources/{provider}/{source_id}")
    async def source_detail(request: Request, provider: str, source_id: str):
        if provider not in ("gmail", "slack"):
            raise HTTPException(404)
        result = await service.fetch(provider)
        item = next((s for s in result["sources"] if s["id"] == source_id), None)
        if not item:
            raise HTTPException(404, "This source is outside the selection or no longer available.")
        return render(request, "source", item=item, result=result)

    @app.get("/artifacts")
    def artifacts(request: Request):
        return render(request, "workspace", artifacts=service.artifacts())

    @app.get("/artifacts/new")
    async def new(request: Request):
        return render(request, "editor", artifact={}, sources=await service.sources())

    @app.get("/artifacts/{artifact_id}")
    async def artifact(request: Request, artifact_id: str):
        item = next((a for a in service.artifacts() if a["id"] == artifact_id), None)
        if not item:
            raise HTTPException(404)
        return render(request, "artifact", artifact=item)

    @app.get("/artifacts/{artifact_id}/edit")
    async def edit(request: Request, artifact_id: str):
        item = next((a for a in service.artifacts() if a["id"] == artifact_id), None)
        if not item:
            raise HTTPException(404)
        return render(request, "editor", artifact=item, sources=await service.sources())

    @app.post("/artifacts/save")
    async def save(request: Request):
        if isinstance(service, GoogleService):
            raise HTTPException(404, "Use the Gmail draft form for native Google work.")
        try:
            item = await service.save(
                dict(await request.form()), "ava" if request.state.worker else "owner"
            )
            return RedirectResponse("/artifacts/" + item, 303)
        except (ValueError, ProviderError) as exc:
            return render(request, "workspace", artifacts=service.artifacts(), error=str(exc))

    @app.get("/artifacts/{artifact_id}/proof")
    async def proof(request: Request, artifact_id: str):
        item = next((a for a in service.artifacts() if a["id"] == artifact_id), None)
        if not item:
            raise HTTPException(404)
        sources = {s["id"]: s for s in await service.sources(fresh=True)}
        cited = [sources.get(s["id"]) for s in item["sources"]]
        unchanged = all(
            s and s["version"] == old["version"] and s["account"] == old["account"]
            for s, old in zip(cited, item["sources"], strict=True)
        )
        return dict(
            artifact=item,
            sources=cited,
            unchanged=unchanged,
            coverage_complete=all(r["complete"] for r in service.cache.values()),
            workspace=vault.identity(),
        )

    @app.post("/runs")
    async def start(request: Request):
        async with run_lock:
            if any(p.poll() is None for p in processes.values()):
                raise HTTPException(409, "Ava is already working.")
            if not identity()["ready"]:
                raise HTTPException(409, "Connect your account and choose task access first.")
            form = await request.form()
            task = str(form.get("task", "")).strip()
            if not task or len(task) > 2000 or form.get("consent") != "yes":
                raise HTTPException(400, "Enter a task and confirm test-data processing.")
            from precedent.worker.events import new_run_id

            run_id, token = new_run_id(), secrets.token_urlsafe(32)
            binding = vault.identity()
            vault.put(
                "worker:" + hashlib.sha256(token.encode()).hexdigest(),
                dict(
                    workspace=binding,
                    expires=time.time() + 1800,
                    request=task,
                    run_id=run_id,
                    allow_event=event_authorized(task),
                ),
            )
            directory = runs_root / run_id
            directory.mkdir(mode=0o700)
            env = {
                **os.environ,
                "PRECEDENT_APPS_URL": base_url,
                "PRECEDENT_CONNECTED_TOKEN": token,
                "PRECEDENT_CONNECTED_MODE": "1",
                "PRECEDENT_RUNS_ROOT": str(runs_root),
                "PRECEDENT_RUN_ID": run_id,
                "PRECEDENT_HUMAN_CHANNEL": "console",
                "PRECEDENT_WATCH": "0",
                "PRECEDENT_TRIBUNAL": "0",
                "PRECEDENT_SCREENING": "0",
            }
            with (directory / "process.log").open("ab") as output:
                process = subprocess.Popen(
                    [sys.executable, "-m", "precedent.cli", "run", "--task", task, "--headed"],
                    cwd=REPO,
                    env=env,
                    stdout=output,
                    stderr=output,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
            processes[run_id] = process
            vault.put(
                "run:" + run_id,
                dict(id=run_id, workspace=binding, task=task, expires=time.time() + 86400),
            )
            return RedirectResponse("/runs/" + run_id, 303)

    def run_directory(run_id):
        if not __import__("re").fullmatch(r"[0-9]{8}-[0-9]{6}-[a-z0-9]+", run_id):
            raise HTTPException(404)
        meta = vault.get("run:" + run_id)
        if not meta or meta["workspace"] != vault.identity() or meta["expires"] < time.time():
            raise HTTPException(404)
        return runs_root / run_id, meta

    @app.get("/runs/{run_id}")
    def run_page(request: Request, run_id: str):
        _, meta = run_directory(run_id)
        return render(request, "run", run=meta)

    @app.post("/runs/{run_id}/answer")
    async def answer(request: Request, run_id: str):
        from precedent.worker.events import read_events

        directory, _ = run_directory(run_id)
        form = await request.form()
        question_id, text = str(form.get("question_id", "")), str(form.get("answer", "")).strip()
        events = read_events(directory / "events.jsonl")
        questions = [e for e in events if e.type == "question"]
        if not questions or questions[-1].data.get("question_id") != question_id:
            raise HTTPException(409, "This question is no longer current.")
        if not text or len(text) > 2000:
            raise HTTPException(400, "Enter an answer of 1–2,000 characters.")
        if not processes.get(run_id) or processes[run_id].poll() is not None:
            raise HTTPException(409, "Ava is no longer waiting in this run.")
        answers = directory / "answers"
        answers.mkdir(exist_ok=True)
        try:
            with (answers / (question_id + ".json")).open("x") as stream:
                json.dump({"question_id": question_id, "text": text}, stream)
        except FileExistsError:
            raise HTTPException(409, "An answer was already submitted.") from None
        return RedirectResponse("/runs/" + run_id, 303)

    @app.get("/runs/{run_id}/events")
    def events(run_id: str):
        from precedent.worker.events import read_events

        directory, _ = run_directory(run_id)
        return {
            "events": [e.model_dump(mode="json") for e in read_events(directory / "events.jsonl")],
            "provider_activity": [
                json.loads(line)
                for line in (directory / "provider-activity.jsonl").read_text().splitlines()
            ]
            if (directory / "provider-activity.jsonl").exists()
            else [],
            "active": run_id in processes and processes[run_id].poll() is None,
        }

    @app.post("/runs/{run_id}/stop")
    def stop(run_id: str):
        run_directory(run_id)
        process = processes.get(run_id)
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        return RedirectResponse("/runs/" + run_id, 303)

    if isinstance(service, GoogleService):
        from precedent.connected.google_web import register

        register(app, service, render, runs_root)

    return app

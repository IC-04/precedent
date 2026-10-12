from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from precedent.connected.providers import GMAIL_SCOPE, ProviderError, Providers, body_text, source
from precedent.connected.service import Service
from precedent.connected.store import Vault
from precedent.connected.web import COOKIE, callback_app, create_app
from precedent.worker.connected import write_policy


def run(coro):
    return asyncio.run(coro)


class FakeProviders:
    config = {
        p: dict(
            client_id="test-client",
            client_secret="fixture-secret",
            redirect_uri="https://callback.example/oauth/" + p + "/callback",
        )
        for p in ("gmail", "slack")
    }

    def __init__(self):
        self.client = httpx.AsyncClient()
        self.changed = False
        self.revoked = []
        self.fetches = 0

    def authorization_url(self, provider, state, challenge):
        return "https://consent.example/?state=" + state

    async def exchange(self, provider, code, verifier):
        return dict(
            account=provider + ":test",
            label=provider + " test",
            scopes=[GMAIL_SCOPE] if provider == "gmail" else ["channels:read", "channels:history"],
            token={"access_token": "fixture-private-token", "refresh_token": "fixture-refresh"},
        )

    async def choices(self, provider, token):
        return [{"id": "L1" if provider == "gmail" else "C1", "name": "Demo sources"}]

    async def revoke(self, provider, token):
        self.revoked.append(provider)

    async def refresh(self, provider, token):
        return {**token, "access_token": "new-token", "expires_at": time.time() + 3600}

    async def fetch(self, provider, grant):
        self.fetches += 1
        text = "Launch review moved to Friday." if self.changed else "Launch review is on Thursday."
        item = source(
            provider,
            grant["account"],
            "m1",
            "thread1",
            "Launch handover",
            "Sam <sam@example.test>",
            text,
            "2026-10-11",
            "https://example.test/source",
        )
        return dict(sources=[item], complete=True, fetched_at=time.time(), note="Selected window")


@pytest.fixture
def service(tmp_path):
    return Service(Vault(tmp_path / "data", tmp_path / "keys/key"), FakeProviders())


def authorize(service, provider):
    session = service.vault.get("owner")["session"]
    url = service.begin(provider, session)
    state = url.split("state=")[1]
    run(service.callback(provider, state, "code"))
    run(service.select(provider, ["L1" if provider == "gmail" else "C1"], 3))
    return state


def ready(service):
    authorize(service, "gmail")
    authorize(service, "slack")


def fields(service):
    sources = run(service.sources())
    return dict(
        workspace=service.vault.identity(),
        topic="launch handover",
        reply_to=sources[0]["id"],
        recipient="sam@example.test",
        subject="Re: Launch handover",
        brief="Review on Thursday.",
        body="Thanks Sam. I have noted the Thursday review.",
        sources=", ".join(s["id"] for s in sources),
        revision="0",
    )


def owner_client(service):
    client = TestClient(create_app(service, base_url="http://testserver"))
    response = client.get("/unlock", params={"ticket": service.vault.ticket()})
    assert response.status_code == 200
    return client


def post(client, path, **data):
    session = client.cookies[COOKIE]
    return client.post(
        path,
        data={"csrf": hashlib.sha256(session.encode()).hexdigest(), **data},
        headers={"Origin": "http://testserver"},
    )


def test_tokens_are_encrypted_and_restart_survives(service):
    authorize(service, "gmail")
    content = service.vault.path.read_bytes()
    assert b"fixture-private-token" not in content
    reopened = Vault(service.vault.root, service.vault.root.parent / "keys/key")
    assert reopened.get("connection:gmail")["token"]["access_token"] == "fixture-private-token"
    assert reopened.identity() == service.vault.identity()


def test_oauth_replay_expiry_and_denial(service):
    state = authorize(service, "gmail")
    with pytest.raises(ValueError, match="expired"):
        run(service.callback("gmail", state, "code"))
    for key, extra in (("expired", {"expires": 0}), ("wrong", {"provider": "slack"})):
        service.vault.put(
            "oauth:" + key,
            dict(
                provider="gmail",
                expires=time.time() + 50,
                session=service.vault.get("owner")["session"],
            )
            | extra,
        )
        with pytest.raises(ValueError):
            run(service.callback("gmail", key, "code"))
    state = service.begin("slack", service.vault.get("owner")["session"]).split("state=")[1]
    with pytest.raises(ValueError, match="cancelled"):
        run(service.callback("slack", state, "", True))
    assert service.vault.get("connection:slack") is None


def test_selection_enforced_and_rotates_binding(service):
    authorize(service, "gmail")
    before = service.vault.identity()
    with pytest.raises(ValueError):
        run(service.select("gmail", ["other-mailbox"], 3))
    with pytest.raises(ValueError):
        run(service.select("gmail", ["L1"], 1000))
    run(service.select("gmail", ["L1"], 1))
    assert service.vault.identity() != before


def test_artifact_recipient_version_and_retry(service):
    ready(service)
    form = fields(service)
    with pytest.raises(ValueError, match="Recipient"):
        run(service.save(form | {"recipient": "wrong@example.test"}, "ava"))
    aid = run(service.save(form, "ava"))
    with pytest.raises(ValueError, match="already exists"):
        run(service.save(form, "ava"))
    assert len(service.artifacts()) == 1
    run(service.save(form | {"revision": "1", "body": "Human revision"}, "owner"))
    with pytest.raises(ValueError, match="already exists"):
        run(service.save(form | {"revision": "1"}, "ava"))
    assert service.vault.get("artifact:" + aid)["body"] == "Human revision"


def test_two_providers_required_and_changed_workspace_refused(service):
    ready(service)
    form = fields(service)
    with pytest.raises(ValueError, match="both"):
        run(service.save(form | {"sources": form["sources"].split(",")[0]}, "ava"))
    run(service.select("slack", ["C1"], 1))
    with pytest.raises(ValueError, match="changed"):
        run(service.save(form, "ava"))


def test_disconnect_forgets_and_blocks_worker(service):
    ready(service)
    run(service.save(fields(service), "ava"))
    token = secrets.token_urlsafe(24)
    service.vault.put(
        "worker:" + hashlib.sha256(token.encode()).hexdigest(),
        dict(workspace=service.vault.identity(), expires=time.time() + 60),
    )
    client = TestClient(create_app(service, base_url="http://testserver"))
    headers = {"X-Precedent-Connected": token, "X-Precedent-Agent": "ava"}
    assert client.get("/workspace", headers=headers).status_code == 200
    assert client.get("/connections", headers=headers).status_code == 403
    run(service.disconnect("gmail"))
    assert client.get("/workspace", headers=headers).status_code == 401
    assert service.artifacts() == []
    assert service.providers.revoked == ["gmail"]


def test_owner_csrf_and_private_routes(service):
    client = TestClient(create_app(service, base_url="http://testserver"))
    assert client.get("/connections").status_code == 401
    client = owner_client(service)
    assert client.post("/forget").status_code == 403
    assert client.post("/forget", headers={"Origin": "http://evil.example"}).status_code == 403
    assert post(client, "/forget").status_code == 200
    assert "fixture-secret" not in client.get("/connections").text


def test_callback_listener_exposes_nothing_else(service):
    client = TestClient(callback_app(service))
    assert client.get("/connections").status_code == 404
    assert client.get("/workspace.json").status_code == 404
    result = client.get("/oauth/gmail/callback?code=private-code&state=not-valid")
    assert "private-code" not in result.text
    assert result.headers["cache-control"] == "no-store"


def test_browser_forms_save_and_fresh_proof_detects_change(service):
    ready(service)
    client = owner_client(service)
    for path in ("/workspace", "/sources/gmail", "/sources/slack", "/artifacts/new", "/setup"):
        assert client.get(path).status_code == 200
    form = fields(service)
    saved = post(client, "/artifacts/save", **form)
    assert saved.status_code == 200 and "Local draft" in saved.text
    aid = service.artifacts()[0]["id"]
    proof = client.get(f"/artifacts/{aid}/proof").json()
    assert proof["unchanged"]
    service.providers.changed = True
    assert not client.get(f"/artifacts/{aid}/proof").json()["unchanged"]
    assert client.get("/sources/gmail/unselected").status_code == 404


def test_mime_html_and_attachments_are_inert():
    encoded = base64.urlsafe_b64encode(
        b'<p>Hello</p><script>send()</script><img src="https://evil.test">'
    ).decode()
    text = body_text({"mimeType": "text/html", "body": {"data": encoded}})
    assert "Hello" in text and "send()" not in text and "evil.test" not in text
    assert body_text({"filename": "secret.txt", "body": {"data": encoded}}) == ""


def test_provider_rates_denial_and_operation_allowlist():
    async def scenario():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(429, headers={"Retry-After": "60"})
            )
        )
        provider = Providers({}, client)
        with pytest.raises(ProviderError, match="60 seconds"):
            await provider.gmail("secret", "profile")
        with pytest.raises(ProviderError, match="not permitted"):
            await provider.slack("secret", "chat.postMessage")
        await client.aclose()

    run(scenario())


def test_gateway_permission_surface():
    assert write_policy("POST", "/artifacts/save", b"") is None
    assert write_policy("GET", "/sources/gmail/abc", b"") is None
    for method, path in (
        ("POST", "/connections/gmail/connect"),
        ("POST", "/mail/send"),
        ("POST", "/calendar/events"),
        ("DELETE", "/artifacts/a"),
    ):
        assert write_policy(method, path, b"")


def test_connected_run_uses_existing_adk_browser_and_no_persistent_memory(
    service, tmp_path, monkeypatch
):
    import socket
    import threading

    import uvicorn

    from precedent.worker import runner
    from precedent.worker.events import read_events
    from tests.test_scripted_runner import ScriptedModel

    ready(service)
    token = secrets.token_urlsafe(24)
    service.vault.put(
        "worker:" + hashlib.sha256(token.encode()).hexdigest(),
        dict(workspace=service.vault.identity(), expires=time.time() + 120),
    )
    monkeypatch.setenv("PRECEDENT_CONNECTED_TOKEN", token)
    monkeypatch.setattr(runner, "make_model", lambda name: ScriptedModel(model="scripted"))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(service, base_url=f"http://localhost:{port}"),
            log_level="error",
            access_log=False,
        )
    )
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    try:
        cfg = runner.RunConfig(
            request="Read connected overview",
            apps_url=f"http://localhost:{port}",
            runs_root=tmp_path / "runs",
            screen=False,
        )
        result = run(runner.run(cfg))
        assert result["error"] is None
        assert result["outcome"] == "unknown"
        events = read_events(tmp_path / "runs" / result["run_id"] / "events.jsonl")
        goal = next(e for e in events if e.type == "goal_contract")
        assert goal.data["task_family"] == "contextual_preparation"
        assert any(e.type == "observation" for e in events)
        assert not any(e.type == "note" and e.data.get("kind") == "memory_recalled" for e in events)
        assert not list(tmp_path.rglob("sessions.sqlite"))
    finally:
        server.should_exit = True
        thread.join(5)

"""Protocol-shaped Google fixtures; these are not live-account demonstration evidence."""

from __future__ import annotations

import asyncio
import base64
import copy
import email
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from precedent.connected.google import GoogleService, event_authorized, normalize_subject
from precedent.connected.providers import GOOGLE_SCOPES, ProviderError, Providers
from precedent.connected.store import Vault
from precedent.connected.verify import inspect, verdict
from precedent.connected.web import create_app
from precedent.learning.store import scope_for
from precedent.worker.google import write_policy


def run(coro):
    return asyncio.run(coro)


class GoogleFixture:
    def __init__(self):
        self.drafts, self.events, self.calls = {}, {}, []
        self.busy = []
        self.missing_marker = False
        self.original = dict(
            id="m1",
            threadId="thread1",
            internalDate=str(int(time.time() * 1000)),
            labelIds=["INBOX"],
            payload=dict(
                mimeType="text/plain",
                headers=[
                    {"name": k, "value": v}
                    for k, v in {
                        "From": "Sam <sam@example.test>",
                        "Reply-To": "review@example.test",
                        "Subject": "Prototype review",
                        "Message-ID": "<source@example.test>",
                        "Date": datetime.now(UTC).isoformat(),
                    }.items()
                ],
                body={
                    "data": base64.urlsafe_b64encode(
                        b"Please review the new prototype next week."
                    ).decode()
                },
            ),
        )

    def response(self, data, status=200):
        return httpx.Response(status, json=data)

    def __call__(self, request):
        path = request.url.path
        if path.endswith("/userinfo"):
            return self.response(
                {"sub": "google-sub-1", "email": "owner@example.test", "email_verified": True}
            )
        self.calls.append((request.method, path))
        if path.endswith("/labels"):
            return self.response({"labels": [{"id": "INBOX", "name": "Inbox"}]})
        if path.endswith("/messages"):
            return self.response({"messages": [{"id": "m1", "threadId": "thread1"}]})
        if path.endswith("/messages/m1"):
            return self.response(self.original)
        if path.endswith("/threads/thread1"):
            return self.response(
                {
                    "id": "thread1",
                    "messages": [self.original] + [d["message"] for d in self.drafts.values()],
                }
            )
        if path.endswith("/drafts"):
            if request.method == "GET":
                marker = request.url.params.get("q", "").replace("rfc822msgid:", "")
                drafts = [
                    d
                    for d in self.drafts.values()
                    if any(
                        h["name"].lower() == "message-id" and marker in h["value"]
                        for h in d["message"]["payload"]["headers"]
                    )
                ]
                return self.response(
                    {"drafts": [] if self.missing_marker else [{"id": d["id"]} for d in drafts]}
                )
            data = json.loads(request.content)
            mime = email.message_from_bytes(base64.urlsafe_b64decode(data["message"]["raw"]))
            body = mime.get_payload(decode=True)
            identifier = "draft" + str(len(self.drafts) + 1)
            value = dict(
                id=identifier,
                message=dict(
                    id="msg-" + identifier,
                    threadId=data["message"]["threadId"],
                    internalDate=str(int(time.time() * 1000)),
                    labelIds=["DRAFT"],
                    payload=dict(
                        mimeType="text/plain",
                        headers=[{"name": k, "value": v} for k, v in mime.items()],
                        body={"data": base64.urlsafe_b64encode(body).decode()},
                    ),
                ),
            )
            self.drafts[identifier] = value
            return self.response(value)
        if "/drafts/" in path:
            identifier = path.rsplit("/", 1)[-1]
            if request.method == "PUT":
                data = json.loads(request.content)
                mime = email.message_from_bytes(base64.urlsafe_b64decode(data["message"]["raw"]))
                value = self.drafts[identifier]
                value["message"]["id"] += "-replacement"
                value["message"]["payload"]["headers"] = [
                    {"name": k, "value": v} for k, v in mime.items()
                ]
                value["message"]["payload"]["body"]["data"] = base64.urlsafe_b64encode(
                    mime.get_payload(decode=True)
                ).decode()
            value = self.drafts.get(identifier)
            return self.response(value or {}, 200 if value else 404)
        if path.endswith("/calendarList"):
            return self.response(
                {
                    "items": [
                        {
                            "id": "cal1",
                            "summary": "My calendar",
                            "timeZone": "Asia/Kolkata",
                            "accessRole": "owner",
                            "primary": True,
                        }
                    ]
                }
            )
        if path.endswith("/freeBusy"):
            return self.response({"calendars": {"cal1": {"busy": self.busy}}})
        if path.endswith("/events"):
            if request.method == "GET":
                return self.response({"items": list(self.events.values())})
            value = json.loads(request.content)
            value.update(
                status="confirmed",
                htmlLink="https://calendar.google.com/calendar/event?eid=fixture",
            )
            self.events[value["id"]] = value
            return self.response(value)
        if "/events/" in path:
            value = self.events.get(path.rsplit("/", 1)[-1])
            return self.response(value or {}, 200 if value else 404)
        raise AssertionError((request.method, path))


@pytest.fixture
def google(tmp_path):
    fixture = GoogleFixture()
    providers = Providers(
        {
            "gmail": {
                "client_id": "fixture",
                "client_secret": "fixture-secret",
                "redirect_uri": "http://localhost/callback",
            },
            "slack": {},
        },
        httpx.AsyncClient(transport=httpx.MockTransport(fixture)),
    )
    service = GoogleService(Vault(tmp_path / "private", tmp_path / "key"), providers)
    service.vault.put(
        "connection:gmail",
        dict(
            account="google-sub-1",
            email="owner@example.test",
            label="owner@example.test",
            scopes=sorted(GOOGLE_SCOPES),
            status="Ready",
            generation="v1",
            selection={"ids": ["INBOX"], "days": 30},
            calendar_id="cal1",
            calendar_timezone="Asia/Kolkata",
            token={"access_token": "fixture-private-token"},
        ),
    )
    return service, fixture


def draft_fields(service):
    return dict(
        workspace=service.vault.identity(),
        thread="thread1",
        reply_to="m1",
        recipient="review@example.test",
        topic="prototype review",
        body="Thanks Sam. I will review the new prototype next week.",
    )


def reservation_fields(service):
    day = datetime.now(UTC).date() + timedelta(days=2)
    return dict(
        workspace=service.vault.identity(),
        title="Prototype review",
        start=day.isoformat() + "T10:00",
        end=day.isoformat() + "T10:30",
    )


def test_native_reply_threading_readback_and_repeat(google):
    service, fixture = google
    fields = draft_fields(service)
    op = run(service.save_draft(fields, "ava"))
    proof = run(inspect(service, op["id"]))
    assert proof["outcome"] == "pass"
    assert proof["native"]["headers"]["in-reply-to"] == "<source@example.test>"
    assert proof["native"]["headers"]["to"] == "review@example.test"
    assert run(service.save_draft(fields, "ava"))["native_id"] == op["native_id"]
    assert len(fixture.drafts) == 1


def test_lost_gmail_ack_reconciles_without_second_post(google):
    service, fixture = google
    service.lost_ack = True
    with pytest.raises(ProviderError):
        run(service.save_draft(draft_fields(service), "ava"))
    op = run(service.save_draft(draft_fields(service), "ava"))
    assert op["state"] == "saved"
    assert len(fixture.drafts) == 1
    assert fixture.calls.count(("POST", "/gmail/v1/users/me/drafts")) == 1


def test_unresolved_save_does_not_blind_retry(google):
    service, fixture = google
    service.lost_ack, fixture.missing_marker = True, True
    with pytest.raises(ProviderError):
        run(service.save_draft(draft_fields(service), "ava"))
    with pytest.raises(ProviderError, match="uncertain"):
        run(service.save_draft(draft_fields(service), "ava"))
    assert len(fixture.drafts) == 1


def test_human_edit_and_missing_native_artifact_are_not_passes(google):
    service, fixture = google
    op = run(service.save_draft(draft_fields(service), "ava"))
    fixture.drafts[op["native_id"]]["message"]["payload"]["body"]["data"] = (
        base64.urlsafe_b64encode(b"Human correction.").decode()
    )
    assert run(inspect(service, op["id"]))["outcome"] == "fail"
    with pytest.raises(ValueError, match="human"):
        run(service.save_draft(draft_fields(service), "ava"))
    fixture.drafts.clear()
    assert run(inspect(service, op["id"]))["outcome"] == "fail"


def test_calendar_ack_recovery_and_fresh_conflict_detection(google):
    service, fixture = google
    fields = reservation_fields(service)
    service.lost_ack = True
    with pytest.raises(ProviderError):
        run(service.reserve(fields, "ava"))
    op = run(service.reserve(fields, "ava"))
    assert run(inspect(service, op["id"]))["outcome"] == "pass"
    assert len(fixture.events) == 1
    other = copy.deepcopy(fixture.events[op["id"]])
    other.update(id="human-conflict", summary="Human event", extendedProperties={})
    fixture.events[other["id"]] = other
    assert run(inspect(service, op["id"]))["outcome"] == "fail"


def test_prewrite_conflict_refuses_calendar_mutation(google):
    service, fixture = google
    fields = reservation_fields(service)
    fixture.busy = [{"start": fields["start"] + ":00+05:30", "end": fields["end"] + ":00+05:30"}]
    with pytest.raises(ValueError, match="busy"):
        run(service.reserve(fields, "ava"))
    assert not fixture.events


def test_wrong_recipient_scope_reduction_and_access_revision(google):
    service, _ = google
    fields = draft_fields(service)
    fields["recipient"] = "wrong@example.test"
    with pytest.raises(ValueError, match="Recipient"):
        run(service.save_draft(fields, "ava"))
    stable = service.stable_id()
    grant = service.vault.get("connection:gmail")
    grant["generation"] = "v2"
    grant["scopes"] = ["https://www.googleapis.com/auth/gmail.readonly"]
    service.vault.put("connection:gmail", grant)
    assert service.stable_id() == stable
    assert service.capabilities() == ["gmail_read"]
    with pytest.raises(ProviderError, match="permission"):
        run(service.save_draft(draft_fields(service), "ava"))
    grant["account"] = "other-account"
    service.vault.put("connection:gmail", grant)
    assert service.stable_id() != stable


def test_worker_cannot_reserve_for_draft_only_task(google):
    service, fixture = google
    token = "worker-fixture"
    service.vault.put(
        "worker:" + hashlib.sha256(token.encode()).hexdigest(),
        dict(workspace=service.vault.identity(), expires=time.time() + 300, allow_event=False),
    )
    with TestClient(create_app(service, base_url="http://testserver")) as client:
        response = client.post(
            "/calendar/events/save",
            data=reservation_fields(service),
            headers={"x-precedent-connected": token},
        )
        assert response.status_code == 403
        assert not fixture.events


def test_connected_surfaces_use_google_without_slack(google):
    service, _ = google
    with TestClient(create_app(service, base_url="http://testserver")) as client:
        assert client.get("/unlock", params={"ticket": service.vault.ticket()}).status_code == 200
        for path in (
            "/workspace",
            "/mail",
            "/mail/threads/thread1",
            "/mail/compose?thread=thread1",
            "/calendar",
            "/mind",
        ):
            response = client.get(path)
            assert response.status_code == 200, (path, response.text)
            assert "fixture-private-token" not in response.text
        identity = client.get("/workspace.json").json()
        assert identity["ready"]
        assert scope_for(identity) == "google:" + service.stable_id() + ":ava"


def test_semantic_permission_and_verdict_boundaries():
    assert event_authorized("Reserve the second option on my calendar without inviting anyone.")
    assert not event_authorized("Draft a reply. Do not reserve time.")
    assert verdict([{"result": "unknown"}, {"result": "fail"}]) == "fail"
    assert verdict([{"result": "unknown"}, {"result": "pass"}]) == "unknown"
    assert write_policy("POST", "/mail/drafts/save", b"") is None
    for path in (
        "/mail/send",
        "/calendar/delete",
        "/google/calendar/select",
        "/connections/gmail/connect",
    ):
        assert write_policy("POST", path, b"")


def test_native_draft_update_keeps_id_and_checks_editor_version(google):
    service, fixture = google
    fields = draft_fields(service)
    op = run(service.save_draft(fields, "ava"))
    native = run(service.read_draft(op["native_id"]))
    fields.update(
        body="Thanks. I will review the prototype and share the next step.",
        update_version=native["version"],
    )
    changed = run(service.save_draft(fields, "ava"))
    assert changed["native_id"] == op["native_id"]
    assert len(fixture.drafts) == 1
    assert run(inspect(service, changed["id"]))["outcome"] == "pass"
    with pytest.raises(ValueError, match="changed since"):
        run(service.save_draft(fields, "ava"))


def test_google_features_and_subject_access_boundary(google):
    from urllib.parse import parse_qs, urlsplit

    service, fixture = google
    scopes = parse_qs(
        urlsplit(service.begin_google(service.vault.get("owner")["session"], ["mail"])).query
    )["scope"][0]
    assert "gmail.compose" in scopes
    assert "calendar" not in scopes
    with pytest.raises(ValueError):
        service.begin_google(service.vault.get("owner")["session"], ["reserve"])
    run(service.select("gmail", ["INBOX"], 30, "Different demo topic"))
    assert run(service.search("OR anything"))["messages"] == []
    with pytest.raises(ProviderError, match="outside"):
        run(service.thread("thread1"))
    assert normalize_subject("Re: Fwd: Prototype review") == "prototype review"


def test_read_only_reconciliation_after_live_shaped_commit(google):
    service, fixture = google
    service.lost_ack = True
    with pytest.raises(ProviderError):
        run(service.reserve(reservation_fields(service), "ava"))
    pending = service.artifacts()[0]
    repaired = run(service.reconcile(pending["id"]))
    assert repaired["state"] == "saved"
    assert repaired["fault_injection"]
    assert len(fixture.events) == 1
    assert sum(method == "POST" and path.endswith("/events") for method, path in fixture.calls) == 1
    assert run(inspect(service, repaired["id"]))["outcome"] == "pass"


def test_stale_source_and_trusted_repeat_key(google):
    from precedent.connected.google import digest

    service, fixture = google
    fields = draft_fields(service)
    source = run(service.thread("thread1"))["sources"][0]
    fields["source_versions"] = digest([{"id": source["message_id"], "version": source["version"]}])
    fields["_trusted_request"] = "Save a reply about the prototype."
    first = run(service.save_draft(fields, "ava"))
    fields["topic"] = "A model's alternative wording"
    assert run(service.save_draft(fields, "ava"))["id"] == first["id"]
    fixture.original["payload"]["body"]["data"] = base64.urlsafe_b64encode(
        b"Changed source request"
    ).decode()
    with pytest.raises(ValueError, match="conversation changed"):
        run(service.save_draft(fields, "ava"))
    assert len(fixture.drafts) == 1


def test_google_candidate_and_forget_keep_native_objects(google):
    from precedent.learning.store import Store

    service, fixture = google
    op = run(service.save_draft(draft_fields(service), "ava"))
    scope = "google:" + service.stable_id() + ":ava"
    store = Store(service.vault.root / "learning")
    note = store.put(
        scope,
        "episode",
        "Verified synthetic reply",
        {"task_family": "google_reply", "outcome": "pass", "uncertain": []},
        run_id="fixture",
    )
    candidate = store.draft_skill(scope, note["id"])
    assert candidate["status"] == "draft"
    with pytest.raises(ValueError, match="sandbox validation"):
        store.activate(scope, candidate["id"])
    service.vault.put("preferences:" + service.stable_id(), {"work_start": 10, "work_end": 18})
    service.forget()
    assert store.list(scope) == []
    assert service.artifacts() == []
    assert op["native_id"] in fixture.drafts


def test_duplicate_warning_does_not_revoke_explicit_reservation():
    assert event_authorized(
        "Reserve a 30-minute owner-only calendar event. Do not create a duplicate."
    )
    assert not event_authorized("Draft an email. Do not create a calendar event.")
    assert not event_authorized("Find times without reserving anything.")


def test_independent_facade_has_no_native_write_tools(google):
    from precedent.connected.verify import ReadOnlyGoogle

    service, _ = google
    reader = ReadOnlyGoogle(service)
    with pytest.raises(AttributeError):
        _ = reader.reserve
    with pytest.raises(AttributeError):
        _ = reader.providers
    with pytest.raises(ValueError):
        run(reader.call("calendar_reserve", "POST", "events"))


def test_disabled_features_stay_disabled_with_existing_google_grants(google):
    service, _ = google
    grant = service.vault.get("connection:gmail")
    grant["enabled_features"] = ["mail"]
    service.vault.put("connection:gmail", grant)
    assert service.capabilities() == ["gmail_read", "gmail_draft"]
    with pytest.raises(ProviderError, match="permission"):
        run(service.reserve(reservation_fields(service), "ava"))


def test_google_episode_persists_proof_metadata_without_source_text(google):
    from precedent.learning.store import Store

    service, _ = google
    scope = "google:" + service.stable_id() + ":ava"
    company = {
        "connector": "google",
        "memory_id": service.stable_id(),
        "instance_id": service.vault.identity(),
    }
    run_id = "fixture"
    events = [
        {"run_id": run_id, "type": kind, "data": data}
        for kind, data in [
            ("run_started", {"request": "Reply to a synthetic demo"}),
            ("note", {"kind": "company", "company": company}),
            ("goal_contract", {"task_family": "google_reply"}),
            (
                "check",
                {
                    "condition_id": "native_persistence",
                    "result": "pass",
                    "claims": ["native_persistence"],
                    "verifier_version": 2,
                    "evidence": "Private source wording should not persist",
                },
            ),
            ("run_finished", {"outcome": "pass"}),
        ]
    ]
    entries = Store(service.vault.root / "learning").ingest(
        scope, run_id, events, {"private": "inbox text"}
    )
    assert entries[0]["payload"]["sources"] == {}
    assert "Private source wording" not in json.dumps(entries[0]["payload"])

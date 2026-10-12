"""Durability, isolation and promotion boundaries, using explicitly synthetic run events."""

import asyncio
import hashlib

import pytest

from precedent.learning.recall import index_entries, recall
from precedent.learning.store import CRITICAL, Store, scope_for
from precedent.workspace import instance_id


@pytest.fixture
def registry(tmp_path):
    return Store(tmp_path / "learning")


def episode(store, scope, complete=True, recheck_failed=False):
    checks = [
        {
            "type": "check",
            "run_id": "r1",
            "data": {
                "condition_id": "c" + str(i),
                "text": key,
                "claims": [key],
                "sources": ["/drive/f/source"],
                "result": "pass",
                "verifier_version": 2,
                "evidence": "Synthetic test evidence",
            },
        }
        for i, key in enumerate(sorted(CRITICAL if complete else {"Amount"}))
    ]
    events = [
        {"type": "run_started", "run_id": "r1", "data": {"request": "Enter and route an invoice"}},
        {
            "type": "note",
            "run_id": "r1",
            "data": {"kind": "company", "company": {"instance_id": scope.split(":")[1]}},
        },
        *checks,
        {"type": "run_finished", "run_id": "r1", "data": {"outcome": "pass"}},
    ]
    if recheck_failed:
        prior = next(
            e for e in events if e["type"] == "check" and e["data"]["claims"] == ["Amount"]
        )
        events.insert(-1, {**prior, "data": {**prior["data"], "result": "fail"}})
    return store.ingest(scope, "r1", events, {})[0]


def test_restart_recall_scope_archive_and_correction(registry):
    scope = scope_for({"instance_id": "a" * 32})
    item = episode(registry, scope)
    asyncio.run(index_entries(registry, scope, [item]))
    reopened = Store(registry.root)
    assert asyncio.run(recall(reopened, scope, "invoice", "next"))[0]["id"] == item["id"]
    assert not asyncio.run(
        recall(reopened, scope_for({"instance_id": "b" * 32}), "invoice", "next")
    )
    reopened.revise(scope, item["id"], correction="The policy has changed")
    assert not asyncio.run(recall(reopened, scope, "invoice", "next"))
    reopened.revise(scope, item["id"], status="archived")
    assert not asyncio.run(recall(reopened, scope, "invoice", "next"))


def test_ingestion_idempotent_and_promotion_blocked(registry):
    scope = scope_for({"instance_id": "a" * 32})
    item = episode(registry, scope, complete=False)
    assert episode(registry, scope, complete=False)["id"] == item["id"]
    assert len(registry.list(scope)) == 1
    draft = registry.draft_skill(scope, item["id"])
    assert "Attachment" in draft["payload"]["missing_coverage"]
    with pytest.raises(ValueError):
        registry.activate(scope, draft["id"])
    with pytest.raises(KeyError):
        registry.get(scope_for({"instance_id": "b" * 32}), draft["id"])


def test_activation_requires_validation_bound_to_procedure(registry):
    scope = scope_for({"instance_id": "a" * 32})
    draft = registry.draft_skill(scope, episode(registry, scope)["id"])
    body = draft["payload"]
    body["validation"] = {"passed": True, "procedure_hash": "wrong"}
    registry.revise(scope, draft["id"], status="validated", payload=body)
    with pytest.raises(ValueError):
        registry.activate(scope, draft["id"])
    body["validation"]["procedure_hash"] = hashlib.sha256(body["instructions"].encode()).hexdigest()
    registry.revise(scope, draft["id"], status="validated", payload=body)
    assert registry.activate(scope, draft["id"])["status"] == "active"
    assert registry.revise(scope, draft["id"], status="inactive")["status"] == "inactive"


def test_instance_survives_restart_but_reset_rotates(tmp_path):
    first = instance_id(tmp_path)
    assert instance_id(tmp_path) == first
    (tmp_path / "instance.json").unlink()  # generator removes the whole world during reset
    assert instance_id(tmp_path) != first


def test_changed_authority_invalidates_recall(registry):
    from precedent.learning.store import revalidate_sources

    scope = scope_for({"instance_id": "a" * 32})
    old = "<p>The current approver is Person A.</p>"
    item = registry.put(
        scope,
        "knowledge",
        "Approval routing",
        {
            "governing": {"ref": "mail:m-1"},
            "sources": {"/mail/m/m-1": {"hash": hashlib.sha256(old.encode()).hexdigest()}},
            "lesson": "invoice approval routing",
        },
        status="needs_revalidation",
    )
    asyncio.run(index_entries(registry, scope, [item]))
    assert not revalidate_sources(registry, scope, [item], {"/mail/m/m-1": old})
    assert revalidate_sources(
        registry, scope, [item], {"/mail/m/m-1": "<p>Person B now approves.</p>"}
    ) == [item["id"]]
    assert not asyncio.run(recall(registry, scope, "approval", "r2"))


def test_mind_routes_are_scoped_and_activation_is_not_a_draft_action(
    registry, monkeypatch, tmp_path
):
    from fastapi.testclient import TestClient

    from precedent.console.server import create_app

    monkeypatch.setenv("PRECEDENT_MEMORY_ROOT", str(registry.root))
    company = {"instance_id": "a" * 32, "name": "Test company", "seed": 7}
    scope = scope_for(company)
    draft = registry.draft_skill(scope, episode(registry, scope)["id"])
    app = create_app(tmp_path / "runs")

    async def identity():
        return company

    app.state.manager.company = identity
    with TestClient(app) as client:
        response = client.get("/mind")
        assert response.status_code == 200 and "Ava’s mind" in response.text
        assert client.get("/mind?tab=skills&entry=" + draft["id"]).status_code == 200
        assert client.post("/mind/" + draft["id"] + "/activate").status_code == 409
        assert (
            client.post(
                "/mind/" + draft["id"] + "/activate", headers={"origin": "https://foreign.example"}
            ).status_code
            == 403
        )
        company["instance_id"] = "b" * 32
        assert client.get("/mind?entry=" + draft["id"]).status_code == 404
        assert client.post("/mind/" + draft["id"] + "/activate").status_code == 404


def test_context_cache_requires_exact_fresh_authority_set(registry):
    from precedent.learning.store import cache_candidates, cached_candidates

    scope = scope_for({"instance_id": "a" * 32})
    original = {"drive:policy": "hash-1"}
    entry = cache_candidates(registry, scope, "r1", original, [{"rule": "Fixture rule"}], [])
    assert cached_candidates(registry, scope, original) == [{"rule": "Fixture rule"}]
    # Even an added authoritative message invalidates reuse, not just an edited source.
    assert cached_candidates(registry, scope, {**original, "mail:new-policy": "hash-2"}) is None
    assert registry.get(scope, entry["id"])["status"] == "invalidated"
    other = scope_for({"instance_id": "b" * 32})
    assert cached_candidates(registry, other, original) is None


def test_later_failed_recheck_cannot_promote_old_passing_claim(registry):
    scope = scope_for({"instance_id": "a" * 32})
    item = episode(registry, scope, recheck_failed=True)
    assert "Amount" in registry.draft_skill(scope, item["id"])["payload"]["missing_coverage"]


def test_correction_invalidates_related_context_cache(registry):
    from precedent.learning.store import cache_candidates, cached_candidates

    scope = scope_for({"instance_id": "a" * 32})
    rule = registry.put(scope, "knowledge", "Rule", {"lesson": "Fixture"})
    cache_candidates(registry, scope, "r1", {"source": "hash"}, [{"rule": "Fixture"}], [])
    registry.revise(scope, rule["id"], correction="Reconsider this policy")
    assert cached_candidates(registry, scope, {"source": "hash"}) is None


@pytest.mark.parametrize("status", ["inactive", "active"])
def test_stale_or_deactivated_skill_cannot_load(registry, tmp_path, monkeypatch, status):
    import threading
    from types import SimpleNamespace

    from precedent.worker.events import EventLog, read_events
    from precedent.worker.failures import WriteGate
    from precedent.worker.guard import Guard
    from precedent.worker.runner import Callbacks, RunConfig

    monkeypatch.setenv("PRECEDENT_MEMORY_ROOT", str(registry.root))
    scope = scope_for({"instance_id": "a" * 32})
    skill = registry.put(
        scope, "skill", "Synthetic procedure", {"instructions": "Read only"}, status="active"
    )
    # Changing the version also blocks an old selection even when the new status is active.
    registry.revise(scope, skill["id"], status=status)
    log = EventLog("test-skill", root=tmp_path / "runs")
    guard = Guard(log, WriteGate(), threading.Lock(), tmp_path)
    guard.memory_scope, guard.selected_skill = scope, skill
    calls = Callbacks(
        RunConfig(request="Synthetic test", runs_root=tmp_path / "runs"), guard, object()
    )

    async def attempt():
        tool, context = SimpleNamespace(name="load_skill"), object()
        result = await calls.before_tool(tool, {}, context)
        assert "error" in result
        await calls.after_tool(tool, {}, context, result)
        assert not calls.lock.locked()

    asyncio.run(attempt())
    assert not any(e.data.get("kind") == "skill_loaded" for e in read_events(log.path))

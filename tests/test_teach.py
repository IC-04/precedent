"""Teach Ava: demonstration or written procedure -> grounded notes -> skill draft.
Models are scripted; grounding runs against the seed-7 apps over real HTTP."""

import json

import httpx

from precedent.learning import teach
from precedent.learning.store import Store
from precedent.learning.teach import AppIndex, SkillDraft, Step, ground, seconds

HEADERS = {"X-Precedent-Agent": "teacher"}


def test_steps_are_checked_against_the_real_apps(live_apps):
    base, _ = live_apps
    with httpx.Client(base_url=base, headers=HEADERS, follow_redirects=True) as client:
        index = AppIndex(client)
        on_form = ground(Step(action="type", path="/books/bills/new", target="Invoice number"),
                         client, index)  # fmt: skip
        assert on_form["status"] == "grounded"
        wrong = ground(Step(action="click", path="/books/bills/new", target="Launch rocket"),
                       client, index)  # fmt: skip
        assert wrong["status"] == "label_missing"
        found = ground(Step(action="type", app="books", target="Invoice number"), client, index)
        assert found["status"] == "grounded" and found["path"].startswith("/books/")
        assert ground(Step(action="read", path="/__scenario/edit"), client)["status"] == (
            "unknown_page"
        )
        assert ground(Step(action="read"), client)["status"] == "no_page"


def test_timestamps():
    assert seconds("01:15") == 75 and seconds("00:02.500") == 2 and seconds("1:02:03") == 3723
    assert seconds("") is None and seconds("soon") is None


def _draft():
    return SkillDraft(
        name="enter-and-route-vendor-invoice",
        title="Enter and route a vendor invoice",
        description="Enter a vendor invoice into Books and route it to the right approver",
        parameters=[{"name": "invoice_number", "description": "Invoice number",
                     "source": "the invoice PDF", "example": "FIG-1842"}],
        sources=["The AP policy in Drive"],
        steps=["Open the invoice email", "Create a bill in Books"],
        rules=[{"rule": "Check recent approval changes in Mail", "why": "the CFO reshuffles"}],
        done_when=["One bill exists for the invoice", "The bill is pending approval"],
        stop_and_ask=["The vendor is not in Books"],
        questions=["Which approver applies below the threshold?"],
        trial_request="Enter the latest Linear invoice and route it for approval.",
    )  # fmt: skip


def test_a_written_procedure_becomes_a_reviewed_skill_draft(live_apps, tmp_path, monkeypatch):
    base, _ = live_apps
    monkeypatch.setattr(teach, "gemini", lambda: (None, "scripted"))

    def watch(client, model, *, video, procedure, on_step):
        assert video is None and "Books" in procedure
        on_step(Step(action="navigate", path="/books/bills/new", target="Invoice number"))
        on_step(Step(action="type", app="books", target="Amount", value="112000"))
        on_step(Step(action="click", path="/books/bills/new", target="Launch rocket"))

    monkeypatch.setattr(teach, "watch_stream", watch)
    monkeypatch.setattr(teach, "abstract", lambda client, model, title, steps, company="": _draft())
    meta = teach.create(tmp_path, "scope-1", "Invoice lesson",
                        procedure="Create a bill in Books for the invoice.")  # fmt: skip
    path = teach.directory(tmp_path, meta["id"])
    teach.run(path, base)
    assert teach.read_meta(path)["status"] == "ready"
    notes = teach.read_notes(path)
    steps = [n for n in notes if n["event"] == "step"]
    assert [s["grounding"]["status"] for s in steps] == ["grounded", "grounded", "label_missing"]
    assert any(n["event"] == "draft" for n in notes) and notes[-1]["event"] == "status"
    skill_md = (path / "SKILL.md").read_text()
    assert skill_md.startswith("---\nname: enter-and-route-vendor-invoice")
    assert "## Done when" in skill_md and "FIG-1842" not in skill_md.split("## Steps")[1]

    store = Store(tmp_path / "learning")
    item = teach.save_skill(store, "scope-1", path, "Enter the latest Notion invoice.")
    assert item["status"] == "draft" and item["payload"]["origin"] == "demonstration"
    assert item["payload"]["done_when"] == _draft().done_when
    assert item["payload"]["trial_request"] == "Enter the latest Notion invoice."
    assert teach.read_meta(path)["status"] == "saved"


def test_a_failed_lesson_is_recorded_not_raised(tmp_path, monkeypatch):
    def broken():
        raise ValueError("no model")

    monkeypatch.setattr(teach, "gemini", broken)
    meta = teach.create(tmp_path, "s", "Lesson", procedure="Do it.")
    path = teach.directory(tmp_path, meta["id"])
    teach.run(path, "http://127.0.0.1:9")
    assert teach.read_meta(path)["status"] == "failed"
    assert teach.read_notes(path)[-1]["event"] == "error"


def test_only_supported_recordings_are_accepted(tmp_path):
    bad = tmp_path / "x.exe"
    bad.write_bytes(b"no")
    try:
        teach.create(tmp_path, "s", "Lesson", video=bad, filename="x.exe")
        raise AssertionError("accepted an unsupported file")
    except ValueError:
        pass


def test_the_tribunal_checks_the_demonstrated_definition_of_done(live_apps, tmp_path):
    from precedent.tribunal.court import convene, read_record
    from tests.test_tribunal import _run_dir

    base, _ = live_apps
    run = _run_dir(tmp_path, base)
    events = (run / "events.jsonl").read_text().splitlines()
    loaded = {"run_id": run.name, "seq": 99, "ts": "t", "type": "note",
              "data": {"kind": "skill_loaded", "origin": "demonstration",
                       "done_when": ["The bill for FIG-1709 is approved"]}}  # fmt: skip
    events.insert(3, json.dumps(loaded))
    (run / "events.jsonl").write_text("\n".join(events) + "\n")
    result = convene(run, apps_url=base, jurors=[], screenshots=False)
    assert "d1" in result["rulings"]
    charge = next(e for e in read_record(run) if e["event"] == "charge" and e["id"] == "d1")
    assert charge["origin"] == "demonstration" and charge["added"] is True

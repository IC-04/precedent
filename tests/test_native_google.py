"""Native Google: the action policy that stands in for the gateway on gmail.com, and the checks
that read a draft back. No browser, network or model: snapshots and drafts are fixtures."""

from types import SimpleNamespace

from precedent.worker import native

GATEWAY = "http://localhost:5100"
COMPOSE = "https://mail.google.com/mail/u/0/"
SNAPSHOT = """
- combobox "To recipients" [ref=e12]
- textbox "Subject" [ref=e13]
- textbox "Message Body" [ref=e14]
- button "Send ‪(⌘Enter)‬" [ref=e20]
- button "Save & close" [ref=e21]
- button "Discard draft ‪(⌘⇧D)‬" [ref=e22]
"""


def policy():
    return native.NativePolicy(GATEWAY, ["owner@example.com"])


def test_native_mode_is_opt_in_and_needs_an_address(monkeypatch):
    monkeypatch.delenv("PRECEDENT_NATIVE_GOOGLE", raising=False)
    assert not native.is_native("Draft a mail to owner@example.com")
    monkeypatch.setenv("PRECEDENT_NATIVE_GOOGLE", "1")
    assert native.is_native("Draft a mail to owner@example.com about the bill")
    assert not native.is_native("Draft a mail about the bill")
    goal = native.native_goal("Draft a mail to Owner@Example.com")
    assert goal.task_family == "native_google"
    assert {c.id for c in goal.conditions} >= {"c1", "c3", "c5", "n1", "n2"}


def test_navigation_is_limited_to_company_apps_gmail_and_calendar():
    p = policy()
    for url in (GATEWAY + "/books/bills", native.COMPOSE_URL, "https://calendar.google.com/r"):
        assert p.check("browser_navigate", {"url": url}, None, "", SimpleNamespace()) is None
    for url in ("https://accounts.google.com/signin", "https://example.org/"):
        assert "not permitted" in p.check("browser_navigate", {"url": url}, None, "", None)
    # A new tab is navigation too, and a compose link may only name the requested recipient.
    tab = {"action": "new", "url": "https://accounts.google.com/"}
    assert "not permitted" in p.check("browser_tabs", tab, None, "", None)
    ok = native.COMPOSE_URL + "&to=owner@example.com"
    assert p.check("browser_tabs", {"action": "new", "url": ok}, None, "", None) is None
    bad = native.COMPOSE_URL + "&to=owner@example.com&bcc=spy@example.org"
    assert "exact addresses" in p.check("browser_navigate", {"url": bad}, None, "", None)
    # Off a permitted page, nothing but going back or switching tabs is allowed.
    refused = p.check("browser_click", {"target": "e1"}, "https://myaccount.google.com", "", None)
    assert "outside the permitted sites" in refused


def test_nothing_can_be_sent_or_deleted_and_shortcuts_are_refused():
    p = policy()
    gate = SimpleNamespace(permit=True)
    assert "refused" in p.check("browser_click", {"target": "e20"}, COMPOSE, SNAPSHOT, gate)
    assert "refused" in p.check("browser_click", {"target": "e22"}, COMPOSE, SNAPSHOT, gate)
    assert p.check("browser_click", {"target": "e21"}, COMPOSE, SNAPSHOT, gate) is None
    for key in ("Meta+Enter", "Control+Enter", "e", "#"):
        assert "not permitted" in p.check("browser_press_key", {"key": key}, COMPOSE, "", gate)
    assert p.check("browser_press_key", {"key": "Escape"}, COMPOSE, "", gate) is None


def test_writing_needs_a_decision_and_recipients_are_locked():
    p = policy()
    gate = SimpleNamespace(permit=False)
    typed = {"target": "e13", "text": "Latest bill"}
    assert "record_decision" in p.check("browser_type", typed, COMPOSE, SNAPSHOT, gate)
    gate.permit = True
    assert p.check("browser_type", typed, COMPOSE, SNAPSHOT, gate) is None
    assert gate.permit is False and p.writing  # one decision opens writing on this site
    to = {"target": "e12"}
    assert (
        p.check("browser_type", to | {"text": "owner@example.com"}, COMPOSE, SNAPSHOT, gate) is None
    )
    for text in ("someone@else.com", "owner@example.com, x@y.com", "Ana"):
        assert "exact addresses" in p.check(
            "browser_type", to | {"text": text}, COMPOSE, SNAPSHOT, gate
        )
    # Company apps keep their own rules: the gateway gates their writes.
    assert p.check("browser_type", typed, GATEWAY + "/books/bills/new", "", gate) is None


FACTS = {
    "bill": {
        "bill": "INV-920",
        "invoice_no": "RE-1086",
        "vendor": "Residency Estates",
        "issue_date": "2026-09-25",
        "due_date": "2026-10-10",
        "amount": "INR 4,20,000.00",
        "status": "pending approval",
    },
    "vendor": {
        "Tax ID (GSTIN)": "29JWZYK3186A1Z6",
        "Email": "billing@residencyestates.example",
        "Phone": "+91 27 8959 5403",
        "Address": "174, Outer Ring Road, Noida 201301",
    },
    "vendor_path": "/books/vendors/V-136",
    "design": [
        {"author": "Ishita Sen", "body": "Reminder: timesheets due Friday."},
        {"author": "Manoj Reddy", "body": "Shipping the release at 5."},
        {"author": "Meera Iyer", "body": "Can someone review the deck before 3?"},
    ],
}
BODY = (
    "The latest bill is INV-920, invoice RE-1086 from Residency Estates for INR 4,20,000, "
    "due 10 October 2026. Vendor GSTIN 29JWZYK3186A1Z6, email billing@residencyestates.example. "
    "In #design, Ishita reminded everyone that timesheets are due, Manoj is shipping the release "
    "and Meera asked for a deck review."
)


def draft(to="owner@example.com", body=BODY, subject="Latest bill and #design"):
    return {"id": "r1", "headers": {"to": to, "subject": subject}, "body": body}


def test_a_complete_draft_passes_every_check():
    results = native.check_draft(draft(), 1, 0, FACTS, ["owner@example.com"])
    assert {r.condition_id: r.result for r in results} == dict.fromkeys(
        ["c1", "c2", "c3", "c4", "c5", "n1", "n2"], "pass"
    )


def test_wrong_facts_a_sent_message_or_extra_recipient_fail():
    wrong = BODY.replace("4,20,000", "4,00,000")
    by_id = {
        r.condition_id: r
        for r in native.check_draft(draft(body=wrong), 1, 1, FACTS, ["owner@example.com"])
    }
    assert by_id["c3"].result == "fail" and "amount" in by_id["c3"].evidence
    assert by_id["n1"].result == "fail"
    extra = draft(to="owner@example.com, x@y.com")
    by_id = {
        r.condition_id: r.result
        for r in native.check_draft(extra, 1, 0, FACTS, ["owner@example.com"])
    }
    assert by_id["c1"] == "fail" and by_id["n2"] == "fail"
    none = {r.condition_id: r.result for r in native.check_draft(None, 0, 0, FACTS, ["o@e.com"])}
    assert none["c1"] == "fail" and none["c3"] == "fail"


def test_calendar_requests_get_a_window_and_owner_only_rules(monkeypatch):
    from datetime import date

    monkeypatch.setenv("PRECEDENT_NATIVE_GOOGLE", "1")
    request = "Put a 45 minute hold on my Google Calendar next week to review the latest bill"
    assert native.is_native(request) and native.wants_calendar(request)
    assert not native.wants_mail(request)
    slot = native.slot_request(request, today=date(2026, 10, 12))  # a Monday
    assert (slot["minutes"], slot["start"], slot["end"]) == (
        45,
        date(2026, 10, 19),
        date(2026, 10, 24),
    )
    goal = native.native_goal(request)
    assert {c.id for c in goal.conditions} == {"k1", "k2", "k3", "k4", "m1", "m2"}
    p = policy()
    url = native.EDIT_URL + "&dates=20261019T100000/20261019T104500&add=x@y.com"
    assert "owner-only" in p.check("browser_navigate", {"url": url}, None, "", None)
    cal = "https://calendar.google.com/calendar/r/eventedit"
    guests = '- combobox "Add guests" [ref=e9]'
    gate = SimpleNamespace(permit=True)
    assert "owner-only" in p.check(
        "browser_type", {"target": "e9", "text": "owner@example.com"}, cal, guests, gate
    )


def test_calendar_checks_read_the_event_back():
    from datetime import UTC, date, datetime

    since = datetime(2026, 10, 12, 10, tzinfo=UTC)
    slot = {"minutes": 30, "start": date(2026, 10, 19), "end": date(2026, 10, 24),
            "label": "next week", "zone": "Asia/Kolkata"}  # fmt: skip
    event = {
        "id": "ev1", "status": "confirmed", "summary": "Review latest bill",
        "created": "2026-10-12T10:05:00Z",
        "start": {"dateTime": "2026-10-20T11:00:00+05:30"},
        "end": {"dateTime": "2026-10-20T11:30:00+05:30"},
    }  # fmt: skip
    ok = {r.condition_id: r.result for r in native.check_calendar([event], [], slot, since)}
    assert set(ok.values()) == {"pass"}
    late = event | {"end": {"dateTime": "2026-10-20T18:00:00+05:30"}, "attendees": [{"email": "a"}]}
    edited = {"id": "old", "status": "confirmed", "created": "2026-09-01T00:00:00Z"}
    bad = {
        r.condition_id: r.result for r in native.check_calendar([late, edited], [{}], slot, since)
    }
    assert bad["k2"] == bad["k3"] == bad["m1"] == bad["m2"] == "fail"


def test_the_tribunal_hears_native_runs_from_its_own_google_reads(live_apps, tmp_path, monkeypatch):
    """Regression: a hearing once read only the company apps for a Gmail task, failed the draft
    (the company's Mail had none) and left the rest unconfirmed. The native court reads Google."""
    import json

    from precedent.contracts import CheckResult
    from precedent.tribunal.court import convene, read_record
    from tests.test_tribunal import _run_dir

    monkeypatch.setenv("PRECEDENT_NATIVE_GOOGLE", "1")
    base, _ = live_apps
    run = _run_dir(tmp_path, base)
    request = (
        "Draft a mail to owner@example.com about the latest bill, and put a 30 minute hold "
        "on my Google Calendar next week"
    )
    goal = native.native_goal(request)
    lines = []
    for i, line in enumerate((run / "events.jsonl").read_text().splitlines()):
        event = json.loads(line) | {"ts": f"2026-10-12T10:0{i}:00Z"}
        if event["type"] == "run_started":
            event["data"]["request"] = request
        if event["type"] == "goal_contract":
            event["data"] = goal.model_dump()
        lines.append(json.dumps(event))
    (run / "events.jsonl").write_text("\n".join(lines) + "\n")
    seen = {}

    def reads(base_url, req, since, until, headers):
        seen.update(since=since, until=until)
        results = [
            CheckResult(condition_id=c.id, text=c.text, result="pass", evidence="read back")
            for c in goal.conditions
        ]
        draft = {"path": "gmail:draft/r1", "title": "Gmail draft · Bill",
                 "text": "To: owner@example.com\nSubject: Bill", "fields": {}}  # fmt: skip
        return results, [draft], []

    monkeypatch.setattr(native, "tribunal_reads", reads)
    result = convene(run, apps_url=base, jurors=[], screenshots=False)
    assert result["overall"] == "pass"
    assert {c: r["result"] for c, r in result["rulings"].items()} == dict.fromkeys(
        [c.id for c in goal.conditions], "pass"
    )
    record = read_record(run)
    assert any(e["event"] == "exhibit" and e["path"] == "gmail:draft/r1" for e in record)
    charges = {e["id"]: e["text"] for e in record if e["event"] == "charge"}
    assert charges["n1"] == "No email is sent." and charges["m1"].startswith("Nobody")
    assert seen["since"].isoformat().startswith("2026-10-12T10:00")  # the run's own window

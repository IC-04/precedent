"""Layer 1 of the adaptive verifier: generic checks over any company page, the court's own
planner (scripted here; never a real model in tests) and the missed-requirement challenger."""

import httpx

from precedent.tribunal.checks import Cell, Check, combine, provenance, run, safe_path
from precedent.tribunal.court import convene, read_record
from precedent.tribunal.planner import CheckPlan, PageChoice, visited_pages

HEADERS = {"X-Precedent-Agent": "tribunal"}


def _reader(base):
    client = httpx.Client(base_url=base, headers=HEADERS, timeout=10)

    def read(path):
        response = client.get(path)
        response.raise_for_status()
        return response.text

    return read


def _bill_id(base):
    from precedent.worker.verify import Reader

    with httpx.Client(base_url=base, headers=HEADERS, timeout=10) as client:
        return Reader(client, {}, {}).bills_for("FIG-1709")[0]


def test_field_row_and_text_checks_run_exactly_on_live_pages(live_apps):
    base, _ = live_apps
    read, bill = _reader(base), _bill_id(base)
    path = f"/books/bills/{bill}"
    check = lambda **kw: run(Check(condition_id="c1", path=kw.pop("path", path), **kw), read)  # noqa: E731
    assert check(op="field_equals", label="Account", value="6120").result == "pass"
    assert check(op="field_equals", label="Account", value="1400").result == "fail"
    assert check(op="field_equals", label="No such label", value="x").result == "unknown"
    assert check(op="field_present", label="Vendor").result == "pass"
    search = "/books/bills?q=FIG-1709"
    one = [Cell(column="Invoice no.", value="FIG-1709")]
    assert check(op="row_count", path=search, cells=one, value="1").result == "pass"
    assert check(op="row_count", path=search, cells=one, value="2").result == "fail"
    assert check(op="row_exists", path=search, cells=[Cell(column="Nope", value="x")]).result == (
        "unknown"
    )
    assert check(op="text_contains", value="FIG-1709").result == "pass"
    assert check(op="text_contains", value="definitely not on this page").result == "fail"


def test_only_company_pages_can_be_read():
    assert safe_path("/books/bills/INV-1") and safe_path("/books/bills?q=FIG-1&page=2")
    for bad in ("/__scenario/edit", "https://evil.example/x", "/books/../hidden", "/admin", ""):
        assert not safe_path(bad)
    outcome = run(Check(condition_id="c1", op="text_contains", path="/__scenario/x", value="a"),
                  lambda p: "")  # fmt: skip
    assert outcome.result == "unknown"


def test_expected_values_need_a_real_source():
    page = "<main><pre>Design spend above INR 50,000 routes to Ana Pereira.</pre></main>"
    pages = {"/mail/m/m-1": page}
    base = dict(condition_id="c1", op="field_equals", path="/books/bills/B-1", label="Approver")
    cited = Check(**base, value="Ana Pereira", source="/mail/m/m-1",
                  source_quote="routes to Ana Pereira")  # fmt: skip
    assert provenance(cited, "r", "c", pages) is None
    invented = cited.model_copy(update={"source_quote": "routes to Raj Mehta"})
    assert "not found" in provenance(invented, "r", "c", pages)
    wrong_value = cited.model_copy(update={"value": "Raj Mehta"})
    assert "not in the cited source" in provenance(wrong_value, "r", "c", pages)
    from_request = Check(**base, value="Ana Pereira", source="request")
    assert provenance(from_request, "Route it to Ana Pereira", "c", pages) is None
    assert provenance(Check(**base, value="Ana Pereira"), "r", "c", pages) is not None
    count = Check(condition_id="c1", op="row_count", path="/books/bills?q=X", value="1",
                  cells=[Cell(column="Invoice no.", value="X")], source="condition")  # fmt: skip
    assert provenance(count, "r", "exactly one bill for invoice X", pages) is None


def test_combine_never_upgrades():
    from precedent.tribunal.checks import Outcome

    p, f, u = (Outcome(result=r, evidence=r) for r in ("pass", "fail", "unknown"))
    assert combine([]) is None
    assert combine([p, p]).result == "pass"
    assert combine([p, u]).result == "unknown"
    assert combine([p, u, f]).result == "fail"


def test_visited_pages_come_from_the_logs_not_claims():
    events = [
        {"type": "observation", "data": {"url": "http://localhost:9/books/bills/B-7"}},
        {"type": "note", "data": {"kind": "app_effect", "path": "/books/bills/new"}},
        {
            "type": "note",
            "data": {"kind": "app_effect", "path": "/books/bills/B-7/request-approval"},
        },
        {"type": "note", "data": {"kind": "goal_progress", "evidence": "/books/bills/B-99"}},
        {"type": "observation", "data": {"url": "http://localhost:9/__scenario/edit"}},
    ]
    assert visited_pages(events) == ["/books/bills/B-7"]


def test_the_court_plans_checks_itself_and_adds_missed_requirements(live_apps, tmp_path):
    from tests.test_tribunal import _run_dir

    base, _ = live_apps
    run_dir = _run_dir(tmp_path, base)
    bill = _bill_id(base)
    prompts = []

    def ask(instruction, prompt, schema):
        prompts.append(prompt)
        if schema is PageChoice:
            return PageChoice(pages=[f"/books/bills/{bill}", "/books/bills?q=FIG-1709", "/__x"])
        return CheckPlan(
            checks=[
                Check(condition_id="c1", op="row_count", path="/books/bills?q=FIG-1709",
                      cells=[Cell(column="Invoice no.", value="FIG-1709")], value="1",
                      source="condition"),
                Check(condition_id="c2", op="field_equals", path=f"/books/bills/{bill}",
                      label="Account", value="1400", source="condition"),
                Check(condition_id="u1", op="field_present", path=f"/books/bills/{bill}",
                      label="Attachment"),
                Check(condition_id="c9", op="field_present", path=f"/books/bills/{bill}",
                      label="Vendor"),
            ],
            uncovered=["The bill has its invoice file attached"],
        )  # fmt: skip

    result = convene(run_dir, apps_url=base, jurors=[], screenshots=False,
                     planner=("scripted", ask))  # fmt: skip
    rulings = result["rulings"]
    assert rulings["c1"]["result"] == "pass"  # one bill, by the court's own count
    assert rulings["c2"]["result"] == "fail"  # the condition says 1400; the record says 6120
    assert rulings["u1"]["basis"] == "exact" and result["missed"][0]["id"] == "u1"
    assert "c9" not in rulings  # a check for an unknown condition is dropped
    events = read_record(run_dir)
    assert any(e["event"] == "plan" and e["checks"] == 3 for e in events)
    assert sum(e["event"] == "check" for e in events) == 3
    assert any(e["event"] == "charge" and e.get("added") for e in events)
    assert not any("/__x" in str(e.get("path", "")) for e in events if e["event"] == "exhibit")
    assert all("coded to 1400" not in p for p in prompts)  # Ava's claim never reaches the planner


def test_a_record_cannot_prove_itself_and_quotes_match_by_words():
    pages = {
        "/mail/drafts/d-1": "<dl><dt>Status</dt><dd>draft</dd></dl>",
        "/calendar/context": "<dl><dt>Organizer ID</dt><dd>E-priya</dd></dl>",
    }
    circular = Check(condition_id="c1", op="field_equals", path="/mail/drafts/d-1",
                     label="Status", value="draft", source="/mail/drafts/d-1",
                     source_quote="Status draft")  # fmt: skip
    assert "cannot be the source" in provenance(circular, "r", "c", pages)
    directory = Check(condition_id="c1", op="field_equals", path="/mail/drafts/d-1",
                      label="Organizer ID", value="E-priya", source="/calendar/context",
                      source_quote="Organizer ID: E-priya")  # fmt: skip
    assert provenance(directory, "r", "c", pages) is None


def test_a_specialist_verdict_is_not_overridden_by_a_planned_check():
    from precedent.contracts import CheckResult, Condition
    from precedent.tribunal.checks import Outcome
    from precedent.tribunal.court import merge

    c = Condition(id="n1", text="No duplicate bill", kind="must_not_happen")
    spec = CheckResult(condition_id="n1", text="", result="pass", evidence="1 bill")
    wrong = Outcome(result="fail", evidence="13 matching rows, expected 1")
    merged = merge(c, spec, wrong)
    assert merged.result == "pass" and "disagree" in merged.evidence
    gap = CheckResult(condition_id="n1", text="", result="unknown", evidence="no source")
    assert merge(c, gap, wrong).result == "fail"  # the planned check fills a gap
    assert merge(c, None, None).result == "unknown"

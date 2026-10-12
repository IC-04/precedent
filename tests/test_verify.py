"""The worker's verifier: fresh reads through the apps' pages; unknown, never a false pass."""

import httpx
import pytest

from precedent.contracts import Condition, GoalContract
from precedent.worker.verify import CheckPlan, CheckSpec, Reader, _equal, outcome, run_check, verify


@pytest.mark.parametrize(
    "actual, expect, ok",
    [
        ("1400 Prepaid expenses", "1400", True),
        ("Figma (V-112)", "V-112", True),
        ("17CFEHX1197R1ZM", "x", False),
        ("6120 Software subscriptions", "1400", False),
        ("INR 1,12,000.00", "112000", True),
        ("INR 1,12,000.00", "1,12,000", True),
        ("INR 1,12,000.00", "11200", False),
        ("INR 1,12,000.00", "112000 INR", True),
        ("INR 1,12,000.00", "₹112,000", True),
        ("INR 112000", "112000 USD", False),
        ("INR -112000", "112000 INR", False),
        ("Ana Pereira", "ana pereira", True),
        ("Raj Mehta", "Ana Pereira", False),
        (None, "1400", None),
    ],
)
def test_matching_is_whole_token_never_substring(actual, expect, ok):
    assert _equal(actual, expect) is ok


def _reader(live_apps, first_seen=None):
    base, _ = live_apps
    return Reader(httpx.Client(base_url=base), first_seen or {})


def test_primitives_read_fresh_pages(live_apps):
    r = _reader(live_apps)

    def check(**kw):
        return run_check(r, CheckSpec(condition_id="c", **kw), "t").result

    assert check(primitive="count_bills", invoice_no="FIG-1709", expect="1") == "pass"
    assert check(primitive="count_bills", invoice_no="FIG-1842", expect="1") == "fail"
    assert (
        check(primitive="count_bills", invoice_no="FIG-1709", vendor_id="V-112", expect="1")
        == "pass"
    )
    assert (
        check(primitive="count_bills", invoice_no="FIG-1709", vendor_id="V-999", expect="0")
        == "pass"
    )
    assert (
        check(primitive="bill_field", invoice_no="FIG-1709", field="Account", expect="6120")
        == "pass"
    )
    assert (
        check(primitive="bill_field", invoice_no="FIG-1709", field="Account", expect="1400")
        == "fail"
    )
    assert check(primitive="approval_status", invoice_no="FIG-1709", expect="approved") == "pass"
    assert (
        check(primitive="bill_field", invoice_no="NOPE-1", field="Account", expect="1") == "unknown"
    )


def test_unchanged_needs_an_earlier_reading(live_apps):
    base, _ = live_apps
    before = httpx.get(f"{base}/books/vendors/V-112").text
    edit = httpx.get(f"{base}/books/vendors/V-112/edit").text
    spec = CheckSpec(
        condition_id="n1", primitive="field_unchanged", vendor_id="V-112", field="Bank account"
    )

    assert run_check(_reader(live_apps), spec, "t").result == "unknown"
    assert (
        run_check(_reader(live_apps, {"/books/vendors/V-112": before}), spec, "t").result
        == "unknown"
    )
    baseline = {"/books/vendors/V-112/edit": edit}
    assert run_check(_reader(live_apps, baseline), spec, "t").result == "pass"
    from precedent.worker.verify import FormValues

    account = FormValues(edit).values["bank_account"]
    changed = edit.replace(account, "Another bank ending " + account[-4:])
    assert (
        run_check(_reader(live_apps, {"/books/vendors/V-112/edit": changed}), spec, "t").result
        == "fail"
    )


def test_shared_latest_proof_requires_same_source_and_actual_vendor(live_apps):
    from precedent.worker.verify import linked_latest

    reader = _reader(live_apps)
    latest = CheckSpec(
        condition_id="selection", primitive="latest_invoice", vendor_id="V-112", expect="f-0004"
    )
    field = CheckSpec(
        condition_id="amount",
        primitive="bill_field",
        invoice_no="FIG-1709",
        field="Amount",
        source_path="/drive/f/f-0004",
    )
    plan = CheckPlan(checks=[latest, field])
    assert linked_latest(reader, [field], plan) == latest
    assert (
        linked_latest(reader, [field.model_copy(update={"source_path": "/drive/f/other"})], plan)
        is None
    )
    wrong = latest.model_copy(update={"vendor_id": "V-other"})
    assert linked_latest(reader, [field], CheckPlan(checks=[wrong, field])) is None


def test_unmapped_conditions_are_unknown_and_outcome_needs_every_pass(live_apps):
    base, _ = live_apps
    goal = GoalContract(request="r", outcome="o", conditions=[
        Condition(id="c1", text="one bill", kind="must_be_true"),
        Condition(id="c2", text="something unreadable", kind="must_be_true"),
    ])  # fmt: skip
    plan = CheckPlan(checks=[CheckSpec(condition_id="c1", primitive="count_bills",
                                       invoice_no="FIG-1709", expect="1")])  # fmt: skip
    seen = []
    results = verify(base, goal, plan, {}, seen.append)
    assert [r.result for r in results] == ["pass", "unknown"] and len(seen) == 2
    assert outcome(results, None, False) == "unknown"
    assert outcome(results[:1], None, False) == "pass"
    assert outcome(results[:1], "budget used", False) == "unknown"
    assert outcome([], None, True) == "blocked"


def test_an_unreadable_search_page_is_unknown_not_zero(live_apps):
    base, _ = live_apps

    class Broken(Reader):
        def html(self, path, params=None):
            return "<html><body>Maintenance</body></html>"

    spec = CheckSpec(condition_id="c", primitive="count_bills", invoice_no="FIG-1842", expect="0")
    assert run_check(Broken(httpx.Client(base_url=base), {}), spec, "t").result == "unknown"
    odd = CheckSpec(condition_id="c", primitive="count_bills", invoice_no="A&B #1", expect="0")
    assert run_check(_reader(live_apps), odd, "t").result == "pass"  # encoded, searched, none


def test_compound_condition_cannot_pass_on_approver_only(live_apps):
    base, _ = live_apps
    goal = GoalContract(
        request="r",
        outcome="o",
        conditions=[
            Condition(
                id="c1",
                text="The bill status is pending approval and routed to the correct approver.",
                kind="must_be_true",
            )
        ],
    )
    plan = CheckPlan(
        checks=[
            CheckSpec(
                condition_id="c1",
                primitive="bill_field",
                invoice_no="FIG-1709",
                field="Approver",
                expect="Ana Pereira",
            )
        ]
    )
    assert verify(base, goal, plan, {}, lambda r: None)[0].result == "unknown"


def test_attachment_compares_browser_visible_file_identity(live_apps):
    r = _reader(live_apps)
    from precedent.worker.verify import record_links
    from precedent.world import db

    _, conn = live_apps
    import sqlite3

    conn.row_factory = sqlite3.Row
    bid = r.bills_for("FIG-1709")[0]
    before = db.row(conn, "bills", bid)
    fid = conn.execute("SELECT id FROM files ORDER BY id LIMIT 1").fetchone()[0]
    db.write(
        conn,
        "system",
        "books",
        "bill.update",
        "bills",
        bid,
        before,
        {**before, "attachment_file_id": fid},
    )
    conn.commit()
    page = r.html("/books/bills/" + bid)
    fid = record_links(page)["Attachment"].rsplit("/", 1)[-1]
    spec = CheckSpec(
        condition_id="c",
        primitive="bill_field",
        invoice_no="FIG-1709",
        field="Attachment",
        expect=fid,
    )
    assert run_check(r, spec, "attachment").result == "pass"
    spec.expect = "wrong-file-id"
    assert run_check(r, spec, "attachment").result == "fail"


def test_duplicate_specs_are_unknown(live_apps):
    base, _ = live_apps
    goal = GoalContract(
        request="r",
        outcome="o",
        conditions=[Condition(id="c1", text="one bill", kind="must_be_true")],
    )
    spec = CheckSpec(condition_id="c1", primitive="count_bills", invoice_no="FIG-1709", expect="1")
    assert (
        verify(base, goal, CheckPlan(checks=[spec, spec]), {}, lambda r: None)[0].result
        == "unknown"
    )


def test_latest_invoice_is_proved_from_accessible_mail_candidates(live_apps):
    result = run_check(
        _reader(live_apps),
        CheckSpec(condition_id="c", primitive="latest_invoice", vendor_id="V-112", expect="f-0004"),
        "Latest invoice is identified",
    )
    assert result.result == "pass", result.evidence
    assert "candidates:" in result.evidence


def test_typed_dates_and_approval_status_normalize_without_weakening(live_apps):
    r = _reader(live_apps)
    from precedent.worker.verify import record_fields

    bid = r.bills_for("FIG-1709")[0]
    from datetime import datetime

    iso = record_fields(r.html("/books/bills/" + bid))["Invoice date"]
    human = datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b %Y")
    check = CheckSpec(
        condition_id="c", primitive="bill_field", bill_id=bid, field="Invoice date", expect=human
    )
    assert run_check(r, check, "invoice date").result == "pass"
    check.expect = "01 Jan 1999"
    assert run_check(r, check, "invoice date").result == "fail"
    check = CheckSpec(
        condition_id="c", primitive="approval_status", bill_id=bid, expect="pending approval"
    )
    assert run_check(r, check, "approval").result == "fail"  # this historic bill is approved
    check.expect = "submitted"
    assert run_check(r, check, "approval").result == "unknown"


def test_email_self_reference_binds_to_sender_with_literal_body_quote(live_apps):
    base, _ = live_apps
    source = httpx.get(base + "/mail/m/m-0001").text
    # Historical bill's approver differs from this authority: supported expectation must fail,
    # rather than becoming unknown merely because the body says 'me'.
    goal = GoalContract(
        request="r",
        outcome="o",
        conditions=[
            Condition(
                id="c",
                text="The bill has the correct approver",
                kind="must_be_true",
                claims=["Approver"],
            )
        ],
    )
    plan = CheckPlan(
        checks=[
            CheckSpec(
                condition_id="c",
                primitive="bill_field",
                invoice_no="FIG-1709",
                field="Approver",
                expect="Ana Pereira",
                source_path="/mail/m/m-0001",
                source_quote=(
                    "From 14 July, design spend above INR 50,000 routes to me instead of Raj."
                ),
            )
        ]
    )
    result = verify(base, goal, plan, {"/mail/m/m-0001": source}, lambda r: None)[0]
    assert result.result == "fail", result.evidence
    plan.checks[0].source_quote = "Invented sender attribution routes to me."
    assert (
        verify(base, goal, plan, {"/mail/m/m-0001": source}, lambda r: None)[0].result == "unknown"
    )


def test_bill_status_vocabulary_and_shared_target_link(live_apps):
    import sqlite3

    from precedent.worker.verify import linked_bill_status
    from precedent.world import db

    reader = _reader(live_apps)
    bid = reader.bills_for("FIG-1709")[0]
    conn = live_apps[1]
    conn.row_factory = sqlite3.Row
    before = db.row(conn, "bills", bid)
    db.write(
        conn,
        "system",
        "books",
        "bill.update",
        "bills",
        bid,
        before,
        {**before, "status": "pending_approval"},
    )
    conn.commit()
    status = CheckSpec(
        condition_id="state",
        primitive="bill_field",
        bill_id=bid,
        field="Status",
        expect="pending_approval",
    )
    assert run_check(reader, status, "Bill status is pending approval").result == "pass"
    approval = CheckSpec(
        condition_id="route", primitive="approval_status", invoice_no="FIG-1709", expect="approved"
    )
    assert (
        linked_bill_status(reader, [approval], CheckPlan(checks=[status, approval]), "Status")
        == status
    )
    wrong = status.model_copy(update={"bill_id": "INV-not-this-bill"})
    assert (
        linked_bill_status(reader, [approval], CheckPlan(checks=[wrong, approval]), "Status")
        is None
    )


def test_chart_names_do_not_prove_policy_applicability(live_apps):
    from precedent.worker.verify import _tokens

    assert _tokens("1400,Prepaid expenses,asset") == ["1400", "prepaid", "expenses", "asset"]
    base, _ = live_apps
    path = "/drive/f/f-0003"
    goal = GoalContract(
        request="r",
        outcome="o",
        conditions=[
            Condition(
                id="c",
                text="Bill account code follows policy",
                kind="must_be_true",
                claims=["Account"],
            )
        ],
    )
    plan = CheckPlan(
        checks=[
            CheckSpec(
                condition_id="c",
                primitive="bill_field",
                invoice_no="FIG-1709",
                field="Account",
                expect="6120 Software subscriptions",
                source_path=path,
                source_quote="6120,Software subscriptions,expense",
            )
        ]
    )
    checks = verify(base, goal, plan, {path: httpx.get(base + path).text}, lambda r: None)
    assert checks[0].result == "unknown"


def test_latest_invoice_without_an_expectation_is_unknown_not_fail(live_apps):
    from precedent.worker.verify import CheckSpec, latest_invoice

    reader = _reader(live_apps)
    spec = CheckSpec(condition_id="c1", primitive="latest_invoice", vendor_id="V-112")
    assert latest_invoice(reader, spec, "latest invoice").result == "unknown"

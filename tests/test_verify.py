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
    spec = CheckSpec(condition_id="n1", primitive="field_unchanged", vendor_id="V-112",
                     field="Bank account")  # fmt: skip
    assert run_check(_reader(live_apps), spec, "t").result == "unknown"
    assert (
        run_check(_reader(live_apps, {"/books/vendors/V-112": before}), spec, "t").result == "pass"
    )
    changed = before.replace("account ending", "account ending 0000 was")
    assert (
        run_check(_reader(live_apps, {"/books/vendors/V-112": changed}), spec, "t").result == "fail"
    )


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

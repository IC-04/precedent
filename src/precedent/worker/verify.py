"""Stage 6: verify the goal contract on freshly read pages, never on the worker's memory.

The worker's verifier lives inside the worker's world: it reads the apps' pages through
the gateway like any other read (D8). A model maps each goal condition to one check
primitive; the primitive runs in code. A condition that cannot be mapped, or a check that
cannot run, is `unknown`, never `pass`. The grader, outside, is what the evaluation trusts.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from html import unescape
from typing import Literal

import httpx
from pydantic import BaseModel

from precedent.contracts import CheckResult, GoalContract
from precedent.worker.context import read_page

Primitive = Literal[
    "count_bills",
    "bill_field",
    "approval_status",
    "vendor_field",
    "field_unchanged",
]


class CheckSpec(BaseModel):
    condition_id: str
    primitive: Primitive | None = None  # None: the condition cannot be checked by reading
    invoice_no: str | None = None
    bill_id: str | None = None
    vendor_id: str | None = None
    field: str | None = None  # a label as shown on the record page, e.g. "Account"
    expect: str | None = None  # expected value, compared without regard to case or spacing


class CheckPlan(BaseModel):
    checks: list[CheckSpec]


CATALOGUE = """Check primitives (each reads a fresh page):
- count_bills(invoice_no): how many bills carry this invoice number. expect: the number.
- bill_field(bill_id or invoice_no, field): a field on the bill page. Fields: Status,
  Vendor, Invoice number, Amount, Invoice date, Due date, Account, Approver, Attachment.
- approval_status(bill_id or invoice_no): status of the latest approval request.
- vendor_field(vendor_id, field): a field on the vendor page (Status, Name, Tax ID (GSTIN),
  Email, Phone, Address, Bank account).
- field_unchanged(vendor_id, field): the field equals what it was when first read in this
  run (use for "must not change" conditions). No expect needed.
Map every condition. If a condition cannot be checked by reading these pages, give it
primitive null; it will be reported as unknown."""


def plan_prompt(goal: GoalContract, facts: list[str], decisions: list[str]) -> str:
    conditions = "\n".join(f"- {c.id} ({c.kind}): {c.text}" for c in goal.conditions)
    return (
        f"{CATALOGUE}\n\nGoal conditions:\n{conditions}\n\nFacts from the run:\n"
        + "\n".join(f"- {f}" for f in facts)
        + "\n\nDecisions recorded:\n"
        + "\n".join(f"- {d}" for d in decisions)
        + "\n\nReturn one check per condition, with the expected values the facts and "
        "decisions imply."
    )


# --------------------------------------------------------------------------- reading


def _clean(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def record_fields(html: str) -> dict[str, str]:
    """dt/dd pairs of a record page, keyed by label."""
    pairs = re.findall(r"<dt>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", html, re.S)
    return {_clean(k): _clean(v) for k, v in pairs}


def _tokens(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9@._-]+", (value or "").lower().replace(",", ""))


def _number(value: str | None) -> float | None:
    digits = re.sub(r"[^0-9.]", "", (value or "").replace(",", ""))
    try:
        return float(digits) if digits and re.search(r"\d", value or "") else None
    except ValueError:
        return None


class Reader:
    """Fresh GET reads through the gateway, with the URL kept as evidence."""

    def __init__(self, client: httpx.Client, first_seen: dict[str, str]):
        self.client, self.first_seen = client, first_seen

    def html(self, path: str) -> str:
        response = self.client.get(path)
        response.raise_for_status()
        return response.text

    def bills_for(self, invoice_no: str) -> list[str]:
        page = read_page(self.html(f"/books/bills?q={invoice_no}"))
        return [r[0] for r in page.rows if len(r) > 1 and r[1].strip() == invoice_no]

    def bill_id(self, spec: CheckSpec) -> str | None:
        if spec.bill_id:
            return spec.bill_id
        ids = self.bills_for(spec.invoice_no or "")
        return ids[0] if len(ids) == 1 else None


def _result(
    spec: CheckSpec, text: str, actual: str | None, ok: bool | None, evidence: str
) -> CheckResult:
    result = "unknown" if ok is None else ("pass" if ok else "fail")
    detail = f"{evidence}: found {actual!r}" + (
        f", expected {spec.expect!r}" if spec.expect else ""
    )
    return CheckResult(condition_id=spec.condition_id, text=text, result=result, evidence=detail)


def _equal(actual: str | None, expect: str | None) -> bool | None:
    """Whole-token match, never a substring: '1400' matches '1400 Prepaid expenses' and
    'V-112' matches 'Figma (V-112)', but 'x' matches nothing. Amounts compare as numbers."""
    if expect is None or actual is None:
        return None
    if _tokens(actual) == _tokens(expect):
        return True
    a_num, e_num = _number(actual), _number(expect)
    if (
        a_num is not None
        and e_num is not None
        and re.fullmatch(r"[\sA-Za-z₹.]*[\d,.]+", expect.strip())
    ):
        return abs(a_num - e_num) < 0.005
    a, e = _tokens(actual), _tokens(expect)
    return bool(e) and any(a[k : k + len(e)] == e for k in range(len(a) - len(e) + 1))


def run_check(reader: Reader, spec: CheckSpec, text: str) -> CheckResult:
    """One primitive on fresh pages. Any reading problem is unknown, never pass."""
    try:
        if spec.primitive == "count_bills":
            ids = reader.bills_for(spec.invoice_no or "")
            ok = None if spec.expect is None else str(len(ids)) == spec.expect.strip()
            return _result(spec, text, str(len(ids)), ok, f"/books/bills?q={spec.invoice_no}")
        if spec.primitive in ("bill_field", "approval_status"):
            bid = reader.bill_id(spec)
            if bid is None:
                return _result(spec, text, None, None, "no single bill found")
            html = reader.html(f"/books/bills/{bid}")
            if spec.primitive == "bill_field":
                actual = record_fields(html).get(spec.field or "")
            else:
                rows = [r for r in read_page(html).rows if len(r) >= 4 and r[0] != "Approver"]
                actual = rows[-1][1] if rows else None
            return _result(spec, text, actual, _equal(actual, spec.expect), f"/books/bills/{bid}")
        if spec.primitive in ("vendor_field", "field_unchanged"):
            path = f"/books/vendors/{spec.vendor_id}"
            actual = record_fields(reader.html(path)).get(spec.field or "")
            if spec.primitive == "vendor_field":
                return _result(spec, text, actual, _equal(actual, spec.expect), path)
            before_html = reader.first_seen.get(path)
            if before_html is None:
                return _result(spec, text, actual, None, f"{path} was not read earlier in the run")
            before = record_fields(before_html).get(spec.field or "")
            spec = spec.model_copy(update={"expect": before})
            return _result(spec, text, actual, None if before is None else before == actual, path)
    except httpx.HTTPError as e:
        return _result(spec, text, None, None, f"read failed ({type(e).__name__})")
    return _result(spec, text, None, None, "no check primitive for this condition")


def verify(
    base_url: str,
    goal: GoalContract,
    plan: CheckPlan,
    first_seen: dict[str, str],
    emit: Callable[[CheckResult], None],
    headers: dict[str, str] | None = None,
) -> list[CheckResult]:
    texts = {c.id: c.text for c in goal.conditions}
    specs = {s.condition_id: s for s in plan.checks if s.condition_id in texts}
    results = []
    with httpx.Client(base_url=base_url, headers=headers or {}, timeout=20) as client:
        reader = Reader(client, first_seen)
        for cid, text in texts.items():
            spec = specs.get(cid, CheckSpec(condition_id=cid))
            result = run_check(reader, spec, text)
            emit(result)
            results.append(result)
    return results


def outcome(results: list[CheckResult], stop_reason: str | None, blocked: bool) -> str:
    """pass only if every check passed; blocked and unknown are real outcomes too."""
    if blocked:
        return "blocked"
    if any(r.result == "fail" for r in results):
        return "fail"
    if not results or stop_reason or any(r.result == "unknown" for r in results):
        return "unknown"
    return "pass"

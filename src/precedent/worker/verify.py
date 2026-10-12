"""Stage 6: verify the goal contract on freshly read pages, never on the worker's memory.

The worker's verifier lives inside the worker's world: it reads the apps' pages through
the gateway like any other read (D8). A model maps each goal condition to one check
primitive; the primitive runs in code. A condition that cannot be mapped, or a check that
cannot run, is `unknown`, never `pass`. The grader, outside, is what the evaluation trusts.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser
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
    "vendor_unchanged",
    "latest_invoice",
]


class CheckSpec(BaseModel):
    condition_id: str
    primitive: Primitive | None = None  # None: the condition cannot be checked by reading
    invoice_no: str | None = None
    bill_id: str | None = None
    vendor_id: str | None = None
    field: str | None = None  # a label as shown on the record page, e.g. "Account"
    expect: str | None = None  # typed expectation from a captured source
    source_path: str | None = None
    source_quote: str | None = None


class CheckPlan(BaseModel):
    checks: list[CheckSpec]


CATALOGUE = """Check primitives (each reads a fresh page):
- count_bills(invoice_no, vendor_id): how many bills match this business key. expect: the number.
- bill_field(bill_id or invoice_no, field): a field on the bill page. Fields: Status,
  Vendor, Invoice number, Amount, Invoice date, Due date, Account, Approver, Attachment.
- approval_status(bill_id or invoice_no): status of the latest approval request.
- vendor_field(vendor_id, field): a field on the vendor page (Status, Name, Tax ID (GSTIN),
  Email, Phone, Address, Bank account).
- field_unchanged(vendor_id, field): the field equals what it was when first read in this
  run (use for "must not change" conditions). No expect needed.
- latest_invoice(vendor_id): latest dated invoice in accessible vendor mail attachments.
  expect: Drive file ID.
- vendor_unchanged(vendor_id): every displayed vendor field equals the pre-write baseline.
Map every condition. If a condition cannot be checked by reading these pages, give it
primitive null; it will be reported as unknown."""


def plan_prompt(
    goal: GoalContract,
    facts: list[str],
    decisions: list[str],
    sources: dict[str, str] | None = None,
) -> str:
    conditions = "\n".join(
        f"- {c.id} ({c.kind}): {c.text}; required claims: {c.claims}" for c in goal.conditions
    )
    return (
        f"{CATALOGUE}\n\nGoal conditions:\n{conditions}\n\nFacts from the run:\n"
        + "\n".join(f"- {f}" for f in facts)
        + "\n\nDecisions recorded:\n"
        + "\n".join(f"- {d}" for d in decisions)
        + "\n\nReturn one check per atomic claim (multiple different checks for a compound "
        "condition). For bill/vendor fields include source_path and source_quote copied "
        "from the captured source page EXACTLY, never paraphrased; "
        "never use the target bill as its own source. "
        "For email routing, source_quote must be the EXACT body sentence only. "
        "The verifier binds 'me' to the captured email sender; do not concatenate fragments. "
        "For Account, cite the applicable accounting policy, not just a chart-of-accounts row. "
        "Attachment expect must be the file ID, with source_path pointing to its Drive page. "
        "Status/count expectations come from the goal. vendor_unchanged compares the whole "
        "vendor record against a baseline before writes. Unknown coverage stays null.\n\n"
        + "Captured source pages:\n"
        + "\n".join(
            f"{path}: {(' '.join(read_page(html).pre) or _clean(html))[:4500]}"
            for path, html in (sources or {}).items()
            if re.match(r"^/(drive/f/[^/]+|mail/m/[^/]+|books/vendors/[^/]+)$", path)
        )
    )


# --------------------------------------------------------------------------- reading


def _clean(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def record_fields(html: str) -> dict[str, str]:
    """dt/dd pairs of a record page, keyed by label."""
    pairs = re.findall(r"<dt>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", html, re.S)
    return {_clean(k): _clean(v) for k, v in pairs}


def record_links(html: str) -> dict[str, str]:
    pairs = re.findall(r"<dt>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", html, re.S)
    result = {}
    for key, value in pairs:
        href = re.search(r'href=["\']([^"\']+)', value)
        if href:
            result[_clean(key)] = unescape(href[1])
    return result


class FormValues(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.select = None
        self.textarea = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name"):
            self.values[attrs["name"]] = attrs.get("value", "")
        if tag == "select":
            self.select = attrs.get("name")
        if tag == "option" and self.select and "selected" in attrs:
            self.values[self.select] = attrs.get("value", "")
        if tag == "textarea":
            self.textarea = attrs.get("name")
            if self.textarea:
                self.values[self.textarea] = ""

    def handle_endtag(self, tag):
        if tag == "select":
            self.select = None
        if tag == "textarea":
            self.textarea = None

    def handle_data(self, data):
        if self.textarea:
            self.values[self.textarea] += data


def required_claims(condition) -> set[str]:
    """Conservative coverage floor for retained free-text contracts as well as typed ones.

    The schema declares coverage. This floor prevents common compound claims from
    being silently narrowed by a model. Unrecognized declared claims stay unknown.
    """
    text = condition.text.casefold()
    claims = set(condition.claims)
    patterns = {
        "Amount": r"amount|total",
        "Invoice number": r"invoice number",
        "Invoice date": r"invoice date|issue date|bill date",
        "Due date": r"due date",
        "Attachment": r"attach",
        "Account": r"account code|coding|ledger account",
        "Approver": r"correct approver|designated approver|approver identity",
        "Status": r"bill status|pending approval",
        "bill_count": r"duplicate bill|no duplicate|one bill",
        "vendor_unchanged": r"vendor.*(?:settings|profile|details).*(?:not|unchanged)|bank.*not",
        "latest_invoice": r"latest.*(?:identified|retrieved|selected)",
        "unsupported": r"line.items|unrelated|all company|other (?:records|bills|invoices)",
    }
    claims.update(key for key, pattern in patterns.items() if re.search(pattern, text))
    if "and" in text and "date" in text and "number" in text:
        claims.update({"Invoice number", "Invoice date"})
    return claims


def claim_key(spec: CheckSpec) -> str:
    if spec.primitive == "bill_field":
        return spec.field or "unsupported"
    if spec.primitive == "count_bills":
        return "bill_count"
    if spec.primitive == "field_unchanged":
        return "unchanged:" + (spec.field or "")
    if spec.primitive == "vendor_field":
        return "vendor:" + (spec.field or "")
    return spec.primitive or "unsupported"


def _tokens(value: str | None) -> list[str]:
    value = re.sub(r"(?<=\d),(?=\d)", "", (value or "").lower())
    return re.findall(r"[a-z0-9@._-]+", value)


def _amount(value: str) -> tuple[Decimal, str | None] | None:
    currency = r"INR|USD|EUR|GBP|₹|\$|€|£"
    match = re.fullmatch(
        rf"\s*({currency})?\s*([-+]?\d[\d,]*(?:\.\d+)?)\s*({currency})?\s*",
        value,
        re.I,
    )
    if not match:
        return None
    aliases = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP"}
    codes = [aliases.get(c, c.upper()) for c in (match[1], match[3]) if c]
    if len(set(codes)) > 1:
        return None
    return Decimal(match[2].replace(",", "")), codes[0] if codes else None


class UnreadablePage(Exception):
    """A page loaded but did not contain what a check needs: the check is unknown."""


class Reader:
    """Fresh GET reads through the gateway, with the URL kept as evidence."""

    def __init__(
        self,
        client: httpx.Client,
        first_seen: dict[str, str],
        baselines: dict[str, str] | None = None,
    ):
        self.client, self.first_seen = client, first_seen
        self.baselines = first_seen if baselines is None else baselines
        self.cache = {}

    def html(self, path: str, params: dict | None = None) -> str:
        key = (path, tuple(sorted((params or {}).items())))
        if key in self.cache:
            return self.cache[key]
        response = self.client.get(path, params=params)
        response.raise_for_status()
        self.cache[key] = response.text
        return response.text

    def bills_for(self, invoice_no: str, vendor_id: str | None = None) -> list[str]:
        """Bill ids with exactly this invoice number. A page without the bills table raises,
        so an unreadable page is unknown rather than 'no bills'."""
        found = []
        for page_no in range(1, 101):
            params = {"q": invoice_no, "page": page_no}
            if vendor_id:
                params["vendor"] = vendor_id
            page = read_page(self.html("/books/bills", params=params))
            if not any(r[:2] == ["Bill", "Invoice no."] for r in page.rows):
                raise UnreadablePage("the bills table was not found on the search page")
            found.extend(r[0] for r in page.rows if len(r) > 1 and r[1].strip() == invoice_no)
            if not any("next" in label.casefold() for _, label in page.links):
                return list(dict.fromkeys(found))
        raise UnreadablePage("bill search exceeded the bounded pagination limit")

    def bill_id(self, spec: CheckSpec) -> str | None:
        if spec.bill_id:
            return spec.bill_id
        ids = self.bills_for(spec.invoice_no or "", spec.vendor_id)
        return ids[0] if len(ids) == 1 else None


def _result(
    spec: CheckSpec, text: str, actual: str | None, ok: bool | None, evidence: str
) -> CheckResult:
    result = "unknown" if ok is None else ("pass" if ok else "fail")
    detail = f"{evidence}: found {actual!r}" + (
        f", expected {spec.expect!r}" if spec.expect else ""
    )
    return CheckResult(condition_id=spec.condition_id, text=text, result=result, evidence=detail)


def date_value(value: str | None) -> str | None:
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime((value or "").strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _equal(actual: str | None, expect: str | None) -> bool | None:
    """Whole-token match, never a substring: '1400' matches '1400 Prepaid expenses' and
    'V-9' matches 'Acme (V-9)', but 'x' matches nothing. Amounts compare as numbers."""
    if expect is None or actual is None:
        return None
    if _tokens(actual) == _tokens(expect):
        return True
    a_amount, e_amount = _amount(actual), _amount(expect)
    if a_amount is not None and e_amount is not None:
        if a_amount[1] and e_amount[1] and a_amount[1] != e_amount[1]:
            return False
        return abs(a_amount[0] - e_amount[0]) < Decimal("0.005")
    a, e = _tokens(actual), _tokens(expect)
    return bool(e) and any(a[k : k + len(e)] == e for k in range(len(a) - len(e) + 1))


def latest_invoice(reader: Reader, spec: CheckSpec, text: str) -> CheckResult:
    vendor = record_fields(reader.html(f"/books/vendors/{spec.vendor_id}"))
    email, legal = vendor.get("Email"), vendor.get("Legal name") or vendor.get("Name")
    if not email or not legal:
        raise UnreadablePage("vendor sender identity is unavailable")
    messages = set()
    for n in range(1, 101):
        page = read_page(reader.html("/mail/", {"q": email, "page": n}))
        if "End of list" not in " ".join(page.chunks) and not any(
            "Next page" in label for _, label in page.links
        ):
            raise UnreadablePage("mail search completeness unavailable")
        messages.update(h for h, _ in page.links if re.fullmatch(r"/mail/m/[^/?]+", h))
        if not any("Next page" in label for _, label in page.links):
            break
    else:
        raise UnreadablePage("mail search exceeded pagination limit")
    candidates = {}
    for message in sorted(messages):
        html = reader.html(message)
        sender = re.search(r'<div class="sender">(.*?)</div><time', html, re.S)
        if sender and email.casefold() not in _clean(sender[1]).casefold():
            continue
        attachments = re.search(r'<section class="files".*?</section>', html, re.S)
        for href, _ in read_page(attachments[0] if attachments else "").links:
            if not re.fullmatch(r"/drive/f/[^/]+", href):
                continue
            body = "\n".join(read_page(reader.html(href)).pre)
            if (
                not re.search(r"(?m)^INVOICE\s*$", body)
                or legal.casefold() not in body[:200].casefold()
            ):
                continue
            issued = re.search(r"Invoice date:\s*(\d{1,2} [A-Za-z]{3} \d{4})", body)
            if not issued:
                raise UnreadablePage("invoice candidate has an unreadable date: " + href)
            candidates[href.rsplit("/", 1)[-1]] = datetime.strptime(issued[1], "%d %b %Y")
    if not candidates:
        raise UnreadablePage("no dated invoice candidates in the accessible vendor mailbox")
    last = max(candidates.values())
    chosen = [fid for fid, date in candidates.items() if date == last]
    if len(chosen) != 1:
        raise UnreadablePage("latest invoice date is ambiguous")
    return _result(
        spec,
        text,
        chosen[0],
        None if not spec.expect else chosen[0] == spec.expect,  # no expectation: unknown
        "Accessible vendor mailbox; invoice date ordering; candidates: "
        + ", ".join(f"{fid}={date.date()}" for fid, date in candidates.items()),
    )


def run_check(reader: Reader, spec: CheckSpec, text: str) -> CheckResult:
    """One primitive on fresh pages. Any reading problem is unknown, never pass."""
    try:
        if spec.primitive == "latest_invoice":
            return latest_invoice(reader, spec, text)
        if spec.primitive == "count_bills":
            ids = reader.bills_for(spec.invoice_no or "", spec.vendor_id)
            ok = None if spec.expect is None else str(len(ids)) == spec.expect.strip()
            return _result(spec, text, str(len(ids)), ok, f"/books/bills?q={spec.invoice_no}")
        if spec.primitive in ("bill_field", "approval_status"):
            bid = reader.bill_id(spec)
            if bid is None:
                return _result(spec, text, None, None, "no single bill found")
            html = reader.html(f"/books/bills/{bid}")
            if spec.primitive == "bill_field":
                actual = record_fields(html).get(spec.field or "")
                if spec.field == "Attachment":
                    href = record_links(html).get("Attachment", "")
                    actual = href.rsplit("/", 1)[-1] if href.startswith("/drive/f/") else None
            else:
                tables = re.findall(r"<table[^>]*>(.*?)</table>", html, re.S)
                rows = next(
                    (
                        read_page(table).rows[1:]
                        for table in tables
                        if read_page(table).rows
                        and read_page(table).rows[0]
                        == ["Approver", "Status", "Requested", "Decided"]
                    ),
                    [],
                )
                rows = [row for row in rows if len(row) == 4]
                actual = rows[-1][1] if rows else None
            expected = spec.expect
            if spec.field in ("Invoice date", "Due date"):
                expected, actual = date_value(expected), date_value(actual)
            if spec.primitive == "approval_status":
                expected = {
                    "pending approval": "pending",
                    "pending_approval": "pending",
                    "awaiting approval": "pending",
                }.get((expected or "").casefold(), expected)
                if expected not in ("pending", "approved", "rejected"):
                    return _result(spec, text, actual, None, "unrecognized approval-request status")
            if spec.primitive == "bill_field" and spec.field == "Status":
                expected = (expected or "").casefold().replace("_", " ")
                actual = (actual or "").casefold().replace("_", " ")
            if spec.field == "Amount":
                amount = _amount(expected or "")
                if amount is None or amount[1] is None:
                    return _result(spec, text, actual, None, "source currency is missing")
            spec = spec.model_copy(update={"expect": expected})
            return _result(spec, text, actual, _equal(actual, expected), f"/books/bills/{bid}")
        if spec.primitive in ("vendor_field", "field_unchanged", "vendor_unchanged"):
            path = f"/books/vendors/{spec.vendor_id}"
            current = record_fields(reader.html(path))
            if spec.primitive == "vendor_unchanged":
                # The summary masks bank numbers and cannot prove their equality.
                # Compare the actual browser form values, captured before any write.
                edit = path + "/edit"
                before = FormValues(reader.baselines.get(edit, "")).values
                after = FormValues(reader.html(edit)).values
                fields = {
                    "name",
                    "legal_name",
                    "tax_id",
                    "email",
                    "phone",
                    "address",
                    "bank_account",
                    "status",
                }
                if not fields <= before.keys() or not fields <= after.keys():
                    return _result(
                        spec,
                        text,
                        None,
                        None,
                        "complete pre-write vendor form baseline unavailable",
                    )
                ok = all(before[key] == after[key] for key in fields)
                return _result(
                    spec,
                    text,
                    "vendor fields",
                    ok,
                    edit + " compared with full pre-write values (values withheld)",
                )
            actual = current.get(spec.field or "")
            if spec.primitive == "vendor_field":
                return _result(spec, text, actual, _equal(actual, spec.expect), path)
            if spec.field == "Bank account":
                before = FormValues(reader.baselines.get(path + "/edit", "")).values.get(
                    "bank_account"
                )
                after = FormValues(reader.html(path + "/edit")).values.get("bank_account")
                return _result(
                    spec,
                    text,
                    "bank field (value withheld)",
                    None if before is None or after is None else before == after,
                    "Full browser form values compared; a masked summary is insufficient",
                )
            before_html = reader.baselines.get(path)
            if before_html is None:
                return _result(spec, text, actual, None, f"{path} was not read earlier in the run")
            before = record_fields(before_html).get(spec.field or "")
            spec = spec.model_copy(update={"expect": before})
            return _result(spec, text, actual, None if before is None else before == actual, path)
    except (httpx.HTTPError, UnreadablePage, ValueError) as e:
        return _result(spec, text, None, None, f"read failed ({e})"[:200])
    return _result(spec, text, None, None, "no check primitive for this condition")


def verify(
    base_url: str,
    goal: GoalContract,
    plan: CheckPlan,
    first_seen: dict[str, str],
    emit: Callable[[CheckResult], None],
    headers: dict[str, str] | None = None,
    baselines: dict[str, str] | None = None,
) -> list[CheckResult]:
    results = []
    ids = [c.id for c in goal.conditions]
    invalid = len(set(ids)) != len(ids) or any(s.condition_id not in ids for s in plan.checks)
    with httpx.Client(base_url=base_url, headers=headers or {}, timeout=20) as client:
        reader = Reader(client, first_seen, baselines)
        for condition in goal.conditions:
            specs = [s for s in plan.checks if s.condition_id == condition.id]
            keys = [claim_key(s) for s in specs]
            missing = required_claims(condition) - set(keys)
            for key in sorted(missing & {"Status", "approval_status"}):
                linked = linked_bill_status(reader, specs, plan, key)
                if linked:
                    specs.append(linked.model_copy(update={"condition_id": condition.id}))
                    keys.append(key)
                    missing.remove(key)
            # A source invoice can be shared by several atomic field conditions. Reuse
            # only its explicit selection specification, bound to the same document AND
            # the freshly observed bill vendor. The primitive still executes below.
            if "latest_invoice" in missing:
                linked = linked_latest(reader, specs, plan)
                if linked:
                    specs.append(linked.model_copy(update={"condition_id": condition.id}))
                    keys.append("latest_invoice")
                    missing.remove("latest_invoice")
            if invalid or not specs or missing or len(keys) != len(set(keys)):
                result = CheckResult(
                    condition_id=condition.id,
                    text=condition.text,
                    result="unknown",
                    evidence="Incomplete or ambiguous coverage: " + ", ".join(sorted(missing)),
                )
            else:
                checks = []
                for spec in specs:
                    source = first_seen.get(spec.source_path or "", "")
                    needs_source = (
                        spec.primitive in ("bill_field", "vendor_field") and spec.field != "Status"
                    )
                    quote = _clean(spec.source_quote or "")
                    if spec.field == "Amount" and spec.expect:
                        amount = _amount(spec.expect)
                        codes = set(
                            re.findall(
                                r"\b(?:INR|USD|EUR|GBP)\b",
                                " ".join(read_page(source).pre) or _clean(source),
                                re.I,
                            )
                        )
                        if amount and not amount[1] and len(codes) == 1:
                            spec = spec.model_copy(
                                update={"expect": f"{next(iter(codes)).upper()} {amount[0]}"}
                            )
                    supported = source and quote and quote in _clean(source)
                    if spec.expect and spec.field != "Attachment":
                        expected_tokens = _tokens(spec.expect)
                        quoted_tokens = _tokens(quote)
                        value_present = any(
                            quoted_tokens[n : n + len(expected_tokens)] == expected_tokens
                            for n in range(len(quoted_tokens))
                        )
                        if spec.field in ("Invoice date", "Due date"):
                            try:
                                date = datetime.strptime(spec.expect, "%Y-%m-%d")
                                value_present = (
                                    value_present
                                    or date.strftime("%d %b %Y").lstrip("0").casefold()
                                    in quote.casefold()
                                )
                            except ValueError:
                                pass
                        number = _amount(spec.expect)
                        if number:
                            value_present = value_present or any(
                                _amount(token) and _amount(token)[0] == number[0]
                                for token in quoted_tokens
                            )
                        supported = supported and value_present
                    if spec.field == "Approver" and source and quote and quote in _clean(source):
                        sender = re.search(
                            r'<div class="sender">.*?<strong>(.*?)</strong>', source, re.S
                        )
                        if sender and re.search(r"\b(?:to me|my approval)\b", quote, re.I):
                            supported = _tokens(_clean(sender[1])) == _tokens(spec.expect)
                    if spec.field == "Attachment":
                        supported = supported and spec.source_path == "/drive/f/" + (
                            spec.expect or ""
                        )
                    if spec.field == "Account" and "code,name,type" in _clean(source):
                        # The chart proves an account exists, not that the invoice belongs there.
                        supported = False
                    if spec.primitive == "bill_field" and (spec.source_path or "").startswith(
                        "/books/bills"
                    ):
                        supported = False
                    if needs_source and not supported:
                        check = _result(
                            spec,
                            condition.text,
                            None,
                            None,
                            "captured independent source/quote missing",
                        )
                    else:
                        check = run_check(reader, spec, condition.text)
                    checks.append(check)
                status = (
                    "fail"
                    if any(c.result == "fail" for c in checks)
                    else ("unknown" if any(c.result == "unknown" for c in checks) else "pass")
                )
                result = CheckResult(
                    condition_id=condition.id,
                    text=condition.text,
                    result=status,
                    evidence="; ".join(c.evidence or "" for c in checks),
                    claims=keys,
                    sources=list(dict.fromkeys(s.source_path for s in specs if s.source_path)),
                )
            emit(result)
            results.append(result)
    return results


def linked_bill_status(
    reader: Reader, specs: list[CheckSpec], plan: CheckPlan, key: str
) -> CheckSpec | None:
    try:
        targets = {
            reader.bill_id(s) for s in specs if s.primitive in ("bill_field", "approval_status")
        }
        if len(targets) != 1 or None in targets:
            return None
        matches = {
            s.model_dump_json(exclude={"condition_id"}): s
            for s in plan.checks
            if claim_key(s) == key and reader.bill_id(s) in targets
        }
        return next(iter(matches.values())) if len(matches) == 1 else None
    except (httpx.HTTPError, UnreadablePage):
        return None


def linked_latest(reader: Reader, specs: list[CheckSpec], plan: CheckPlan) -> CheckSpec | None:
    fields = [
        s
        for s in specs
        if s.primitive == "bill_field"
        and s.field in {"Invoice number", "Amount", "Invoice date", "Due date", "Attachment"}
    ]
    if not fields:
        return None
    candidates = {
        (s.vendor_id, s.expect): s
        for s in plan.checks
        if s.primitive == "latest_invoice"
        and s.vendor_id
        and s.expect
        and all(f.source_path == "/drive/f/" + s.expect for f in fields)
    }
    if len(candidates) != 1:
        return None
    selected = next(iter(candidates.values()))
    try:
        for field in fields:
            bid = reader.bill_id(field)
            actual = (
                record_fields(reader.html(f"/books/bills/{bid}")).get("Vendor") if bid else None
            )
            if _equal(actual, selected.vendor_id) is not True:
                return None
    except (httpx.HTTPError, UnreadablePage):
        return None
    return selected


def outcome(results: list[CheckResult], stop_reason: str | None, blocked: bool) -> str:
    """pass only if every check passed; blocked and unknown are real outcomes too."""
    if blocked:
        return "blocked"
    if any(r.result == "fail" for r in results):
        return "fail"
    if not results or stop_reason or any(r.result == "unknown" for r in results):
        return "unknown"
    return "pass"


def capture_vendor_baselines(base_url: str, request: str) -> list[str]:
    """Read the public forms of vendors explicitly named in this request, before acting.

    GETs use the existing gateway and its pre-write capture. No company values are
    inferred; unrecognized/ambiguous requests still rely on the worker's observations.
    """
    captured = []
    with httpx.Client(base_url=base_url, timeout=20) as client:
        for page_no in range(1, 31):
            response = client.get("/books/vendors", params={"page": page_no})
            response.raise_for_status()
            page = read_page(response.text)
            for row in page.rows:
                if len(row) != 6 or row[0] == "Vendor" or not row[1].strip():
                    continue
                if re.search(r"(?<!\w)" + re.escape(row[1]) + r"(?!\w)", request, re.I):
                    for suffix in ("", "/edit"):
                        view = client.get("/books/vendors/" + row[0] + suffix)
                        view.raise_for_status()
                    captured.append(row[0])
            if not any("Next page" in label for _, label in page.links):
                return captured
    return captured

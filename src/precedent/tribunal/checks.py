"""Generic exact checks over any company page (layer 1 of the adaptive verifier).

Every company app renders a record as labelled fields, a list as a table and a document
as text. A small typed vocabulary over that structure covers most conditions without
code per task family. A model proposes the checks; this module runs them in code. An
expected value is accepted only when it comes from the request, the condition text, or
a quote that really appears on a page the court read. Anything else stays unknown.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from precedent.worker.context import read_page
from precedent.worker.verify import _amount, _clean, _equal, date_value, record_fields

Op = Literal[
    "field_equals",
    "field_present",
    "field_absent",
    "row_exists",
    "row_count",
    "text_contains",
    "quote_in_source",
]
VALUE_OPS = {"field_equals", "row_exists", "row_count", "text_contains", "quote_in_source"}
APP_PATH = re.compile(
    r"^/(books|mail|drive|chat|calendar)(/[A-Za-z0-9_.\-/]*)?(\?[A-Za-z0-9_.\-=&%+]*)?$"
)
PAGE_LIMIT = 20


class Cell(BaseModel):
    column: str
    value: str


class Check(BaseModel):
    condition_id: str
    op: Op
    path: str = Field(description="Company page to read, for example /books/bills/INV-1")
    label: str | None = Field(None, description="Field label as shown, for field checks")
    cells: list[Cell] = Field(default_factory=list, description="Column values for row checks")
    value: str | None = Field(None, description="Expected value, row count, or quote")
    source: str | None = Field(
        None, description="Where the expected value comes from: request, condition, or a page"
    )
    source_quote: str | None = Field(None, description="Exact words on that page, if a page")

    @property
    def columns(self) -> dict[str, str]:
        return {c.column: c.value for c in self.cells}


class Outcome(BaseModel):
    result: Literal["pass", "fail", "unknown"]
    evidence: str


def words(text: str | None) -> list[str]:
    """Lowercase words; punctuation around them is ignored, joined forms like E-ana or
    2026-10-05 stay whole, and digit-group commas are dropped."""
    text = re.sub(r"(?<=\d),(?=\d)", "", _clean(text or "").casefold())
    return re.findall(r"[a-z0-9@]+(?:[._:/+-][a-z0-9@]+)*", text)


def contains_words(corpus: str, phrase: str) -> bool:
    want, have = words(phrase), words(corpus)
    return bool(want) and any(have[i : i + len(want)] == want for i in range(len(have)))


DATES = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2} [A-Za-z]{3,9} \d{4})\b")
NUMBERS = re.compile(r"\d[\d,]*(?:\.\d+)?")


def supported(corpus: str, value: str) -> bool:
    """The value appears in the cited words: as whole words, as the same date written
    another way, or as the same amount written another way."""
    if contains_words(corpus, value):
        return True
    day = date_value(value)
    if day and any(date_value(d) == day for d in DATES.findall(corpus)):
        return True
    amount = _amount(value)
    if amount is not None:
        figures = {Decimal(n.replace(",", "")) for n in NUMBERS.findall(corpus)}
        return amount[0] in figures
    return False


def safe_path(path: str) -> bool:
    return bool(APP_PATH.match(path or "")) and ".." not in path and "__" not in path


def _norm(text: str | None) -> str:
    return " ".join(_clean(text or "").casefold().split())


def _tables(html: str) -> list[list[list[str]]]:
    tables = []
    for body in re.findall(r"<table[^>]*>(.*?)</table>", html, re.S):
        rows = [r for r in read_page(body).rows if r]
        if rows:
            tables.append(rows)
    return tables


def _next_page(html: str) -> str | None:
    for href, label in read_page(html).links:
        if "next" in label.casefold() and href.startswith("/"):
            return href
    return None


def page_text(html: str) -> str:
    page = read_page(html)
    return " ".join(page.chunks) + " " + "\n".join(page.pre)


def provenance(check: Check, request: str, condition: str, pages: dict[str, str]) -> str | None:
    """None if every expected value is supported; otherwise why the check cannot count.

    Expected values must come from the request, the condition, or an exact quote on a page
    the court itself read. Never from the worker's report of what it did."""
    if check.op not in VALUE_OPS:
        return None
    values = [v for v in check.columns.values() if v]
    if check.op == "row_count":
        if not (check.value or "").strip().isdigit():
            return "the expected count is not a number"
    elif check.value:
        values.append(check.value)
    if not values:
        return None if check.op == "row_count" else "no expected value"
    if check.source == "request":
        corpus = request
    elif check.source == "condition":
        corpus = condition
    elif check.source and check.source.split("?")[0] == check.path.split("?")[0]:
        return "a record cannot be the source of its own expected value"
    elif check.source and check.source in pages:
        html = pages[check.source]
        text = page_text(html) + " " + " ".join(f"{k} {v}" for k, v in record_fields(html).items())
        if not contains_words(text, check.source_quote or ""):
            return f"the cited words were not found on {check.source}"
        corpus = check.source_quote or ""
    else:
        return "the expected value has no cited source"
    for value in values:
        # Whole words only: "no" must not be found inside "not".
        if not supported(corpus, value):
            return f"{value!r} is not in the cited source"
    return None


def run(check: Check, read: Callable[[str], str]) -> Outcome:
    """One check on a fresh read. Any problem reading is unknown, never pass."""
    if not safe_path(check.path):
        return Outcome(result="unknown", evidence=f"{check.path}: not a company page")
    try:
        html = read(check.path)
    except httpx.HTTPError as exc:
        return Outcome(
            result="unknown", evidence=f"{check.path}: read failed ({type(exc).__name__})"
        )
    where = check.path
    if check.op in ("field_equals", "field_present", "field_absent"):
        fields = record_fields(html)
        if check.label not in fields:
            if check.op == "field_absent" and fields:
                return Outcome(result="pass", evidence=f"{where}: no {check.label!r} field")
            return Outcome(result="unknown", evidence=f"{where}: no field labelled {check.label!r}")
        actual = fields[check.label]
        if check.op == "field_present":
            ok = bool(actual.strip()) and actual.strip().casefold() not in ("none", "not set", "-")
        elif check.op == "field_absent":
            ok = not actual.strip() or actual.strip().casefold() in ("none", "not set", "-")
        else:
            ok = _equal(actual, check.value)
            if ok is None:
                return Outcome(
                    result="unknown", evidence=f"{where}: {check.label} could not be compared"
                )
        return Outcome(
            result="pass" if ok else "fail",
            evidence=f"{where}: {check.label} = {actual!r}"
            + (f", expected {check.value!r}" if check.op == "field_equals" else ""),
        )
    if check.op in ("row_exists", "row_count"):
        matched, seen_header, page, pages = 0, False, html, 0
        while page is not None and pages < PAGE_LIMIT:
            for table in _tables(page):
                header = [_norm(h) for h in table[0]]
                index = {
                    _norm(k): header.index(_norm(k)) for k in check.columns if _norm(k) in header
                }
                if len(index) != len(check.columns):
                    continue
                seen_header = True
                for row in table[1:]:
                    if all(
                        i < len(row) and _equal(row[i], check.columns[k]) is True
                        for k, i in ((k, index[_norm(k)]) for k in check.columns)
                    ):
                        matched += 1
            pages += 1
            nxt = _next_page(page)
            page = read(nxt) if nxt and safe_path(nxt) else None
        if not seen_header:
            return Outcome(
                result="unknown", evidence=f"{where}: no table with {sorted(check.columns)}"
            )
        if check.op == "row_exists":
            return Outcome(
                result="pass" if matched else "fail", evidence=f"{where}: {matched} matching rows"
            )
        try:
            expected = int((check.value or "").strip())
        except ValueError:
            return Outcome(
                result="unknown", evidence=f"{where}: count {check.value!r} is not a number"
            )
        return Outcome(
            result="pass" if matched == expected else "fail",
            evidence=f"{where}: {matched} matching rows, expected {expected}",
        )
    text = _norm(page_text(html))
    quote = _norm(check.value)
    if not quote:
        return Outcome(result="unknown", evidence=f"{where}: nothing to look for")
    found = quote in text
    return Outcome(
        result="pass" if found else "fail",
        evidence=f"{where}: {'contains' if found else 'does not contain'} {check.value!r}"[:300],
    )


def combine(outcomes: list[Outcome]) -> Outcome | None:
    """One condition's generic result: any fail fails; all pass passes; otherwise unknown."""
    if not outcomes:
        return None
    evidence = "; ".join(o.evidence for o in outcomes)[:900]
    if any(o.result == "fail" for o in outcomes):
        return Outcome(result="fail", evidence=evidence)
    if all(o.result == "pass" for o in outcomes):
        return Outcome(result="pass", evidence=evidence)
    return Outcome(result="unknown", evidence=evidence)

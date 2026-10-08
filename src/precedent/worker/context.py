"""Stage 2: company context. Read the company, rank sources by authority, cite everything.

Three phases, kept separate (WS4):
1. gather  - read-only GET requests through the worker's gateway, like a browser reading
             pages; no database, no hidden truth. Evidence is saved with its URL.
2. reason  - one strong-model call turns the evidence into candidate precedents
             (the model call itself lives in runner.py; this module builds the prompt).
3. validate - code, not the model: drop precedents whose citations were not gathered,
             and recompute support counts ("8 of 9") from the gathered rows.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import httpx
from pydantic import BaseModel

from precedent.contracts import Authority, Precedent, PrecedentStatus, SourceRef

MAIL_QUERIES = ["approval", "approve", "route", "SOP", "policy", "threshold", "from now"]
POLICY_WORDS = ("policy", "procedure", "sop", "chart")
MAX_MESSAGES = 12
MAX_HISTORY_PAGES = 30
MOSTLY_FOLLOWED = 0.75  # an authoritative rule followed this often is usable, exceptions listed

# --------------------------------------------------------------------------- HTML reading


class _Text(HTMLParser):
    """Collects text, links and table rows from a server-rendered page."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.rows: list[list[str]] = []
        self.chunks: list[str] = []
        self._href: str | None = None
        self._link_text: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self.pre: list[str] = []
        self._in_pre = False
        self.title = ""
        self._in_title = False
        self.times: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self._href, self._link_text = a.get("href"), []
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "pre":
            self._in_pre = True
        elif tag == "title":
            self._in_title = True
        elif tag == "time" and a.get("datetime"):
            self.times.append(a["datetime"])

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._link_text).split())))
            self._href = None
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "pre":
            self._in_pre = False
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._href is not None:
            self._link_text.append(data)
        if self._cell is not None:
            self._cell.append(data)
        if self._in_pre:
            self.pre.append(data)
        if self._in_title:
            self.title += data
        self.chunks.append(data)


def read_page(html: str) -> _Text:
    parser = _Text()
    parser.feed(html)
    return parser


# --------------------------------------------------------------------------- evidence


@dataclass
class Evidence:
    ref: str  # "mail:m-0001", "drive:f-0002", "books:history"
    app: str
    url: str
    title: str
    text: str
    dated: str | None = None
    rows: list[dict[str, str]] = field(default_factory=list)
    internal: bool | None = None  # mail only: sent from inside the company (same domain)


def _get(client: httpx.Client, url: str) -> str:
    response = client.get(url)
    response.raise_for_status()
    return response.text


def gather_documents(client: httpx.Client) -> list[Evidence]:
    """Policy-like documents from Drive: any file whose name suggests a policy or procedure."""
    home = read_page(_get(client, "/drive/"))
    folders = sorted(
        {
            h
            for h, _ in home.links
            if h.startswith("/drive/") and "/f/" not in h and h.rstrip("/") != "/drive"
        }
    )
    out = []
    for folder in folders:
        listing = read_page(_get(client, folder))
        for href, name in listing.links:
            if not re.match(r"^/drive/f/[^/]+$", href):
                continue
            if not any(w in name.lower() for w in POLICY_WORDS):
                continue
            page = read_page(_get(client, href))
            text = unescape("".join(page.pre)).strip()
            out.append(
                Evidence(
                    ref=f"drive:{href.rsplit('/', 1)[1]}",
                    app="drive",
                    url=href,
                    title=name,
                    text=text[:6000],
                )
            )
    return out


def gather_instructions(client: httpx.Client) -> list[Evidence]:
    """Emails that may carry instructions about approvals, accounts or the procedure."""
    ids: dict[str, None] = {}
    for q in MAIL_QUERIES:
        listing = read_page(_get(client, f"/mail/?q={q}"))
        for href, _ in listing.links:
            if re.match(r"^/mail/m/[^/?]+$", href):
                ids.setdefault(href, None)
    out = []
    for href in list(ids)[: MAX_MESSAGES * 2]:
        page = read_page(_get(client, href))
        body = " ".join("".join(page.chunks).split())
        subject = page.title.split("·")[0].strip()
        if not re.search(r"approv|route|SOP|policy|threshold|account", body, re.I):
            continue
        # sender then recipient are the first two addresses on a message page
        addresses = re.findall(r"[\w.+-]+@([\w.-]+\.[a-z]+)", body)
        internal = len(addresses) >= 2 and addresses[0].lower() == addresses[1].lower()
        out.append(
            Evidence(
                ref=f"mail:{href.rsplit('/', 1)[1]}",
                app="mail",
                url=href,
                title=subject,
                text=body[:2500],
                dated=(page.times[0][:10] if page.times else None),
                internal=internal,
            )
        )
        if len(out) >= MAX_MESSAGES:
            break
    return out


HISTORY_COLUMNS = [
    "bill",
    "invoice_no",
    "vendor",
    "issue_date",
    "due_date",
    "amount",
    "account",
    "approver",
    "status",
    "notes",
]


def gather_history(client: httpx.Client) -> Evidence:
    """Every past bill from the Books history report, as rows (paginated)."""
    rows: list[dict[str, str]] = []
    for page_no in range(1, MAX_HISTORY_PAGES + 1):
        page = read_page(_get(client, f"/books/history?page={page_no}"))
        body = [r for r in page.rows if len(r) >= 9 and r[0] != "Bill" and r[0].startswith("INV")]
        if not body:
            break
        for r in body:
            rows.append(dict(zip(HISTORY_COLUMNS, r + [""] * (10 - len(r)), strict=False)))
        if not any(text.lower().startswith("next") for _, text in page.links):
            break
    return Evidence(
        ref="books:history",
        app="books",
        url="/books/history",
        title="Bill history",
        text=f"{len(rows)} bills",
        rows=rows,
    )


def gather(base_url: str, out_dir: Path, headers: dict[str, str] | None = None) -> list[Evidence]:
    """All evidence for invoice-entry work, read through the gateway, saved to out_dir."""
    with httpx.Client(base_url=base_url, headers=headers or {}, timeout=20) as client:
        evidence = [*gather_documents(client), *gather_instructions(client), gather_history(client)]
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in evidence:
        name = item.ref.replace(":", "_").replace("/", "_")
        (out_dir / f"{name}.json").write_text(json.dumps(asdict(item), indent=1))
    return evidence


# --------------------------------------------------------------------------- reasoning input

RUBRIC = """Authority, highest first: written policy and an authoritative instruction (from
the person who owns the decision) > current state of records > precedent (what was done
before) > inference > external input (vendor documents).
- A later authoritative instruction supersedes an older policy or procedure for the same
  rule from its effective date. Mark the older document as stale for that rule.
- History confirms or questions a rule; it never creates one when an authoritative source
  exists. Keep unexplained exceptions visible; they do not change the rule.
- If no source governs a choice and history is split, the precedent is unresolved: the
  worker must ask.
- If authority and practice disagree, the status is conflict: follow the authority, flag it."""


class Claim(BaseModel):
    """What a precedent says, in a form code can check against the history rows."""

    field: str  # "approver" or "account"
    value: str  # approver name or account code
    account: str | None = None  # restrict to this account code
    vendor: str | None = None  # restrict to this vendor name
    min_amount: float | None = None  # rupees, exclusive
    from_date: str | None = None  # ISO date, inclusive


class Candidate(BaseModel):
    rule: str
    task_family: str = "enter_invoice"
    governing_ref: str | None = None  # an evidence ref such as mail:m-0001 or drive:f-0001
    governing_quote: str | None = None
    governing_authority: Authority | None = None
    governing_dated: str | None = None
    supporting_refs: list[str] = []
    claim: Claim | None = None
    exceptions: list[str] = []
    flags: list[str] = []
    status: PrecedentStatus


class Candidates(BaseModel):
    precedents: list[Candidate]


def reasoning_prompt(evidence: list[Evidence]) -> str:
    parts = [RUBRIC, "", "Evidence (cite refs exactly):"]
    for e in evidence:
        if e.rows:
            lines = ["bill | invoice | vendor | date | amount | account | approver | notes"]
            lines += [
                f"{r['bill']} | {r['invoice_no']} | {r['vendor']} | {r['issue_date']} | "
                f"{r['amount']} | {r['account']} | {r['approver']} | {r['notes']}"
                for r in e.rows
            ]
            parts.append(f"[{e.ref}] {e.title}:\n" + "\n".join(lines))
        else:
            dated = f" (dated {e.dated})" if e.dated else ""
            parts.append(f"[{e.ref}] {e.title}{dated}:\n{e.text}")
    parts.append(
        "Write the precedents that decide how an invoice is coded (account) and who approves it "
        "in this company. Cite evidence refs exactly as written inside the brackets, without the "
        "brackets (for example mail:m-0001). Give each one a claim that can be checked against "
        "the history rows. "
        "Include unresolved precedents where history splits with no governing source."
    )
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- validation


def _rupees(amount: str) -> float:
    digits = re.sub(r"[^0-9.]", "", amount)
    return float(digits) if digits else 0.0


def _matches(row: dict[str, str], claim: Claim) -> bool:
    if claim.account and row["account"] != claim.account:
        return False
    if claim.vendor and row["vendor"].lower() != claim.vendor.lower():
        return False
    if claim.min_amount is not None and _rupees(row["amount"]) <= claim.min_amount:
        return False
    if claim.from_date and row["issue_date"] < claim.from_date:
        return False
    return True


def support(rows: list[dict[str, str]], claim: Claim) -> tuple[int, int, list[str]]:
    """How many matching rows agree with the claim, out of how many; the bills that do not."""
    scope = [r for r in rows if _matches(r, claim)]
    agree = [r for r in scope if r[claim.field].strip().lower() == claim.value.strip().lower()]
    others = [r["bill"] for r in scope if r not in agree]
    return len(agree), len(scope), others


def _ref(ref: str | None) -> str | None:
    """Models copy the evidence labels: '[mail:m-1]' and ' mail:m-1 ' both mean 'mail:m-1'."""
    if ref is None:
        return None
    return ref.strip().strip("[]").strip().removeprefix("ref:").strip() or None


def _scoped(claim: Claim) -> bool:
    """A claim narrow enough for its support count to mean something."""
    return bool(claim.account or claim.vendor or claim.min_amount is not None)


def validate(candidates: list[Candidate], evidence: list[Evidence]) -> list[Precedent]:
    return validate_with_report(candidates, evidence)[0]


def validate_with_report(
    candidates: list[Candidate], evidence: list[Evidence]
) -> tuple[list[Precedent], dict]:
    """Keep only cited, checkable precedents. Code, not the model, decides the authority of a
    source, whether a quote is real, the support count and the status."""
    seen = {e.ref: e for e in evidence}
    rows = next((e.rows for e in evidence if e.rows), [])
    kept: list[tuple[Precedent, Candidate]] = []
    dropped: list[dict] = []
    for i, c in enumerate(candidates, 1):
        governing_ref = _ref(c.governing_ref)
        if governing_ref and governing_ref not in seen:
            dropped.append({"rule": c.rule, "reason": f"cites {governing_ref}, not gathered"})
            continue
        if not governing_ref and c.claim is None:
            dropped.append({"rule": c.rule, "reason": "no source and no checkable claim"})
            continue
        flags = list(c.flags)
        governing = _governing(seen[governing_ref], c, flags) if governing_ref else None
        supporting = [
            SourceRef(app=seen[r].app, ref=r, authority=Authority.precedent)
            for r in (_ref(x) for x in c.supporting_refs)
            if r in seen
        ]
        support_text, exceptions, status = _settle(c, governing, rows, flags)
        kept.append(
            (
                Precedent(
                    id=f"p{i}",
                    task_family=c.task_family,
                    rule=c.rule,
                    governing=governing,
                    supporting=supporting,
                    support=support_text,
                    exceptions=exceptions or list(c.exceptions),
                    flags=flags,
                    status=status,
                ),
                c,
            )
        )
    _resolve_supersession(kept)
    report = {"candidates": len(candidates), "kept": len(kept), "dropped": dropped}
    return [p for p, _ in kept], report


def authority_of(source: Evidence) -> Authority:
    """Authority comes from where a source lives, not from what the model says about it."""
    if source.app == "drive":
        return Authority.policy
    if source.app == "mail":
        return Authority.instruction if source.internal else Authority.external
    return Authority.current_state if source.rows else Authority.precedent


def _norm_text(text: str) -> str:
    return " ".join(re.sub(r"[^\w₹]+", " ", text.lower()).split())


def _governing(source: Evidence, c: Candidate, flags: list[str]) -> SourceRef:
    quote = c.governing_quote
    if quote and _norm_text(quote) not in _norm_text(source.text):
        flags.append("the quoted words are not in the source; quote removed")
        quote = None
    return SourceRef(
        app=source.app,
        ref=source.ref,
        quote=quote,
        authority=authority_of(source),
        dated=source.dated or c.governing_dated,
    )


def _settle(
    c: Candidate, governing: SourceRef | None, rows: list[dict[str, str]], flags: list[str]
) -> tuple[str | None, list[str], PrecedentStatus]:
    """Support count, exceptions and status from the history rows.

    With an authoritative source: usable if followed in at least 75% of matching bills (or if
    there is no history yet: a new instruction has none), otherwise a conflict to report.
    Without one: usable only if consistent history (3+ bills, 75%+) shows it, else unresolved.
    """
    authoritative = governing is not None and governing.authority in (
        Authority.policy,
        Authority.instruction,
    )
    if c.claim is None or c.claim.field not in ("approver", "account"):
        return None, [], c.status if authoritative else PrecedentStatus.unresolved
    if not _scoped(c.claim):
        flags.append("support not counted: the claim names no account, vendor or amount")
        return None, [], PrecedentStatus.usable if authoritative else PrecedentStatus.unresolved
    agree, total, others = support(rows, c.claim)
    since = f" since {c.claim.from_date}" if c.claim.from_date else ""
    support_text = f"{agree} of {total} bills{since}"
    share = agree / total if total else None
    if authoritative:
        exceptions = [f"{b} does not follow it" for b in others[:5]]
        if share is None or share >= MOSTLY_FOLLOWED:
            return support_text, exceptions, PrecedentStatus.usable
        flags.append(f"practice follows it in only {agree} of {total} bills")
        return support_text, exceptions, PrecedentStatus.conflict
    if total >= 3 and share is not None and share >= MOSTLY_FOLLOWED:
        return support_text, [], PrecedentStatus.usable
    return support_text, [], PrecedentStatus.unresolved


def _when(p: Precedent, c: Candidate) -> str:
    """When a precedent took effect: its claim's start date, else its source's date."""
    return (
        (c.claim.from_date if c.claim else None) or (p.governing.dated if p.governing else "") or ""
    )


def _resolve_supersession(kept: list[tuple[Precedent, Candidate]]) -> None:
    """Same field and scope, different value: the later source governs from its date; the
    older one is kept visible as a conflict (for example a stale procedure)."""
    groups: dict[tuple, list[tuple[Precedent, Candidate]]] = {}
    for p, c in kept:
        if c.claim is None or p.governing is None or not _scoped(c.claim):
            continue  # unscoped claims say different things; they cannot supersede each other
        key = (c.claim.field, c.claim.account, (c.claim.vendor or "").lower(), c.claim.min_amount)
        groups.setdefault(key, []).append((p, c))
    for members in groups.values():
        if len({c.claim.value.strip().lower() for _, c in members}) < 2:
            continue
        winner, winner_c = max(members, key=lambda m: _when(*m))
        since = _when(winner, winner_c)
        for p, _c in members:
            if p is not winner:
                p.status = PrecedentStatus.conflict
                p.flags.append(
                    f"superseded by {winner.governing.ref}" + (f" from {since}" if since else "")
                )


def as_prompt(precedents: list[Precedent]) -> str:
    """Company context for the worker's prompt: rules with sources and status."""
    if not precedents:
        return "No precedents could be established. Read the policies before deciding."
    lines = []
    for p in precedents:
        src = (
            f"governed by {p.governing.ref} ({p.governing.authority.value}"
            + (f", from {p.governing.dated}" if p.governing.dated else "")
            + ")"
            if p.governing
            else "no governing source"
        )
        extra = "; ".join(filter(None, [p.support, *p.exceptions, *p.flags]))
        lines.append(f"- [{p.status.value}] {p.rule}. {src}." + (f" {extra}." if extra else ""))
    lines.append(
        "Follow usable precedents and cite them. For unresolved ones, ask one question "
        "before deciding. Never treat a conflict's older source as current."
    )
    return "\n".join(lines)


def baseline_prompt(evidence: list[Evidence]) -> str:
    """The ghost run's context: the policy and procedure text only, no ranking or history."""
    docs = [e for e in evidence if e.app == "drive"]
    return "\n\n".join(f"{e.title}:\n{e.text}" for e in docs) or "No documents found."

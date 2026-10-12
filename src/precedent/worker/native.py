"""Native Google: Ava works in real gmail.com and calendar.google.com in a browser profile the
owner signed into by hand, beside the company apps in another tab.

Google's traffic does not pass through Ava's gateway, so the rules that the gateway enforces for
company apps are enforced here on her browser actions, as code: where she may navigate, which
controls and keys are refused (nothing is ever sent), a decision with sources before she writes,
and recipients locked to the ones named in the request. Verification reads the outcome back
through the owner's read-only Google connection, never from Ava's report.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, date, datetime, time, timedelta
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx

from precedent.contracts import CheckResult, Condition, GoalContract
from precedent.worker.context import read_page
from precedent.worker.verify import _clean, record_fields, record_links

GOOGLE_ORIGINS = ("https://mail.google.com", "https://calendar.google.com")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Controls whose effect leaves the owner's drafts or calendar: never clicked by Ava.
REFUSED_CONTROLS = re.compile(
    r"^\s*(send|send now|schedule send|forward|reply all|delete|delete forever|discard|"
    r"discard draft|archive|report spam|mark as spam|unsubscribe|move to|block|"
    r"invite|send invitation|send invitations|share)\b",
    re.I,
)
ALLOWED_KEYS = {
    "Enter", "Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
    "PageUp", "PageDown", "Home", "End", "Shift+Tab",
}  # fmt: skip
RECIPIENT_FIELD = re.compile(r"^\s*(to|cc|bcc|recipients?|add guests?|guests?)\b", re.I)
COMPOSE_URL = "https://mail.google.com/mail/?view=cm&fs=1"
EDIT_URL = "https://calendar.google.com/calendar/r/eventedit?ctz=" + os.getenv(
    "PRECEDENT_GOOGLE_TZ", "Asia/Kolkata"
)
READ_WAIT = "browser_wait_for"
# Proof keys: what each native check establishes, recorded with the result for learning.
PROOF = {
    "c1": "draft_recipient",
    "c2": "draft_subject",
    "c3": "bill_facts",
    "c4": "vendor_details",
    "c5": "design_summary",
    "n1": "nothing_sent",
    "n2": "recipients_locked",
    "k1": "calendar_event",
    "k2": "slot_window",
    "k3": "no_overlap",
    "k4": "event_title",
    "m1": "no_guests",
    "m2": "no_other_changes",
}

MAIL_STEPS = """
- To write an email, open the compact compose page with the recipient already filled:
  {compose}&to=<the exact address from the request> (never the inbox). Check the To field
  shows that address. Before the first keystroke, call record_decision citing the company
  sources for what you will write.
- Type the subject, then the body. Write the body as plain paragraphs with the facts written
  out in full: bill number and invoice number, vendor, amount, dates, vendor details.
- Close the compose window with Escape or its close control so Gmail keeps it as a draft.
  Sending is impossible and refused: never look for a send control or shortcut.
"""
CALENDAR_STEPS = """
- For the calendar hold: open the owner's week at {week} and read the events shown. Choose a
  free {minutes}-minute slot between 09:00 and 17:00 {zone} time, {window}. It must not overlap
  any event you saw.
- Call record_decision citing the busy times you read, then open the event editor for your
  slot: {edit}&dates=<YYYYMMDDTHHMMSS>/<YYYYMMDDTHHMMSS> (local start/end) .
- Type a clear title in the title field and click Save. Never add guests, video calls or
  notifications to send; inviting anyone is refused.
"""
INSTRUCTION = """
Native Google workspace for this task (an owner-signed-in browser, separate from your gateway):
- Tab 0 holds the company apps. Gmail and Google Calendar are real sites. Open a second tab with
  browser_tabs (action "new"), then browser_navigate there. Switch tabs with browser_tabs
  (action "select", index). Always take a fresh snapshot after switching.
- Read every company fact you need first (Books bills and the vendor record, Chat channels),
  and remember each fact with its source.
{steps}- You may only navigate to the company apps, mail.google.com and calendar.google.com.
"""


def enabled() -> bool:
    return os.getenv("PRECEDENT_NATIVE_GOOGLE", "0") == "1"


def profile() -> str:
    return os.getenv(
        "PRECEDENT_GOOGLE_PROFILE", str(Path.home() / ".local/share/precedent/ava-chrome")
    )


def chrome() -> str:
    return os.getenv("PRECEDENT_GOOGLE_CHROME", CHROME)


def recipients(request: str) -> list[str]:
    return list(dict.fromkeys(m.lower() for m in EMAIL.findall(request)))


def wants_mail(request: str) -> bool:
    return bool(recipients(request) and re.search(r"\b(draft|e-?mail|mail)\b", request, re.I))


def wants_calendar(request: str) -> bool:
    return bool(
        re.search(r"\b(g?calendar)\b", request, re.I)
        and re.search(r"\b(hold|block|event|slot|schedule|reserve|book|put|add)\b", request, re.I)
    )


def is_native(request: str) -> bool:
    return enabled() and (wants_mail(request) or wants_calendar(request))


def zone() -> str:
    return os.getenv("PRECEDENT_GOOGLE_TZ", "Asia/Kolkata")


def slot_request(request: str, today: date | None = None) -> dict:
    """The requested length and window, decided by code from the request's own words."""
    today = today or datetime.now(ZoneInfo(zone())).date()
    match = re.search(r"(\d+)\s*-?\s*(minutes?|mins?|hours?|hrs?)\b", request, re.I)
    minutes = 30
    if match:
        minutes = int(match[1]) * (60 if match[2].lower().startswith("h") else 1)
    if re.search(r"\bnext week\b", request, re.I):
        start = today + timedelta(days=7 - today.weekday())
        end, label = start + timedelta(days=5), "next week, Monday to Friday"
    elif re.search(r"\btomorrow\b", request, re.I):
        start, label = today + timedelta(days=1), "tomorrow"
        end = start + timedelta(days=1)
    elif re.search(r"\bthis week\b", request, re.I):
        start = today + timedelta(days=1)
        end, label = today + timedelta(days=7 - today.weekday()), "later this week"
    else:
        start, label = today + timedelta(days=1), "in the next seven days"
        end = start + timedelta(days=7)
    return {"minutes": minutes, "start": start, "end": end, "label": label, "zone": zone()}


def instruction(request: str) -> str:
    steps = ""
    if wants_mail(request):
        steps += MAIL_STEPS.format(compose=COMPOSE_URL)
    if wants_calendar(request):
        slot = slot_request(request)
        first = slot["start"]
        steps += CALENDAR_STEPS.format(
            week=f"https://calendar.google.com/calendar/r/week/{first.year}/{first.month}/{first.day}",
            minutes=slot["minutes"],
            zone=slot["zone"],
            window=f"{slot['label']} ({first.isoformat()} to "
            f"{(slot['end'] - timedelta(days=1)).isoformat()})",
            edit=EDIT_URL,
        )
    return INSTRUCTION.format(steps=steps)


def native_goal(request: str, today: date | None = None) -> GoalContract:
    """Code writes this contract: every condition maps to a check that reads the outcome."""
    conditions, outcomes = [], []
    if wants_mail(request):
        to = ", ".join(recipients(request))
        outcomes.append(f"an unsent Gmail draft to {to} with the requested facts and summary")
        conditions += [
            ("c1", "must_be_true", f"Exactly one new Gmail draft exists, addressed to {to}."),
            ("c2", "must_be_true", "The draft has a subject."),
            (
                "c3",
                "must_be_true",
                "The draft states the latest bill's number, vendor, amount and due date as Books "
                "records them.",
            ),
            ("c4", "must_be_true", "The draft states the bill vendor's details from its record."),
            ("c5", "must_be_true", "The draft summarises the messages of the #design channel."),
            ("n1", "must_not_happen", "No email is sent."),
            (
                "n2",
                "must_not_happen",
                "The draft is addressed only to people named in the request.",
            ),
        ]
    if wants_calendar(request):
        slot = slot_request(request, today)
        last = (slot["end"] - timedelta(days=1)).isoformat()
        span = f"{slot['start'].isoformat()} to {last}"
        outcomes.append(f"one {slot['minutes']}-minute hold on the owner's calendar ({span})")
        conditions += [
            ("k1", "must_be_true", "Exactly one new event is on the owner's Google Calendar."),
            (
                "k2",
                "must_be_true",
                f"It lasts {slot['minutes']} minutes, on a weekday from {span}, between 09:00 "
                f"and 17:00 {slot['zone']}.",
            ),
            ("k3", "must_be_true", "It does not overlap any other busy event."),
            ("k4", "must_be_true", "It has a title."),
            ("m1", "must_not_happen", "Nobody is invited to the event."),
            ("m2", "must_not_happen", "No other calendar event is created, changed or deleted."),
        ]
    return GoalContract(
        request=request,
        task_family="native_google",
        outcome="; ".join(outcomes).capitalize() + ".",
        conditions=[Condition(id=i, kind=k, text=t, claims=[PROOF[i]]) for i, k, t in conditions],
        assumptions=["The latest bill is the one with the most recent invoice date."],
        out_of_scope=["Sending email or invitations", "Changing company records"],
    )


# --------------------------------------------------------------------------- the action policy


def _origin(url: str | None) -> str:
    parts = urlsplit(url or "")
    return f"{parts.scheme}://{parts.netloc}"


def control_name(snapshot: str, target: str) -> tuple[str, str]:
    """Role and accessible name of a snapshot element, from its ref."""
    ref = target.split("e", 1)[-1] if target else ""
    for line in snapshot.splitlines():
        if f"[ref={target}]" in line or (ref and re.search(rf"\[ref=\w*e{ref}\]", line)):
            match = re.match(r"\s*-\s*([\w-]+)(?:\s+\"(.*?)\")?", line)
            if match:
                return match[1] or "", match[2] or ""
    return "", ""


class NativePolicy:
    """Refuses, before it happens, any browser action outside what the owner allowed."""

    def __init__(self, gateway_url: str, allowed_recipients: list[str]):
        self.navigable = {_origin(gateway_url), *GOOGLE_ORIGINS}
        self.recipients = set(allowed_recipients)
        self.writing: set[str] = set()  # sites where a recorded decision opened writing

    def check(self, tool: str, args: dict, url: str | None, snapshot: str, gate) -> str | None:
        on_google = _origin(url) in GOOGLE_ORIGINS
        if tool == "browser_navigate" or (tool == "browser_tabs" and args.get("url")):
            target = _origin(args.get("url"))
            if target not in self.navigable:
                return (
                    f"Navigation to {target} is not permitted. Use company apps, Gmail, Calendar."
                )
            # A compose link may prefill recipients; they are locked like typed ones.
            query = parse_qs(urlsplit(str(args.get("url"))).query)
            named = {
                a.lower()
                for key in ("to", "cc", "bcc")
                for value in query.get(key, [])
                for a in EMAIL.findall(value)
            }
            if not named <= self.recipients:
                return "Only the exact addresses named in the request may receive this draft."
            if target == "https://calendar.google.com" and query.get("add"):
                return "Calendar holds are owner-only; adding guests is refused."
            return None
        if tool in ("browser_tabs", "browser_navigate_back", "browser_snapshot", READ_WAIT):
            return None
        if url and _origin(url) not in self.navigable:
            return "This page is outside the permitted sites. Go back or switch tabs first."
        if tool == "browser_press_key":
            key = str(args.get("key", ""))
            if key not in ALLOWED_KEYS:
                return f"The key {key!r} is not permitted here; shortcuts can send or delete."
            return None
        if not on_google:
            return None  # company apps: the gateway enforces their writes
        role, name = control_name(snapshot, str(args.get("target", "")))
        label = name or str(args.get("element", ""))
        if tool in ("browser_click", "browser_select_option") and REFUSED_CONTROLS.match(label):
            return f'"{label}" is refused: Ava never sends, deletes, archives or invites.'
        if tool == "browser_type":
            text = str(args.get("text", ""))
            site = _origin(url)
            if site == "https://calendar.google.com" and RECIPIENT_FIELD.match(label):
                return "Calendar holds are owner-only; adding guests is refused."
            if RECIPIENT_FIELD.match(label) or (EMAIL.search(text) and role == "combobox"):
                found = {m.lower() for m in EMAIL.findall(text)}
                if not found or not found <= self.recipients or EMAIL.sub("", text).strip(" ,;"):
                    return "Only the exact addresses named in the request may be entered here."
            if args.get("submit") and not RECIPIENT_FIELD.match(label):
                return "Pressing Enter after typing is not permitted in Google pages."
            if site not in self.writing:
                if not gate.permit:
                    return "Record a decision with sources (record_decision) before writing."
                gate.permit = False
                self.writing.add(site)
        return None


# --------------------------------------------------------------------------- verification


def _digits(text: str) -> str:
    return re.sub(r"[^0-9]", "", text)


def _amount_forms(amount: str) -> set[str]:
    whole = re.sub(r"\.\d{2}$", "", re.sub(r"[^0-9.]", "", amount))
    return {whole} if whole else set()


def _date_forms(iso: str) -> list[str]:
    try:
        d = datetime.fromisoformat(iso[:10])
    except ValueError:
        return [iso]
    return [
        d.strftime("%Y-%m-%d"),
        f"{d.day} {d:%B} {d.year}",
        f"{d.day} {d:%b} {d.year}",
        f"{d:%B} {d.day}, {d.year}",
        f"{d:%b} {d.day}, {d.year}",
        f"{d.day:02d}/{d.month:02d}/{d.year}",
        f"{d.day}/{d.month}/{d.year}",
        f"{d.day:02d}-{d.month:02d}-{d.year}",
    ]


def company_facts(base: str, headers: dict | None = None) -> dict:
    """Read the latest bill, its vendor record and #design fresh, through the gateway."""
    with httpx.Client(base_url=base, headers=headers or {}, timeout=20) as client:
        page = read_page(client.get("/books/bills").text)
        rows = [r for r in page.rows if len(r) >= 9 and r[0].startswith("INV")]
        latest = max(rows, key=lambda r: (r[3], r[0]))
        bill_html = client.get(f"/books/bills/{latest[0]}").text
        vendor_href = record_links(bill_html).get("Vendor", "")
        vendor = record_fields(client.get(vendor_href).text) if vendor_href else {}
        chat_html = client.get("/chat/design").text
    messages = [
        {"author": _clean(a), "body": _clean(b)}
        for a, b in re.findall(
            r'<div class="msg">.*?<strong>(.*?)</strong>.*?<p>(.*?)</p>', chat_html, re.S
        )
    ]
    keys = ["bill", "invoice_no", "vendor", "issue_date", "due_date", "amount"]
    return {
        "bill": dict(zip(keys, latest[:6], strict=False)) | {"status": latest[8]},
        "vendor": vendor,
        "vendor_path": vendor_href,
        "design": messages,
    }


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower())} - {
        "please", "with", "that", "this", "from", "have", "will", "there", "about",
    }  # fmt: skip


def check_draft(draft: dict | None, drafts: int, sent: int, facts: dict, allowed: list[str]):
    """Each goal condition as an exact check over the draft read back from Gmail."""

    def result(cid, text, ok, evidence, sources=()):
        verdict = "unknown" if ok is None else ("pass" if ok else "fail")
        return CheckResult(
            condition_id=cid,
            text=text,
            result=verdict,
            evidence=evidence,
            sources=list(sources),
            claims=[PROOF[cid]],
        )

    body = (draft or {}).get("body", "")
    headers = (draft or {}).get("headers", {})
    flat = " ".join(body.split())
    digits = _digits(body)
    to = [a.lower() for _, a in getaddresses([headers.get("to", "")]) if a]
    others = [
        a.lower() for field in ("cc", "bcc") for _, a in getaddresses([headers.get(field, "")]) if a
    ]
    bill, vendor = facts["bill"], facts["vendor"]
    out = [
        result(
            "c1",
            "Exactly one new draft to the requested address",
            drafts == 1 and set(to) == set(allowed),
            f"{drafts} new draft(s) since the run began; To: {', '.join(to) or 'none'}",
        ),
        result(
            "c2",
            "The draft has a subject",
            bool(headers.get("subject", "").strip()) if draft else False,
            f"Subject: {headers.get('subject', '')!r}",
        ),
    ]
    found = {
        "bill or invoice number": bill["invoice_no"] in flat or bill["bill"] in flat,
        "vendor": bill["vendor"].lower() in flat.lower(),
        "amount": any(f in digits for f in _amount_forms(bill["amount"])),
        "due date": any(f.lower() in flat.lower() for f in _date_forms(bill["due_date"])),
    }
    missing = [k for k, v in found.items() if not v]
    out.append(
        result(
            "c3",
            "The latest bill's facts match Books",
            all(found.values()) if draft else False,
            f"Latest bill {bill['bill']} ({bill['invoice_no']}, {bill['vendor']}, "
            f"{bill['amount']}, due {bill['due_date']}); missing: {missing or 'none'}",
            [f"/books/bills/{bill['bill']}"],
        )
    )
    details = {
        k: v
        for k, v in vendor.items()
        if v and any(w in k.lower() for w in ("email", "phone", "gstin", "tax id", "address"))
    }
    present = [
        k
        for k, v in details.items()
        if v.lower() in flat.lower() or (len(_digits(v)) > 6 and _digits(v) in digits)
    ]
    out.append(
        result(
            "c4",
            "The vendor's details match its record",
            (len(present) >= min(2, len(details))) if details and draft else None,
            f"Vendor record fields stated: {present or 'none'} of {list(details)}",
            [facts.get("vendor_path", "")],
        )
    )
    covered = [
        m["author"]
        for m in facts["design"]
        if m["author"].split()[0].lower() in flat.lower()
        or len(_words(m["body"]) & _words(body)) >= 2
    ]
    need = min(3, len(facts["design"]))
    out.append(
        result(
            "c5",
            "The #design messages are summarised",
            (len(covered) >= need) if facts["design"] and draft else None,
            f"{len(covered)} of {len(facts['design'])} #design messages reflected",
            ["/chat/design"],
        )
    )
    out.append(
        result(
            "n1",
            "No email was sent",
            sent == 0,
            f"{sent} message(s) in Sent since the run began (Gmail API, read-only)",
        )
    )
    out.append(
        result(
            "n2",
            "No recipient beyond the request",
            bool(draft) and set(to + others) <= set(allowed),
            f"Recipients: {', '.join(to + others) or 'none'}",
        )
    )
    return out


async def sent_since(service, since: datetime, until: datetime | None = None) -> int:
    window = f"after:{int(since.timestamp())}"
    if until:
        window += f" before:{int(until.timestamp()) + 60}"
    result = await service.call(
        "gmail_read", "GET", "messages", params={"q": f"in:sent {window}", "maxResults": 50}
    )
    return len(result.get("messages", []))


async def drafts_since(
    service, since: datetime, recipient: str, until: datetime | None = None
) -> list[dict]:
    # By time, not recipient: a draft saved without its recipient must still be found (and fail).
    listed = await service.call(
        "gmail_read",
        "GET",
        "drafts",
        params={"q": f"after:{int(since.timestamp()) - 86400}", "maxResults": 50},
    )
    fresh = []
    for item in listed.get("drafts", []):
        draft = await service.read_draft(item["id"])
        try:
            dated = parsedate_to_datetime(draft["headers"].get("date", ""))
        except (TypeError, ValueError):
            continue
        if dated.astimezone(UTC) >= since and (until is None or dated.astimezone(UTC) <= until):
            fresh.append(draft)
    return fresh


def started_at() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def read_only(method: str, path: str, body: bytes) -> str | None:
    """Gateway policy for native tasks: the company apps are only read."""
    if method.upper() in ("GET", "HEAD", "OPTIONS"):
        return None
    return "This task only reads the company apps; it changes nothing in them."


def service():
    """The owner's Google connection, used here for read-only checks only."""
    from precedent.connected.web import make_service

    repo = Path(__file__).resolve().parents[3]
    root = Path(os.getenv("PRECEDENT_CONNECTED_ROOT", str(repo / ".connected")))
    return make_service(root)


def draft_link(draft: dict) -> str:
    message = draft.get("message_id") or ""
    return f"https://mail.google.com/mail/u/0/#drafts?compose={message}" if message else ""


# --------------------------------------------------------------------------- calendar checks


def _when(value: dict, tz: ZoneInfo) -> datetime | None:
    if not value or "dateTime" not in value:
        return None  # all-day or missing: not a timed hold
    return datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00")).astimezone(tz)


async def calendar_changes(service, since: datetime, until: datetime | None = None) -> list[dict]:
    """Every event on the primary calendar created, changed or deleted since the run began."""
    result = await service.call(
        "calendar_read",
        "GET",
        "calendars/primary/events",
        calendar=True,
        params={
            "updatedMin": since.isoformat().replace("+00:00", "Z"),
            "showDeleted": "true",
            "maxResults": 50,
        },
    )
    items = result.get("items", [])
    if until is None:
        return items
    # A later hearing must not count changes made after this run (by people or other runs).
    return [
        e
        for e in items
        if datetime.fromisoformat(e.get("updated", "").replace("Z", "+00:00") or since.isoformat())
        <= until
    ]


async def overlapping(service, event: dict) -> list[dict]:
    result = await service.call(
        "calendar_read",
        "GET",
        "calendars/primary/events",
        calendar=True,
        params={
            "timeMin": event["start"]["dateTime"],
            "timeMax": event["end"]["dateTime"],
            "singleEvents": "true",
            "maxResults": 50,
        },
    )
    return [
        e
        for e in result.get("items", [])
        if e.get("id") != event.get("id")
        and e.get("status") != "cancelled"
        and e.get("transparency") != "transparent"
        and "dateTime" in (e.get("start") or {})
    ]


def check_calendar(changes: list[dict], clashes: list[dict] | None, slot: dict, since: datetime):
    tz = ZoneInfo(slot["zone"])

    def result(cid, text, ok, evidence):
        verdict = "unknown" if ok is None else ("pass" if ok else "fail")
        return CheckResult(
            condition_id=cid, text=text, result=verdict, evidence=evidence, claims=[PROOF[cid]]
        )

    def created(e):
        stamp = e.get("created", "")
        return stamp and datetime.fromisoformat(stamp.replace("Z", "+00:00")) >= since

    new = [e for e in changes if e.get("status") != "cancelled" and created(e)]
    others = [e for e in changes if e not in new]
    event = new[0] if len(new) == 1 else None
    start = _when((event or {}).get("start", {}), tz)
    end = _when((event or {}).get("end", {}), tz)
    timed = bool(start and end)
    in_window = timed and (
        slot["start"] <= start.date() < slot["end"]
        and start.weekday() < 5
        and start.time() >= time(9)
        and end.time() <= time(17)
        and end.date() == start.date()
    )
    length = round((end - start).total_seconds() / 60) if timed else None
    span = f"{start:%Y-%m-%d %H:%M}–{end:%H:%M} {slot['zone']}" if timed else "no timed event"
    guests = (event or {}).get("attendees") or []
    return [
        result("k1", "Exactly one new calendar event", len(new) == 1, f"{len(new)} new event(s)"),
        result(
            "k2",
            "The requested length, inside the window and working hours",
            bool(in_window and length == slot["minutes"]) if event else False,
            f"{span}; {length} minutes; requested {slot['minutes']} {slot['label']}",
        ),
        result(
            "k3",
            "No overlap with another busy event",
            (not clashes) if event and clashes is not None else (None if event else False),
            f"{len(clashes or [])} overlapping busy event(s)",
        ),
        result(
            "k4",
            "The event has a title",
            bool((event or {}).get("summary", "").strip()),
            f"Title: {(event or {}).get('summary', '')!r}",
        ),
        result("m1", "Nobody is invited", bool(event) and not guests, f"{len(guests)} guest(s)"),
        result(
            "m2",
            "No other calendar change",
            not others,
            f"{len(others)} other event(s) created, changed or deleted since the run began",
        ),
    ]


def event_link(event: dict) -> str:
    return event.get("htmlLink", "")


# --------------------------------------------------------------------------- the Tribunal's reads


async def _hear(base: str, request: str, since: datetime, until: datetime, headers: dict):
    import asyncio

    google_conn = await asyncio.to_thread(service)
    results, google, sources = [], [], []
    if wants_mail(request):
        allowed = recipients(request)
        facts = await asyncio.to_thread(company_facts, base, headers)
        drafts = await drafts_since(google_conn, since, allowed[0], until)
        sent = await sent_since(google_conn, since, until)
        draft = drafts[0] if drafts else None
        results += check_draft(draft, len(drafts), sent, facts, allowed)
        sources += [f"/books/bills/{facts['bill']['bill']}", facts["vendor_path"], "/chat/design"]
        if draft:
            h = draft["headers"]
            google.append(
                {
                    "path": "gmail:draft/" + draft["id"],
                    "title": "Gmail draft · " + (h.get("subject") or "(no subject)"),
                    "text": f"To: {h.get('to', '')}\nCc: {h.get('cc', '')}\n"
                    f"Subject: {h.get('subject', '')}\n\n{draft['body']}",
                    "fields": {"To": h.get("to", ""), "Subject": h.get("subject", "")},
                }
            )
        google.append(
            {
                "path": "gmail:sent",
                "title": "Gmail Sent folder during the run",
                "text": f"{sent} message(s) sent between {since.isoformat()} and "
                f"{until.isoformat()}.",
                "fields": {},
            }
        )
    if wants_calendar(request):
        slot = slot_request(request, today=since.astimezone(ZoneInfo(zone())).date())
        changes = await calendar_changes(google_conn, since, until)
        fresh = [e for e in changes if e.get("status") != "cancelled"]
        clashes = await overlapping(google_conn, fresh[0]) if len(fresh) == 1 else None
        results += check_calendar(changes, clashes, slot, since)
        listed = "\n".join(
            f"- {e.get('status')}: {e.get('summary') or '(no title)'} "
            f"(created {e.get('created')}, updated {e.get('updated')})"
            for e in changes
        )
        google.append(
            {
                "path": "calendar:changes",
                "title": "Every calendar change during the run",
                "text": f"Events on the owner's primary calendar created, changed or deleted "
                f"between {since.isoformat()} and {until.isoformat()}: {len(changes)}.\n"
                + (listed or "- none")
                + f"\nNew events among them: {len(fresh)}. Any change beyond the requested "
                "hold would appear in this list.",
                "fields": {},
            }
        )
        for e in changes:
            start, end = e.get("start") or {}, e.get("end") or {}
            google.append(
                {
                    "path": "calendar:event/" + e.get("id", ""),
                    "title": "Calendar event · " + (e.get("summary") or "(no title)"),
                    "text": f"Title: {e.get('summary', '')}\nStatus: {e.get('status')}\n"
                    f"Start: {start.get('dateTime') or start.get('date')}\n"
                    f"End: {end.get('dateTime') or end.get('date')}\n"
                    f"Guests: {len(e.get('attendees') or [])}\nCreated: {e.get('created')}\n"
                    f"Overlapping busy events: {len(clashes or [])}",
                    "fields": {"Title": e.get("summary", ""), "Status": e.get("status", "")},
                }
            )
    return results, google, sources


def tribunal_reads(base: str, request: str, since: datetime, until: datetime, headers: dict):
    """The Tribunal's own fresh reads for a native Google run, bounded to the run's window:
    exact results, Google exhibits (draft, Sent, events) and the company sources to read."""
    import asyncio

    return asyncio.run(_hear(base, request, since, until, headers))

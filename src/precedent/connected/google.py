"""Bounded Google capabilities and durable native-write reconciliation.

The account owner grants access; the worker never receives the OAuth credential.
This service is application-owned, not a company database shortcut for the worker.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import time
from contextvars import ContextVar
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from precedent.connected.providers import GMAIL_SCOPE, ProviderError, body_text, source
from precedent.connected.service import Service
from precedent.scheduling import instant, next_week, options, suitable

PREFIX = "https://www.googleapis.com/auth/"
ACTIVITY = ContextVar("google_activity_file", default=None)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def normalize_subject(value):
    return re.sub(r"^(?:(?:re|fw|fwd):\s*)+", "", value.strip(), flags=re.I).casefold()


def event_authorized(request: str) -> bool:
    """Conservative task authorization, independent of retrieved source instructions."""
    if re.search(
        r"\b(?:do not|don't|without|never)\s+(?:ever\s+)?"
        r"(?:reserve|reserv(?:e|ing)|hold (?:time|a meeting)|block (?:time|my)|"
        r"create (?:a |an )?(?:calendar )?event)\b",
        request,
        re.I,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:reserve|place (?:a |the )?hold|block (?:time|my)|"
            r"create (?:a |an )?(?:calendar )?event)\b",
            request,
            re.I,
        )
    )


class GoogleService(Service):
    def __init__(self, vault, providers):
        super().__init__(vault, providers)
        self.write_lock = asyncio.Lock()
        self.lost_ack = os.getenv("PRECEDENT_GOOGLE_LOST_ACK_ONCE") == "1"
        for op in self.vault.list("operation:"):
            if op.pop("expires", None):
                self.vault.put("operation:" + op["id"], op)

    def begin_google(self, session, features):
        if not features or not set(features) <= {"mail", "calendar", "reserve"}:
            raise ValueError("Choose the Google features to enable.")
        if "reserve" in features and "calendar" not in features:
            raise ValueError("Enable Calendar to allow explicit holds.")
        scopes = {"openid", "email"}
        if "mail" in features:
            scopes.update({GMAIL_SCOPE, PREFIX + "gmail.compose"})
        if "calendar" in features:
            scopes.update(
                {
                    PREFIX + "calendar.calendarlist.readonly",
                    PREFIX + "calendar.freebusy",
                    PREFIX
                    + (
                        "calendar.events.owned"
                        if "reserve" in features
                        else "calendar.events.owned.readonly"
                    ),
                }
            )
        url = urlsplit(super().begin("gmail", session))
        params = parse_qs(url.query)
        state = params["state"][0]
        pending = self.vault.get("oauth:" + state)
        pending["features"] = list(features)
        self.vault.put("oauth:" + state, pending)
        params["scope"] = [" ".join(sorted(scopes))]
        return urlunsplit(url._replace(query=urlencode(params, doseq=True)))

    async def callback(self, provider, state, code, denied=False):
        pending = self.vault.get("oauth:" + state) or {}
        await super().callback(provider, state, code, denied)
        if provider == "gmail" and pending.get("features"):
            grant = self.vault.get("connection:gmail")
            grant["enabled_features"] = pending["features"]
            self.vault.put("connection:gmail", grant)

    def capabilities(self):
        grant = self.vault.get("connection:gmail") or {}
        scopes = set(grant.get("scopes", []))
        if grant.get("status") == "Reconnect needed":
            return []
        caps = []
        for capability, scope in (
            ("gmail_read", GMAIL_SCOPE),
            ("gmail_draft", PREFIX + "gmail.compose"),
            ("calendar_list", PREFIX + "calendar.calendarlist.readonly"),
            ("calendar_availability", PREFIX + "calendar.freebusy"),
            ("calendar_read", PREFIX + "calendar.events.owned.readonly"),
            ("calendar_reserve", PREFIX + "calendar.events.owned"),
        ):
            if scope in scopes:
                caps.append(capability)
        if "calendar_reserve" in caps:
            caps.append("calendar_read")
        features = grant.get("enabled_features")
        if features is not None:
            caps = [
                c
                for c in caps
                if (
                    c.startswith("gmail_")
                    and "mail" in features
                    or c.startswith("calendar_")
                    and "calendar" in features
                    and (c != "calendar_reserve" or "reserve" in features)
                )
            ]
        return list(dict.fromkeys(caps))

    def stable_id(self):
        grant = self.vault.get("connection:gmail") or {}
        scope = digest(
            [self.vault.get("owner")["id"], "google", grant.get("account", "unconnected")]
        )[:32]
        if grant.get("account") and not self.vault.get("memory-scope:" + scope):
            self.vault.put("memory-scope:" + scope, {"id": scope})
        return scope

    async def require(self, capability):
        grant = await self.grant("gmail")
        if capability not in self.capabilities():
            raise ProviderError(
                f"Google permission for {capability.replace('_', ' ')} is missing. Reconnect "
                f"to enable it."
            )
        return grant

    async def identity(self):
        grant = await self.grant("gmail")
        return await self.providers.request(
            "GET",
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": "Bearer " + grant["token"]["access_token"]},
        )

    async def call(self, capability, method, path, *, calendar=False, **kwargs):
        grant = await self.require(capability)
        revision = grant["generation"]
        root = (
            "https://www.googleapis.com/calendar/v3/"
            if calendar
            else "https://gmail.googleapis.com/gmail/v1/users/me/"
        )
        started = time.monotonic()
        result, status = None, "completed"
        try:
            for attempt in range(3):
                try:
                    result = await self.providers.request(
                        method,
                        root + path,
                        headers={"Authorization": "Bearer " + grant["token"]["access_token"]},
                        **kwargs,
                    )
                    break
                except ProviderError as exc:
                    # Retry only semantic reads. Native writes always reconcile first.
                    read = method == "GET" or capability == "calendar_availability"
                    if not read or exc.status not in (429, 500, 502, 503, 504) or attempt == 2:
                        raise
                    await asyncio.sleep(0.5 * 2**attempt)
        except ProviderError:
            status = "failed"
            raise
        finally:
            activity = ACTIVITY.get()
            if activity:
                with activity.open("a") as stream:
                    stream.write(
                        json.dumps(
                            dict(
                                at=time.time(),
                                capability=capability,
                                method=method,
                                status=status,
                                seconds=round(time.monotonic() - started, 3),
                            )
                        )
                        + "\n"
                    )
        current = self.vault.get("connection:gmail")
        if not current or current["generation"] != revision:
            raise ProviderError(
                "Google access changed during this operation. Reconcile before continuing."
            )
        return result

    async def select(self, provider, ids, days, subject=""):
        if provider != "gmail":
            return await super().select(provider, ids, days)
        if days not in (1, 3, 7, 30, 90):
            raise ValueError("Choose a supported retrieval window.")
        grant = await self.require("gmail_read")
        choices = await self.providers.choices(provider, grant["token"]["access_token"])
        if len(ids) != 1 or ids[0] not in {r["id"] for r in choices}:
            raise ValueError("Choose one accessible Gmail label.")
        grant.update(
            selection={"ids": ids, "days": days, "subject": subject.strip()[:200]},
            status="Ready",
            generation=__import__("secrets").token_hex(16),
        )
        self.vault.put("connection:gmail", grant)
        self.cache.clear()

    async def search(self, query=""):
        grant = await self.require("gmail_read")
        selection = grant.get("selection")
        if not selection:
            raise ProviderError("Choose the Gmail label and retrieval window first.")
        rows, page = [], None
        for _ in range(3):
            bounded_query = query
            if selection.get("subject"):
                bounded_query = (
                    'subject:"' + selection["subject"].replace('"', "") + '" (' + query + ")"
                )
            params = dict(
                labelIds=selection["ids"][0],
                q=f"newer_than:{selection['days']}d ({bounded_query})"
                if bounded_query
                else f"newer_than:{selection['days']}d",
                maxResults=20,
            )
            if page:
                params["pageToken"] = page
            result = await self.call("gmail_read", "GET", "messages", params=params)
            for item in result.get("messages", []):
                msg = await self.call(
                    "gmail_read",
                    "GET",
                    "messages/" + quote(item["id"], safe=""),
                    params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                )
                headers = {
                    h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])
                }
                if selection.get("subject") and normalize_subject(
                    headers.get("subject", "")
                ) != normalize_subject(selection["subject"]):
                    continue
                rows.append(
                    dict(
                        id=msg["id"],
                        thread=msg["threadId"],
                        title=headers.get("subject", "No subject"),
                        author=headers.get("from", ""),
                        timestamp=headers.get("date", ""),
                        internal_date=int(msg.get("internalDate", 0)),
                    )
                )
            page = result.get("nextPageToken")
            if not page:
                break
        rows.sort(key=lambda r: r["internal_date"], reverse=True)
        return dict(messages=rows, complete=not page, fetched_at=time.time(), query=query)

    async def thread(self, thread_id):
        grant = await self.require("gmail_read")
        selection = grant.get("selection")
        if not selection:
            raise ProviderError("Choose Gmail sources first.")
        data = await self.call(
            "gmail_read", "GET", "threads/" + quote(thread_id, safe=""), params={"format": "full"}
        )
        messages = data.get("messages", [])
        cutoff = (time.time() - selection["days"] * 86400) * 1000
        if not any(
            selection["ids"][0] in m.get("labelIds", [])
            and int(m.get("internalDate", 0)) >= cutoff
            and (
                not selection.get("subject")
                or any(
                    h["name"].lower() == "subject"
                    and normalize_subject(h["value"]) == normalize_subject(selection["subject"])
                    for h in m.get("payload", {}).get("headers", [])
                )
            )
            for m in messages
        ):
            raise ProviderError("This thread is outside your selected Gmail access.")
        rows = []
        for msg in sorted(messages, key=lambda m: int(m.get("internalDate", 0))):
            headers = {
                h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])
            }
            text = body_text(msg.get("payload", {}), limit=20001)
            item = source(
                "gmail",
                grant["account"],
                msg["id"],
                data["id"],
                headers.get("subject", "No subject"),
                headers.get("from", ""),
                text[:20000],
                headers.get("date", ""),
                "https://mail.google.com/mail/u/?authuser="
                + quote(grant["email"], safe="")
                + "#all/"
                + quote(data["id"], safe=""),
            )
            item.update(
                headers=headers,
                labels=msg.get("labelIds", []),
                internal_date=msg.get("internalDate"),
                body_truncated=len(text) > 20000,
            )
            item["version"] = digest([item["version"], headers])
            rows.append(item)
        return dict(
            id=data["id"],
            sources=rows,
            complete=True,
            fetched_at=time.time(),
            account=grant["account"],
        )

    async def calendars(self):
        entries, page = [], None
        for _ in range(3):
            result = await self.call(
                "calendar_list",
                "GET",
                "users/me/calendarList",
                calendar=True,
                params={"maxResults": 100, **({"pageToken": page} if page else {})},
            )
            entries.extend(c for c in result.get("items", []) if c.get("accessRole") == "owner")
            page = result.get("nextPageToken")
            if not page:
                break
        if page:
            raise ProviderError(
                "Calendar list is incomplete. Narrow account access before selecting."
            )
        return sorted(entries, key=lambda c: not c.get("primary", False))

    async def calendar(self):
        grant = await self.grant("gmail")
        selected = grant.get("calendar_id")
        calendar = next((c for c in await self.calendars() if c["id"] == selected), None)
        if not calendar:
            raise ProviderError("Choose an owned Google calendar before scheduling.")
        return calendar

    async def select_calendar(self, calendar_id):
        choices = await self.calendars()
        if calendar_id not in {c["id"] for c in choices}:
            raise ValueError("Choose a calendar you own.")
        grant = await self.grant("gmail")
        calendar = next(c for c in choices if c["id"] == calendar_id)
        grant.update(
            calendar_id=calendar_id,
            calendar_timezone=calendar.get("timeZone", "UTC"),
            generation=__import__("secrets").token_hex(16),
        )
        self.vault.put("connection:gmail", grant)

    async def availability(self, start="", end="", duration=30):
        calendar = await self.calendar()
        zone = calendar.get("timeZone", "UTC")
        today = datetime.now(ZoneInfo(zone)).date().isoformat()
        if not start:
            start, end = next_week(today)
        # Validate bounds before making a provider request.
        options([], zone, start, end, duration)
        result = await self.call(
            "calendar_availability",
            "POST",
            "freeBusy",
            calendar=True,
            json={
                "timeMin": instant(start + "T00:00", zone).isoformat(),
                "timeMax": instant(end + "T00:00", zone).isoformat(),
                "timeZone": zone,
                "items": [{"id": calendar["id"]}],
            },
        )
        coverage = result.get("calendars", {}).get(calendar["id"], {})
        if coverage.get("errors") or "busy" not in coverage:
            raise ProviderError(
                "Selected calendar availability is unavailable; do not treat it as free."
            )
        busy = [dict(start_at=b["start"], end_at=b["end"]) for b in coverage["busy"]]
        prefs = self.vault.get("preferences:" + self.stable_id()) or {
            "work_start": 9,
            "work_end": 17,
        }
        found = options(busy, zone, start, end, duration, prefs["work_start"], prefs["work_end"])
        first_each_day = {}
        for item in found:
            first_each_day.setdefault(item["start"][:10], item)
        chosen = list(first_each_day.values())
        chosen += [o for o in found if o not in chosen]
        return dict(
            calendar=calendar,
            timezone=zone,
            today=today,
            start=start,
            end=end,
            duration=duration,
            busy=busy,
            options=chosen[:32],
            complete=True,
            fetched_at=time.time(),
            working_hours=prefs,
            preference_source="Owner preference"
            if self.vault.get("preferences:" + self.stable_id())
            else "Default weekdays 09:00–17:00",
        )

    async def events(self, start, end):
        calendar = await self.calendar()
        zone = calendar.get("timeZone", "UTC")
        rows, page = [], None
        for _ in range(3):
            result = await self.call(
                "calendar_read",
                "GET",
                "calendars/" + quote(calendar["id"], safe="") + "/events",
                calendar=True,
                params={
                    "timeMin": instant(start + "T00:00", zone).isoformat(),
                    "timeMax": instant(end + "T00:00", zone).isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": 100,
                    **({"pageToken": page} if page else {}),
                },
            )
            rows.extend(result.get("items", []))
            page = result.get("nextPageToken")
            if not page:
                break
        return dict(events=rows, complete=not page, calendar=calendar)

    def artifacts(self):
        return [
            o for o in self.vault.list("operation:") if o.get("account_scope") == self.stable_id()
        ]

    def artifact(self, artifact_id):
        return next((o for o in self.artifacts() if o["id"] == artifact_id), None)

    async def read_draft(self, draft_id):
        data = await self.call(
            "gmail_read", "GET", "drafts/" + quote(draft_id, safe=""), params={"format": "full"}
        )
        msg = data["message"]
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        return dict(
            id=data["id"],
            message_id=msg["id"],
            thread=msg.get("threadId"),
            headers=headers,
            body=body_text(msg.get("payload", {})),
            labels=msg.get("labelIds", []),
            version=digest(msg),
        )

    async def find_drafts(self, marker):
        result = await self.call(
            "gmail_read", "GET", "drafts", params={"q": "rfc822msgid:" + marker, "maxResults": 100}
        )
        if result.get("nextPageToken"):
            raise ProviderError("Draft reconciliation is incomplete.")
        return [await self.read_draft(d["id"]) for d in result.get("drafts", [])]

    async def reconcile(self, artifact_id):
        """Only fresh provider reads; never retries a native write."""
        op = self.artifact(artifact_id)
        if not op or op.get("state") not in ("pending", "uncertain"):
            return op
        if op["kind"] == "gmail_draft":
            candidates = (
                [await self.read_draft(op["native_id"])]
                if op.get("native_id")
                else await self.find_drafts(op["marker"])
            )
            if len(candidates) != 1:
                return op
            current = candidates[0]
            if (
                current["thread"] != op["thread"]
                or digest(current["body"].strip()) != op["body_hash"]
                or parseaddr(current["headers"].get("to", ""))[1].casefold()
                != op["recipient"].casefold()
            ):
                raise ValueError("Reconciliation found a changed draft; preserve it for review.")
            grant = await self.grant("gmail")
            url = (
                "https://mail.google.com/mail/u/?authuser="
                + quote(grant["email"], safe="")
                + "#drafts"
            )
        else:
            calendar = await self.calendar()
            if calendar["id"] != op["calendar_id"]:
                raise ValueError(
                    "The selected calendar changed; restore access before reconciliation."
                )
            try:
                current = await self.call(
                    "calendar_read",
                    "GET",
                    "calendars/" + quote(op["calendar_id"], safe="") + "/events/" + op["id"],
                    calendar=True,
                )
            except ProviderError as exc:
                if exc.status == 404:
                    return op
                raise
            if (
                current.get("summary") != op["title"]
                or current.get("attendees")
                or current.get("conferenceData")
                or current.get("status") == "cancelled"
                or instant(current["start"]["dateTime"]) != instant(op["start"])
                or instant(current["end"]["dateTime"]) != instant(op["end"])
            ):
                raise ValueError("Reconciliation found a changed event; preserve it for review.")
            url = current.get("htmlLink", "")
        op.update(
            state="saved",
            native_id=current["id"],
            native_url=url,
            status="Gmail draft · unsent"
            if op["kind"] == "gmail_draft"
            else "Google Calendar · owner-only hold",
        )
        self.vault.put("operation:" + op["id"], op, op.get("actor", "ava"))
        return op

    async def save_draft(self, fields, actor):
        if fields.get("workspace") != self.vault.identity():
            raise ValueError("Access changed. Reopen this form.")
        await self.require("gmail_draft")
        thread = await self.thread(fields["thread"])
        source_versions = digest(
            [
                {"id": m["message_id"], "version": m["version"]}
                for m in thread["sources"]
                if "DRAFT" not in m["labels"]
            ]
        )
        if fields.get("source_versions") and fields["source_versions"] != source_versions:
            raise ValueError(
                "The conversation changed since composition. Reopen it and review the new message."
            )
        message = next(
            (m for m in thread["sources"] if m["message_id"] == fields["reply_to"]), None
        )
        if not message or "DRAFT" in message["labels"]:
            raise ValueError("Choose an original message to reply to.")
        recipient = parseaddr(message["headers"].get("reply-to", message["author"]))[1]
        grant = await self.grant("gmail")
        if (
            recipient.casefold() == grant["email"].casefold()
            or not recipient
            or fields.get("recipient", "").casefold() != recipient.casefold()
        ):
            raise ValueError(
                "Recipient must match the source Reply-To or sender, not your own address."
            )
        for key in ("body", "topic"):
            if not fields.get(key, "").strip() or len(fields[key]) > 10000:
                raise ValueError(f"Enter a valid {key}.")
        slots = json.loads(fields.get("options", "[]"))
        schedule = None
        if slots:
            if len(slots) != 2 or slots[0] == slots[1]:
                raise ValueError("Choose two distinct meeting options.")
            schedule = await self.availability(
                fields["range_start"], fields["range_end"], int(fields.get("duration", 30))
            )
            for slot in slots:
                if not suitable(
                    slot["start"],
                    slot["end"],
                    schedule["busy"],
                    schedule["timezone"],
                    schedule["start"],
                    schedule["end"],
                    schedule["duration"],
                    **schedule["working_hours"],
                ):
                    raise ValueError(
                        "A proposed time is no longer free. Refresh Calendar and choose another."
                    )
                if (
                    slot["start"][:10] not in fields["body"]
                    or slot["start"][11:16] not in fields["body"]
                    or schedule["timezone"] not in fields["body"]
                ):
                    raise ValueError(
                        "The reply must include both option dates/times and their timezone."
                    )
        subject = message["title"]
        key = digest(
            [
                self.stable_id(),
                thread["id"],
                " ".join((fields.get("_trusted_request") or fields["topic"]).casefold().split()),
                schedule and [schedule["start"], schedule["end"]],
            ]
        )[:32]
        if fields.get("artifact_id"):
            editing = self.artifact(fields["artifact_id"])
            if not editing or editing["kind"] != "gmail_draft" or editing["thread"] != thread["id"]:
                raise ValueError("The edited draft belongs to a different conversation or account.")
            key = editing["id"]
        marker = key + "@precedent.local"
        payload = {
            "recipient": recipient,
            "subject": subject,
            "body": fields["body"].strip(),
            "thread": thread["id"],
        }
        async with self.write_lock:
            old = self.artifact(key)
            if old and old.get("native_id"):
                current = await self.read_draft(old["native_id"])
                if digest(current["body"].strip()) != old["body_hash"]:
                    raise ValueError(
                        "The Gmail draft was changed by a human. Review it; Ava will preserve the "
                        "edit."
                    )
                if not fields.get("update_version"):
                    old.update(state="saved", status="Gmail draft · unsent")
                    self.vault.put("operation:" + key, old, actor)
                    return old
                if fields["update_version"] != current["version"]:
                    raise ValueError("The draft changed since the edit form opened. Reload it.")
            if old and old["state"] in ("pending", "uncertain"):
                for attempt in range(3):
                    found = await self.find_drafts(marker)
                    if (
                        len(found) == 1
                        and found[0]["thread"] == thread["id"]
                        and digest(found[0]["body"].strip()) == old["body_hash"]
                    ):
                        old.update(
                            native_id=found[0]["id"],
                            state="saved",
                            status="Gmail draft · unsent",
                            native_url="https://mail.google.com/mail/u/?authuser="
                            + quote(grant["email"], safe="")
                            + "#drafts",
                        )
                        self.vault.put("operation:" + key, old, actor)
                        return old
                    if found:
                        raise ValueError(
                            "Ambiguous Gmail drafts. Human review is needed before another write."
                        )
                    await asyncio.sleep(0.25 * (attempt + 1))
                raise ProviderError(
                    "The Gmail save is uncertain. No duplicate was created; inspect Gmail "
                    "Drafts before proceeding."
                )
            op = dict(
                id=key,
                kind="gmail_draft",
                account_scope=self.stable_id(),
                workspace=self.vault.identity(),
                state="pending",
                title=subject,
                topic=fields["topic"],
                recipient=recipient,
                thread=thread["id"],
                reply_to=message["message_id"],
                sources=[
                    {"id": m["message_id"], "version": m["version"]}
                    for m in thread["sources"]
                    if "DRAFT" not in m["labels"]
                ],
                body_hash=digest(payload["body"]),
                marker=marker,
                options=slots,
                schedule={
                    k: schedule[k]
                    for k in ("start", "end", "duration", "timezone", "working_hours")
                }
                if schedule
                else None,
                created=time.time(),
                actor=actor,
            )
            updating = bool(old and old.get("native_id") and fields.get("update_version"))
            if updating:
                op["native_id"] = old["native_id"]
            self.vault.put("operation:" + key, op, actor)
            email = EmailMessage()
            email["To"], email["Subject"], email["From"], email["Message-ID"] = (
                recipient,
                subject,
                grant["email"],
                "<" + marker + ">",
            )
            if message["headers"].get("message-id"):
                email["In-Reply-To"] = message["headers"]["message-id"]
                email["References"] = (
                    message["headers"].get("references", "") + " " + email["In-Reply-To"]
                ).strip()
            email.set_content(payload["body"])
            try:
                result = await self.call(
                    "gmail_draft",
                    "PUT" if updating else "POST",
                    "drafts/" + quote(old["native_id"], safe="") if updating else "drafts",
                    json={
                        "message": {
                            "threadId": thread["id"],
                            "raw": base64.urlsafe_b64encode(email.as_bytes()).decode(),
                        }
                    },
                )
                if self.lost_ack:
                    self.lost_ack = False
                    op["fault_injection"] = (
                        "Acknowledgement suppressed after actual provider commit"
                    )
                    raise ProviderError("Injected lost acknowledgement after native commit.")
            except ProviderError:
                op.update(state="uncertain", status="Save uncertain · reconcile first")
                self.vault.put("operation:" + key, op, actor)
                raise
            op.update(
                native_id=result["id"],
                state="saved",
                status="Gmail draft · unsent",
                native_url="https://mail.google.com/mail/u/?authuser="
                + quote(grant["email"], safe="")
                + "#drafts",
            )
            self.vault.put("operation:" + key, op, actor)
            return op

    async def reserve(self, fields, actor):
        if fields.get("workspace") != self.vault.identity():
            raise ValueError("Access changed. Reopen this form.")
        await self.require("calendar_reserve")
        calendar = await self.calendar()
        start, end = fields["start"], fields["end"]
        zone = calendar.get("timeZone", "UTC")
        a, b = instant(start, zone), instant(end, zone)
        if not 15 <= (b - a).total_seconds() / 60 <= 240:
            raise ValueError("Choose an event duration of 15–240 minutes.")
        title = fields.get("title", "").strip()
        if not title or len(title) > 200:
            raise ValueError("Enter a short event title.")
        linked = self.artifact(fields.get("draft", "")) if fields.get("draft") else None
        if fields.get("draft") and (not linked or linked.get("kind") != "gmail_draft"):
            raise ValueError("The referenced scheduling draft is unavailable.")
        if linked and not any(
            instant(o["start"], zone) == a and instant(o["end"], zone) == b
            for o in linked.get("options", [])
        ):
            raise ValueError("Choose an actual option from the referenced draft.")
        key = digest(
            [self.stable_id(), calendar["id"], title.casefold(), a.isoformat(), b.isoformat()]
        )[:32]
        async with self.write_lock:
            old = self.artifact(key)
            path = "calendars/" + quote(calendar["id"], safe="") + "/events/" + key
            if old:
                try:
                    current = await self.call("calendar_read", "GET", path, calendar=True)
                    if (
                        current.get("status") == "cancelled"
                        or instant(current["start"]["dateTime"]) != a
                        or instant(current["end"]["dateTime"]) != b
                        or current.get("summary") != title
                        or current.get("attendees")
                    ):
                        raise ValueError(
                            "The existing event differs from this intent. Preserve it and ask for "
                            "review."
                        )
                    old.update(
                        state="saved",
                        status="Google Calendar · owner-only hold",
                        native_id=current["id"],
                        native_url=current.get("htmlLink", ""),
                    )
                    self.vault.put("operation:" + key, old, actor)
                    return old
                except ProviderError as exc:
                    if exc.status != 404 or old["state"] in ("pending", "uncertain"):
                        raise
                    raise ValueError(
                        "The previously created event was removed. Confirm before recreating it."
                    ) from None
            date = a.astimezone(ZoneInfo(zone)).date().isoformat()
            from datetime import timedelta

            stop = (a.astimezone(ZoneInfo(zone)).date() + timedelta(days=1)).isoformat()
            schedule = await self.availability(date, stop, int((b - a).total_seconds() / 60))
            if any(
                a < instant(e["end_at"]) and instant(e["start_at"]) < b for e in schedule["busy"]
            ):
                raise ValueError(
                    "That time is now busy. Recheck Calendar and propose another option."
                )
            op = dict(
                id=key,
                kind="calendar_event",
                account_scope=self.stable_id(),
                workspace=self.vault.identity(),
                state="pending",
                title=title,
                calendar_id=calendar["id"],
                start=a.isoformat(),
                end=b.isoformat(),
                timezone=zone,
                created=time.time(),
                actor=actor,
                linked_draft=fields.get("draft", ""),
            )
            self.vault.put("operation:" + key, op, actor)
            try:
                result = await self.call(
                    "calendar_reserve",
                    "POST",
                    "calendars/" + quote(calendar["id"], safe="") + "/events",
                    calendar=True,
                    params={"sendUpdates": "none"},
                    json={
                        "id": key,
                        "summary": title,
                        "start": {"dateTime": a.isoformat(), "timeZone": zone},
                        "end": {"dateTime": b.isoformat(), "timeZone": zone},
                        "extendedProperties": {"private": {"precedentIntent": key}},
                    },
                )
                if self.lost_ack:
                    self.lost_ack = False
                    op["fault_injection"] = (
                        "Acknowledgement suppressed after actual provider commit"
                    )
                    raise ProviderError("Injected lost acknowledgement after native commit.")
            except ProviderError:
                op.update(state="uncertain", status="Save uncertain · reconcile first")
                self.vault.put("operation:" + key, op, actor)
                raise
            op.update(
                native_id=result["id"],
                native_url=result.get("htmlLink", ""),
                state="saved",
                status="Google Calendar · owner-only hold",
            )
            self.vault.put("operation:" + key, op, actor)
            return op

    def forget(self):
        self.stable_id()  # Register this owner/account scope before erasure.
        from precedent.learning.store import Store, root_for

        store = Store(root_for(self.vault.root / "runs"))
        for record in self.vault.list("memory-scope:"):
            scope = record["id"]
            store.forget("google:" + scope + ":ava")
            self.vault.delete("preferences:" + scope)
        self.vault.delete_prefix("memory-scope:")
        self.vault.delete_prefix("worker:")
        self.vault.delete_prefix("demo-input:")
        super().forget()
        for op in self.vault.list("operation:"):
            self.vault.delete("operation:" + op["id"])

"""Fresh read-only provider checks, independent of the worker's save response."""

from __future__ import annotations

import time
from urllib.parse import quote

from precedent.connected.google import digest
from precedent.connected.providers import ProviderError
from precedent.scheduling import instant, overlap


class ReadOnlyGoogle:
    """The verifier cannot obtain native write methods or authenticated transport."""

    METHODS = {
        "artifact",
        "stable_id",
        "grant",
        "identity",
        "read_draft",
        "thread",
        "find_drafts",
        "availability",
        "calendar",
        "events",
    }

    def __init__(self, service):
        self._service = service

    def __getattr__(self, name):
        if name not in self.METHODS:
            raise AttributeError("Not available to the read-only verifier")
        return getattr(self._service, name)

    async def call(self, capability, method, path, **kwargs):
        if method != "GET" or capability not in {"calendar_read", "calendar_list", "gmail_read"}:
            raise ValueError("Independent verification permits only provider reads")
        return await self._service.call(capability, method, path, **kwargs)


def verdict(checks):
    results = {c["result"] for c in checks}
    if "fail" in results:
        return "fail"
    return "pass" if results == {"pass"} else "unknown"


async def inspect(service, artifact_id):
    service = ReadOnlyGoogle(service)
    op = service.artifact(artifact_id)
    if not op:
        return {
            "checks": [
                {
                    "claim": "native_artifact",
                    "result": "fail",
                    "evidence": "No operation for the selected account.",
                }
            ],
            "outcome": "fail",
        }
    checks = []

    def check(claim, valid, evidence):
        checks.append(
            dict(
                claim=claim,
                result="pass" if valid else "fail",
                evidence=evidence,
                checked_at=time.time(),
            )
        )

    try:
        grant = await service.grant("gmail")
        identity = await service.identity()
        check(
            "account_binding",
            op["account_scope"] == service.stable_id()
            and identity.get("sub") == grant["account"]
            and identity.get("email", "").casefold() == grant["email"].casefold()
            and identity.get("email_verified") is True,
            "Fresh Google userinfo identity, verified email and operation scope",
        )
        if op["kind"] == "gmail_draft":
            if not op.get("native_id"):
                checks.append(
                    dict(
                        claim="native_artifact",
                        result="unknown",
                        evidence="Save acknowledgement unresolved; reconciliation required.",
                    )
                )
                return dict(checks=checks, outcome=verdict(checks))
            draft = await service.read_draft(op["native_id"])
            thread = await service.thread(op["thread"])
            if any(s.get("body_truncated") for s in thread["sources"]):
                checks.append(
                    dict(
                        claim="source_coverage",
                        result="unknown",
                        evidence="At least one relevant message body is truncated.",
                        checked_at=time.time(),
                    )
                )
            from email.utils import parseaddr

            source = next((s for s in thread["sources"] if s["message_id"] == op["reply_to"]), None)
            expected_recipient = (
                parseaddr(source["headers"].get("reply-to", source["author"]))[1] if source else ""
            )
            check(
                "draft_identity",
                draft["id"] == op["native_id"]
                and draft["thread"] == op["thread"]
                and parseaddr(draft["headers"].get("to", ""))[1].casefold()
                == expected_recipient.casefold()
                and bool(expected_recipient)
                and expected_recipient.casefold() != grant["email"].casefold(),
                "Fresh Gmail draft, original message recipient, and thread association",
            )
            check(
                "draft_unsent",
                "DRAFT" in draft["labels"] and "SENT" not in draft["labels"],
                "Fresh Gmail system labels",
            )
            check(
                "draft_content",
                digest(draft["body"].strip()) == op["body_hash"]
                and draft["headers"].get("subject") == op["title"],
                "Native body fingerprint and subject match the recorded operation",
            )
            fresh = {
                s["message_id"]: s["version"]
                for s in thread["sources"]
                if "DRAFT" not in s["labels"]
            }
            recorded = {s["id"]: s["version"] for s in op["sources"]}
            check(
                "sources_current",
                fresh == recorded,
                "Independent full thread read; non-draft source versions",
            )
            matches = await service.find_drafts(op["marker"])
            check(
                "no_duplicate",
                len(matches) == 1 and matches[0]["id"] == draft["id"],
                "Complete marker-scoped native draft listing",
            )
            if op.get("schedule"):
                s = op["schedule"]
                availability = await service.availability(s["start"], s["end"], s["duration"])
                from precedent.scheduling import suitable

                slots = op["options"]
                valid = (
                    len(slots) == 2
                    and slots[0] != slots[1]
                    and all(
                        suitable(
                            x["start"],
                            x["end"],
                            availability["busy"],
                            availability["timezone"],
                            s["start"],
                            s["end"],
                            s["duration"],
                            **s["working_hours"],
                        )
                        for x in slots
                    )
                )
                check(
                    "meeting_availability",
                    valid,
                    "Fresh selected-owner calendar availability; recipient availability not "
                    "asserted",
                )
                check(
                    "meeting_options",
                    all(
                        x["start"][:10] in draft["body"] and x["start"][11:16] in draft["body"]
                        for x in slots
                    )
                    and s["timezone"] in draft["body"],
                    "Both recorded options and timezone appear in the actual reply",
                )
            return dict(
                checks=checks,
                outcome=verdict(checks),
                artifact=op,
                native=draft,
                sources=thread["sources"],
                account=grant["account"],
            )
        if not op.get("native_id"):
            checks.append(
                dict(
                    claim="native_artifact",
                    result="unknown",
                    evidence="Event save requires reconciliation.",
                )
            )
            return dict(checks=checks, outcome=verdict(checks))
        path = (
            "calendars/"
            + quote(op["calendar_id"], safe="")
            + "/events/"
            + quote(op["native_id"], safe="")
        )
        event = await service.call("calendar_read", "GET", path, calendar=True)
        calendar = await service.calendar()
        check(
            "event_identity",
            calendar["id"] == op["calendar_id"]
            and calendar["accessRole"] == "owner"
            and event.get("id") == op["id"]
            and event.get("summary") == op["title"]
            and event.get("status") != "cancelled",
            "Fresh owned Calendar metadata and native event",
        )
        check(
            "event_times",
            instant(event["start"]["dateTime"]) == instant(op["start"])
            and instant(event["end"]["dateTime"]) == instant(op["end"]),
            "Native start/end instants match requested operation",
        )
        check(
            "event_owner_only",
            not event.get("attendees") and not event.get("conferenceData"),
            "Fresh event has no guests or conference invitation",
        )
        from zoneinfo import ZoneInfo

        date = instant(op["start"]).astimezone(ZoneInfo(op["timezone"])).date().isoformat()
        from datetime import date as day
        from datetime import timedelta

        stop = (day.fromisoformat(date) + timedelta(days=2)).isoformat()
        listing = await service.events(date, stop)
        if not listing["complete"]:
            checks.append(
                dict(
                    claim="event_conflicts",
                    result="unknown",
                    evidence="Event coverage is incomplete.",
                )
            )
        else:
            a, b = instant(op["start"]), instant(op["end"])
            conflicts = []
            for other in listing["events"]:
                if (
                    other.get("id") == event["id"]
                    or other.get("status") == "cancelled"
                    or other.get("transparency") == "transparent"
                ):
                    continue
                start = other["start"].get(
                    "dateTime",
                    other["start"].get("date") + "T00:00" if other["start"].get("date") else "",
                )
                end = other["end"].get(
                    "dateTime",
                    other["end"].get("date") + "T00:00" if other["end"].get("date") else "",
                )
                if overlap(
                    a,
                    b,
                    instant(start, calendar.get("timeZone", "UTC")),
                    instant(end, calendar.get("timeZone", "UTC")),
                ):
                    conflicts.append(other["id"])
            check(
                "event_conflicts",
                not conflicts,
                "Fresh expanded event list, excluding only this exact hold; concurrent "
                "changes remain possible",
            )
            duplicate = [
                e
                for e in listing["events"]
                if e.get("status") != "cancelled"
                and e.get("extendedProperties", {}).get("private", {}).get("precedentIntent")
                == op["id"]
            ]
            check(
                "no_duplicate",
                len(duplicate) == 1 and duplicate[0]["id"] == event["id"],
                "Complete selected-calendar intent-scoped event listing",
            )
        linked = service.artifact(op.get("linked_draft", "")) if op.get("linked_draft") else None
        if linked and linked.get("native_id"):
            await service.thread(linked["thread"])
            linked_native = await service.read_draft(linked["native_id"])
            check(
                "referenced_draft_current",
                digest(linked_native["body"].strip()) == linked["body_hash"],
                "Fresh read of the scheduling draft; human changes require review",
            )
            linked = {**linked, "fresh_native": linked_native}
        if op.get("linked_draft"):
            check(
                "reserved_option",
                bool(linked)
                and any(
                    instant(x["start"]) == instant(op["start"])
                    and instant(x["end"]) == instant(op["end"])
                    for x in (linked or {}).get("options", [])
                ),
                "Reservation matches an option in the account-scoped scheduling operation",
            )
        return dict(
            checks=checks,
            outcome=verdict(checks),
            artifact=op,
            native=event,
            referenced_draft=linked,
            account=grant["account"],
        )
    except ProviderError as exc:
        checks.append(
            dict(
                claim="native_artifact",
                result="fail" if exc.status == 404 else "unknown",
                evidence="Native artifact absent." if exc.status == 404 else str(exc),
            )
        )
    except (KeyError, ValueError):
        checks.append(
            dict(
                claim="native_artifact",
                result="fail",
                evidence="Provider artifact is missing required fields or has invalid values.",
            )
        )
    return dict(checks=checks, outcome=verdict(checks))

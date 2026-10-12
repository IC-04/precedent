"""Public scheduling value semantics. No database, worker or evaluator access."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def instant(value: str, timezone: str | None = None) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        if timezone is None:
            raise ValueError("A timezone is required")
        zone = ZoneInfo(timezone)
        candidates = [dt.replace(tzinfo=zone, fold=f) for f in (0, 1)]
        valid = [
            x for x in candidates if x.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == dt
        ]
        if not valid or len({x.utcoffset() for x in valid}) > 1:
            raise ValueError("This local time is missing or ambiguous; choose an unambiguous time")
        dt = valid[0]
    return dt.astimezone(UTC)


def next_week(today: str) -> tuple[str, str]:
    day = date.fromisoformat(today[:10])
    monday = day + timedelta(days=7 - day.weekday())
    return monday.isoformat(), (monday + timedelta(days=7)).isoformat()


def overlap(a: datetime, b: datetime, c: datetime, d: datetime) -> bool:
    return a < d and c < b


def intent_key(organizer: str, recipient: str, topic: str, start: str, end: str) -> str:
    topic = " ".join(re.findall(r"\w+", topic.casefold()))
    return hashlib.sha256("|".join([organizer, recipient, topic, start, end]).encode()).hexdigest()[
        :24
    ]


def suitable(
    start: str,
    end: str,
    events: list[dict],
    timezone: str,
    range_start: str,
    range_end: str,
    duration: int,
    work_start: int = 9,
    work_end: int = 17,
) -> bool:
    a, b = instant(start, timezone), instant(end, timezone)
    zone = ZoneInfo(timezone)
    local_a, local_b = a.astimezone(zone), b.astimezone(zone)
    return (
        b - a == timedelta(minutes=duration)
        and range_start <= local_a.date().isoformat() < range_end
        and local_a.weekday() < 5
        and local_a.date() == local_b.date()
        and local_a.time() >= time(work_start)
        and local_b.time() <= time(work_end)
        and not any(
            overlap(a, b, instant(e["start_at"]), instant(e["end_at"]))
            for e in events
            if e.get("status") != "cancelled"
        )
    )


def options(
    events: list[dict],
    timezone: str,
    start: str,
    end: str,
    duration: int,
    work_start: int = 9,
    work_end: int = 17,
) -> list[dict]:
    first, stop = date.fromisoformat(start), date.fromisoformat(end)
    if not 0 < (stop - first).days <= 31 or not 15 <= duration <= 240:
        raise ValueError("Choose 1–31 days and a duration of 15–240 minutes")
    found = []
    day = first
    while day < stop:
        for minute in range(work_start * 60, work_end * 60 - duration + 1, 30):
            a = datetime.combine(day, time(minute // 60, minute % 60))
            b = a + timedelta(minutes=duration)
            try:
                aa, bb = instant(a.isoformat(), timezone), instant(b.isoformat(), timezone)
            except ValueError:
                continue
            if suitable(
                aa.isoformat(),
                bb.isoformat(),
                events,
                timezone,
                start,
                end,
                duration,
                work_start,
                work_end,
            ):
                found.append(
                    {
                        "start": a.isoformat(timespec="minutes"),
                        "end": b.isoformat(timespec="minutes"),
                        "label": a.strftime("%a %d %b · %H:%M") + "–" + b.strftime("%H:%M"),
                    }
                )
        day += timedelta(days=1)
    return found

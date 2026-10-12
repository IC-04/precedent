"""Convene the Tribunal on a finished run, and record every step for the screen."""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

from precedent.contracts import CheckResult, Condition
from precedent.tribunal import verdict as rules
from precedent.tribunal.audit import Finding, audit
from precedent.tribunal.case import Case, CaseError, load_case
from precedent.tribunal.checks import Outcome, combine, provenance
from precedent.tribunal.checks import run as run_check
from precedent.tribunal.evidence import HEADERS, Exhibit, collect, collect_paths
from precedent.tribunal.jury import Juror, Vote, deliberate, question
from precedent.tribunal.planner import (
    choose_pages,
    default_planner,
    digest,
    visited_pages,
    write_checks,
)
from precedent.worker import verify as v

FOLDER = "tribunal"
CLAIMED = {"written", "met", "done", "inferred", "verified"}
UNCHANGED_CLAIMS = {"vendor_unchanged"}
CHARGES_AT_ONCE = 3


class Record:
    """Append-only event log for one hearing (tribunal/events.jsonl)."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "events.jsonl"
        self.path.write_text("")
        self.seq = 0
        self.lock = threading.Lock()
        self.started = time.monotonic()

    def emit(self, event: str, /, **data) -> None:
        with self.lock:
            self.seq += 1
            line = {
                "seq": self.seq,
                "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "t": round(time.monotonic() - self.started, 2),
                "event": event,
                **data,
            }
            with self.path.open("a") as out:
                out.write(json.dumps(line, default=str) + "\n")


def read_record(run_dir: Path, folder: str = FOLDER) -> list[dict]:
    path = Path(run_dir) / folder / "events.jsonl"
    if not path.is_file():
        return []
    items = []
    for line in path.read_text().splitlines():
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def _identity(apps_url: str, case: Case) -> str | None:
    """None if the running apps are the company this run worked in; else the reason."""
    try:
        response = httpx.get(apps_url.rstrip("/") + "/workspace.json", headers=HEADERS, timeout=5)
        response.raise_for_status()
        company = response.json()
    except (httpx.HTTPError, ValueError):
        return "the company apps are not reachable"
    expected = case.company.get("instance_id")
    if not expected or company.get("instance_id") != expected:
        return "the running company is not the one this run worked in"
    return None


def _vote_dict(vote: Vote) -> dict:
    ballot = vote.ballot.model_dump() if vote.ballot else None
    return {
        "juror": vote.juror,
        "family": vote.family,
        "sample": vote.sample,
        "ballot": ballot,
        "error": vote.error,
        "seconds": vote.seconds,
    }


def convene(
    run_dir: Path,
    apps_url: str | None = None,
    jurors: list[Juror] | None = None,
    arbiter: Juror | None = None,
    k: int = 3,
    screenshots: bool = True,
    jurors_factory: Callable[[], tuple[list[Juror], Juror | None]] | None = None,
    folder: str = FOLDER,
    in_run: bool = False,
    planner=None,
) -> dict:
    run_dir = Path(run_dir)
    try:
        case = load_case(run_dir, require_finished=not in_run)
    except CaseError as exc:
        return {"overall": "unknown", "reason": str(exc)}  # the previous record stays
    record = Record(run_dir / folder)
    try:
        return _hear_case(record, case, apps_url, jurors, arbiter, k, screenshots,
                          jurors_factory, planner)  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - a broken court adjourns visibly, never passes
        reason = f"the court failed ({type(exc).__name__})"
        record.emit("adjourned", reason=reason)
        result = {"overall": "unknown", "reason": reason}
        (record.directory / "verdict.json").write_text(json.dumps(result, indent=2))
        return result


def _hear_case(
    record, case, apps_url, jurors, arbiter, k, screenshots, jurors_factory, planner=None
) -> dict:
    base = apps_url or case.apps_url
    record.emit(
        "convened",
        run_id=case.run_id,
        request=case.request,
        company=case.company.get("name"),
        conditions=len(case.goal.conditions),
    )
    problem = _identity(base, case) if base else "no company apps address for this run"
    if problem:
        record.emit("adjourned", reason=problem)
        result = {"overall": "unknown", "reason": problem}
        (record.directory / "verdict.json").write_text(json.dumps(result, indent=2))
        return result
    if jurors is None:
        jurors, arbiter = (jurors_factory or _default)()
    record.emit(
        "bench",
        jurors=[{"name": j.name, "family": j.family} for j in jurors],
        arbiter=arbiter.name if arbiter else None,
        samples=k,
    )
    if case.goal.task_family == "native_google":
        # A native contract is written by code from the request, so the court states it in the
        # current wording, dated to the run's own day (never the day of a later hearing).
        from precedent.worker import native

        first = next((e.get("ts") for e in case.events if e.get("ts")), "")
        day = datetime.fromisoformat(first.replace("Z", "+00:00")).astimezone(
            native.ZoneInfo(native.zone())
        )
        case.goal = native.native_goal(case.request, today=day.date())
    for condition in case.goal.conditions:
        record.emit(
            "charge",
            id=condition.id,
            text=condition.text,
            kind=condition.kind,
            claims=sorted(v.required_claims(condition)),
        )

    findings = audit(case)
    exact: dict[str, CheckResult] = {}
    process: set[str] = set()
    on_exhibit = lambda e: record.emit("exhibit", **e.public())  # noqa: E731
    conditions = list(case.goal.conditions)
    # A skill taught by demonstration brings the person's own definition of done.
    taught: list[str] = []
    for event in case.events:
        data = event.get("data", {})
        if data.get("kind") == "skill_loaded" and data.get("origin") == "demonstration":
            for text in data.get("done_when") or []:
                cid = f"d{len(taught) + 1}"
                conditions.append(Condition(id=cid, text=str(text)[:400], kind="must_be_true"))
                taught.append(cid)
                record.emit("charge", id=cid, text=str(text)[:400], kind="must_be_true",
                            claims=[], added=True, origin="demonstration")  # fmt: skip

    # 1 the court's own plan, step one: which pages to read (layer 1, any task family)
    if planner is None:
        planner = default_planner()
    plan_pages: list[str] = []
    if planner:
        try:
            plan_pages = choose_pages(planner[1], case.request, conditions,
                                      visited_pages(case.events))  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - no plan only means fewer exact checks
            record.emit("plan", model=planner[0], error=type(exc).__name__, pages=[], checks=0)
            planner = None

    # 2 evidence and the specialist checks for families that have them
    if case.goal.task_family == "meeting":
        exhibits, results = _meeting_court(base, case, record.directory, screenshots, on_exhibit)
    elif case.goal.task_family == "native_google":
        exhibits, results = _native_court(base, case, record.directory, screenshots, on_exhibit)
    else:
        exhibits = collect(base, case.plan, record.directory, screenshots, on_exhibit)
        # Any page the court read can be a cited source; the target bill never cites itself.
        results = v.verify(
            base,
            case.goal,
            case.plan,
            {e.path: e.html for e in exhibits},
            lambda r: None,
            headers=HEADERS,
            baselines={},
        )
    have = {e.path for e in exhibits}
    extra = [p for p in plan_pages if p not in have]
    if case.goal.task_family == "native_google":
        # The work lives in Google; the company's own Mail and Calendar hold none of it.
        extra = [p for p in extra if not p.startswith(("/mail", "/calendar"))]
    if extra:
        exhibits += collect_paths(base, extra, [], record.directory, screenshots, on_exhibit,
                                  start=len(exhibits))  # fmt: skip

    # 3 the court's own plan, step two: typed checks over what those pages really show
    generic: dict[str, list[Outcome]] = {}
    added: list[str] = []
    if planner:
        pages = {e.path: e.html for e in exhibits}
        try:
            plan = write_checks(planner[1], case.request, conditions,
                                [digest(p, h) for p, h in pages.items()])  # fmt: skip
        except Exception as exc:  # noqa: BLE001
            plan = None
            record.emit("plan", model=planner[0], error=type(exc).__name__, pages=list(pages),
                        checks=0)  # fmt: skip
        if plan is not None:
            for i, text in enumerate(plan.uncovered, 1):
                missed = Condition(id=f"u{i}", text=text, kind="must_be_true")
                conditions.append(missed)
                added.append(missed.id)
                record.emit("charge", id=missed.id, text=text, kind=missed.kind, claims=[],
                            added=True, origin="request")  # fmt: skip
            record.emit("plan", model=planner[0], pages=list(pages), checks=len(plan.checks),
                        missed=plan.uncovered)  # fmt: skip
            texts = {c.id: c.text for c in conditions}
            with httpx.Client(base_url=base, headers=HEADERS, timeout=20) as client:

                def read(path: str) -> str:
                    if path not in pages:
                        response = client.get(path)
                        response.raise_for_status()
                        pages[path] = response.text
                    return pages[path]

                for check in plan.checks:
                    reason = provenance(check, case.request, texts[check.condition_id], pages)
                    outcome = (
                        Outcome(result="unknown", evidence=f"not counted: {reason}")
                        if reason
                        else run_check(check, read)
                    )
                    generic.setdefault(check.condition_id, []).append(outcome)
                    record.emit("check", **check.model_dump(), **outcome.model_dump())

    # 4 audit; the exact court borrows its master-data finding
    for f in findings:
        record.emit("audit", **f.model_dump())
    no_master_writes = next(f for f in findings if f.rule.startswith("No company master"))
    specialist = {r.condition_id: r for r in results}
    for condition in conditions:
        result = merge(
            condition, specialist.get(condition.id), combine(generic.get(condition.id, []))
        )
        if (
            result.result == "unknown"
            and condition.kind == "must_not_happen"
            and v.required_claims(condition) <= UNCHANGED_CLAIMS
            and no_master_writes.result == "pass"
        ):
            # Not an exact check: the gateway's own write log is process evidence. It stays
            # a separately labelled basis and never counts as an exact pass.
            process.add(condition.id)
            result = result.model_copy(
                update={"evidence": f"{result.evidence}; write log: {no_master_writes.detail}"}
            )
        exact[condition.id] = result
        record.emit("exact", **result.model_dump())

    # The run's own write log is evidence too: what changed, where, with what result.
    log_text = "\n".join(f"{w.method} {w.path} -> {w.status}" for w in case.writes) or (
        "No writes were made."
    )
    write_log = Exhibit(
        id=f"E{len(exhibits) + 1}",
        path="(the run's write log)",
        title="Write log",
        kind="log",
        text=log_text,
        fields={},
        sha256=hashlib.sha256(log_text.encode()).hexdigest(),
        captured_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    exhibits.append(write_log)
    on_exhibit(write_log)

    # 4 jury, then 6 verdict per charge
    images = [
        (record.directory / e.screenshot).read_bytes()
        for e in exhibits
        if e.screenshot and (record.directory / e.screenshot).is_file()
    ][:2]

    def hear(condition):
        cid = condition.id
        record.emit("deliberating", id=cid)
        prompt = question(condition.text, exhibits)
        votes = deliberate(
            jurors,
            prompt,
            images,
            k=k,
            on_vote=lambda vote: record.emit("vote", id=cid, **_vote_dict(vote)),
        )
        exact_result = exact[cid].result if cid in exact else "unknown"
        t = rules.tally(votes) if jurors else None
        ruling = rules.rule(exact_result, t, process=cid in process)
        if ruling.result == "disputed" and arbiter is not None:
            record.emit("arbiter_called", id=cid, arbiter=arbiter.name)
            answer = None
            try:
                ballot = arbiter.ask(prompt, images)
                answer = ballot.answer
                record.emit("arbiter", id=cid, ballot=ballot.model_dump())
            except Exception as exc:  # noqa: BLE001
                record.emit("arbiter", id=cid, ballot=None, error=type(exc).__name__)
            ruling = rules.arbitrate(ruling, exact_result, answer)
        record.emit(
            "ruling",
            id=cid,
            exact=exact_result,
            tally=t.model_dump() if t else None,
            **ruling.model_dump(),
        )
        return cid, {**ruling.model_dump(), "valid_votes": t.valid if t else 0}

    # Charges are heard three at a time; each charge's votes run in parallel too.
    with cf.ThreadPoolExecutor(max_workers=CHARGES_AT_ONCE) as pool:
        verdicts = dict(pool.map(hear, conditions))

    return _close(record, case, verdicts, findings, exhibits, len(jurors), added)


def merge(condition, specialist: CheckResult | None, generic: Outcome | None) -> CheckResult:
    """One exact result per condition. A curated specialist check decides whenever it
    reaches a verdict; the court's model-planned checks fill only the gaps it leaves. A
    disagreement is recorded in the evidence, never allowed to override (a planned check can
    be mis-specified, as a count over the wrong rows once showed)."""
    gen_text = "court checks: " + generic.evidence if generic else ""
    if specialist is not None and specialist.result in ("pass", "fail"):
        evidence = specialist.evidence or ""
        if generic and generic.result in ("pass", "fail") and generic.result != specialist.result:
            evidence += f"; the court's own checks disagree ({gen_text})"
        return CheckResult(condition_id=condition.id, text=condition.text,
                           result=specialist.result, evidence=evidence[:1200])  # fmt: skip
    if generic and generic.result in ("pass", "fail"):
        return CheckResult(condition_id=condition.id, text=condition.text, result=generic.result,
                           evidence=gen_text[:1200])  # fmt: skip
    evidence = "; ".join(x for x in ((specialist.evidence if specialist else ""), gen_text) if x)
    return CheckResult(condition_id=condition.id, text=condition.text, result="unknown",
                       evidence=(evidence or "no exact check could be made")[:1200])  # fmt: skip


def _meeting_court(base, case, directory, screenshots, on_exhibit):
    """Meeting tasks: rerun the deterministic meeting checks with the Tribunal's identity,
    then read the draft, availability, any hold and the cited Mail/Chat sources itself."""
    from precedent.worker.meetings import verify as verify_meeting

    sources_file = case.directory / "learning-sources.json"
    try:
        captured = json.loads(sources_file.read_text()) if sources_file.is_file() else {}
    except ValueError:
        captured = {}
    writes = [(w.method, w.path, w.status) for w in case.writes]
    results, links = verify_meeting(base, case.goal, captured, writes, headers=HEADERS)
    records = [link["path"] for link in links]
    cited = []
    with httpx.Client(base_url=base, headers=HEADERS, timeout=15) as client:
        for path in records:
            if path.startswith("/mail/drafts/"):
                try:
                    fields = v.record_fields(client.get(path).text)
                except httpx.HTTPError:
                    continue
                cited += re.findall(
                    r"/(?:mail/m|chat)/[A-Za-z0-9_.-]+", fields.get("Source paths", "")
                )
    exhibits = collect_paths(base, records, cited, directory, screenshots, on_exhibit)
    return exhibits, results


def _native_court(base, case, directory, screenshots, on_exhibit):
    """Native Google tasks: the work lives in the owner's Gmail and Calendar, not the company
    apps. The court reads the draft, the Sent folder and the calendar changes itself, through
    the owner's read-only connection and bounded to the run's own time window, reruns the
    exact checks on those reads, and reads the company sources the draft must agree with."""
    from precedent.worker import native

    stamps = [e.get("ts", "") for e in case.events if e.get("ts")]
    since = datetime.fromisoformat(stamps[0].replace("Z", "+00:00")).replace(microsecond=0)
    until = datetime.fromisoformat(stamps[-1].replace("Z", "+00:00"))
    results, google, sources = native.tribunal_reads(base, case.request, since, until, HEADERS)
    exhibits = collect_paths(base, [], sources, directory, screenshots, on_exhibit)
    for item in google:
        exhibit = Exhibit(
            id=f"E{len(exhibits) + 1}",
            path=item["path"],
            title=item["title"],
            kind="record",
            text=item["text"],
            fields=item["fields"],
            sha256=hashlib.sha256(item["text"].encode()).hexdigest(),
            captured_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        exhibits.append(exhibit)
        on_exhibit(exhibit)
    return exhibits, results


def _close(
    record: Record,
    case: Case,
    verdicts: dict[str, dict],
    findings: list[Finding],
    exhibits: list[Exhibit],
    jurors: int,
    added: list[str] | None = None,
) -> dict:
    results = [r["result"] for r in verdicts.values()]
    audit_failed = any(f.result == "fail" for f in findings)
    overall = rules.overall(results, audit_failed)
    unsupported = []
    for cid, ruling in verdicts.items():
        claim = case.claims.get(cid)
        if claim and claim.get("status") in CLAIMED and ruling["result"] != "pass":
            unsupported.append(
                {
                    "id": cid,
                    "claimed": claim.get("evidence"),
                    "status": claim.get("status"),
                    "ruling": ruling["result"],
                }
            )
    claimed = (case.finish or {}).get("outcome")
    result = {
        "run_id": case.run_id,
        "overall": overall,
        "rulings": verdicts,
        "counts": {k: results.count(k) for k in ("pass", "fail", "disputed", "unknown")},
        "judged": sum(
            1 for r in verdicts.values() if r["result"] == "pass" and r["basis"] != "exact"
        ),
        "jurors": jurors,
        "missed": [
            {"id": cid, "ruling": verdicts[cid]["result"]}
            for cid in (added or [])
            if cid in verdicts
        ],
        "audit_failed": audit_failed,
        "ava_claimed": claimed,
        "unsupported_claims": unsupported,
        "overclaimed": claimed == "pass" and overall != "pass",
        "grader": (case.grade or {}).get("overall"),
        "exhibits": len(exhibits),
        "seconds": round(time.monotonic() - record.started, 1),
    }
    (record.directory / "verdict.json").write_text(json.dumps(result, indent=2))
    record.emit("verdict", **result)
    return result


def _default():
    from precedent.tribunal.jury import default_jurors

    return default_jurors()

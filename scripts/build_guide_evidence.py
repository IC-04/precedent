"""Build the guide's evidence snapshot from retained runs, lessons and the test suite.

  .venv/bin/python scripts/build_guide_evidence.py

Writes src/precedent/console/guide_evidence.json and copies the recorded images the page
shows into src/precedent/apps/static/guide/. Every number on the guide comes from here, and
every entry names the run it was read from. Nothing is invented: a missing run is an error.
Run it again after new evidence is retained; the page itself never reads runs/ for numbers.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml
from PIL import Image, ImageFilter

REPO = Path(__file__).resolve().parents[1]
EMAIL_RE = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
RUNS = REPO / "runs"
LESSONS = REPO / "learning" / "demonstrations"
OUT = REPO / "src/precedent/console/guide_evidence.json"
IMAGES = REPO / "src/precedent/apps/static/guide"

HERO = "20261010-185357-0f7d"  # clean invoice run: Ava, Tribunal and grader all pass
GHOST = "20261008-131612-d12a"  # the only baseline (policy text only) run
STAGED = "20261010-193810-dd3f"  # lost routing staged by a scenario edit, remanded, pruned
MEETING = "20261010-210219-2c92"  # meeting run with an unstaged branch
BLOCKED = "20261010-225940-0ded"  # refused to create a duplicate
RESTART = "20261010-154410-fc9a"  # different invoice after a service restart
TAUGHT = "20261010-232230-9a49"  # taught skill loaded and passed
LESSON = "b986691bcc8f46b98fcf5bdf326f8d4e"  # the demonstration behind that skill
NATIVE = "20261011-210344-d343"  # draft in the owner's real Gmail and a hold in real Calendar
# Frames of the owner's real account are cropped, and personal details blurred, by explicit
# boxes (frame pixels, 1280 x 773): the owner's name, avatar, organisation logo, calendar
# name and addresses.
NATIVE_FRAMES = [
    ("view-00022.png", "native-0-books", "Company apps tab · reading bill INV-920", None, []),
    ("view-00057.png", "native-1-calendar", "Google Calendar tab · typing the hold's title",
     None, [(1040, 0, 1280, 64), (60, 470, 240, 515)]),
    ("view-00060.png", "native-2-saved", "Google Calendar · Event saved",
     (240, 0, 1280, 773), [(1040, 0, 1280, 64)]),
    ("view-00075.png", "native-3-gmail", "Gmail tab · writing the draft body",
     (0, 85, 1280, 773), [(0, 0, 1280, 0)]),
]  # fmt: skip


def events(run: str) -> list[dict]:
    path = RUNS / run / "events.jsonl"
    if not path.exists():
        sys.exit(f"Missing retained run {run}")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def finished(evs: list[dict]) -> dict:
    return next((e["data"] for e in reversed(evs) if e["type"] == "run_finished"), {})


def notes(evs: list[dict], kind: str) -> list[dict]:
    return [e["data"] for e in evs if e["type"] == "note" and e["data"].get("kind") == kind]


def grade(run: str) -> dict | None:
    path = RUNS / run / "grade.json"
    if not path.exists():
        return None
    g = json.loads(path.read_text())
    items = g["items"]
    return {
        "overall": g["overall"],
        "passed": sum(i["result"] == "pass" for i in items),
        "total": len(items),
        "items": {
            i["name"]: {k: i.get(k) for k in ("result", "expected", "actual")} for i in items
        },
    }


def verdict(run: str, folder: str = "tribunal") -> dict | None:
    path = RUNS / run / folder / "verdict.json"
    return json.loads(path.read_text()) if path.exists() else None


def people() -> dict[str, str]:
    template = yaml.safe_load((REPO / "src/precedent/world/templates/northwind.yaml").read_text())
    names = [p["name"]["value"] for p in template["people"].values()]
    return {"E-" + n.split()[0].lower(): n for n in names}


def save_image(source: Path, name: str, width: int = 1280, crop: tuple | None = None) -> str:
    IMAGES.mkdir(parents=True, exist_ok=True)
    image = Image.open(source).convert("RGB")
    if crop:
        image = image.crop(crop)
    if image.width > width:
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
    target = IMAGES / f"{name}.webp"
    image.save(target, "WEBP", quality=74, method=6)
    return f"/static/guide/{target.name}"


def seconds_between(a: str, b: str) -> float:
    parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
    return round((parse(b) - parse(a)).total_seconds(), 1)


def hero() -> dict:
    evs = events(HERO)
    start = evs[0]["ts"]
    goal = next(e["data"] for e in evs if e["type"] == "goal_contract")
    frames, caption = [], None
    for e in evs:
        if e["type"] == "action":
            caption = e["data"].get("caption")
        if e["type"] == "observation" and e["data"].get("screenshot"):
            shot = RUNS / HERO / e["data"]["screenshot"]
            frames.append(
                {
                    "src": save_image(shot, f"run-{len(frames):02d}", width=1280),
                    "caption": caption or "Reading the page",
                    "title": (e["data"].get("title") or "").split(" · ")[0],
                    "t": seconds_between(start, e["ts"]),
                }
            )
    checks = {}
    for e in evs:
        if e["type"] == "check":
            d = e["data"]
            checks[d["condition_id"]] = {"result": d["result"], "evidence": d.get("evidence", "")}
    tribunal = verdict(HERO)
    context = notes(evs, "context_gathered")[0]
    timing = notes(evs, "context_timing")[0]
    plan = next(e["data"]["steps"] for e in evs if e["type"] == "plan")
    done = finished(evs)
    g = grade(HERO)
    precedents = [
        {
            "rule": e["data"]["rule"],
            "support": e["data"].get("support"),
            "status": e["data"]["status"],
            "flags": e["data"].get("flags", []),
            "exceptions": e["data"].get("exceptions", []),
            "source": (e["data"].get("governing") or {}).get("ref"),
            "authority": (e["data"].get("governing") or {}).get("authority"),
            "quote": (e["data"].get("governing") or {}).get("quote"),
            "dated": (e["data"].get("governing") or {}).get("dated"),
        }
        for e in evs
        if e["type"] == "precedent"
    ]
    featured = next(p for p in precedents if "stale_sop" in p["flags"])
    return {
        "run_id": HERO,
        "request": goal["request"],
        "featured": featured,
        "precedents": precedents,
        "outcome": goal["outcome"],
        "conditions": [
            {"id": c["id"], "text": c["text"], "kind": c["kind"]} for c in goal["conditions"]
        ],
        "plan": [s["intent"] for s in plan],
        "context": {
            "sources": context["items"],
            "rows": context["rows"],
            "seconds": timing["seconds"],
        },
        "decisions": [
            {
                "decided": e["data"]["decided"],
                "sources": e["data"]["sources"],
                "gate": e["data"].get("gate"),
            }
            for e in evs
            if e["type"] == "decision_record"
        ],
        "facts": [n["fact"] for n in notes(evs, "fact")],
        "effects": [f"{n['method']} {n['path']} → {n['status']}" for n in notes(evs, "app_effect")],
        "checks": [{"id": k, **v} for k, v in checks.items()],
        "frames": frames,
        "ava": {
            "passed": sum(c["result"] == "pass" for c in checks.values()),
            "total": len(checks),
        },
        "tribunal": {
            "overall": tribunal["overall"],
            "passed": tribunal["counts"]["pass"],
            "total": sum(tribunal["counts"].values()),
            "seconds": tribunal.get("seconds"),
        },
        "grader": {k: g[k] for k in ("overall", "passed", "total")},
        "seconds": done["seconds"],
        "tokens_in": done["tokens_in"],
        "model_responses": done.get("model_responses"),
        "steps": done["steps"],
        "questions": done["questions"],
        "actions": sum(e["type"] == "action" for e in evs),
    }


def sources() -> dict:
    """The two sources that disagree about design approvals, quoted exactly as gathered."""
    folder = RUNS / HERO / "evidence"
    gathered = [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))]
    listing = [
        {"ref": g["ref"], "app": g["app"], "title": g["title"], "dated": g.get("dated"),
         "rows": len(g.get("rows") or [])}
        for g in gathered
    ]  # fmt: skip
    sop = next(g for g in gathered if g["ref"] == "drive:f-0002")
    mail = next(g for g in gathered if g["ref"] == "mail:m-0001")
    rule = re.search(r"Route design spend[^.]*\.", sop["text"]).group(0)
    body = re.search(r"Hi all,.*", mail["text"]).group(0).strip()
    # The sender's address is first.last@company; the page shows the name just before it.
    last = re.search(r"\.([a-z]+)@", mail["text"]).group(1)
    sender = re.search(r"([A-Z][a-z]+) (" + last.capitalize() + ")", mail["text"])
    effective = re.search(r"Effective ([A-Za-z]+ \d{4})", sop["text"]).group(1)
    return {
        "listing": listing,
        "sop": {
            "ref": sop["ref"],
            "title": sop["title"],
            "section": "3.2",
            "text": rule,
            "effective": effective,
        },
        "mail": {
            "ref": mail["ref"],
            "title": mail["title"],
            "dated": mail["dated"],
            "sender": " ".join(sender.groups()) if sender else "",
            "text": body,
        },
    }


def ghost(hero_grade: dict) -> dict:
    evs = events(GHOST)
    started = next(e["data"] for e in evs if e["type"] == "run_started")
    assert started["worker"] == "baseline", "the ghost run must be the baseline worker"
    g, names = grade(GHOST), people()
    item = g["items"]["approver"]
    return {
        "run_id": GHOST,
        "date": evs[0]["ts"][:10],
        "request": started["request"],
        "approver": names.get(item["actual"], item["actual"]),
        "expected": names.get(item["expected"], item["expected"]),
        "result": item["result"],
        "grader": {k: g[k] for k in ("overall", "passed", "total")},
        "ava_approver": names.get(
            hero_grade["items"]["approver"]["actual"], hero_grade["items"]["approver"]["actual"]
        ),
        "ava_result": hero_grade["items"]["approver"]["result"],
    }


def staged() -> dict:
    before, after = verdict(STAGED, "tribunal-before-remand"), verdict(STAGED)
    record = [
        json.loads(line)
        for line in (RUNS / STAGED / "tribunal-before-remand/events.jsonl").read_text().splitlines()
    ]
    exact = {e["condition_id"]: e["evidence"] for e in record if e["event"] == "exact"}
    votes = [e for e in record if e["event"] == "vote"]
    remand = notes(events(STAGED), "remand")[0]
    # The bill's field panel, and the activity line that discloses the staged change.
    e1 = RUNS / STAGED / "tribunal-before-remand/E1.png"
    exhibit = save_image(e1, "tribunal-exhibit", 1000, crop=(204, 130, 1200, 720))
    staging = save_image(e1, "tribunal-staging", 1000, crop=(204, 1356, 1200, 1428))
    return {
        "run_id": STAGED,
        "claims": [c["claimed"] for c in before["unsupported_claims"]],
        "evidence": {k: exact[k] for k in remand["charges"] if k in exact},
        "branches": len(before["unsupported_claims"]),
        "before": {"counts": before["counts"], "seconds": before["seconds"]},
        "after": {"counts": after["counts"], "seconds": after["seconds"]},
        "remanded": remand["charges"],
        "votes": len(votes),
        "families": sorted({v["family"] for v in votes}),
        "exhibit": exhibit,
        "staging": staging,
    }


def meeting() -> dict:
    v = verdict(MEETING)
    failed = [k for k, r in v["rulings"].items() if r["result"] != "pass"]
    record = [
        json.loads(line)
        for line in (RUNS / MEETING / "tribunal/events.jsonl").read_text().splitlines()
    ]
    evidence = next(
        (
            e.get("evidence")
            for e in record
            if e["event"] == "exact" and e["condition_id"] in failed
        ),
        "",
    )
    started = next(e["data"] for e in events(MEETING) if e["type"] == "run_started")
    return {
        "run_id": MEETING,
        "request": started["request"].split(".")[0] + ".",
        "counts": v["counts"],
        "failed": failed,
        "evidence": evidence,
    }


def blocked() -> dict:
    evs = events(BLOCKED)
    started = next(e["data"] for e in evs if e["type"] == "run_started")
    return {"run_id": BLOCKED, "request": started["request"], "outcome": finished(evs)["outcome"]}


def restart() -> dict:
    evs = events(RESTART)
    checks = {e["data"]["condition_id"]: e["data"]["result"] for e in evs if e["type"] == "check"}
    g = grade(RESTART)
    return {
        "run_id": RESTART,
        "ava": {"passed": sum(r == "pass" for r in checks.values()), "total": len(checks)},
        "grader": {k: g[k] for k in ("overall", "passed", "total")},
        "recalled": [n.get("text") for n in notes(evs, "memory_recalled")][:1],
    }


def taught() -> dict:
    evs = events(TAUGHT)
    loaded = notes(evs, "skill_loaded")[0]
    v = verdict(TAUGHT)
    lesson = LESSONS / LESSON
    steps = [
        json.loads(line)
        for line in (lesson / "notes.jsonl").read_text().splitlines()
        if json.loads(line).get("event") == "step"
    ]
    grounded = [
        s for s in steps if (s.get("grounding") or {}).get("status") in ("grounded", "page_found")
    ]
    shown = []
    for s in steps:
        if s.get("frame") and s.get("action") in ("type", "select", "click") and len(shown) < 4:
            shown.append(
                {
                    "t": (s.get("t") or "").split(".")[0],
                    "action": s["action"],
                    "target": s.get("target"),
                    "value": s.get("value"),
                    "confirmed": s in grounded,
                    "frame": save_image(
                        lesson / "frames" / s["frame"], f"lesson-{len(shown)}", 900
                    ),
                }
            )
    draft = json.loads((lesson / "draft.json").read_text())
    return {
        "run_id": TAUGHT,
        "lesson_id": LESSON,
        "skill": loaded["text"].removeprefix("Taught skill loaded: "),
        "done_when": loaded["done_when"],
        "steps": len(steps),
        "grounded": len(grounded),
        "notes": shown,
        "parameters": [p["name"].replace("_", " ") for p in draft.get("parameters", [])][:6],
        "tribunal": {
            "overall": v["overall"],
            "passed": v["counts"]["pass"],
            "total": sum(v["counts"].values()),
        },
        "outcome": finished(evs)["outcome"],
    }


def totals() -> dict:
    workers, outcomes, failures, failure_runs = Counter(), [], Counter(), 0
    heard = remanded = 0
    for run in sorted(p for p in RUNS.iterdir() if (p / "events.jsonl").exists()):
        evs = [json.loads(x) for x in (run / "events.jsonl").read_text().splitlines() if x.strip()]
        if not evs:
            continue
        started = next((e["data"] for e in evs if e["type"] == "run_started"), {})
        workers[started.get("worker", "unknown")] += 1
        kinds = [e["data"].get("kind") for e in evs if e["type"] == "failure"]
        failures.update(kinds)
        failure_runs += bool(kinds)
        heard += (run / "tribunal/verdict.json").exists()
        remanded += (run / "tribunal-before-remand").exists()
        done = finished(evs)
        if started.get("worker") == "precedent" and done.get("outcome"):
            outcomes.append(
                {
                    "run_id": run.name,
                    "date": evs[0]["ts"][:10],
                    "outcome": done["outcome"],
                    "family": "meeting"
                    if re.search(r"catch-up|meeting", started.get("request", ""), re.I)
                    else "invoice",
                    "tribunal": (verdict(run.name) or {}).get("overall"),
                }
            )
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    tests = int(re.search(r"(\d+) tests? collected", collected).group(1))
    lines = sum(len(p.read_text().splitlines()) for p in (REPO / "src").rglob("*.py"))
    return {
        "runs": sum(workers.values()),
        "workers": dict(workers),
        "failures": sum(failures.values()),
        "failure_kinds": dict(failures),
        "failure_runs": failure_runs,
        "tribunal_heard": heard,
        "remanded": remanded,
        "outcomes": outcomes,
        "tests": tests,
        "python_lines": lines,
    }


def redacted(source: Path, name: str, crop, blurs) -> str:
    image = Image.open(source).convert("RGB")
    for box in blurs:
        if box[3] > box[1]:
            region = image.crop(box).filter(ImageFilter.GaussianBlur(14))
            image.paste(region, box[:2])
    if crop:
        image = image.crop(crop)
    IMAGES.mkdir(parents=True, exist_ok=True)
    target = IMAGES / f"{name}.webp"
    image.save(target, "WEBP", quality=74, method=6)
    return f"/static/guide/{target.name}"


def native() -> dict:
    evs = events(NATIVE)
    started = next(e["data"] for e in evs if e["type"] == "run_started")
    done = finished(evs)
    own = json.loads((RUNS / NATIVE / "native-verification.json").read_text())["checks"]
    court = verdict(NATIVE)
    actions = [e["data"] for e in evs if e["type"] == "action"]
    refused = sum(1 for n in notes(evs, "write_refused"))
    frames = [
        {"src": redacted(RUNS / NATIVE / "shots" / f, name, crop, blurs), "caption": caption}
        for f, name, caption, crop, blurs in NATIVE_FRAMES
    ]
    sites = []
    for a in actions:
        url = str((a.get("args") or {}).get("url", ""))
        site = (
            "Gmail" if "mail.google.com" in url
            else "Google Calendar" if "calendar.google.com" in url
            else None
        )  # fmt: skip
        if site and site not in sites:
            sites.append(site)
    return {
        "run_id": NATIVE,
        "request": re.sub(EMAIL_RE, "your own address", started["request"]),
        "seconds": done["seconds"],
        "steps": done["steps"],
        "actions": len(actions),
        "sites": sites,
        "refused": refused,
        "ava": {"passed": sum(c["result"] == "pass" for c in own), "total": len(own)},
        "tribunal": {
            "overall": court["overall"],
            "passed": court["counts"]["pass"],
            "total": sum(court["counts"].values()),
        },
        "frames": frames,
    }


def main() -> None:
    h = hero()
    data = {
        "generated": datetime.now(UTC).strftime("%Y-%m-%d"),
        "note": "Read from retained runs, lessons and tests by scripts/build_guide_evidence.py.",
        "hero": h,
        "sources": sources(),
        "ghost": ghost(grade(HERO)),
        "staged": staged(),
        "meeting": meeting(),
        "blocked": blocked(),
        "restart": restart(),
        "taught": taught(),
        "native": native(),
        "totals": totals(),
    }
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"Wrote {OUT.relative_to(REPO)} and {len(list(IMAGES.glob('*.webp')))} images")


if __name__ == "__main__":
    main()

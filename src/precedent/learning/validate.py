"""Isolated skill trial harness. Creates a disposable company, then runs the real worker."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import socket
import threading
import time
from pathlib import Path

import uvicorn

from precedent.apps.server import create_app
from precedent.learning.store import CRITICAL, Store
from precedent.worker.events import read_events
from precedent.worker.runner import RunConfig, run
from precedent.world.generator import generate


async def validate(
    root: Path,
    scope: str,
    skill_id: str,
    runs: Path,
    run_id: str,
    seed: int,
    template: str,
    headed: bool = False,
):
    os.environ["PRECEDENT_MEMORY_ROOT"] = str(root)
    store = Store(root)
    skill = store.get(scope, skill_id)
    server = None
    try:
        if skill["status"] != "validating" or skill["payload"].get("missing_coverage"):
            raise ValueError("Skill is not ready for validation")
        taught = skill["payload"].get("origin") == "demonstration"
        request = (
            skill["payload"]["trial_request"]
            if taught
            else store.get(scope, skill["payload"]["source_episode"])["payload"]["request"]
        )
        trial = root / "validation" / run_id
        worlds = trial / "worlds"
        generate(template, seed, worlds / str(seed))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        app = create_app(seed, worlds)
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        if not server.started:
            raise RuntimeError("Sandbox company could not start")
        result = await run(
            RunConfig(
                request=request,
                seed=seed,
                apps_url=f"http://127.0.0.1:{port}",
                runs_root=runs,
                run_id=run_id,
                headed=headed,
                validation_skill=skill,
            )
        )
        events = read_events(runs / run_id / "events.jsonl")
        checks = [e.data for e in events if e.type == "check"]
        covered = set().union(*(set(c.get("claims", [])) for c in checks if c["result"] == "pass"))
        used = any(e.type == "note" and e.data.get("kind") == "skill_loaded" for e in events)
        if taught:
            # A taught skill passes its rehearsal when Ava loaded it and the outcome, which
            # includes the Tribunal's verdict on the person's "done when" list, is a pass.
            passed = used and result["outcome"] == "pass"
            covered = CRITICAL if passed else set()
        else:
            passed = CRITICAL <= covered and not any(c["result"] == "fail" for c in checks) and used
        payload = skill["payload"]
        payload["validation"] = {
            "passed": passed,
            "run_id": run_id,
            "at": time.time(),
            "missing": sorted(CRITICAL - covered),
            "skill_loaded": used,
            "worker_outcome": result["outcome"],
            "instance_id": app.state.company["instance_id"],
            "procedure_hash": hashlib.sha256(payload["instructions"].encode()).hexdigest(),
        }
        store.revise(
            scope, skill_id, status="validated" if passed else "validation_failed", payload=payload
        )
    except Exception as exc:
        payload = skill["payload"]
        payload["validation"] = {
            "passed": False,
            "run_id": run_id,
            "error": f"{type(exc).__name__}: {exc}"[:500],
        }
        store.revise(scope, skill_id, status="validation_failed", payload=payload)
    finally:
        if server:
            server.should_exit = True
            await asyncio.to_thread(thread.join, 5)


def main():
    p = argparse.ArgumentParser()
    for name in ("root", "scope", "skill", "runs", "run-id", "template"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--headed", action="store_true")
    args = p.parse_args()
    from dotenv import load_dotenv

    load_dotenv()
    asyncio.run(
        validate(
            Path(args.root),
            args.scope,
            args.skill,
            Path(args.runs),
            args.run_id,
            args.seed,
            args.template,
            args.headed,
        )
    )


if __name__ == "__main__":
    main()

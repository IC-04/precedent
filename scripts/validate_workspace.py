"""Clearly labelled scripted MCP workflow, exclusively against a supplied disposable world.

No model calls, no hidden truth and no direct company writes. Fixture choices are known
seed-7 test inputs; this validates browser operation, observation and app semantics.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

import httpx

from precedent.contracts import Condition, GoalContract
from precedent.worker.events import RUNS, EventLog, new_run_id
from precedent.worker.failures import WriteGate
from precedent.worker.gateway import Gateway
from precedent.worker.guard import Guard
from precedent.worker.receipt import write_receipt
from precedent.worker.runner import browser_toolset


async def validate(apps_url: str, root: Path):
    import hashlib
    import tempfile

    root = root.resolve()
    if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()) and not root.is_relative_to(
        Path("/tmp").resolve()
    ):
        raise ValueError(
            "Validation requires a disposable world under the system temporary directory"
        )
    manifest = root / "7" / "manifest.json"
    async with httpx.AsyncClient() as client:
        company = (await client.get(apps_url + "/workspace.json")).json()
    if company.get("world_id") != hashlib.sha256(manifest.read_bytes()).hexdigest():
        raise ValueError("The served company does not match the disposable manifest")
    log = EventLog("scripted-" + new_run_id(), root=RUNS)
    (log.dir / "mcp").mkdir(exist_ok=True)
    (log.dir / "launch.json").write_text(
        json.dumps(
            {
                "request": "Scripted validation: invoice entry and routing",
                "seed": 7,
                "company": company,
                "apps_url": apps_url,
            }
        )
    )
    log.emit(
        "run_started",
        request="Scripted validation: invoice entry and routing",
        worker="scripted",
        seed=7,
        model="none",
        validation="scripted browser workflow; no AI/model decisions",
    )
    log.emit("note", kind="company", company=company)
    gate = WriteGate()
    gateway = Gateway(apps_url, gate)
    base = gateway.start()
    guard = Guard(log, gate, gateway.lock, log.dir / "mcp")
    gateway.on_exchange = guard.on_exchange
    browser = browser_toolset(base, log.dir / "mcp", False)
    tools = {t.name: t for t in await browser.get_tools()}
    last = ""

    async def action(name, **args):
        nonlocal last
        tool = tools[name]
        assert guard.before_tool(tool, args, None) is None
        response = await tool.run_async(args=args, tool_context=None)
        capture = await browser.capture(log)
        compact = guard.after_tool(tool, args, None, response, capture=capture)
        assert not compact["isError"], compact
        last = compact["content"][0]["text"]
        return last

    async def navigate(path):
        return await action("browser_navigate", url=base + path)

    async def fill(field, text):
        return await action("browser_type", target="#f-" + field, text=text)

    async def select(field, value):
        return await action("browser_select_option", target="#f-" + field, values=[value])

    try:
        goal = GoalContract(
            request="Enter the seed-7 fixture invoice and request approval",
            outcome="One bill routed, approval pending",
            conditions=[
                Condition(
                    id="c1", text="Exactly one bill for the source invoice", kind="must_be_true"
                ),
                Condition(
                    id="c2", text="Correct invoice fields and attachment", kind="must_be_true"
                ),
                Condition(id="c3", text="Approval requested and pending", kind="must_be_true"),
                Condition(id="n1", text="No bank detail changes", kind="must_not_happen"),
            ],
        )
        log.emit("goal_contract", **goal.model_dump())
        guard.condition_ids = {condition.id for condition in goal.conditions}
        guard.update_plan(
            [
                "Read invoice and authority | Source facts visible",
                "Enter draft | Saved bill matches the fixture",
                "Request approval | Approval is pending",
                "Read back | Actual fields visible",
            ]
        )
        await navigate("/mail/?q=FIG-1842")
        message = re.search(r"/mail/m/(m-[\w-]+)", last)[1]
        await navigate("/mail/m/" + message)
        file_id = re.search(r"/drive/f/(f-[\w-]+)", last)[1]
        await navigate("/drive/f/" + file_id)
        await action("browser_click", target="text=Text of the file")
        assert "12 months prepaid" in last
        await navigate("/mail/?q=approval")
        # The script's choices are explicit fixture values, never labelled learned context.
        await navigate("/books/history?q=annual")
        await navigate("/books/bills?q=FIG-1842")
        assert "No bills match" in last
        guard.report_plan_step(
            "s1", "done", "Fixture source invoice and company records opened in browser"
        )
        await navigate("/books/bills/new")
        await select("vendor_id", "V-112")
        for field, text in [
            ("invoice_no", "FIG-1842"),
            ("amount", "112000"),
            ("currency", "INR"),
            ("issue_date", "2026-09-28"),
            ("due_date", "2026-10-21"),
        ]:
            await fill(field, text)
        await select("account_code", "1400")
        await select("attachment_file_id", file_id)
        await fill(
            "notes",
            "Scripted validation in a disposable world. Fixture values; no model decisions.",
        )
        guard.record_decision(
            observed="The real source invoice and search result were read",
            means="Scripted seed-7 validation uses known fixture inputs, not learned rules",
            decided="Save one fixture draft with the actual source attachment",
            sources=["mail:" + message, "drive:" + file_id, "books:search FIG-1842 absent"],
            action="Save draft",
            check="Read the saved fields back",
        )
        await action("browser_click", target='button:has-text("Save draft")')
        assert "Bill saved as a draft" in last
        bid = re.search(r"/books/bills/(INV-\d+)", last)[1]
        guard.report_goal_progress("c2", "written", "Draft save acknowledged by the application")
        guard.report_plan_step("s2", "done", "Draft bill save acknowledgement and fields visible")
        await navigate("/books/bills/" + bid)
        await select("approver_id", "E-ana")
        guard.record_decision(
            observed="Saved draft is visible in Books",
            means="The scripted validation has a known fixture approver; "
            "this is not model reasoning",
            decided="Request approval from the fixture approver; leave it pending",
            sources=["books:" + bid, "mail:approval search"],
            action="Request approval",
            check="Read pending approval",
        )
        await action("browser_click", target='button:has-text("Request approval")')
        assert "Approval requested" in last
        await navigate("/books/bills/" + bid)
        assert "pending approval" in last.lower() and "Ana Pereira" in last
        guard.report_plan_step("s3", "done", "Pending approval visible after fresh navigation")
        guard.report_plan_step(
            "s4",
            "done",
            "Fresh read-back performed by scripted harness; worker verifier unavailable",
        )
        guard.finish(
            "unknown",
            "Scripted browser validation saved and routed a fixture bill. "
            "Fresh worker verification remains unavailable.",
        )
        summary = {
            "outcome": "unknown",
            "claimed": "unknown",
            "usd": None,
            "steps": guard.steps,
            "seconds": guard.seconds(),
            "tokens_in": 0,
            "tokens_out": 0,
            "questions": 0,
            "error": None,
        }
        write_receipt(log, goal.request, guard.finished, summary)
        log.emit("run_finished", **summary)
        print(
            json.dumps(
                {
                    "run_id": log.run_id,
                    "bill_url": apps_url + "/books/bills/" + bid,
                    "invoice_url": apps_url + "/drive/f/" + file_id,
                    "captures": len(list((log.dir / "shots").glob("*.png"))),
                }
            )
        )
    finally:
        await browser.close()
        gateway.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apps-url", required=True)
    parser.add_argument("--disposable-root", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(validate(args.apps_url.rstrip("/"), args.disposable_root))

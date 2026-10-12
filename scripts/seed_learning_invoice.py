"""Add one labelled deterministic source invoice to the disposable Northwind-7 demo.

This fixture creates only a document and an email, never a bill or a worker memory.
The independent evaluator receives its own explicit benchmark contract separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from precedent.contracts import ExpectedTask
from precedent.grader.grade import register_followup_benchmark
from precedent.world import db
from precedent.world.pdf import Invoice, write_invoice


def seed(world: Path):
    manifest = json.loads((world / "manifest.json").read_text())
    if manifest["seed"] != 7 or manifest["template"] != "northwind":
        raise ValueError("This labelled demo fixture is for Northwind seed 7 only")
    conn = db.connect(world / "world.db")
    try:
        if db.row(conn, "files", "f-learning-0001"):
            raise ValueError("Follow-up source already exists; nothing changed")
        vendor = db.row(conn, "vendors", "V-112")
        relative = Path("files/FIG-1843.pdf")
        write_invoice(
            world / relative,
            Invoice(
                vendor_legal=vendor["legal_name"],
                vendor_address=vendor["address"],
                vendor_tax_id=vendor["tax_id"],
                invoice_no="FIG-1843",
                issue_date=date(2026, 10, 2),
                due_date=date(2026, 10, 31),
                bill_to=manifest["company"]["name"],
                lines=[("Organization plan, 52 editors. Annual, 12 months prepaid", 14600000)],
            ),
        )
        digest = hashlib.sha256((world / relative).read_bytes()).hexdigest()
        ts = "2026-10-02T08:12:00+00:00"
        file = {
            "id": "f-learning-0001",
            "folder": "Mail attachments",
            "name": "FIG-1843.pdf",
            "mime": "application/pdf",
            "path": str(relative),
            "uploaded_by": None,
            "uploaded_at": ts,
            "sha256": digest,
        }
        message = {
            "id": "m-learning-0001",
            "thread_id": "t-learning-0001",
            "folder": "Inbox",
            "from_name": vendor["name"] + " Billing",
            "from_addr": vendor["email"],
            "to_addr": "finance-team@northwind.example",
            "subject": "Invoice FIG-1843 from Figma",
            "body": (
                "Your next annual invoice FIG-1843 for INR 1,46,000 is attached. Due 31 Oct 2026."
            ),
            "sent_at": ts,
        }
        db.write(conn, "system", "drive", "file.create", "files", file["id"], None, file, ts=ts)
        db.write(
            conn,
            "system",
            "mail",
            "message.create",
            "mail_messages",
            message["id"],
            None,
            message,
            ts=ts,
        )
        db.write(
            conn,
            "system",
            "mail",
            "attachment.create",
            "mail_attachments",
            message["id"],
            None,
            {"message_id": message["id"], "file_id": file["id"]},
            ts=ts,
        )
        conn.commit()
        register_followup_benchmark(
            world,
            ExpectedTask(
                task_id="T1_followup",
                request="Enter the latest Figma invoice and route it for approval.",
                expected={
                    "bill_count": 1,
                    "vendor_id": vendor["id"],
                    "invoice_no": "FIG-1843",
                    "amount_minor": 14600000,
                    "currency": "INR",
                    "issue_date": "2026-10-02",
                    "due_date": "2026-10-31",
                    "account": "1400",
                    "approver": "E-ana",
                    "status": "pending_approval",
                    "approval_status": "pending",
                    "attachment_file_id": file["id"],
                    "attachment_sha256": digest,
                },
                must_not={"vendor_bank_changed": [vendor["id"]], "other_bills_created": True},
            ),
        )
        print("Created labelled demo source FIG-1843; no bill or memory was created.")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("world", type=Path)
    seed(parser.parse_args().world)

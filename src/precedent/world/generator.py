"""Generate a deterministic company world from a template and a seed.

Output: worlds/<seed>/{world.db, hidden.json, files/, held/, manifest.json}.
Everything is written through db.write(), with historical timestamps and actors,
so audit_log tells the same story as the records.
"""

from __future__ import annotations

import shutil
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from precedent.world import db
from precedent.world.history import History, VendorSpec
from precedent.world.params import Resolver, load_template
from precedent.world.rules import Rules, SplitGroup
from precedent.world.story import Story
from precedent.world.util import initials, iso, sha256, slug


class Manifest(BaseModel):
    template: str
    seed: int
    generated_at: str  # the world clock, so the manifest is deterministic too
    company: dict[str, str] = {}
    counts: dict[str, int]
    db_sha256: str
    files: dict[str, str]  # relative path -> sha256


def generate(template: str, seed: int, out_dir: Path) -> Manifest:
    return Builder(template, seed, out_dir).run()


BANKS = ["HDFC Bank", "ICICI Bank", "Axis Bank", "Kotak Mahindra Bank", "State Bank of India"]
STREETS = [
    "MG Road",
    "Outer Ring Road",
    "Linking Road",
    "Park Street",
    "Anna Salai",
    "Banjara Hills Road",
    "Sector 18",
    "Koramangala 5th Block",
    "Baner Road",
]
CITIES = [
    "Bengaluru 560001",
    "Mumbai 400050",
    "Kolkata 700016",
    "Chennai 600002",
    "Hyderabad 500034",
    "Noida 201301",
    "Pune 411045",
]


class Builder:
    def __init__(self, template: str, seed: int, out: Path):
        self.tpl = load_template(template)
        self.template, self.seed, self.out = template, seed, out
        pools = {**self.tpl["name_pools"], **self.tpl["vendors"]["pools"]}
        self.R = Resolver(seed, self.tpl["canonical_seed"], pools)
        self.rng = self.R.rng
        self.company = self.tpl["company"]
        self.today: date = self.company["today"]
        self.start: date = self.company["history_start"]
        self.domain: str = self.company["domain"]
        self.people: dict[str, str] = {}  # story key -> employee id
        self.names: dict[str, str] = {}  # employee id -> name
        self.emails: dict[str, str] = {}
        self.vendors: dict[str, VendorSpec] = {}
        self.vendor_rows: dict[str, dict[str, Any]] = {}
        self.story_ids: dict[str, str] = {}  # story role -> vendor id
        self.mail: list[dict[str, Any]] = []
        self.file_count = 0

    # ------------------------------------------------------------------ run
    def run(self) -> Manifest:
        if self.out.exists():
            shutil.rmtree(self.out)
        (self.out / "files").mkdir(parents=True)
        (self.out / "held").mkdir()
        self.conn = db.create(self.out / "world.db")
        self.write_people()
        self.write_accounts()
        self.make_vendors()
        self.rules = self.make_rules()
        self.write_vendors()
        self.write_history()
        story = Story(self)
        story.write_all()
        self.flush_mail()
        self.conn.commit()
        from precedent.world.meetings import seed as seed_meetings

        hidden = story.hidden_truth()
        hidden.tasks.extend(seed_meetings(self))
        self.conn.commit()
        (self.out / "hidden.json").write_text(hidden.model_dump_json(indent=2))
        manifest = self.manifest()
        (self.out / "manifest.json").write_text(manifest.model_dump_json(indent=2))
        self.conn.close()
        return manifest

    def w(
        self,
        actor: str,
        app: str,
        action: str,
        entity: str,
        eid: str,
        after: dict[str, Any],
        ts: str,
    ) -> None:
        db.write(self.conn, actor, app, action, entity, eid, None, after, ts=ts)

    # ------------------------------------------------------------------ people
    def write_people(self) -> None:
        specs = self.tpl["people"]
        for key, spec in specs.items():
            self.people[key] = self._add_person(self.R(spec["name"]))
        ex = self.tpl["extras"]
        roles = self.rng.sample(ex["roles"], self.R(ex["count"]))
        extras = [(self._add_person(self.R.take("staff_names")), role) for role in roles]
        ts = iso(datetime.combine(self.start - timedelta(days=30), time(9)))
        cfo = self.people["cfo"]
        for key, spec in specs.items():
            eid = self.people[key]
            mgr = self.people.get(spec.get("manager", ""), None)
            self._write_employee(eid, spec["role"], mgr, cfo, ts)
        for eid, role in extras:
            mgr = self.people[self.rng.choice(["cfo", "eng_manager", "design_lead"])]
            self._write_employee(eid, role, mgr, cfo, ts)
        self.names["ava"] = "Ava"
        self.emails["ava"] = f"ap@{self.domain}"
        self.w(
            cfo,
            "admin",
            "employee.create",
            "employees",
            "ava",
            {
                "id": "ava",
                "name": "Ava",
                "role": "Accounts payable (AI worker)",
                "email": self.emails["ava"],
                "manager_id": cfo,
            },
            ts,
        )

    def _add_person(self, name: str) -> str:
        first, last = name.split()[0], name.split()[-1]
        eid = f"E-{first.lower()}"
        if eid in self.names:
            eid = f"E-{first.lower()}{last[0].lower()}"
        self.names[eid] = name
        self.emails[eid] = f"{first.lower()}.{last.lower()}@{self.domain}"
        return eid

    def _write_employee(self, eid: str, role: str, mgr: str | None, actor: str, ts: str) -> None:
        self.w(
            actor,
            "admin",
            "employee.create",
            "employees",
            eid,
            {
                "id": eid,
                "name": self.names[eid],
                "role": role,
                "email": self.emails[eid],
                "manager_id": mgr,
            },
            ts,
        )

    def first(self, key: str) -> str:
        return self.names[self.people[key]].split()[0]

    # ------------------------------------------------------------------ accounts
    def write_accounts(self) -> None:
        ts = iso(datetime.combine(self.start - timedelta(days=30), time(9)))
        for a in self.tpl["accounts"]:
            self.w(self.people["cfo"], "books", "account.create", "accounts", a["code"], a, ts)

    # ------------------------------------------------------------------ vendors
    def make_vendors(self) -> None:
        vt = self.tpl["vendors"]
        story = vt["story"]
        specs: list[VendorSpec] = []

        def add(name: str, role: str, category: str, cost_center: str, amount: list[int]) -> None:
            prefix = initials(name)  # unique per world, so an invoice number names one vendor
            while prefix in {v.prefix for v in specs}:
                prefix += "X"
            specs.append(VendorSpec("", name, role, category, cost_center, tuple(amount), prefix))

        for role in ("invoice_vendor", "split_vendor"):
            s = story[role]
            add(self.R(s["name"]), role, s["category"], s["cost_center"], [0, 0])
        for role, g in vt["groups"].items():
            if g["count"] == "rest":
                continue
            for _ in range(g["count"]):
                add(self.R.take(g["pool"]), role, g["category"], g["cost_center"], g["amount"])
        noise = vt["groups"]["noise"]
        for _ in range(self.R(vt["total"]) - len(specs) - 2):  # 2: the planted pair
            item = self.R.take(noise["pool"])
            add(item["name"], "noise", item["category"], noise["cost_center"], noise["amount"])
        self._assign_vendor_ids(specs, story)

    def _assign_vendor_ids(self, specs: list[VendorSpec], story: dict[str, Any]) -> None:
        pinned = self.R(story["invoice_vendor"]["id"]) if self.R.canonical else None
        order = specs[:]
        self.rng.shuffle(order)
        n = 100
        for v in order:
            if v.role == "invoice_vendor" and pinned:
                v.id = pinned
                continue
            n += self.rng.randint(1, 3)
            if pinned and f"V-{n}" == pinned:
                n += 1
            v.id = f"V-{n}"
        for v in specs:
            self.vendors[v.id] = v
            if v.role in ("invoice_vendor", "split_vendor"):
                self.story_ids[v.role] = v.id
        dup = story["dup_vendor"]
        if self.R.canonical:
            self.story_ids["dup_vendor"] = self.R(dup["id"])
            self.story_ids["dup_draft"] = self.R(dup["dup_id"])
        else:
            first = n + self.rng.randint(3, 9)
            self.story_ids["dup_vendor"] = f"V-{first}"
            self.story_ids["dup_draft"] = f"V-{first + self.rng.randint(1, 6)}"
        self.dup_name = self.R(dup["name"])

    def vendor_row(self, v: VendorSpec) -> dict[str, Any]:
        legal = v.name + self.rng.choice([" Private Limited", " India Pvt Ltd", " Inc.", " LLP"])
        created = datetime.combine(
            self.start - timedelta(days=self.rng.randint(10, 300)), time(self.rng.randint(9, 17))
        )
        return {
            "id": v.id,
            "name": v.name,
            "legal_name": legal,
            "tax_id": self.gstin(),
            "email": f"billing@{slug(v.name)}.example",
            "phone": self.phone(),
            "address": self.address(),
            "bank_account": self.bank_account(),
            "status": "active",
            "created_by": self.people["cfo"],
            "created_at": iso(created),
        }

    def write_vendors(self) -> None:
        rows = [self.vendor_row(v) for v in self.vendors.values()]
        for row in sorted(rows, key=lambda r: (r["created_at"], r["id"])):
            self.vendor_rows[row["id"]] = row
            self.w(
                row["created_by"],
                "books",
                "vendor.create",
                "vendors",
                row["id"],
                row,
                row["created_at"],
            )

    def gstin(self) -> str:
        letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        pan = "".join(self.rng.choice(letters) for _ in range(5))
        return (
            f"{self.rng.randint(10, 36)}{pan}{self.rng.randint(1000, 9999)}"
            f"{self.rng.choice(letters)}1Z{self.rng.choice(letters + '0123456789')}"
        )

    def phone(self) -> str:
        return (
            f"+91 {self.rng.randint(20, 99)} {self.rng.randint(1000, 9999)} "
            f"{self.rng.randint(1000, 9999)}"
        )

    def address(self) -> str:
        return f"{self.rng.randint(2, 220)}, {self.rng.choice(STREETS)}, {self.rng.choice(CITIES)}"

    def bank_account(self, last4: str | None = None) -> str:
        digits = "".join(str(self.rng.randint(0, 9)) for _ in range(10))
        return f"{self.rng.choice(BANKS)} A/c {digits}{last4 or self.rng.randint(1000, 9999)}"

    # ------------------------------------------------------------------ rules
    def make_rules(self) -> Rules:
        rt = self.tpl["rules"]
        da = rt["design_approval"]
        groups = []
        for g in rt["split_vendor"]["groups"]:
            groups.append(
                SplitGroup(
                    account=g["account"],
                    approver=self.people[g["approver"]],
                    count=self.R(g["count"]),
                    note=g["note"],
                )
            )
        if groups[0].count == groups[1].count:  # a tie is not a "split"
            groups[0].count += 1
        return Rules(
            prepaid_account=rt["prepaid_account"],
            category_account=self.tpl["category_account"],
            default_approver={cc: self.people[k] for cc, k in self.tpl["default_approver"].items()},
            design_threshold_minor=self.R(da["threshold"]) * 100,
            design_effective=self.R(da["effective"]),
            design_old_approver=self.people["design_lead"],
            design_new_approver=self.people[self.R(da["new_approver"])],
            split_vendor_id=self.story_ids["split_vendor"],
            split_groups=groups,
        )

    # ------------------------------------------------------------------ history
    def write_history(self) -> None:
        vt, ht = self.tpl["vendors"], self.tpl["history"]
        h = History(self.rng, self.rules, self.people["ap_clerk"], self.start, self.today)
        by_role: dict[str, list[VendorSpec]] = {}
        for v in self.vendors.values():
            by_role.setdefault(v.role, []).append(v)
        this_month = self.today.replace(day=1)
        last_month = (this_month - timedelta(days=1)).replace(day=1)

        fig = by_role["invoice_vendor"][0]
        inv = vt["story"]["invoice_vendor"]
        h.monthly(fig, inv["monthly_bills"], last_month, self.R(inv["monthly_amount"]))
        self.receipts = self._renumber_receipts(h, fig)
        others = by_role["monthly_software"]
        rest = vt["monthly_software_total"] - inv["monthly_bills"]
        for i, v in enumerate(others):
            count = rest // len(others) + (1 if i < rest % len(others) else 0)
            h.monthly(v, count, this_month, h.amount(v))
        for v in by_role["annual_software"]:
            h.annual(v)
        da = self.tpl["rules"]["design_approval"]
        exc = self.R(da["exception_date"]) if self.R.canonical else None
        h.design(
            by_role["design_assets"],
            self.R(da["post_change_bills"]),
            self.R(ht["pre_change_design_above"]),
            self.R(ht["design_below"]),
            exc,
        )
        h.split(by_role["split_vendor"][0], self.R(vt["story"]["split_vendor"]["amount"]))
        for role in ("cloud", "rent", "utilities"):
            for v in by_role[role]:
                h.monthly(v, 99, this_month, h.amount(v))
        adhoc = by_role["noise"] + by_role["contractor_tools"]
        for _ in range(self.R(ht["bills_total"]) - len(h.bills)):
            h.adhoc(self.rng.choice(adhoc))
        self.history = h
        self._write_bills(h)

    def _renumber_receipts(self, h: History, fig: VendorSpec) -> list[str]:
        """The story vendor's last two monthly bills are the receipts mailed to AP."""
        receipts = self.R(self.tpl["scenarios"]["T1"]["receipts"])
        if not self.R.canonical:
            n = self.rng.randint(1200, 1800)
            receipts = [f"{fig.prefix}-{n}", f"{fig.prefix}-{n + self.rng.randint(60, 120)}"]
        bills = [b for b in h.bills if b.vendor_id == fig.id]
        n = int(receipts[0].split("-")[1])
        for b in reversed(bills[:-2]):
            n -= self.rng.randint(85, 110)
            b.invoice_no = f"{fig.prefix}-{n}"
        bills[-2].invoice_no, bills[-1].invoice_no = receipts
        for b in bills[-2:]:
            b.tags.append("receipt")
        return receipts

    def _write_bills(self, h: History) -> None:
        bills = sorted(h.bills, key=lambda b: (b.created_at, b.invoice_no))
        first = 921 - len(bills)
        self.bill_ids: dict[int, str] = {}
        for i, b in enumerate(bills):
            bid = f"INV-{first + i}"
            self.bill_ids[id(b)] = bid
            if b.due_date < self.today:
                status = "paid"
            elif b.issue_date < self.today - timedelta(days=7):
                status = "approved"
            else:
                status = "pending_approval"
            row = {
                "id": bid,
                "vendor_id": b.vendor_id,
                "invoice_no": b.invoice_no,
                "amount_minor": b.amount_minor,
                "currency": self.company["currency"],
                "issue_date": iso(b.issue_date),
                "due_date": iso(b.due_date),
                "account_code": b.account_code,
                "approver_id": b.approver_id,
                "status": status,
                "attachment_file_id": None,
                "created_by": b.created_by,
                "created_at": iso(b.created_at),
                "notes": b.notes,
            }
            self.w(b.created_by, "books", "bill.create", "bills", bid, row, row["created_at"])
            self._write_approval(bid, b.approver_id, b.created_by, b.created_at, status)

    def _write_approval(
        self, bid: str, approver: str, clerk: str, created: datetime, status: str
    ) -> None:
        aid = f"A-{bid.split('-')[1]}"
        req = created + timedelta(minutes=self.rng.randint(2, 30))
        row = {
            "id": aid,
            "bill_id": bid,
            "approver_id": approver,
            "status": "pending",
            "requested_by": clerk,
            "requested_at": iso(req),
            "decided_at": None,
        }
        self.w(clerk, "books", "approval.request", "approvals", aid, row, iso(req))
        if status == "pending_approval":
            return
        decided = min(
            req + timedelta(hours=self.rng.randint(2, 40)), datetime.combine(self.today, time(8))
        )
        after = {**row, "status": "approved", "decided_at": iso(decided)}
        db.write(
            self.conn,
            approver,
            "books",
            "approval.approve",
            "approvals",
            aid,
            row,
            after,
            ts=iso(decided),
        )

    # ------------------------------------------------------------------ files and mail
    def add_file(self, folder: str, path: Path, by: str | None, at: datetime) -> str:
        self.file_count += 1
        fid = f"f-{self.file_count:04d}"
        mime = "text/csv" if path.suffix == ".csv" else "application/pdf"
        self.w(
            by or "system",
            "drive",
            "file.upload",
            "files",
            fid,
            {
                "id": fid,
                "folder": folder,
                "name": path.name,
                "mime": mime,
                "path": str(path.relative_to(self.out)),
                "uploaded_by": by,
                "uploaded_at": iso(at),
                "sha256": sha256(path),
            },
            iso(at),
        )
        return fid

    def queue_mail(
        self,
        sender: str,
        addr: str,
        subject: str,
        body: str,
        at: datetime,
        to: str | None = None,
        attachments: tuple[str, ...] = (),
        folder: str = "inbox",
    ) -> None:
        self.mail.append(
            {
                "from_name": sender,
                "from_addr": addr,
                "subject": subject,
                "body": body,
                "sent_at": iso(at),
                "to_addr": to or self.emails["ava"],
                "folder": folder,
                "attachments": list(attachments),
            }
        )

    def flush_mail(self) -> None:
        threads: dict[str, str] = {}
        for i, m in enumerate(sorted(self.mail, key=lambda m: (m["sent_at"], m["subject"]))):
            mid = f"m-{i + 1:04d}"
            topic = m["subject"].removeprefix("Re: ")
            threads.setdefault(topic, f"t-{len(threads) + 1:04d}")
            row = {k: v for k, v in m.items() if k != "attachments"}
            row.update(id=mid, thread_id=threads[topic])
            self.w("system", "mail", "mail.receive", "mail_messages", mid, row, m["sent_at"])
            for fid in m["attachments"]:
                self.w(
                    "system",
                    "mail",
                    "mail.attach",
                    "mail_attachments",
                    mid,
                    {"message_id": mid, "file_id": fid},
                    m["sent_at"],
                )

    # ------------------------------------------------------------------ manifest
    def manifest(self) -> Manifest:
        tables = [
            "employees",
            "accounts",
            "vendors",
            "bills",
            "approvals",
            "mail_messages",
            "mail_attachments",
            "files",
            "chat_channels",
            "chat_messages",
            "audit_log",
            "scheduling_settings",
            "calendars",
            "calendar_events",
            "mail_drafts",
        ]
        counts = {t: self.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
        files = {
            str(p.relative_to(self.out)): sha256(p)
            for p in sorted(self.out.rglob("*"))
            if p.is_file() and p.suffix != ".json" and p.name != "world.db"
        }
        return Manifest(
            template=self.template,
            seed=self.seed,
            generated_at=iso(self.today),
            company={k: str(v) for k, v in self.company.items()},
            counts=counts,
            db_sha256=db.dump_sha(self.conn),
            files=files,
        )

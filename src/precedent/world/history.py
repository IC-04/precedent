"""Bill history generated from the true rules. Pure: returns drafts, writes nothing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from random import Random

from precedent.world.rules import Rules, account_for, approver_for


@dataclass
class VendorSpec:
    id: str
    name: str
    role: str  # invoice_vendor, split_vendor, monthly_software, noise, ...
    category: str
    cost_center: str
    amount: tuple[int, int]  # rupees
    prefix: str  # invoice number prefix


@dataclass
class BillDraft:
    vendor_id: str
    invoice_no: str
    amount_minor: int
    issue_date: date
    due_date: date
    account_code: str
    approver_id: str
    created_by: str
    created_at: datetime
    notes: str | None = None
    tags: list[str] = field(default_factory=list)  # for tests and hidden truth only


def months_between(start: date, end: date) -> list[date]:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        out.append(d)
        d = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return out


class History:
    def __init__(self, rng: Random, rules: Rules, clerk: str, start: date, today: date):
        self.rng, self.rules, self.clerk = rng, rules, clerk
        self.start, self.today = start, today
        self.bills: list[BillDraft] = []
        self.numbers: dict[str, int] = {}

    def _invoice_no(self, v: VendorSpec) -> str:
        n = self.numbers.get(v.id, self.rng.randint(100, 900))
        n += self.rng.randint(3, 40)
        self.numbers[v.id] = n
        return f"{v.prefix}-{n:04d}"

    def _created(self, issue: date) -> datetime:
        d = issue + timedelta(days=self.rng.randint(0, 3))
        d = min(d, self.today - timedelta(days=1))
        return datetime.combine(d, time(self.rng.randint(9, 17), self.rng.randint(0, 59)))

    def add(
        self,
        v: VendorSpec,
        issue: date,
        amount_rupees: int,
        periods: int = 1,
        *,
        account: str | None = None,
        approver: str | None = None,
        invoice_no: str | None = None,
        notes: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> BillDraft:
        minor = amount_rupees * 100
        bill = BillDraft(
            vendor_id=v.id,
            invoice_no=invoice_no or self._invoice_no(v),
            amount_minor=minor,
            issue_date=issue,
            due_date=issue + timedelta(days=self.rng.choice([15, 30])),
            account_code=account or account_for(self.rules, v.category, periods),
            approver_id=approver or approver_for(self.rules, v.cost_center, minor, issue),
            created_by=self.clerk,
            created_at=self._created(issue),
            notes=notes,
            tags=list(tags),
        )
        self.bills.append(bill)
        return bill

    def amount(self, v: VendorSpec) -> int:
        lo, hi = v.amount
        return self.rng.randint(lo // 100, hi // 100) * 100

    def random_day(self, lo: date, hi: date) -> date:
        return lo + timedelta(days=self.rng.randint(0, max((hi - lo).days, 0)))

    # ------------------------------------------------------------------ cadences
    def monthly(self, v: VendorSpec, count: int, last_month: date, amount: int) -> None:
        day = self.rng.randint(1, 26)
        months = [m for m in months_between(self.start, last_month)][-count:]
        for m in months:
            self.add(v, m.replace(day=day), amount, tags=("monthly",))

    def annual(self, v: VendorSpec) -> None:
        issue = self.random_day(self.start + timedelta(days=30), self.today - timedelta(days=60))
        self.add(
            v,
            issue,
            self.amount(v),
            periods=12,
            notes="Annual plan, 12 months prepaid",
            tags=("annual",),
        )

    def design(
        self,
        vendors: list[VendorSpec],
        post: int,
        pre_above: int,
        below: int,
        exception_day: date | None,
    ) -> None:
        r = self.rules
        thr = r.design_threshold_minor // 100
        eff = r.design_effective
        after_days = sorted(
            self._distinct_days(eff + timedelta(days=3), self.today - timedelta(days=1), post)
        )
        if exception_day is None:
            exc = self.rng.choice(after_days[1:-1] or after_days)
        else:  # pinned in the canonical world
            exc = exception_day
            if exc not in after_days:
                after_days[len(after_days) // 2] = exc
                after_days.sort()
        for d in after_days:
            v = self.rng.choice(vendors)
            amt = self.rng.randint(thr + 1000, int(thr * 1.9)) // 100 * 100
            if d == exc:
                self.add(
                    v, d, amt, approver=r.design_old_approver, tags=("design_post", "exception")
                )
            else:
                self.add(v, d, amt, tags=("design_post",))
        for _ in range(pre_above):
            d = self.random_day(self.start + timedelta(days=20), eff - timedelta(days=1))
            amt = self.rng.randint(thr + 1000, int(thr * 1.8)) // 100 * 100
            self.add(self.rng.choice(vendors), d, amt, tags=("design_pre",))
        for _ in range(below):
            d = self.random_day(self.start, self.today - timedelta(days=2))
            amt = self.rng.randint(int(thr * 0.25), thr - 500) // 100 * 100
            self.add(self.rng.choice(vendors), d, amt, tags=("design_below",))

    def split(self, v: VendorSpec, amount: int) -> None:
        groups = [(g, i) for i, g in enumerate(self.rules.split_groups) for _ in range(g.count)]
        self.rng.shuffle(groups)
        months = months_between(self.start, self.today - timedelta(days=20))
        picked = sorted(self.rng.sample(months, len(groups)))
        for m, (g, i) in zip(picked, groups, strict=True):
            issue = m.replace(day=self.rng.randint(3, 24))
            self.add(
                v,
                issue,
                amount,
                account=g.account,
                approver=g.approver,
                notes=g.note,
                tags=(f"split_{i}",),
            )

    def adhoc(self, v: VendorSpec) -> None:
        day = self.random_day(self.start, self.today - timedelta(days=2))
        self.add(v, day, self.amount(v), tags=("noise",))

    def _distinct_days(self, lo: date, hi: date, n: int) -> list[date]:
        days = [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]
        return self.rng.sample(days, n)

"""The true operating rules of a generated company.

The generator uses these functions to write history *and* to compute hidden.json,
so the hidden truth agrees with the world by construction.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel


class SplitGroup(BaseModel):
    account: str
    approver: str  # employee id
    count: int
    note: str | None


class Rules(BaseModel):
    prepaid_account: str
    category_account: dict[str, str]
    default_approver: dict[str, str]  # cost centre -> employee id
    design_threshold_minor: int
    design_effective: date
    design_old_approver: str
    design_new_approver: str
    split_vendor_id: str
    split_groups: list[SplitGroup]


def account_for(r: Rules, category: str, periods: int) -> str:
    """Payments covering more than one period are prepaid; otherwise by category."""
    if periods > 1:
        return r.prepaid_account
    return r.category_account[category]


def approver_for(r: Rules, cost_center: str, amount_minor: int, on: date) -> str:
    """Design spend above the threshold moved to a new approver on the effective date."""
    if cost_center == "design" and amount_minor > r.design_threshold_minor:
        return r.design_new_approver if on >= r.design_effective else r.design_old_approver
    return r.default_approver[cost_center]


def as_hidden(r: Rules) -> list[dict[str, Any]]:
    """The rules as written to hidden.json (for the grader and the eval report)."""
    return [
        {
            "id": "prepaid_multi_period",
            "rule": f"Payments covering more than one period are coded to {r.prepaid_account}",
            "governing": "ap_policy#4",
        },
        {
            "id": "single_period_by_category",
            "rule": "Single-period bills are coded by category",
            "map": r.category_account,
        },
        {
            "id": "design_approval",
            "rule": "Design spend above the threshold is approved by the new approver "
            "from the effective date",
            "threshold_minor": r.design_threshold_minor,
            "effective": r.design_effective.isoformat(),
            "old_approver": r.design_old_approver,
            "new_approver": r.design_new_approver,
            "governing": "mail:approvals_reshuffle",
            "stale": "sop#3.2",
        },
        {
            "id": "split_vendor",
            "rule": "History splits between two accounts; no source governs it; ask",
            "vendor_id": r.split_vendor_id,
            "groups": [g.model_dump() for g in r.split_groups],
            "resolution": "the account of the group whose note matches the invoice "
            "(contractor-only licences -> the contractor group)",
        },
        {"id": "default_approver", "map": r.default_approver},
    ]

"""Books: vendors, bills, approvals and a history report."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from precedent.apps.common import (
    ACTOR,
    activity,
    get_conn,
    money,
    paginate,
    parse_amount,
    people,
    redirect,
    render,
    write,
)
from precedent.world import db

router = APIRouter(prefix="/books")
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

BILL_FIELDS = [
    "vendor_id",
    "invoice_no",
    "amount",
    "currency",
    "issue_date",
    "due_date",
    "account_code",
    "attachment_file_id",
    "notes",
]
VENDOR_FIELDS = [
    "name",
    "legal_name",
    "tax_id",
    "email",
    "phone",
    "address",
    "bank_account",
    "status",
]
VENDOR_STATUSES = ["active", "draft", "retired"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _next_id(conn: sqlite3.Connection, table: str, prefix: str) -> str:
    rows = conn.execute(f"SELECT id FROM {table}").fetchall()
    nums = [int(r[0].split("-")[1]) for r in rows if r[0].split("-")[1].isdigit()]
    return f"{prefix}-{max(nums, default=100) + 1}"


def _blank_to_none(values: dict[str, Any]) -> dict[str, Any]:
    return {k: (v if v not in ("", None) else None) for k, v in values.items()}


def _options(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "vendors": conn.execute(
            "SELECT id, name, status FROM vendors WHERE status != 'retired' ORDER BY name"
        ).fetchall(),
        "accounts": conn.execute("SELECT code, name FROM accounts ORDER BY code").fetchall(),
        "files": conn.execute(
            "SELECT id, name, folder FROM files ORDER BY folder, name"
        ).fetchall(),
        "employees": conn.execute(
            "SELECT id, name, role FROM employees WHERE id != ? ORDER BY name", [ACTOR]
        ).fetchall(),
    }


@router.get("/")
def books_home() -> RedirectResponse:
    return RedirectResponse("/books/bills")


# ---------------------------------------------------------------------- bills
def _bill_filters(f: dict[str, str]) -> tuple[str, list[Any]]:
    where, params = ["1 = 1"], []
    if f.get("q"):
        like = f"%{f['q']}%"
        where.append("(b.invoice_no LIKE ? OR b.id LIKE ? OR v.name LIKE ? OR b.notes LIKE ?)")
        params += [like] * 4
    for key, col in (
        ("vendor", "b.vendor_id"),
        ("account", "b.account_code"),
        ("approver", "b.approver_id"),
        ("status", "b.status"),
    ):
        if f.get(key):
            where.append(f"{col} = ?")
            params.append(f[key])
    if f.get("from"):
        where.append("b.issue_date >= ?")
        params.append(f["from"])
    if f.get("to"):
        where.append("b.issue_date <= ?")
        params.append(f["to"])
    if f.get("min_amount"):
        try:
            where.append("b.amount_minor > ?")
            params.append(parse_amount(f["min_amount"]))
        except ValueError:
            where.pop()
    return " AND ".join(where), params


def _filters(request: Request) -> dict[str, str]:
    keys = ["q", "vendor", "account", "approver", "status", "from", "to", "min_amount"]
    return {k: request.query_params.get(k, "").strip() for k in keys}


BILL_SELECT = (
    "SELECT b.*, v.name AS vendor_name FROM bills b JOIN vendors v ON v.id = b.vendor_id"
    " WHERE {where} ORDER BY b.issue_date DESC, b.id DESC"
)


@router.get("/bills")
def bills(request: Request, conn: Conn, page: int = 1):
    f = _filters(request)
    where, params = _bill_filters(f)
    rows, has_next, page = paginate(conn, BILL_SELECT.format(where=where), params, page)
    return render(
        request,
        "books/bills.html",
        rows=rows,
        f=f,
        page=page,
        has_next=has_next,
        names=people(conn),
        **_options(conn),
    )


@router.get("/history")
def history(request: Request, conn: Conn, page: int = 1):
    f = _filters(request)
    where, params = _bill_filters(f)
    rows, has_next, page = paginate(conn, BILL_SELECT.format(where=where), params, page)
    summary = conn.execute(
        "SELECT b.account_code, b.approver_id, count(*) AS n, sum(b.amount_minor) AS total"
        f" FROM bills b JOIN vendors v ON v.id = b.vendor_id WHERE {where}"
        " GROUP BY 1, 2 ORDER BY n DESC",
        params,
    ).fetchall()
    total = sum(s["n"] for s in summary)
    return render(
        request,
        "books/history.html",
        rows=rows,
        f=f,
        page=page,
        has_next=has_next,
        summary=summary,
        total=total,
        names=people(conn),
        **_options(conn),
    )


def _bill_form(
    request: Request,
    conn: sqlite3.Connection,
    values: dict[str, Any],
    error: str | None = None,
    bill: Any = None,
    status: int = 200,
):
    return render(
        request,
        "books/bill_form.html",
        status=status,
        values=values,
        error=error,
        bill=bill,
        **_options(conn),
    )


@router.get("/bills/new")
def bill_new(request: Request, conn: Conn):
    return _bill_form(request, conn, {"currency": "INR"})


def _parse_bill(conn: sqlite3.Connection, values: dict[str, str]) -> dict[str, Any]:
    """Validate a bill form. Raises ValueError with a message for the user."""
    vendor = db.row(conn, "vendors", values.get("vendor_id", ""))
    if vendor is None:
        raise ValueError("Choose a vendor.")
    if vendor["status"] != "active":
        raise ValueError(
            f"Vendor {vendor['id']} is {vendor['status']}; bills need an active vendor."
        )
    if not values.get("invoice_no"):
        raise ValueError("Invoice number is required.")
    for key, name in (("issue_date", "Invoice date"), ("due_date", "Due date")):
        try:
            date.fromisoformat(values.get(key, ""))
        except ValueError:
            raise ValueError(f"{name} must be a date (YYYY-MM-DD).") from None
    if db.row(conn, "accounts", values.get("account_code", "")) is None:
        raise ValueError("Choose an account.")
    fid = values.get("attachment_file_id") or None
    if fid and db.row(conn, "files", fid) is None:
        raise ValueError("The attachment does not exist in Drive.")
    return {
        "vendor_id": vendor["id"],
        "invoice_no": values["invoice_no"],
        "amount_minor": parse_amount(values.get("amount", "")),
        "currency": (values.get("currency") or "INR").upper(),
        "issue_date": values["issue_date"],
        "due_date": values["due_date"],
        "account_code": values["account_code"],
        "attachment_file_id": fid,
        "notes": values.get("notes") or None,
    }


@router.post("/bills/new")
async def bill_create(request: Request, conn: Conn):
    form = await request.form()
    values = {k: str(form.get(k, "")).strip() for k in BILL_FIELDS}
    try:
        fields = _parse_bill(conn, values)
    except ValueError as e:
        return _bill_form(request, conn, values, error=str(e), status=400)
    bid = _next_id(conn, "bills", "INV")
    row = {
        "id": bid,
        **fields,
        "approver_id": None,
        "status": "draft",
        "created_by": ACTOR,
        "created_at": _now(),
    }
    write(conn, "books", "bill.create", "bills", bid, None, row)
    return redirect(f"/books/bills/{bid}", "bill_created")


def _bill_or_404(request: Request, conn: sqlite3.Connection, bid: str):
    bill = db.row(conn, "bills", bid)
    if bill is None:
        return None, render(
            request,
            "books/message.html",
            status=404,
            title="Bill not found",
            text=f"There is no bill {bid}.",
        )
    return bill, None


@router.get("/bills/{bid}")
def bill_view(request: Request, conn: Conn, bid: str):
    bill, missing = _bill_or_404(request, conn, bid)
    if missing:
        return missing
    approvals = conn.execute(
        "SELECT * FROM approvals WHERE bill_id = ? ORDER BY requested_at", [bid]
    ).fetchall()
    events = activity(conn, "bills", bid)
    for a in approvals:
        events += activity(conn, "approvals", a["id"])
    return render(
        request,
        "books/bill.html",
        bill=bill,
        vendor=db.row(conn, "vendors", bill["vendor_id"]),
        file=db.row(conn, "files", bill["attachment_file_id"] or ""),
        account=db.row(conn, "accounts", bill["account_code"] or ""),
        approvals=approvals,
        names=people(conn),
        events=sorted(events, key=lambda e: e["ts"]),
        **_options(conn),
    )


def _bill_values(bill: dict[str, Any]) -> dict[str, Any]:
    return {**bill, "amount": money(bill["amount_minor"])}


@router.get("/bills/{bid}/edit")
def bill_edit_form(request: Request, conn: Conn, bid: str):
    bill, missing = _bill_or_404(request, conn, bid)
    if missing:
        return missing
    if bill["status"] != "draft":
        return render(
            request,
            "books/message.html",
            status=409,
            title="Bill is locked",
            text=f"{bid} is {bill['status']}. Only draft bills can be edited.",
        )
    return _bill_form(request, conn, _bill_values(bill), bill=bill)


@router.post("/bills/{bid}/edit")
async def bill_update(request: Request, conn: Conn, bid: str):
    bill, missing = _bill_or_404(request, conn, bid)
    if missing:
        return missing
    if bill["status"] != "draft":
        return render(
            request,
            "books/message.html",
            status=409,
            title="Bill is locked",
            text=f"{bid} is {bill['status']}. Only draft bills can be edited.",
        )
    form = await request.form()
    values = {k: str(form.get(k, "")).strip() for k in BILL_FIELDS}
    was = {k: str(form.get(f"was__{k}", "")).strip() for k in BILL_FIELDS}
    try:
        after = _parse_bill(conn, values)
        before = _blank_to_none({k: was[k] for k in BILL_FIELDS if k != "amount"})
        before["amount_minor"] = parse_amount(was["amount"]) if was["amount"] else None
    except ValueError as e:
        return _bill_form(request, conn, values, error=str(e), bill=bill, status=400)
    return _save(
        request,
        conn,
        "bills",
        bid,
        before,
        after,
        f"/books/bills/{bid}",
        "bill.update",
        "bill_updated",
    )


def _save(
    request: Request,
    conn: sqlite3.Connection,
    entity: str,
    eid: str,
    before: dict[str, Any],
    after: dict[str, Any],
    url: str,
    action: str,
    done: str,
):
    """Write only what the user changed; refuse if someone else changed it meanwhile."""
    try:
        write(conn, "books", action, entity, eid, before, after)
    except db.StaleWrite:
        conn.rollback()
        current = db.row(conn, entity, eid) or {}
        clash = [
            f"{k}: now {current.get(k)!r}"
            for k, v in after.items()
            if before.get(k) != v and current.get(k) != before.get(k)
        ]
        return render(
            request,
            "books/message.html",
            status=409,
            title="This record changed since you opened it",
            text="Someone else saved a change to the same field. Nothing was "
            "saved. Open the record again and re-apply your change. " + "; ".join(clash),
            link=url,
        )
    return redirect(url, done)


@router.post("/bills/{bid}/request-approval")
async def request_approval(request: Request, conn: Conn, bid: str):
    bill, missing = _bill_or_404(request, conn, bid)
    if missing:
        return missing
    form = await request.form()
    approver = str(form.get("approver_id", "")).strip()
    person = db.row(conn, "employees", approver)
    if bill["status"] != "draft":
        return render(
            request,
            "books/message.html",
            status=409,
            title="Approval not requested",
            text=f"{bid} is {bill['status']}. Approval can be requested for drafts.",
        )
    if person is None or approver == ACTOR:
        return render(
            request,
            "books/message.html",
            status=400,
            title="Approval not requested",
            text="Choose an approver.",
            link=f"/books/bills/{bid}",
        )
    now = _now()
    aid = f"A-{bid.split('-')[1]}"
    approval = {
        "id": aid,
        "bill_id": bid,
        "approver_id": approver,
        "status": "pending",
        "requested_by": ACTOR,
        "requested_at": now,
        "decided_at": None,
    }
    db.write(conn, ACTOR, "books", "approval.request", "approvals", aid, None, approval, ts=now)
    db.write(
        conn,
        ACTOR,
        "books",
        "bill.route",
        "bills",
        bid,
        bill,
        {**bill, "approver_id": approver, "status": "pending_approval"},
        ts=now,
    )
    conn.commit()
    return redirect(f"/books/bills/{bid}", "approval_requested")


# ---------------------------------------------------------------------- vendors
@router.get("/vendors")
def vendors(request: Request, conn: Conn, q: str = "", status: str = "", page: int = 1):
    where, params = ["1 = 1"], []
    if q:
        where.append(
            "(name LIKE ? OR legal_name LIKE ? OR id LIKE ? OR tax_id LIKE ? OR email LIKE ?)"
        )
        params += [f"%{q}%"] * 5
    if status:
        where.append("status = ?")
        params.append(status)
    sql = f"SELECT * FROM vendors WHERE {' AND '.join(where)} ORDER BY name"
    rows, has_next, page = paginate(conn, sql, params, page)
    return render(
        request,
        "books/vendors.html",
        rows=rows,
        q=q,
        status=status,
        page=page,
        has_next=has_next,
        statuses=VENDOR_STATUSES,
    )


def _vendor_form(
    request: Request,
    values: dict[str, Any],
    error: str | None = None,
    vendor: Any = None,
    status: int = 200,
):
    return render(
        request,
        "books/vendor_form.html",
        status=status,
        values=values,
        error=error,
        vendor=vendor,
        statuses=VENDOR_STATUSES,
    )


def _parse_vendor(values: dict[str, str]) -> dict[str, Any]:
    if not values.get("name"):
        raise ValueError("Vendor name is required.")
    if values.get("status") not in VENDOR_STATUSES:
        raise ValueError("Choose a status.")
    return _blank_to_none(values)


@router.get("/vendors/new")
def vendor_new(request: Request):
    return _vendor_form(request, {"status": "active"})


@router.post("/vendors/new")
async def vendor_create(request: Request, conn: Conn):
    form = await request.form()
    values = {k: str(form.get(k, "")).strip() for k in VENDOR_FIELDS}
    try:
        fields = _parse_vendor(values)
    except ValueError as e:
        return _vendor_form(request, values, error=str(e), status=400)
    vid = _next_id(conn, "vendors", "V")
    row = {"id": vid, **fields, "created_by": ACTOR, "created_at": _now()}
    write(conn, "books", "vendor.create", "vendors", vid, None, row)
    return redirect(f"/books/vendors/{vid}", "vendor_created")


def _vendor_or_404(request: Request, conn: sqlite3.Connection, vid: str):
    vendor = db.row(conn, "vendors", vid)
    if vendor is None:
        return None, render(
            request,
            "books/message.html",
            status=404,
            title="Vendor not found",
            text=f"There is no vendor {vid}.",
        )
    return vendor, None


@router.get("/vendors/{vid}")
def vendor_view(request: Request, conn: Conn, vid: str):
    vendor, missing = _vendor_or_404(request, conn, vid)
    if missing:
        return missing
    recent = conn.execute(
        "SELECT * FROM bills WHERE vendor_id = ? ORDER BY issue_date DESC LIMIT 10", [vid]
    ).fetchall()
    count = conn.execute("SELECT count(*) FROM bills WHERE vendor_id = ?", [vid]).fetchone()[0]
    return render(
        request,
        "books/vendor.html",
        vendor=vendor,
        recent=recent,
        count=count,
        names=people(conn),
        events=activity(conn, "vendors", vid),
    )


@router.get("/vendors/{vid}/edit")
def vendor_edit_form(request: Request, conn: Conn, vid: str):
    vendor, missing = _vendor_or_404(request, conn, vid)
    if missing:
        return missing
    return _vendor_form(request, vendor, vendor=vendor)


@router.post("/vendors/{vid}/edit")
async def vendor_update(request: Request, conn: Conn, vid: str):
    vendor, missing = _vendor_or_404(request, conn, vid)
    if missing:
        return missing
    form = await request.form()
    values = {k: str(form.get(k, "")).strip() for k in VENDOR_FIELDS}
    before = _blank_to_none({k: str(form.get(f"was__{k}", "")).strip() for k in VENDOR_FIELDS})
    try:
        after = _parse_vendor(values)
    except ValueError as e:
        return _vendor_form(request, values, error=str(e), vendor=vendor, status=400)
    return _save(
        request,
        conn,
        "vendors",
        vid,
        before,
        after,
        f"/books/vendors/{vid}",
        "vendor.update",
        "vendor_updated",
    )


@router.post("/vendors/{vid}/retire")
def vendor_retire(request: Request, conn: Conn, vid: str):
    vendor, missing = _vendor_or_404(request, conn, vid)
    if missing:
        return missing
    if vendor["status"] != "retired":
        write(
            conn, "books", "vendor.retire", "vendors", vid, vendor, {**vendor, "status": "retired"}
        )
    return redirect(f"/books/vendors/{vid}", "vendor_retired")

import sqlite3

import pytest
from fastapi.testclient import TestClient

from precedent.apps.server import create_app
from precedent.world.generator import generate

TOKEN = "test-token"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEDENT_SCENARIO_TOKEN", TOKEN)
    generate("northwind", 7, tmp_path / "7")
    client = TestClient(create_app(7, tmp_path))
    conn = sqlite3.connect(tmp_path / "7" / "world.db")
    conn.row_factory = sqlite3.Row
    return client, conn


def _file_id(conn, name):
    return conn.execute("select id from files where name = ?", [name]).fetchone()[0]


def _bill_form(conn, **over):
    form = {
        "vendor_id": "V-112", "invoice_no": "FIG-1842", "amount": "1,12,000",
        "currency": "INR", "issue_date": "2026-09-28", "due_date": "2026-10-21",
        "account_code": "1400", "attachment_file_id": _file_id(conn, "FIG-1842.pdf"),
        "notes": "",
    }  # fmt: skip
    return {**form, **over}


def _audit(conn, n=1):
    return conn.execute(
        "select actor, action, entity, entity_id from audit_log order by id desc limit ?", [n]
    ).fetchall()


def test_create_bill_then_request_approval(world):
    client, conn = world
    r = client.post("/books/bills/new", data=_bill_form(conn), follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/books/bills/INV-921?done=bill_created"
    bill = conn.execute("select * from bills where id = 'INV-921'").fetchone()
    assert bill["amount_minor"] == 11200000 and bill["status"] == "draft"
    assert tuple(_audit(conn)[0]) == ("ava", "bill.create", "bills", "INV-921")

    page = client.get(r.headers["location"])
    assert "Bill saved as a draft." in page.text and "FIG-1842.pdf" in page.text

    r = client.post("/books/bills/INV-921/request-approval", data={"approver_id": "E-ana"},
                    follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    bill = conn.execute("select * from bills where id = 'INV-921'").fetchone()
    assert (bill["status"], bill["approver_id"]) == ("pending_approval", "E-ana")
    approval = conn.execute("select * from approvals where bill_id = 'INV-921'").fetchone()
    assert (approval["approver_id"], approval["status"]) == ("E-ana", "pending")
    assert [tuple(a)[1] for a in _audit(conn, 2)] == ["bill.route", "approval.request"]

    page = client.get("/books/bills/INV-921").text
    assert "Ava (AP)" in page and "approval.request" in page  # activity is visible

    again = client.post("/books/bills/INV-921/request-approval", data={"approver_id": "E-ana"})
    assert again.status_code == 409


def test_duplicate_invoice_numbers_are_allowed(world):
    client, conn = world
    for _ in range(2):
        client.post("/books/bills/new", data=_bill_form(conn))
    n = conn.execute("select count(*) from bills where invoice_no = 'FIG-1842'").fetchone()[0]
    assert n == 2  # the worker has to prevent duplicates, not the app


@pytest.mark.parametrize(
    "over, message",
    [
        ({"vendor_id": "V-224"}, "draft"),
        ({"amount": "abc"}, "not a number"),
        ({"due_date": "21/10/2026"}, "Due date"),
        ({"account_code": ""}, "Choose an account"),
    ],
)
def test_invalid_bill_is_not_saved(world, over, message):
    client, conn = world
    r = client.post("/books/bills/new", data=_bill_form(conn, **over))
    assert r.status_code == 400 and message in r.text
    assert conn.execute("select count(*) from bills where id = 'INV-921'").fetchone()[0] == 0


@pytest.mark.parametrize("text", ["1,12,000", "112000", "₹1,12,000.00", "INR 112000"])
def test_amount_formats(world, text):
    client, conn = world
    client.post("/books/bills/new", data=_bill_form(conn, amount=text))
    bill = conn.execute("select amount_minor from bills where id = 'INV-921'").fetchone()
    assert bill[0] == 11200000


def test_vendor_edit_keeps_a_colleagues_change(world):
    client, conn = world
    form = client.get("/books/vendors/V-219/edit").text
    assert 'name="was__phone"' in form
    vendor = dict(conn.execute("select * from vendors where id = 'V-219'").fetchone())
    fields = ["name", "legal_name", "tax_id", "email", "phone", "address", "bank_account",
              "status"]  # fmt: skip
    shown = {k: vendor[k] or "" for k in fields}
    was = {f"was__{k}": v for k, v in shown.items()}

    # A colleague changes the phone after Ava opened the form.
    conn.execute("update vendors set phone = '+91 80 1111 2222' where id = 'V-219'")
    conn.commit()

    # Ava saves the tax ID only: allowed, and the colleague's phone survives.
    r = client.post("/books/vendors/V-219/edit", data={**shown, **was, "tax_id": "29ABCDE1234F1Z5"},
                    follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    row = conn.execute("select phone, tax_id from vendors where id = 'V-219'").fetchone()
    assert tuple(row) == ("+91 80 1111 2222", "29ABCDE1234F1Z5")

    # Ava changes the phone from her stale view: refused, nothing written.
    r = client.post("/books/vendors/V-219/edit", data={**shown, **was, "phone": "+91 99"})
    assert r.status_code == 409 and "changed since you opened it" in r.text
    assert conn.execute("select phone from vendors where id='V-219'").fetchone()[0] == (
        "+91 80 1111 2222"
    )


def test_vendor_create_and_retire(world):
    client, conn = world
    r = client.post("/books/vendors/new", data={"name": "Acme Tools", "status": "active"},
                    follow_redirects=False)  # fmt: skip
    vid = r.headers["location"].split("/")[3].split("?")[0]
    assert conn.execute("select name from vendors where id = ?", [vid]).fetchone()[0] == (
        "Acme Tools"
    )
    client.post("/books/vendors/V-224/retire")
    assert conn.execute("select status from vendors where id='V-224'").fetchone()[0] == "retired"
    assert tuple(_audit(conn)[0])[:2] == ("ava", "vendor.retire")


def test_draft_bill_edit(world):
    client, conn = world
    client.post("/books/bills/new", data=_bill_form(conn, account_code="6120"))
    form = client.get("/books/bills/INV-921/edit").text
    assert 'name="was__account_code" value="6120"' in form
    was = {f"was__{k}": v for k, v in _bill_form(conn, account_code="6120").items()}
    was["was__amount"] = "1,12,000.00"
    r = client.post("/books/bills/INV-921/edit",
                    data={**_bill_form(conn, account_code="1400"), **was},
                    follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    assert conn.execute("select account_code from bills where id='INV-921'").fetchone()[0] == "1400"
    last = conn.execute("select after_json from audit_log order by id desc limit 1").fetchone()[0]
    assert '"account_code": "1400"' in last


def test_history_report_counts(world):
    client, _ = world
    r = client.get("/books/history?account=6400&min_amount=50000&from=2026-07-14")
    assert "Summary: 9 bills" in r.text


def test_mail_search_and_attachment_links(world):
    client, conn = world
    r = client.get("/mail/?q=FIGMA")  # case-insensitive
    assert "Invoice FIG-1842 from Figma" in r.text and "Your receipt from Figma" in r.text
    mid = conn.execute("select id from mail_messages where subject like 'Invoice FIG-1842%'")
    page = client.get(f"/mail/m/{mid.fetchone()[0]}").text
    fid = _file_id(conn, "FIG-1842.pdf")
    assert f'href="/drive/f/{fid}"' in page and "Download FIG-1842.pdf" in page


def test_mail_paginates_at_25(world):
    client, _ = world
    first = client.get("/mail/").text
    assert first.count('<li><a href="/mail/m/') == 25 and "Next page" in first
    assert "Previous page" in client.get("/mail/?page=2").text


def test_drive_viewer_shows_text_and_download_matches(world, tmp_path):
    client, conn = world
    fid = _file_id(conn, "FIG-1842.pdf")
    view = client.get(f"/drive/f/{fid}").text
    assert "Annual, 12 months prepaid" in view and "1,12,000" in view
    data = client.get(f"/drive/f/{fid}/download").content
    assert data == (tmp_path / "7" / "files" / "FIG-1842.pdf").read_bytes()
    assert client.get("/drive/Policies").status_code == 200
    assert "AP-SOP-v3.pdf" in client.get("/drive/Policies").text


def test_drive_never_serves_hidden_or_held_files(world):
    client, _ = world
    for url in ["/drive/f/..%2Fhidden.json", "/drive/held", "/drive/f/held%2FZL-0081.pdf"]:
        assert client.get(url).status_code == 404


def test_chat_post_as_ava(world):
    client, conn = world
    page = client.get("/chat/finance-approvals").text
    assert "Started setting up Zenith Labs" in page and 'name="body"' in page
    r = client.post("/chat/finance-approvals", data={"body": "Could SOP 3.2 be updated?"},
                    follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    assert "Could SOP 3.2 be updated?" in client.get(r.headers["location"]).text
    assert tuple(_audit(conn)[0])[:2] == ("ava", "message.post")
    assert client.post("/chat/finance-approvals", data={"body": " "}).status_code == 400


def _hook(client, path, **kw):
    return client.post(f"/__scenario/{path}", headers={"X-Scenario-Token": TOKEN}, **kw)


def test_scenario_hooks_need_the_token(world):
    client, _ = world
    assert client.post("/__scenario/relabel?field=due_date&label=x").status_code == 403
    bad = {"X-Scenario-Token": "wrong"}
    assert client.post("/__scenario/relabel?field=due_date&label=x", headers=bad).status_code == 403


def test_colleague_edit_is_logged_as_the_colleague(world):
    client, conn = world
    r = _hook(
        client,
        "edit",
        json={
            "entity": "vendors",
            "id": "V-219",
            "fields": {"phone": "+91 80 5555 0000"},
            "actor": "E-raj",
        },
    )
    assert r.status_code == 200
    assert conn.execute("select phone from vendors where id='V-219'").fetchone()[0] == (
        "+91 80 5555 0000"
    )
    assert tuple(_audit(conn)[0])[:2] == ("E-raj", "vendors.update")
    assert "Raj Mehta" in client.get("/books/vendors/V-219").text  # visible in Activity


def test_dropped_response_still_commits_the_bill(world):
    client, conn = world
    assert (
        _hook(client, "drop-next-response", params={"path": "/books/bills/new"}).status_code == 200
    )
    r = client.post("/books/bills/new", data=_bill_form(conn), follow_redirects=False)
    assert r.status_code == 502
    n = conn.execute("select count(*) from bills where invoice_no='FIG-1842'").fetchone()[0]
    assert n == 1  # the write landed; only the acknowledgement was lost
    r = client.post("/books/bills/new", data=_bill_form(conn, invoice_no="X-1"),
                    follow_redirects=False)  # fmt: skip
    assert r.status_code == 303  # armed once only


def test_relabel_changes_the_label_not_the_name(world):
    client, _ = world
    _hook(client, "relabel", params={"field": "due_date", "label": "Payment due"})
    form = client.get("/books/bills/new").text
    assert 'for="f-due_date">Payment due</label>' in form and 'name="due_date"' in form


def test_deliver_held_item(world):
    client, conn = world
    assert client.get("/mail/?q=LIN-0412").text.count("/mail/m/") == 0
    r = _hook(client, "deliver", params={"item": "T3"})
    assert r.status_code == 200
    page = client.get("/mail/?q=LIN-0412").text
    assert "Invoice LIN-0412" in page
    fid = r.json()["file_ids"][0]
    assert "contractor-only" in client.get(f"/drive/f/{fid}").text
    assert _hook(client, "deliver", params={"item": "T3"}).status_code == 409

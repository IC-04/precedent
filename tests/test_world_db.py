import pytest

from precedent.world import db


def test_write_inserts_updates_deletes_and_audits(tmp_path):
    conn = db.create(tmp_path / "w.db")
    v = {"id": "V-1", "name": "Acme", "status": "active", "phone": "1"}
    db.write(conn, "E-x", "books", "vendor.create", "vendors", "V-1", None, v, ts="t1")
    db.write(conn, "E-y", "books", "vendor.update", "vendors", "V-1", v, {**v, "phone": "2"})
    assert db.row(conn, "vendors", "V-1")["phone"] == "2"
    db.write(conn, "ava", "books", "vendor.delete", "vendors", "V-1", v, None)
    assert db.row(conn, "vendors", "V-1") is None

    log = conn.execute("SELECT actor, action, ts FROM audit_log ORDER BY id").fetchall()
    assert [r["actor"] for r in log] == ["E-x", "E-y", "ava"]
    assert log[0]["ts"] == "t1"


def test_dump_sha_tracks_content(tmp_path):
    a, b = db.create(tmp_path / "a.db"), db.create(tmp_path / "b.db")
    for c in (a, b):
        db.write(
            c,
            "E-x",
            "books",
            "acct",
            "accounts",
            "1400",
            None,
            {"code": "1400", "name": "Prepaid", "type": "asset"},
            ts="t",
        )
    assert db.dump_sha(a) == db.dump_sha(b)
    db.write(
        b,
        "E-x",
        "books",
        "acct",
        "accounts",
        "6120",
        None,
        {"code": "6120", "name": "Software", "type": "expense"},
        ts="t",
    )
    assert db.dump_sha(a) != db.dump_sha(b)


def test_write_rejects_unknown_tables_and_columns(tmp_path):
    conn = db.create(tmp_path / "w.db")
    with pytest.raises(ValueError):
        db.write(conn, "ava", "x", "x", "vendors; DROP TABLE bills", "1", None, {"id": "1"})
    with pytest.raises(ValueError):
        db.write(conn, "ava", "x", "x", "vendors", "V-1", None, {"id": "V-1", "evil) --": 1})


def test_update_refuses_to_overwrite_a_colleagues_edit(tmp_path):
    conn = db.create(tmp_path / "w.db")
    v = {"id": "V-1", "name": "Acme", "status": "active", "phone": "1"}
    db.write(conn, "E-x", "books", "vendor.create", "vendors", "V-1", None, v)
    db.write(
        conn, "E-colleague", "books", "vendor.update", "vendors", "V-1", v, {**v, "phone": "2"}
    )
    with pytest.raises(db.StaleWrite):  # ava read phone "1" and saves "3" over the colleague's "2"
        db.write(conn, "ava", "books", "vendor.update", "vendors", "V-1", v, {**v, "phone": "3"})
    # changing a different field from the same stale read is fine
    db.write(conn, "ava", "books", "vendor.update", "vendors", "V-1", v, {**v, "status": "retired"})
    assert db.row(conn, "vendors", "V-1")["phone"] == "2"
    with pytest.raises(db.StaleWrite):
        db.write(conn, "ava", "books", "vendor.update", "vendors", "V-9", v, {**v, "phone": "4"})

import httpx

from precedent.contracts import FailureKind
from precedent.worker.failures import WriteGate
from precedent.worker.gateway import Gateway
from tests.conftest import TOKEN


def _vendor(name):
    return {"name": name, "status": "active"}


def _gateway(base):
    gate, seen = WriteGate(), []
    gw = Gateway(base, gate, on_exchange=seen.append)
    gw.start()
    return gw, gate, seen


def _count(conn, name):
    return conn.execute("select count(*) from vendors where name = ?", [name]).fetchone()[0]


def test_reads_pass_and_writes_need_a_decision(live_apps):
    base, conn = live_apps
    gw, gate, seen = _gateway(base)
    with httpx.Client(base_url=gw.url) as c:
        assert c.get("/books/bills?q=FIG").status_code == 200
        r = c.post("/books/vendors/new", data=_vendor("Gate Test"))
        assert r.status_code == 409 and "safety gate" in r.text
        assert _count(conn, "Gate Test") == 0  # nothing reached the app
        gate.on_decision(["test"])
        r = c.post("/books/vendors/new", data=_vendor("Gate Test"))
        assert r.status_code == 303
        assert r.headers["location"].startswith("/books/vendors/")
        assert _count(conn, "Gate Test") == 1
    assert seen[1].refused and seen[2].status == 303
    gw.stop()


def test_lost_acknowledgement_locks_writes(live_apps):
    base, conn = live_apps
    httpx.post(
        f"{base}/__scenario/drop-next-response",
        params={"path": "/books/vendors/new"},
        headers={"X-Scenario-Token": TOKEN},
    )
    gw, gate, seen = _gateway(base)
    with httpx.Client(base_url=gw.url) as c:
        gate.on_decision(["test"])
        r = c.post("/books/vendors/new", data=_vendor("Maybe Saved"))
        assert r.status_code == 502
        assert seen[-1].kind is FailureKind.uncertain_write
        assert _count(conn, "Maybe Saved") == 1  # it landed; only the answer was lost
        assert c.post("/books/vendors/new", data=_vendor("Maybe Saved")).status_code == 409
        assert _count(conn, "Maybe Saved") == 1  # the blind retry never reached the app
    gw.stop()


def test_gateway_never_forwards_the_scenario_token(live_apps):
    base, _ = live_apps
    gw, _, _ = _gateway(base)
    r = httpx.post(
        f"{gw.url}/__scenario/relabel",
        params={"field": "x", "label": "y"},
        headers={"X-Scenario-Token": TOKEN},
    )
    assert r.status_code == 409  # a POST without a decision; and even with one:
    gw.gate.on_decision(["test"])
    r = httpx.post(
        f"{gw.url}/__scenario/relabel",
        params={"field": "x", "label": "y"},
        headers={"X-Scenario-Token": TOKEN},
    )
    assert r.status_code == 403
    gw.stop()

import os, tempfile
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
import pytest
from fastapi.testclient import TestClient
from app.main import app, db, LATENCY, seed_demo

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean():
    with db() as c:
        c.execute("delete from requests")
    LATENCY.clear()


def new(kind, amount, emp="asha"):
    return client.post("/requests", json={"employee": emp, "kind": kind, "amount": amount})


def test_small_leave_auto_approved():
    r = new("leave", 2)
    assert r.status_code == 201 and r.json()["status"] == "approved" and r.json()["decided_by"] == "auto"


def test_large_expense_pending_then_approved():
    r = new("expense", 5000).json()
    assert r["status"] == "pending"
    d = client.post(f"/requests/{r['id']}/decision", json={"approver": "meera", "action": "approve"})
    assert d.json()["status"] == "approved" and d.json()["decided_by"] == "meera"


def test_reject_flow():
    r = new("expense", 5000).json()
    d = client.post(f"/requests/{r['id']}/decision", json={"approver": "meera", "action": "reject"})
    assert d.json()["status"] == "rejected"


def test_self_approval_blocked():
    r = new("expense", 5000).json()
    d = client.post(f"/requests/{r['id']}/decision", json={"approver": "asha", "action": "approve"})
    assert d.status_code == 403


def test_double_decision_conflict():
    r = new("expense", 5000).json()
    body = {"approver": "meera", "action": "approve"}
    client.post(f"/requests/{r['id']}/decision", json=body)
    assert client.post(f"/requests/{r['id']}/decision", json=body).status_code == 409


def test_leave_balance_deducted_and_enforced():
    assert new("leave", 2).status_code == 201
    assert client.get("/employees/asha/leave-balance").json()["remaining_days"] == 18
    assert new("leave", 19).status_code == 400


def test_approval_rechecks_balance():
    a, b = new("leave", 15).json(), new("leave", 15).json()
    ok = client.post(f"/requests/{a['id']}/decision", json={"approver": "m", "action": "approve"})
    bad = client.post(f"/requests/{b['id']}/decision", json={"approver": "m", "action": "approve"})
    assert ok.status_code == 200 and bad.status_code == 400


def test_validation_and_not_found():
    assert client.post("/requests", json={"employee": "a", "kind": "gift", "amount": 1}).status_code == 422
    assert client.post("/requests/999/decision", json={"approver": "m", "action": "approve"}).status_code == 404


def test_listing_filter_and_summary():
    new("expense", 500)
    new("expense", 5000)
    assert len(client.get("/requests").json()) == 2
    assert len(client.get("/requests?status=pending").json()) == 1
    assert client.get("/summary").json()["approved_expense_total"] == 500


def test_metrics_record_latency():
    client.get("/requests")
    m = client.get("/metrics").json()
    assert m["/requests"]["count"] >= 1 and "p95_ms" in m["/requests"]


def test_index_served():
    assert "PeopleOps Hub" in client.get("/").text


def test_seed_demo_fills_empty_db_once():
    seed_demo()
    seed_demo()
    rows = client.get("/requests").json()
    assert len(rows) == 6 and {r["status"] for r in rows} == {"approved", "pending", "rejected"}

from datetime import datetime, timedelta

import mysql.connector
import pytest

from app import db
from app.app import app as flask_app, check_slot

DOCTOR = {"id": 1, "name": "Dr. Arun Kumar", "specialization": "General Medicine",
          "experience": 8, "available_days": "Mon,Tue,Wed,Thu,Fri,Sat,Sun"}
APPT = {"id": 5, "appointment_date": datetime.now() + timedelta(days=2), "doctor_name": "Dr. Arun Kumar",
        "specialization": "General Medicine", "reason": "Checkup", "status": "Booked"}
MED = {"id": 3, "medicine": "Paracetamol", "dosage": "500 mg", "schedule": "Twice daily", "created_at": datetime.now()}


@pytest.fixture()
def client():
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def csrf(client):
    with client.session_transaction() as s:
        s["csrf_token"] = "tok"
    return "tok"


def login(client):
    csrf(client)
    with client.session_transaction() as s:
        s["uid"], s["user_name"] = 1, "Asha"
    return "tok"


@pytest.fixture()
def db_down(monkeypatch):
    def boom(*a, **k):
        raise mysql.connector.errors.DatabaseError("Can't connect", 2003)
    monkeypatch.setattr(db, "get_connection", boom)
    monkeypatch.setattr(db, "_ready", False)


@pytest.fixture()
def fake_db(monkeypatch):
    calls = []

    def fake_query(sql, args=(), one=False):
        s = " ".join(sql.split())
        if "SELECT id FROM appointments" in s:
            rows = []
        elif "COUNT(*)" in s:
            rows = [{"n": 2}]
        elif "LIMIT 1" in s:
            rows = [APPT]
        elif "FROM doctors WHERE id" in s:
            rows = [DOCTOR]
        elif "FROM doctors" in s:
            rows = [DOCTOR]
        elif "JOIN doctors" in s:
            rows = [APPT]
        elif "FROM medications" in s:
            rows = [MED]
        else:
            rows = []
        return (rows[0] if rows else None) if one else rows

    def fake_execute(sql, args=()):
        calls.append(" ".join(sql.split()))
        return 1, 1

    monkeypatch.setattr(db, "query", fake_query)
    monkeypatch.setattr(db, "execute", fake_execute)
    return calls


# ---------------- infrastructure endpoints ----------------
def test_health_has_no_db_dependency(client, db_down):
    r = client.get("/health")
    assert r.status_code == 200 and r.get_json()["status"] == "healthy"


def test_version(client):
    assert "version" in client.get("/version").get_json()


def test_db_endpoint_reports_outage(client, db_down):
    assert client.get("/db").status_code == 503


def test_stress_disabled_by_default(client):
    assert client.get("/stress").status_code == 404


# ---------------- public + security ----------------
def test_index_and_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200 and b"CareConnect" in r.data
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]


@pytest.mark.parametrize("path", ["/dashboard", "/appointments", "/medications", "/book/1"])
def test_protected_pages_redirect(client, path):
    r = client.get(path)
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_post_without_csrf_rejected(client):
    assert client.post("/login", data={"email": "a@b.com", "password": "x"}).status_code == 400


def test_register_validation_without_db(client):
    t = csrf(client)
    r = client.post("/register", data={"csrf_token": t, "name": "", "email": "bad",
                                       "password": "short", "confirm": "nope"})
    assert r.status_code == 200
    assert b"valid email" in r.data and b"at least 8" in r.data and b"do not match" in r.data


def test_login_during_db_outage_shows_503_page(client, db_down):
    t = csrf(client)
    r = client.post("/login", data={"csrf_token": t, "email": "a@b.com", "password": "x"})
    assert r.status_code == 503 and b"temporarily unavailable" in r.data


# ---------------- business rules ----------------
def test_check_slot_rules():
    now = datetime(2026, 10, 5, 8, 0)  # Monday
    doc = {"name": "Dr X", "available_days": "Mon,Wed"}
    assert check_slot(doc, datetime(2026, 10, 5, 7, 0), now)            # past
    assert check_slot(doc, datetime(2026, 10, 6, 10, 0), now)           # Tuesday not available
    assert check_slot(doc, datetime(2026, 10, 7, 18, 0), now)           # after hours
    assert check_slot(doc, datetime(2026, 10, 7, 10, 15), now)          # not a 30-min slot
    assert check_slot(doc, datetime(2026, 10, 7, 10, 30), now) is None  # Wednesday 10:30 OK
    assert check_slot(doc, now + timedelta(days=120), now)              # too far ahead


# ---------------- logged-in pages render (DB faked) ----------------
def test_pages_render(client, fake_db):
    login(client)
    for path, text in [("/dashboard", b"Welcome, Asha"), ("/doctors", b"Dr. Arun Kumar"),
                       ("/appointments", b"Checkup"), ("/medications", b"Paracetamol"),
                       ("/book/1", b"Book with")]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert text in r.data, path


def test_booking_flow(client, fake_db):
    t = login(client)
    when = (datetime.now() + timedelta(days=1)).replace(hour=10, minute=0).strftime("%Y-%m-%dT%H:%M")
    r = client.post("/book/1", data={"csrf_token": t, "appointment_date": when, "reason": "Fever"})
    assert r.status_code == 302 and "/appointments" in r.headers["Location"]
    assert any(c.startswith("INSERT INTO appointments") for c in fake_db)


def test_booking_rejects_past_slot(client, fake_db):
    t = login(client)
    when = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT10:00")
    r = client.post("/book/1", data={"csrf_token": t, "appointment_date": when, "reason": "Fever"})
    assert r.status_code == 200 and b"future" in r.data
    assert not any(c.startswith("INSERT INTO appointments") for c in fake_db)


def test_cancel_and_medication_actions(client, fake_db):
    t = login(client)
    assert client.post("/cancel/5", data={"csrf_token": t}).status_code == 302
    r = client.post("/medications", data={"csrf_token": t, "medicine": "Aspirin", "dosage": "75mg", "schedule": "Daily"})
    assert r.status_code == 302
    assert client.post("/medications/3/delete", data={"csrf_token": t}).status_code == 302
    assert any("UPDATE appointments SET status='Cancelled'" in c for c in fake_db)
    assert any(c.startswith("INSERT INTO medications") for c in fake_db)
    assert any(c.startswith("DELETE FROM medications") for c in fake_db)


def test_logout_requires_post(client):
    login(client)
    assert client.get("/logout").status_code == 405

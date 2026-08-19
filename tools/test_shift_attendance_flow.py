"""Regression test for Phase 1 shift assignment and attendance linkage.
Run with DATABASE_URL pointing to an isolated SQLite database seeded by seed.py.
"""
import json
import os
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, BASE)

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.entities import Attendance, Courier, Shift, Tenant, User, UserRole
from app.routers.auth import hash_password
from app.routers.shifts import _shift_window

PASSWORD = "ShiftTestPass123"


def headers(client, phone):
    response = client.post("/auth/login", json={"phone": phone, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def prepare_fixture():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.is_dou_internal.is_(False)).first()
        assert tenant, "Expected a seeded company tenant"
        courier = db.query(Courier).filter(Courier.tenant_id == tenant.id).order_by(Courier.id).first()
        assert courier, "Expected a seeded courier"
        company = db.query(User).filter(User.tenant_id == tenant.id, User.role == UserRole.COMPANY).first()
        account = db.query(User).filter(User.courier_id == courier.id, User.role == UserRole.COURIER).first()
        assert company and account, "Expected seeded company and courier accounts"
        company.password_hash = hash_password(PASSWORD)
        account.password_hash = hash_password(PASSWORD)
        company.is_active = True
        account.is_active = True
        db.query(Attendance).filter(Attendance.courier_id == courier.id).delete()
        db.query(Shift).filter(Shift.name.in_(["Assigned Flow Test", "Night Window Test"])).delete()
        db.commit()
        return {"tenant_id": tenant.id, "courier_id": courier.id, "company_phone": company.phone, "courier_phone": account.phone}
    finally:
        db.close()


def main():
    fixture = prepare_fixture()
    client = TestClient(app)
    company_headers = headers(client, fixture["company_phone"])
    courier_headers = headers(client, fixture["courier_phone"])
    now = datetime.utcnow().replace(second=0, microsecond=0)
    start = (now - timedelta(minutes=3)).strftime("%H:%M")
    end = (now + timedelta(minutes=57)).strftime("%H:%M")

    created = client.post("/fleet/shifts", headers=company_headers, json={
        "name": "Assigned Flow Test", "zone": "QA Zone", "start_time": start,
        "end_time": end, "required_couriers": 1, "courier_ids": [fixture["courier_id"]],
    })
    assert created.status_code == 200, created.text
    shift = created.json()
    assert shift["courier_ids"] == [fixture["courier_id"]], shift
    assert shift["duration_hours"] > 0, shift

    rider_shifts = client.get("/shifts/me", headers=courier_headers)
    assert rider_shifts.status_code == 200, rider_shifts.text
    assert any(row["id"] == shift["id"] for row in rider_shifts.json()["shifts"]), rider_shifts.text

    check_in = client.post("/shifts/attendance/check-in", headers=courier_headers, json={"courier_id": fixture["courier_id"]})
    assert check_in.status_code == 200, check_in.text
    assert check_in.json()["shift_id"] == shift["id"], check_in.text
    assert check_in.json()["late_minutes"] >= 0, check_in.text

    attendance = client.get("/fleet/attendance", headers=company_headers)
    assert attendance.status_code == 200, attendance.text
    row = next(item for item in attendance.json() if item["shift_id"] == shift["id"])
    assert row["shift"] == "Assigned Flow Test", row
    assert row["scheduled_start"] and row["scheduled_end"], row

    check_out = client.post("/shifts/attendance/check-out", headers=courier_headers, json={"courier_id": fixture["courier_id"]})
    assert check_out.status_code == 200, check_out.text
    assert check_out.json()["shift_id"] == shift["id"], check_out.text
    assert check_out.json()["early_leave_minutes"] >= 0, check_out.text

    db = SessionLocal()
    try:
        night = Shift(tenant_id=fixture["tenant_id"], name="Night Window Test", zone="QA Zone",
                      start_time="22:00", end_time="06:00", required_couriers=1,
                      courier_ids=json.dumps([fixture["courier_id"]]))
        db.add(night)
        db.commit()
        reference = datetime(2026, 8, 20, 2, 0)
        scheduled_start, scheduled_end, overnight = _shift_window(night, reference)
        assert overnight is True
        assert scheduled_start == datetime(2026, 8, 19, 22, 0), (scheduled_start, scheduled_end)
        assert scheduled_end == datetime(2026, 8, 20, 6, 0), (scheduled_start, scheduled_end)
    finally:
        db.close()

    print("PASS: assigned shift, rider visibility, attendance linkage, and overnight window")


if __name__ == "__main__":
    main()

"""Regression test for supervisor team isolation in the Phase 1 API.
Run with DATABASE_URL pointing to an isolated SQLite database seeded by seed.py.
"""
import os
import sys
import json
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, BASE)

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.entities import (
    Courier,
    DailyLog,
    PerformanceNote,
    Project,
    Shift,
    ShiftStatus,
    Tenant,
    User,
    UserRole,
)
from app.routers.auth import hash_password

PASSWORD = "SupervisorPass123"
PHONE_A = "966599100001"
PHONE_B = "966599100002"


def prepare_fixture():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.is_dou_internal.is_(False)).first()
        assert tenant, "Expected a seeded company tenant"
        couriers = db.query(Courier).filter(Courier.tenant_id == tenant.id).order_by(Courier.id).limit(2).all()
        assert len(couriers) == 2, "Expected at least two seeded riders"
        rider_a, rider_b = couriers

        db.query(PerformanceNote).filter(PerformanceNote.note == "Supervisor A live update").delete()
        for courier in (rider_a, rider_b):
            courier.supervisor_id = None
            courier.zone = "Supervisor A Zone" if courier.id == rider_a.id else "Supervisor B Zone"
            courier.primary_project_id = None
        db.query(DailyLog).filter(DailyLog.notes == "supervisor-scope-sync").delete()
        db.query(Shift).filter(Shift.name.in_(["Supervisor A Shift", "Supervisor B Shift"])).delete()
        for phone in (PHONE_A, PHONE_B):
            old = db.query(User).filter(User.phone == phone).first()
            if old:
                db.delete(old)
        db.flush()

        supervisor_a = User(
            phone=PHONE_A,
            name="Supervisor A",
            password_hash=hash_password(PASSWORD),
            role=UserRole.SUPERVISOR,
            tenant_id=tenant.id,
            is_active=True,
        )
        supervisor_b = User(
            phone=PHONE_B,
            name="Supervisor B",
            password_hash=hash_password(PASSWORD),
            role=UserRole.SUPERVISOR,
            tenant_id=tenant.id,
            is_active=True,
        )
        db.add_all([supervisor_a, supervisor_b])
        db.flush()
        rider_a.supervisor_id = supervisor_a.id
        rider_b.supervisor_id = supervisor_b.id
        db.add_all([
            Shift(tenant_id=tenant.id, name="Supervisor A Shift", zone="Supervisor A Zone", start_time="08:00", end_time="16:00", required_couriers=1, courier_ids=json.dumps([rider_a.id]), status=ShiftStatus.ACTIVE),
            Shift(tenant_id=tenant.id, name="Supervisor B Shift", zone="Supervisor B Zone", start_time="16:00", end_time="23:00", required_couriers=1, courier_ids=json.dumps([rider_b.id]), status=ShiftStatus.ACTIVE),
        ])
        project = db.query(Project).filter(
            Project.tenant_id == tenant.id,
            Project.name == "Supervisor Scope Test Project",
        ).first()
        if not project:
            project = Project(tenant_id=tenant.id, name="Supervisor Scope Test Project", is_active=True)
            db.add(project)
            db.flush()
        rider_a.primary_project_id = project.id
        rider_b.primary_project_id = project.id
        db.add(DailyLog(
            tenant_id=tenant.id,
            courier_id=rider_a.id,
            project_id=project.id,
            log_date=date.today(),
            orders_count=7,
            notes="supervisor-scope-sync",
        ))
        db.commit()
        return {
            "supervisor_a": supervisor_a.id,
            "supervisor_b": supervisor_b.id,
            "rider_a": rider_a.id,
            "rider_b": rider_b.id,
            "daily_log_project": project.id,
        }
    finally:
        db.close()


def auth_headers(client, phone):
    response = client.post("/auth/login", json={"phone": phone, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def ids(rows):
    return {row["id"] for row in rows}


def main():
    fixture = prepare_fixture()
    client = TestClient(app)
    headers = auth_headers(client, PHONE_A)
    rider_a = fixture["rider_a"]
    rider_b = fixture["rider_b"]

    checks = []

    def check(name, response, expected=200):
        assert response.status_code == expected, f"{name}: expected {expected}, got {response.status_code}: {response.text}"
        checks.append(name)
        return response

    team = check("Supervisor A can list only Rider A", client.get("/fleet/couriers", headers=headers)).json()
    assert ids(team) == {rider_a}, team

    profile_a = check("Supervisor A can open Rider A profile", client.get(f"/fleet/couriers/{rider_a}", headers=headers)).json()
    assert profile_a["id"] == rider_a
    check("Supervisor A cannot open Rider B profile", client.get(f"/fleet/couriers/{rider_b}", headers=headers), 404)

    attendance = check("Supervisor A attendance is team-scoped", client.get("/fleet/attendance", headers=headers)).json()
    assert all(row["name"] == profile_a["name"] for row in attendance), attendance

    shifts = check("Supervisor A shifts are team-scoped", client.get("/fleet/shifts", headers=headers)).json()
    assert {row["name"] for row in shifts} == {"Supervisor A Shift"}, shifts

    overview = check("Supervisor A KPI dashboard is team-scoped", client.get("/fleet/overview", headers=headers)).json()
    assert overview["couriers_total"] == 1, overview
    assert overview["orders_today"] == 7, overview

    performance = check("Supervisor A performance is team-scoped", client.get("/fleet/performance", headers=headers)).json()
    assert {row["id"] for row in performance["rows"]} == {rider_a}, performance

    orders = check("Supervisor A orders are team-scoped", client.get("/fleet/orders", headers=headers)).json()
    assert all(row["courier_id"] == rider_a for row in orders), orders

    report = check("Supervisor A report is team-scoped", client.get("/fleet/reports?report_type=documents", headers=headers)).json()
    assert {row["السائق"] for row in report} == {profile_a["name"]}, report

    hr_couriers = check("Supervisor A HR list is team-scoped", client.get("/hr/couriers", headers=headers)).json()
    assert ids(hr_couriers) == {rider_a}, hr_couriers
    check("Supervisor A cannot read Rider B logs", client.get(f"/hr/couriers/{rider_b}/logs", headers=headers), 404)
    check("Supervisor A cannot read Rider B notes", client.get(f"/hr/couriers/{rider_b}/notes", headers=headers), 404)
    check("Supervisor A cannot rate Rider B", client.post(f"/hr/couriers/{rider_b}/rating", headers=headers, json={"score": 4.5}), 403)
    check("Supervisor A cannot modify Rider B", client.patch(f"/hr/couriers/{rider_b}", headers=headers, json={"name": "Blocked"}), 403)
    check("Supervisor A cannot request Rider B", client.post("/hr/assignment-requests", headers=headers, json={"courier_id": rider_b}), 404)

    supervisors = check("Supervisor A can see only own supervisor record", client.get("/hr/supervisors", headers=headers)).json()
    assert ids(supervisors) == {fixture["supervisor_a"]}, supervisors

    check("Supervisor A can rate Rider A", client.post(f"/hr/couriers/{rider_a}/rating", headers=headers, json={"score": 4.5}))
    check("Supervisor A can note Rider A", client.post(f"/hr/couriers/{rider_a}/note", headers=headers, json={"note": "Supervisor A live update"}))
    updated_hr = check("Rating update is visible in Supervisor A team data", client.get("/hr/couriers", headers=headers)).json()
    assert updated_hr[0]["avg_rating"] == 4.5, updated_hr
    updated_notes = check("Note update is visible in Rider A data", client.get(f"/hr/couriers/{rider_a}/notes", headers=headers)).json()
    assert any(row["note"] == "Supervisor A live update" for row in updated_notes), updated_notes

    db = SessionLocal()
    try:
        log = db.query(DailyLog).filter(DailyLog.courier_id == rider_a, DailyLog.notes == "supervisor-scope-sync").one()
        log.orders_count = 11
        db.commit()
    finally:
        db.close()
    refreshed = check("Operational updates refresh in Supervisor A KPI data", client.get("/fleet/overview", headers=headers)).json()
    assert refreshed["orders_today"] == 11, refreshed

    print(f"PASS: {len(checks)} supervisor isolation and synchronization checks")


if __name__ == "__main__":
    main()

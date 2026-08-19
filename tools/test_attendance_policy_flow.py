"""Attendance-policy and payroll-safety integration test.

Run with DATABASE_URL pointing to an isolated SQLite database seeded by seed.py.
"""
import os
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, BASE)

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.entities import Tenant, User, UserRole
from app.routers.auth import hash_password

PASSWORD = "AttendancePolicyPass123"
COMPANY_PHONE = "966581112233"
SUPERVISOR_PHONE = "966599400001"
COURIER_PHONE = "966599400002"


def headers(client, phone, password=PASSWORD):
    response = client.post("/auth/login", json={"phone": phone, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def prepare_company():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.is_dou_internal.is_(False)).first()
        company = db.query(User).filter(User.tenant_id == tenant.id, User.phone == COMPANY_PHONE).first()
        assert tenant and company, "Expected seeded company"
        company.password_hash = hash_password(PASSWORD)
        company.is_active = True
        db.commit()
        return company.phone
    finally:
        db.close()


def shift_payload(name, start, end, rider_id):
    return {"name": name, "zone": "Attendance QA", "start_time": start, "end_time": end,
            "required_couriers": 1, "courier_ids": [rider_id]}


def main():
    company_phone = prepare_company()
    client = TestClient(app)
    company_headers = headers(client, company_phone)

    supervisor = client.post("/hr/supervisors", headers=company_headers, json={
        "name": "Attendance Policy Supervisor", "phone": SUPERVISOR_PHONE, "password": PASSWORD,
    })
    assert supervisor.status_code == 200, supervisor.text
    supervisor_id = supervisor.json()["id"]
    city = client.post("/hr/operating-cities", headers=company_headers, json={"name": "Attendance Policy City"})
    assert city.status_code == 200, city.text
    contract = client.post("/hr/contracts", headers=company_headers, json={
        "name": "Attendance Policy Contract", "client_name": "QA Client", "client_rate_per_order": 10,
        "contract_type": "COMMERCIAL", "status": "ACTIVE",
        "cities": [{"city_id": city.json()["id"], "supervisor_id": supervisor_id}],
    })
    assert contract.status_code == 200, contract.text
    contract_id = contract.json()["id"]
    contract_row = next(row for row in client.get("/hr/contracts", headers=company_headers).json()["rows"] if row["id"] == contract_id)
    branch = contract_row["branches"][0]
    rider = client.post("/fleet/couriers", headers=company_headers, json={
        "name": "Attendance Policy Rider", "phone": COURIER_PHONE, "password": PASSWORD,
        "country": "SA", "courier_type": "COMPANY", "contract_id": contract_id,
        "contract_branch_id": branch["id"], "city_id": city.json()["id"], "supervisor_id": supervisor_id,
        "base_salary": 1200, "per_delivery_rate": 5,
    })
    assert rider.status_code == 200, rider.text
    rider_id = rider.json()["id"]
    rider_headers = headers(client, rider.json()["login_phone"])
    month = datetime.utcnow().strftime("%Y-%m")
    today = datetime.utcnow().date().isoformat()

    now = datetime.utcnow().replace(second=0, microsecond=0)
    late_start = (now - timedelta(minutes=10)).strftime("%H:%M")
    late_end = (now + timedelta(minutes=30)).strftime("%H:%M")
    no_policy_shift = client.post("/fleet/shifts", headers=company_headers, json=shift_payload(
        "No Policy Late Shift", late_start, late_end, rider_id))
    assert no_policy_shift.status_code == 200, no_policy_shift.text
    first_checkin = client.post("/shifts/attendance/check-in", headers=rider_headers, json={"courier_id": rider_id})
    assert first_checkin.status_code == 200 and first_checkin.json()["late_minutes"] > 0, first_checkin.text
    repeated_checkin = client.post("/shifts/attendance/check-in", headers=rider_headers, json={"courier_id": rider_id})
    assert repeated_checkin.status_code == 200 and repeated_checkin.json()["already_checked_in"] is True, repeated_checkin.text
    events = client.get(f"/hr/attendance-events?month={month}", headers=company_headers).json()["rows"]
    no_policy_event = next(row for row in events if row["event_type"] == "LATE")
    assert no_policy_event["status"] == "NO_POLICY" and no_policy_event["payroll_adjustment_id"] is None, no_policy_event
    assert client.post("/shifts/attendance/check-out", headers=rider_headers, json={"courier_id": rider_id}).status_code == 200

    late_policy = client.post("/hr/attendance-policies", headers=company_headers, json={
        "name": "QA Late Fixed", "event_type": "LATE", "calculation_method": "FIXED",
        "amount_rate": 15, "grace_minutes": 0, "effective_from": today, "requires_approval": False,
    })
    assert late_policy.status_code == 200, late_policy.text
    auto_start = (now - timedelta(minutes=20)).strftime("%H:%M")
    auto_end = (now + timedelta(minutes=45)).strftime("%H:%M")
    auto_shift = client.post("/fleet/shifts", headers=company_headers, json=shift_payload(
        "Automatic Late Deduction Shift", auto_start, auto_end, rider_id))
    assert auto_shift.status_code == 200, auto_shift.text
    automatic_checkin = client.post("/shifts/attendance/check-in", headers=rider_headers, json={"courier_id": rider_id})
    assert automatic_checkin.status_code == 200, automatic_checkin.text
    automatic_checkin_repeat = client.post("/shifts/attendance/check-in", headers=rider_headers, json={"courier_id": rider_id})
    assert automatic_checkin_repeat.status_code == 200 and automatic_checkin_repeat.json()["already_checked_in"] is True
    late_events = [row for row in client.get(f"/hr/attendance-events?month={month}", headers=company_headers).json()["rows"] if row["event_type"] == "LATE"]
    applied = next(row for row in late_events if row["status"] == "APPLIED")
    assert applied["deduction_amount"] == 15.0 and applied["payroll_adjustment_id"], applied
    late_adjustments = [row for row in client.get(f"/hr/adjustments?month={month}", headers=company_headers).json() if row["kind"] == "LATE"]
    assert len(late_adjustments) == 1 and late_adjustments[0]["amount"] == 15.0, late_adjustments
    assert client.post("/shifts/attendance/check-out", headers=rider_headers, json={"courier_id": rider_id}).status_code == 200

    early_policy = client.post("/hr/attendance-policies", headers=company_headers, json={
        "name": "QA Early Approval", "event_type": "EARLY_LEAVE", "calculation_method": "FIXED",
        "amount_rate": 20, "effective_from": today, "requires_approval": True,
    })
    assert early_policy.status_code == 200, early_policy.text
    approval_start = (now - timedelta(minutes=5)).strftime("%H:%M")
    approval_end = (now + timedelta(hours=2)).strftime("%H:%M")
    approval_shift = client.post("/fleet/shifts", headers=company_headers, json=shift_payload(
        "Approval Early Leave Shift", approval_start, approval_end, rider_id))
    assert approval_shift.status_code == 200, approval_shift.text
    assert client.post("/shifts/attendance/check-in", headers=rider_headers, json={"courier_id": rider_id}).status_code == 200
    assert client.post("/shifts/attendance/check-out", headers=rider_headers, json={"courier_id": rider_id}).status_code == 200
    pending = next(row for row in client.get(f"/hr/attendance-events?month={month}&status=PENDING_APPROVAL", headers=company_headers).json()["rows"] if row["event_type"] == "EARLY_LEAVE")
    assert pending["payroll_adjustment_id"] is None and pending["deduction_amount"] == 20.0, pending
    approved = client.post(f"/hr/attendance-events/{pending['id']}/decide", headers=company_headers, json={"action": "approve"})
    assert approved.status_code == 200 and approved.json()["status"] == "APPLIED", approved.text

    absence_policy = client.post("/hr/attendance-policies", headers=company_headers, json={
        "name": "QA Absence Fixed", "event_type": "ABSENCE", "calculation_method": "FIXED",
        "amount_rate": 100, "effective_from": today, "requires_approval": False,
    })
    assert absence_policy.status_code == 200, absence_policy.text
    absent_start = (now - timedelta(hours=3)).strftime("%H:%M")
    absent_end = (now - timedelta(hours=2)).strftime("%H:%M")
    absence_shift = client.post("/fleet/shifts", headers=company_headers, json=shift_payload(
        "Absence Reconciliation Shift", absent_start, absent_end, rider_id))
    assert absence_shift.status_code == 200, absence_shift.text
    reconcile = client.post("/hr/attendance-events/reconcile-absences", headers=company_headers, json={"date": today})
    assert reconcile.status_code == 200 and reconcile.json()["created"] >= 1, reconcile.text
    reconcile_repeat = client.post("/hr/attendance-events/reconcile-absences", headers=company_headers, json={"date": today})
    assert reconcile_repeat.status_code == 200 and reconcile_repeat.json()["created"] == 0, reconcile_repeat.text
    absence_events = [row for row in client.get(f"/hr/attendance-events?month={month}", headers=company_headers).json()["rows"] if row["event_type"] == "ABSENCE"]
    assert len(absence_events) == 1 and absence_events[0]["status"] == "APPLIED" and absence_events[0]["deduction_amount"] == 100.0, absence_events
    attention = client.get("/fleet/needs-attention", headers=company_headers)
    assert attention.status_code == 200, attention.text
    attention_codes = {item["code"] for item in attention.json()["items"]}
    assert {"LATE", "ABSENT", "PAYROLL_REVIEW"}.issubset(attention_codes), attention.json()

    payroll = client.get(f"/hr/payroll?month={month}", headers=company_headers)
    assert payroll.status_code == 200
    rider_payroll = next(row for row in payroll.json()["rows"] if row["id"] == rider_id)
    assert rider_payroll["deductions"] >= 135.0, rider_payroll
    finalized = client.post("/hr/payroll/finalize", headers=company_headers, json={"month": month})
    assert finalized.status_code == 200, finalized.text
    blocked_manual = client.post("/hr/adjustments", headers=company_headers, json={
        "courier_id": rider_id, "month": month, "kind": "DEDUCTION", "amount": 5, "note": "Must be blocked",
    })
    assert blocked_manual.status_code == 409, blocked_manual.text
    next_month = (datetime.utcnow().replace(day=28) + timedelta(days=4)).strftime("%Y-%m")
    correction = client.post("/hr/payroll/corrections", headers=company_headers, json={
        "courier_id": rider_id, "original_month": month, "target_month": next_month,
        "kind": "OVERTIME", "amount": 25, "note": "QA correction after close",
    })
    assert correction.status_code == 200 and correction.json()["already_exists"] is False, correction.text
    correction_repeat = client.post("/hr/payroll/corrections", headers=company_headers, json={
        "courier_id": rider_id, "original_month": month, "target_month": next_month,
        "kind": "OVERTIME", "amount": 25, "note": "QA correction after close",
    })
    assert correction_repeat.status_code == 200 and correction_repeat.json()["already_exists"] is True, correction_repeat.text

    print("PASS: attendance policy no-policy safety, automatic and approved deductions, absence reconciliation idempotency, closed-period protection, and future-period correction")


if __name__ == "__main__":
    main()

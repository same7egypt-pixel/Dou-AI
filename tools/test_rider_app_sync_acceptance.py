"""Acceptance matrix for actual rider-app actions and their active company/supervisor consumers."""
import csv
import io
import os
import sys
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, BASE)

from app.database import SessionLocal
from app.main import app
from app.models.entities import Tenant, User
from app.routers.auth import hash_password
from app.services.rider_imports import RIDER_IMPORT_HEADERS

PASSWORD = "RiderSyncPass123"
COMPANY_PHONE = "966581112233"
RIDER_A_PHONE = "966599830001"
RIDER_B_PHONE = "966599830002"


def auth(client, phone, password=PASSWORD):
    response = client.post("/auth/login", json={"phone": phone, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def prepare_company():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.is_dou_internal.is_(False)).first()
        company = db.query(User).filter(User.tenant_id == tenant.id, User.phone == COMPANY_PHONE).first()
        assert tenant and company
        company.password_hash = hash_password(PASSWORD); company.is_active = True; db.commit()
        return company.phone
    finally:
        db.close()


def csv_rows(rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=RIDER_IMPORT_HEADERS, lineterminator="\r\n")
    writer.writeheader(); writer.writerows(rows)
    return "\ufeff" + out.getvalue()


def rider(name, mobile, suffix):
    return {
        "name": name, "mobile": mobile, "initial_password": PASSWORD, "national_id_or_iqama": f"2458300{suffix}",
        "nationality": "Egyptian", "city": "Sync Riyadh", "branch": "Sync Riyadh",
        "contract_or_project": "Sync HungerStation", "supervisor": "Sync Ahmed", "base_salary": "1000",
        "employment_status": "ACTIVE", "rider_rate_per_order": "0", "vehicle_type": "Motorcycle", "vehicle_plate": f"SYNC-{suffix}",
    }


def row_by_phone(client, headers, phone):
    return next(row for row in client.get("/fleet/couriers", headers=headers).json() if row["phone"] == phone)


def main():
    client = TestClient(app)
    company_headers = auth(client, prepare_company())
    supervisor = client.post("/hr/supervisors", headers=company_headers, json={"name": "Sync Ahmed", "phone": "966599830010", "password": PASSWORD})
    city = client.post("/hr/operating-cities", headers=company_headers, json={"name": "Sync Riyadh"})
    assert supervisor.status_code == 200 and city.status_code == 200
    contract = client.post("/hr/contracts", headers=company_headers, json={
        "name": "Sync HungerStation", "client_name": "Sync Client", "client_rate_per_order": 10,
        "contract_type": "COMMERCIAL", "status": "ACTIVE", "cities": [{"city_id": city.json()["id"], "supervisor_id": supervisor.json()["id"]}],
    })
    assert contract.status_code == 200, contract.text
    branch = next(row for row in client.get("/hr/contracts", headers=company_headers).json()["rows"] if row["id"] == contract.json()["id"])["branches"][0]
    import_preview = client.post("/fleet/imports/riders/preview", headers=company_headers, json={"file_name": "sync.csv", "csv_text": csv_rows([rider("Sync Rider A", RIDER_A_PHONE, "01"), rider("Sync Rider B", RIDER_B_PHONE, "02")])})
    assert import_preview.status_code == 200 and import_preview.json()["valid_rows"] == 2, import_preview.text
    assert client.post(f"/fleet/imports/riders/{import_preview.json()['id']}/confirm", headers=company_headers).status_code == 200
    rider_a, rider_b = row_by_phone(client, company_headers, RIDER_A_PHONE), row_by_phone(client, company_headers, RIDER_B_PHONE)
    a_headers, b_headers, supervisor_headers = auth(client, RIDER_A_PHONE), auth(client, RIDER_B_PHONE), auth(client, "966599830010")

    # Profile writes one Courier/User record read by rider, company, and supervisor.
    changed = client.patch("/couriers/me", headers=a_headers, json={"name": "Sync Rider A Updated", "bank_iban": "SA0000000000000000000001"})
    assert changed.status_code == 200, changed.text
    rider_self = client.get("/couriers/me", headers=a_headers).json()
    company_profile = client.get(f"/fleet/couriers/{rider_a['id']}", headers=company_headers).json()
    supervisor_profile = client.get(f"/fleet/couriers/{rider_a['id']}", headers=supervisor_headers).json()
    assert rider_self["name"] == company_profile["name"] == supervisor_profile["name"] == "Sync Rider A Updated"
    assert rider_self["bank_iban"] == company_profile["bank_iban"] == supervisor_profile["bank_iban"] == "SA0000000000000000000001"

    # Rider online/offline writes the same authoritative Courier status.
    assert client.post(f"/couriers/{rider_a['id']}/online", headers=a_headers).status_code == 200
    assert client.get(f"/fleet/couriers/{rider_a['id']}", headers=company_headers).json()["is_online"] is True
    assert client.get(f"/fleet/couriers/{rider_a['id']}", headers=supervisor_headers).json()["is_online"] is True
    assert client.post(f"/couriers/{rider_a['id']}/offline", headers=a_headers).status_code == 200
    assert client.get(f"/fleet/couriers/{rider_a['id']}", headers=company_headers).json()["is_online"] is False

    # Company-assigned shift reaches the rider and the same attendance record reaches company and supervisor.
    now = datetime.utcnow()
    shift = client.post("/shifts", headers=company_headers, json={
        "name": "Sync Shift", "start_time": (now - timedelta(minutes=1)).strftime("%H:%M"),
        "end_time": (now + timedelta(minutes=5)).strftime("%H:%M"), "required_couriers": 1,
        "courier_ids": [rider_a["id"]],
    })
    assert shift.status_code == 200, shift.text
    rider_shifts = client.get("/shifts/me", headers=a_headers).json()
    assert any(row["id"] == shift.json()["id"] for row in rider_shifts["shifts"]), rider_shifts
    check_in = client.post("/shifts/attendance/check-in", headers=a_headers, json={"courier_id": rider_a["id"], "lat": 24.7136, "lng": 46.6753})
    assert check_in.status_code == 200 and check_in.json()["shift_id"] == shift.json()["id"], check_in.text
    retry_check_in = client.post("/shifts/attendance/check-in", headers=a_headers, json={"courier_id": rider_a["id"]})
    assert retry_check_in.status_code == 200 and retry_check_in.json()["already_checked_in"] is True and retry_check_in.json()["attendance_id"] == check_in.json()["attendance_id"], retry_check_in.text
    check_out = client.post("/shifts/attendance/check-out", headers=a_headers, json={"courier_id": rider_a["id"], "lat": 24.7136, "lng": 46.6753})
    assert check_out.status_code == 200 and check_out.json()["attendance_id"] == check_in.json()["attendance_id"], check_out.text
    assert client.post("/shifts/attendance/check-out", headers=a_headers, json={"courier_id": rider_a["id"]}).status_code == 404
    company_attendance = client.get("/fleet/attendance", headers=company_headers).json()
    supervisor_attendance = client.get("/fleet/attendance", headers=supervisor_headers).json()
    company_attendance_row = next(row for row in company_attendance if row["id"] == check_in.json()["attendance_id"])
    supervisor_attendance_row = next(row for row in supervisor_attendance if row["id"] == check_in.json()["attendance_id"])
    assert company_attendance_row["check_out"] and supervisor_attendance_row["check_out"] and company_attendance_row["hours"] == supervisor_attendance_row["hours"]

    # Document upload writes the rider-owned record and appears in both permitted company consumers.
    document = client.post("/hr/me/documents", headers=a_headers, json={"document_type": "IQAMA", "filename": "qa.txt", "mime_type": "text/plain", "file_data": "data:text/plain;base64,cWE="})
    assert document.status_code == 200, document.text
    assert any(row["id"] == document.json()["id"] for row in client.get("/hr/me/documents", headers=a_headers).json())
    assert any(row["id"] == document.json()["id"] for row in client.get("/hr/documents", headers=company_headers).json())
    assert any(row["id"] == document.json()["id"] for row in client.get("/hr/documents", headers=supervisor_headers).json())

    # Leave request and two-stage decision round-trip to the rider app.
    leave = client.post("/hr/me/leave", headers=a_headers, json={"from_date": (now.date() + timedelta(days=1)).isoformat(), "to_date": (now.date() + timedelta(days=2)).isoformat(), "reason": "QA leave"})
    assert leave.status_code == 200, leave.text
    assert any(row["id"] == leave.json()["id"] for row in client.get("/hr/leaves", headers=company_headers).json())
    assert any(row["id"] == leave.json()["id"] for row in client.get("/hr/leaves", headers=supervisor_headers).json())
    assert client.post(f"/hr/leaves/{leave.json()['id']}/decide", headers=supervisor_headers, json={"action": "approve"}).status_code == 200
    assert next(row for row in client.get("/hr/me/leaves", headers=a_headers).json() if row["id"] == leave.json()["id"])["status"] == "SUPERVISOR_APPROVED"
    assert client.post(f"/hr/leaves/{leave.json()['id']}/decide", headers=company_headers, json={"action": "approve"}).status_code == 200
    assert next(row for row in client.get("/hr/me/leaves", headers=a_headers).json() if row["id"] == leave.json()["id"])["status"] == "APPROVED"

    # Ticket links to the authenticated rider and the company reply returns to the rider.
    ticket = client.post("/couriers/me/tickets", headers=a_headers, json={"subject": "QA support", "message": "Need review"})
    assert ticket.status_code == 200, ticket.text
    assert any(row["id"] == ticket.json()["id"] and row["courier"] == "Sync Rider A Updated" for row in client.get("/fleet/tickets", headers=company_headers).json())
    assert any(row["id"] == ticket.json()["id"] for row in client.get("/fleet/tickets", headers=supervisor_headers).json())
    assert client.post(f"/fleet/tickets/{ticket.json()['id']}/reply", headers=company_headers, json={"reply": "QA reply"}).status_code == 200
    ticket_self = next(row for row in client.get("/couriers/me/tickets", headers=a_headers).json() if row["id"] == ticket.json()["id"])
    assert ticket_self["status"] == "REPLIED" and ticket_self["reply"] == "QA reply", ticket_self

    # Rider identity is derived from JWT, not a request-body ID. Suspension is enforced on sensitive routes.
    assert client.post(f"/couriers/{rider_b['id']}/online", headers=a_headers).status_code == 404
    assert client.post("/shifts/attendance/check-in", headers=a_headers, json={"courier_id": rider_b["id"]}).status_code == 404
    assert client.post("/fleet/couriers/bulk", headers=company_headers, json={"action": "SUSPEND", "courier_ids": [rider_a["id"]]}).status_code == 200
    assert client.post(f"/couriers/{rider_a['id']}/online", headers=a_headers).status_code in (401, 403)
    assert client.post("/shifts/attendance/check-in", headers=a_headers, json={"courier_id": rider_a["id"]}).status_code in (401, 403)
    assert client.post("/hr/me/log", headers=a_headers, json={"project_id": branch["project_id"], "orders_count": 1}).status_code in (401, 403)
    assert client.post("/hr/me/documents", headers=a_headers, json={"document_type": "IQAMA", "filename": "blocked.txt", "file_data": "data:text/plain;base64,cWE="}).status_code in (401, 403)
    assert client.post(f"/couriers/{rider_a['id']}/tasks/999999/accept", headers=a_headers).status_code in (401, 403)

    print("PASS: rider profile, availability, shift, attendance retry, document, leave, ticket, dashboard/supervisor synchronization, JWT ID protection, and suspension enforcement")


if __name__ == "__main__":
    main()

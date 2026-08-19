"""Negative authorization checks for supervisor shift and attendance routes."""
import os
import sys
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE); sys.path.insert(0, BASE)

from app.database import SessionLocal
from app.main import app
from app.models.entities import Tenant, User
from app.routers.auth import hash_password

PASSWORD = "SupervisorShiftScope123"
COMPANY_PHONE = "966581112233"


def login(client, phone, password=PASSWORD):
    response = client.post("/auth/login", json={"phone": phone, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def prepare_company():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.is_dou_internal.is_(False)).first()
        company = db.query(User).filter(User.tenant_id == tenant.id, User.phone == COMPANY_PHONE).first()
        company.password_hash = hash_password(PASSWORD); company.is_active = True; db.commit(); return company.phone
    finally:
        db.close()


def main():
    client = TestClient(app); company = login(client, prepare_company())
    a = client.post("/hr/supervisors", headers=company, json={"name": "Shift Scope A", "phone": "966599710001", "password": PASSWORD})
    b = client.post("/hr/supervisors", headers=company, json={"name": "Shift Scope B", "phone": "966599710002", "password": PASSWORD})
    city_a = client.post("/hr/operating-cities", headers=company, json={"name": "Shift Scope City A"})
    city_b = client.post("/hr/operating-cities", headers=company, json={"name": "Shift Scope City B"})
    assert all(x.status_code == 200 for x in (a, b, city_a, city_b))
    contract = client.post("/hr/contracts", headers=company, json={
        "name": "Shift Scope Contract", "client_name": "QA", "client_rate_per_order": 10, "contract_type": "COMMERCIAL", "status": "ACTIVE",
        "cities": [{"city_id": city_a.json()["id"], "supervisor_id": a.json()["id"]}, {"city_id": city_b.json()["id"], "supervisor_id": b.json()["id"]}],
    })
    assert contract.status_code == 200
    row = next(x for x in client.get("/hr/contracts", headers=company).json()["rows"] if x["id"] == contract.json()["id"])
    branch_a, branch_b = row["branches"]
    rider_a = client.post("/fleet/couriers", headers=company, json={"name": "Shift Rider A", "phone": "966599710011", "password": PASSWORD, "country": "SA", "courier_type": "COMPANY", "contract_id": contract.json()["id"], "contract_branch_id": branch_a["id"], "city_id": city_a.json()["id"], "supervisor_id": a.json()["id"]})
    rider_b = client.post("/fleet/couriers", headers=company, json={"name": "Shift Rider B", "phone": "966599710012", "password": PASSWORD, "country": "SA", "courier_type": "COMPANY", "contract_id": contract.json()["id"], "contract_branch_id": branch_b["id"], "city_id": city_b.json()["id"], "supervisor_id": b.json()["id"]})
    assert rider_a.status_code == 200 and rider_b.status_code == 200
    a_headers = login(client, "966599710001")
    now = datetime.utcnow(); start = (now + timedelta(minutes=1)).strftime("%H:%M"); end = (now + timedelta(hours=2)).strftime("%H:%M")
    foreign_create = client.post("/shifts", headers=a_headers, json={"name": "Foreign Shift", "start_time": start, "end_time": end, "required_couriers": 1, "courier_ids": [rider_b.json()["id"]]})
    assert foreign_create.status_code == 400, foreign_create.text
    own_shift = client.post("/shifts", headers=a_headers, json={"name": "Own Shift", "start_time": start, "end_time": end, "required_couriers": 1, "courier_ids": [rider_a.json()["id"]]})
    assert own_shift.status_code == 200, own_shift.text
    foreign_start = client.post(f"/shifts/{own_shift.json()['id']}/start", headers=login(client, "966599710002"))
    assert foreign_start.status_code == 404, foreign_start.text
    foreign_checkin = client.post("/shifts/attendance/check-in", headers=a_headers, json={"courier_id": rider_b.json()["id"]})
    assert foreign_checkin.status_code == 404, foreign_checkin.text
    own_checkin = client.post("/shifts/attendance/check-in", headers=a_headers, json={"courier_id": rider_a.json()["id"]})
    assert own_checkin.status_code == 200, own_checkin.text
    print("PASS: supervisor shift creation, start, and attendance remain isolated to the supervisor team")


if __name__ == "__main__":
    main()

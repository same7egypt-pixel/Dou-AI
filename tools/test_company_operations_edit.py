"""Acceptance test for Phase 1 company edit flows.
Run with DATABASE_URL pointing to an isolated SQLite database seeded by seed.py.
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, BASE)

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.entities import Courier, Tenant, User, UserRole
from app.routers.auth import hash_password

COMPANY_PHONE = "966581112233"
PASSWORD = "dou123456"


def login_headers(client, phone, password=PASSWORD):
    response = client.post("/auth/login", json={"phone": phone, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def main():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.is_dou_internal.is_(False)).first()
        assert tenant, "Expected seeded company tenant"
        company = db.query(User).filter(User.phone == COMPANY_PHONE, User.tenant_id == tenant.id).first()
        courier = db.query(Courier).filter(Courier.tenant_id == tenant.id).order_by(Courier.id).first()
        assert company and courier, "Expected seeded company user and rider"
        courier_id = courier.id
        company.password_hash = hash_password(PASSWORD)
        company.is_active = True
        db.commit()
        company_phone = company.phone
    finally:
        db.close()

    client = TestClient(app)
    company_headers = login_headers(client, company_phone)

    sup_a = client.post("/hr/supervisors", headers=company_headers, json={
        "name": "Operations Supervisor A", "phone": "966599200001", "password": "SupervisorPass123",
    })
    assert sup_a.status_code == 200, sup_a.text
    sup_a_id = sup_a.json()["id"]
    sup_b = client.post("/hr/supervisors", headers=company_headers, json={
        "name": "Operations Supervisor B", "phone": "966599200002", "password": "SupervisorPass123",
    })
    assert sup_b.status_code == 200, sup_b.text
    sup_b_id = sup_b.json()["id"]

    riyadh_city = client.post("/hr/operating-cities", headers=company_headers, json={"name": "Riyadh QA"})
    assert riyadh_city.status_code == 200, riyadh_city.text
    jeddah_city = client.post("/hr/operating-cities", headers=company_headers, json={"name": "Jeddah QA"})
    assert jeddah_city.status_code == 200, jeddah_city.text

    created_contract = client.post("/hr/contracts", headers=company_headers, json={
        "name": "Operations Edit Contract", "client_name": "Operations QA Client",
        "client_rate_per_order": 12.5, "contract_type": "COMMERCIAL", "status": "ACTIVE",
        "start_date": "2026-08-01", "end_date": "2027-01-31",
        "cities": [{"city_id": riyadh_city.json()["id"], "supervisor_id": sup_a_id}],
    })
    assert created_contract.status_code == 200, created_contract.text
    contract_id = created_contract.json()["id"]
    contracts = client.get("/hr/contracts", headers=company_headers).json()["rows"]
    contract = next(row for row in contracts if row["id"] == contract_id)
    branch_id = contract["branches"][0]["id"]

    rider_update = client.patch(f"/hr/couriers/{courier_id}", headers=company_headers, json={
        "name": "Edited Rider", "phone": "966599200003", "nationality": "Egyptian",
        "zone": "North QA", "contract_branch_id": branch_id,
    })
    assert rider_update.status_code == 200, rider_update.text
    profile = client.get(f"/fleet/couriers/{courier_id}", headers=company_headers).json()
    assert profile["name"] == "Edited Rider", profile
    assert profile["contract_id"] == contract_id and profile["contract_branch_id"] == branch_id, profile
    assert profile["supervisor_id"] == sup_a_id and profile["work_city"] == "Riyadh QA", profile
    assert contract["start_date"].startswith("2026-08-01"), contract

    edited_contract = client.patch(f"/hr/contracts/{contract_id}", headers=company_headers, json={
        "name": "Operations Edit Contract", "client_name": "Operations QA Client Updated",
        "client_rate_per_order": 13.0, "contract_type": "COMMERCIAL", "status": "ACTIVE",
        "start_date": "2026-08-15", "end_date": "2027-02-28",
        "branches": [{"id": branch_id, "city_id": jeddah_city.json()["id"], "supervisor_id": sup_b_id}],
    })
    assert edited_contract.status_code == 200, edited_contract.text
    profile_after = client.get(f"/fleet/couriers/{courier_id}", headers=company_headers).json()
    assert profile_after["supervisor_id"] == sup_b_id and profile_after["work_city"] == "Jeddah QA", profile_after
    updated_contract = next(row for row in client.get("/hr/contracts", headers=company_headers).json()["rows"] if row["id"] == contract_id)
    assert updated_contract["start_date"].startswith("2026-08-15"), updated_contract
    assert updated_contract["client_name"] == "Operations QA Client Updated", updated_contract
    assert updated_contract["client_rate_per_order"] == 13.0, updated_contract

    sup_edit = client.patch(f"/hr/supervisors/{sup_b_id}", headers=company_headers, json={
        "name": "Operations Supervisor B Updated", "phone": "966599200004",
        "branch_ids": [branch_id], "courier_ids": [courier_id],
    })
    assert sup_edit.status_code == 200, sup_edit.text
    supervisors = client.get("/hr/supervisors", headers=company_headers).json()
    supervisor_b = next(row for row in supervisors if row["id"] == sup_b_id)
    assert supervisor_b["name"] == "Operations Supervisor B Updated", supervisor_b
    assert courier_id in supervisor_b["courier_ids"] and branch_id in supervisor_b["branch_ids"], supervisor_b

    sup_a_headers = login_headers(client, "966599200001", "SupervisorPass123")
    sup_b_headers = login_headers(client, "966599200004", "SupervisorPass123")
    assert client.get(f"/fleet/couriers/{courier_id}", headers=sup_a_headers).status_code == 404
    assert client.get(f"/fleet/couriers/{courier_id}", headers=sup_b_headers).status_code == 200

    print("PASS: company supervisor, contract, rider edit, reassignment, and authorization refresh")


if __name__ == "__main__":
    main()

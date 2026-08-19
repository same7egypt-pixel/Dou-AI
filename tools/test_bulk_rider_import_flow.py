"""Bulk rider import and bulk operation integration test.

Run with DATABASE_URL pointing to an isolated SQLite database seeded by seed.py.
"""
import csv
import io
import os
import sys

from fastapi.testclient import TestClient

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, BASE)

from app.database import SessionLocal
from app.main import app
from app.models.entities import Tenant, User, UserRole
from app.routers.auth import hash_password

PASSWORD = "BulkImportPass123"
COMPANY_PHONE = "966581112233"


def login_headers(client, phone, password=PASSWORD):
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


def csv_text(rows):
    fields = ["name", "phone", "initial_password", "city", "contract", "branch", "supervisor", "supervisor_phone", "nationality", "base_salary", "per_delivery_rate", "status", "vehicle_type"]
    out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    return out.getvalue()


def main():
    client = TestClient(app)
    company_headers = login_headers(client, prepare_company())
    sup_a = client.post("/hr/supervisors", headers=company_headers, json={"name": "Bulk Riyadh Supervisor", "phone": "966599500001", "password": PASSWORD})
    sup_b = client.post("/hr/supervisors", headers=company_headers, json={"name": "Bulk Jeddah Supervisor", "phone": "966599500002", "password": PASSWORD})
    assert sup_a.status_code == 200 and sup_b.status_code == 200
    city_a = client.post("/hr/operating-cities", headers=company_headers, json={"name": "Bulk Riyadh"})
    city_b = client.post("/hr/operating-cities", headers=company_headers, json={"name": "Bulk Jeddah"})
    assert city_a.status_code == 200 and city_b.status_code == 200
    contract = client.post("/hr/contracts", headers=company_headers, json={
        "name": "Bulk Client Contract", "client_name": "Bulk Client", "client_rate_per_order": 11,
        "contract_type": "COMMERCIAL", "status": "ACTIVE",
        "cities": [{"city_id": city_a.json()["id"], "supervisor_id": sup_a.json()["id"]},
                   {"city_id": city_b.json()["id"], "supervisor_id": sup_b.json()["id"]}],
    })
    assert contract.status_code == 200, contract.text
    contract_row = next(row for row in client.get("/hr/contracts", headers=company_headers).json()["rows"] if row["id"] == contract.json()["id"])
    branches = {row["city"]: row for row in contract_row["branches"]}
    riyadh_branch, jeddah_branch = branches["Bulk Riyadh"], branches["Bulk Jeddah"]

    invalid = csv_text([{
        "name": "Invalid Cross City", "phone": "966599500010", "initial_password": "BulkPass123",
        "city": "Bulk Riyadh", "contract": "Bulk Client Contract", "branch": "Bulk Riyadh",
        "supervisor": "Bulk Jeddah Supervisor", "supervisor_phone": "966599500002", "nationality": "Egyptian",
        "base_salary": "1000", "per_delivery_rate": "5", "status": "ACTIVE", "vehicle_type": "Bike",
    }])
    invalid_preview = client.post("/fleet/imports/riders/preview", headers=company_headers, json={"file_name": "invalid.csv", "csv_text": invalid})
    assert invalid_preview.status_code == 200, invalid_preview.text
    assert invalid_preview.json()["valid_rows"] == 0 and invalid_preview.json()["invalid_rows"] == 1, invalid_preview.json()
    assert client.post(f"/fleet/imports/riders/{invalid_preview.json()['id']}/confirm", headers=company_headers).status_code == 400

    valid = csv_text([
        {"name": "Bulk Rider One", "phone": "966599500011", "initial_password": "BulkPass123", "city": "Bulk Riyadh", "contract": "Bulk Client Contract", "branch": "Bulk Riyadh", "supervisor": "Bulk Riyadh Supervisor", "supervisor_phone": "966599500001", "nationality": "Egyptian", "base_salary": "1000", "per_delivery_rate": "5", "status": "ACTIVE", "vehicle_type": "Bike"},
        {"name": "Bulk Rider Two", "phone": "966599500012", "initial_password": "BulkPass123", "city": "Bulk Riyadh", "contract": "Bulk Client Contract", "branch": "Bulk Riyadh", "supervisor": "Bulk Riyadh Supervisor", "supervisor_phone": "966599500001", "nationality": "Egyptian", "base_salary": "1100", "per_delivery_rate": "5", "status": "ACTIVE", "vehicle_type": "Bike"},
    ])
    preview = client.post("/fleet/imports/riders/preview", headers=company_headers, json={"file_name": "riders.csv", "csv_text": valid})
    assert preview.status_code == 200 and preview.json()["valid_rows"] == 2 and preview.json()["invalid_rows"] == 0, preview.text
    confirmed = client.post(f"/fleet/imports/riders/{preview.json()['id']}/confirm", headers=company_headers)
    assert confirmed.status_code == 200 and confirmed.json()["result"]["imported"] == 2, confirmed.text
    duplicate_file = client.post("/fleet/imports/riders/preview", headers=company_headers, json={"file_name": "riders.csv", "csv_text": valid})
    assert duplicate_file.status_code == 400, duplicate_file.text

    company_rows = client.get("/fleet/couriers", headers=company_headers).json()
    imported = [row for row in company_rows if row["phone"] in {"966599500011", "966599500012"}]
    assert len(imported) == 2 and all(row["contract_branch_id"] == riyadh_branch["id"] for row in imported), imported
    rider_ids = [row["id"] for row in imported]
    move = client.post("/fleet/couriers/bulk", headers=company_headers, json={"action": "ASSIGN_BRANCH", "courier_ids": rider_ids, "contract_branch_id": jeddah_branch["id"]})
    assert move.status_code == 200 and move.json()["updated"] == 2, move.text
    moved = [row for row in client.get("/fleet/couriers", headers=company_headers).json() if row["id"] in rider_ids]
    assert all(row["contract_branch_id"] == jeddah_branch["id"] and row["supervisor_id"] == sup_b.json()["id"] for row in moved), moved
    sup_a_headers = login_headers(client, "966599500001")
    sup_b_headers = login_headers(client, "966599500002")
    assert not any(row["id"] in rider_ids for row in client.get("/fleet/couriers", headers=sup_a_headers).json())
    assert {row["id"] for row in client.get("/fleet/couriers", headers=sup_b_headers).json() if row["id"] in rider_ids} == set(rider_ids)

    suspended = client.post("/fleet/couriers/bulk", headers=company_headers, json={"action": "SUSPEND", "courier_ids": rider_ids})
    assert suspended.status_code == 200 and suspended.json()["updated"] == 2, suspended.text
    assert client.post("/auth/login", json={"phone": "966599500011", "password": "BulkPass123"}).status_code == 403
    exported = client.get("/fleet/couriers/export", headers=company_headers)
    assert exported.status_code == 200 and "Bulk Rider One" in exported.text and "Bulk Jeddah" in exported.text, exported.text

    print("PASS: rider CSV template-compatible preview, cross-city rejection, atomic confirmation, duplicate-file protection, bulk branch reassignment, supervisor scope refresh, suspension, and export")


if __name__ == "__main__":
    main()

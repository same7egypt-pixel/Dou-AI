"""Acceptance test for the professional rider-only CSV import workflow.

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
from app.models.entities import Tenant, User
from app.routers.auth import hash_password
from app.services.rider_imports import RIDER_IMPORT_HEADERS

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
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=RIDER_IMPORT_HEADERS, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return "\ufeff" + out.getvalue()


def rider_row(number, *, name=None, city="Bulk Riyadh", branch="Bulk Riyadh", contract="Bulk Client Contract",
              supervisor="Bulk Riyadh Supervisor", salary="1000", mobile=None, **overrides):
    row = {
        "name": name or f"Bulk Rider {number}", "mobile": mobile or f"96659950{number:04d}",
        "initial_password": "BulkPass123", "national_id_or_iqama": f"245500{number:04d}",
        "nationality": "Egyptian", "city": city, "branch": branch, "contract_or_project": contract,
        "supervisor": supervisor, "base_salary": salary, "employment_status": "ACTIVE",
        "rider_rate_per_order": "5", "vehicle_type": "Motorcycle", "vehicle_plate": f"QA-{number:04d}",
    }
    row.update(overrides)
    return row


def main():
    client = TestClient(app)
    company_headers = login_headers(client, prepare_company())

    # Downloaded CSV: UTF-8 BOM, a header-only first row, and exactly one QA example row.
    template = client.get("/fleet/imports/riders/template", headers=company_headers)
    assert template.status_code == 200, template.text
    assert template.text.startswith("\ufeff")
    template_rows = list(csv.DictReader(io.StringIO(template.text.lstrip("\ufeff"))))
    assert list(template_rows[0].keys()) == RIDER_IMPORT_HEADERS and len(template_rows) == 1, template.text
    assert not any(word in template.text.lower() for word in ("client_rate", "client_revenue", "operational_margin", "supervisor_phone"))
    assert template_rows[0]["rider_rate_per_order"] == "0", template_rows[0]

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

    # Preview must return useful, row-level errors with the supplied input value and create no riders.
    missing_name = rider_row(4); missing_name["name"] = ""
    invalid_rows = [
        rider_row(1, supervisor="Bulk Jeddah Supervisor"),
        rider_row(2, city="Unknown City", branch="Unknown City"),
        rider_row(3, salary="not-a-number"),
        missing_name,
        rider_row(5, mobile="966599500005"),
        rider_row(6, mobile="966599500005"),
    ]
    invalid_preview = client.post("/fleet/imports/riders/preview", headers=company_headers, json={"file_name": "invalid.csv", "csv_text": csv_text(invalid_rows)})
    assert invalid_preview.status_code == 200, invalid_preview.text
    invalid_json = invalid_preview.json()
    assert invalid_json["valid_rows"] == 1 and invalid_json["invalid_rows"] == 5, invalid_json
    assert all({"row", "field", "value", "reason"}.issubset(error) for error in invalid_json["errors"]), invalid_json
    assert any(error["field"] == "supervisor" and error["value"] == "Bulk Jeddah Supervisor" for error in invalid_json["errors"])
    assert any(error["field"] == "city" and error["value"] == "Unknown City" for error in invalid_json["errors"])
    assert any(error["field"] == "base_salary" and error["value"] == "not-a-number" for error in invalid_json["errors"])
    assert any(error["field"] == "name" and error["value"] == "" for error in invalid_json["errors"])
    assert any(error["field"] == "mobile" and error["value"] == "966599500005" for error in invalid_json["errors"])
    assert client.post(f"/fleet/imports/riders/{invalid_json['id']}/confirm", headers=company_headers).status_code == 400

    # Fifteen valid riders, including an Arabic name, are previewed and committed atomically.
    valid_rows = [rider_row(number) for number in range(11, 25)]
    valid_rows.append(rider_row(25, name="محمد اختبار"))
    valid = csv_text(valid_rows)
    preview = client.post("/fleet/imports/riders/preview", headers=company_headers, json={"file_name": "riders.csv", "csv_text": valid})
    assert preview.status_code == 200 and preview.json()["valid_rows"] == 15 and preview.json()["invalid_rows"] == 0, preview.text
    confirmed = client.post(f"/fleet/imports/riders/{preview.json()['id']}/confirm", headers=company_headers)
    assert confirmed.status_code == 200 and confirmed.json()["result"]["imported"] == 15, confirmed.text
    duplicate_file = client.post("/fleet/imports/riders/preview", headers=company_headers, json={"file_name": "riders.csv", "csv_text": valid})
    assert duplicate_file.status_code == 400, duplicate_file.text

    company_rows = client.get("/fleet/couriers", headers=company_headers).json()
    imported = [row for row in company_rows if row["phone"] in {r["mobile"] for r in valid_rows}]
    assert len(imported) == 15 and all(row["contract_branch_id"] == riyadh_branch["id"] for row in imported), imported
    assert any(row["name"] == "محمد اختبار" for row in imported), imported
    rider_ids = [row["id"] for row in imported[:2]]

    # Existing branch reassignment keeps supervisor scope derived from the target branch.
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
    assert client.post("/auth/login", json={"phone": valid_rows[0]["mobile"], "password": "BulkPass123"}).status_code == 403
    exported = client.get("/fleet/couriers/export", headers=company_headers)
    assert exported.status_code == 200 and "Bulk Riyadh" in exported.text and "محمد اختبار" in exported.text, exported.text

    print("PASS: professional rider-only CSV template, UTF-8/BOM and Excel-safe structure, row-value errors, 15-row atomic import, Arabic rider, relationship safety, duplicate-file protection, bulk reassignment, supervisor scope, suspension, and export")


if __name__ == "__main__":
    main()

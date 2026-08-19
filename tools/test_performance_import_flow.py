"""Performance CSV import and financial consistency integration test."""
import csv
import io
import os
import sys
from datetime import date

from fastapi.testclient import TestClient

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, BASE)

from app.database import SessionLocal
from app.main import app
from app.models.entities import Tenant, User
from app.routers.auth import hash_password

PASSWORD = "PerformanceImportPass123"
COMPANY_PHONE = "966581112233"


def headers(client, phone, password=PASSWORD):
    response = client.post("/auth/login", json={"phone": phone, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def prepare_company():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.is_dou_internal.is_(False)).first()
        company = db.query(User).filter(User.tenant_id == tenant.id, User.phone == COMPANY_PHONE).first()
        assert company
        company.password_hash = hash_password(PASSWORD); company.is_active = True; db.commit()
        return company.phone
    finally:
        db.close()


def as_csv(rows):
    out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=["rider_phone", "date", "project", "completed_orders", "notes"])
    writer.writeheader(); writer.writerows(rows); return out.getvalue()


def main():
    client = TestClient(app)
    company_headers = headers(client, prepare_company())
    sup = client.post("/hr/supervisors", headers=company_headers, json={"name": "Performance Import Supervisor", "phone": "966599600001", "password": PASSWORD})
    city = client.post("/hr/operating-cities", headers=company_headers, json={"name": "Performance Import City"})
    assert sup.status_code == 200 and city.status_code == 200
    contract = client.post("/hr/contracts", headers=company_headers, json={
        "name": "Performance Import Contract", "client_name": "QA Platform", "client_rate_per_order": 12,
        "contract_type": "COMMERCIAL", "status": "ACTIVE", "cities": [{"city_id": city.json()["id"], "supervisor_id": sup.json()["id"]}],
    })
    assert contract.status_code == 200, contract.text
    branch = next(row for row in client.get("/hr/contracts", headers=company_headers).json()["rows"] if row["id"] == contract.json()["id"])["branches"][0]
    rider = client.post("/fleet/couriers", headers=company_headers, json={
        "name": "Performance Import Rider", "phone": "966599600002", "password": PASSWORD, "country": "SA", "courier_type": "COMPANY",
        "contract_id": contract.json()["id"], "contract_branch_id": branch["id"], "city_id": city.json()["id"], "supervisor_id": sup.json()["id"],
        "base_salary": 1000, "per_delivery_rate": 5,
    })
    assert rider.status_code == 200, rider.text
    rider_id = rider.json()["id"]
    bonus = client.post("/hr/bonus", headers=company_headers, json={
        "contract_branch_id": branch["id"], "target_orders": 500, "bonus_amount": 1800, "over_target_rate": 5,
        "effective_from": date.today().isoformat(),
    })
    assert bonus.status_code == 200, bonus.text
    project = branch["project"]
    source = as_csv([{"rider_phone": "966599600002", "date": date.today().isoformat(), "project": project, "completed_orders": "550", "notes": "Platform export"}])
    preview = client.post("/fleet/imports/performance/preview", headers=company_headers, json={"file_name": "platform.csv", "csv_text": source})
    assert preview.status_code == 200 and preview.json()["valid_rows"] == 1 and preview.json()["invalid_rows"] == 0, preview.text
    confirm = client.post(f"/fleet/imports/performance/{preview.json()['id']}/confirm", headers=company_headers)
    assert confirm.status_code == 200 and confirm.json()["result"] == {"imported": 1, "updated": 0, "skipped": 0, "failed": 0}, confirm.text
    duplicate = client.post("/fleet/imports/performance/preview", headers=company_headers, json={"file_name": "platform.csv", "csv_text": source})
    assert duplicate.status_code == 400, duplicate.text
    payroll = client.get(f"/hr/payroll?month={date.today().strftime('%Y-%m')}", headers=company_headers)
    rider_row = next(row for row in payroll.json()["rows"] if row["id"] == rider_id)
    assert rider_row["orders"] == 550 and rider_row["bonus"] == 2050.0 and rider_row["delivery"] == 2750.0, rider_row
    financial = client.get(f"/hr/financial/branches?month={date.today().strftime('%Y-%m')}", headers=company_headers)
    financial_row = next(row for row in financial.json()["rows"] if row["contract_branch_id"] == branch["id"])
    assert financial_row["eligible_orders"] == 550 and financial_row["client_revenue"] == 6600.0, financial_row
    rider_headers = headers(client, "966599600002")
    rider_logs = client.get("/hr/me/logs", headers=rider_headers)
    assert rider_logs.status_code == 200 and rider_logs.json()["month_orders"] == 550 and rider_logs.json()["bonus_earned"] == 2050.0, rider_logs.text

    replacement = as_csv([{"rider_phone": "966599600002", "date": date.today().isoformat(), "project": project, "completed_orders": "560", "notes": "Corrected platform export"}])
    replacement_preview = client.post("/fleet/imports/performance/preview", headers=company_headers, json={"file_name": "platform-corrected.csv", "csv_text": replacement})
    assert replacement_preview.status_code == 200 and replacement_preview.json()["warning_rows"] == 1, replacement_preview.text
    replacement_confirm = client.post(f"/fleet/imports/performance/{replacement_preview.json()['id']}/confirm", headers=company_headers)
    assert replacement_confirm.status_code == 200 and replacement_confirm.json()["result"]["updated"] == 1, replacement_confirm.text
    row_after = next(row for row in client.get(f"/hr/payroll?month={date.today().strftime('%Y-%m')}", headers=company_headers).json()["rows"] if row["id"] == rider_id)
    assert row_after["orders"] == 560 and row_after["bonus"] == 2100.0, row_after

    finalized = client.post("/hr/payroll/finalize", headers=company_headers, json={"month": date.today().strftime("%Y-%m")})
    assert finalized.status_code == 200, finalized.text
    closed_logs = client.get("/hr/me/logs", headers=rider_headers)
    assert closed_logs.status_code == 200 and closed_logs.json()["payroll"]["finalized"] is True and closed_logs.json()["payroll"]["source"] == "PAYROLL_SNAPSHOT", closed_logs.text

    invalid_project = as_csv([{"rider_phone": "966599600002", "date": date.today().isoformat(), "project": "Wrong Project", "completed_orders": "1", "notes": ""}])
    invalid = client.post("/fleet/imports/performance/preview", headers=company_headers, json={"file_name": "wrong.csv", "csv_text": invalid_project})
    assert invalid.status_code == 200 and invalid.json()["invalid_rows"] == 1, invalid.text
    print("PASS: performance CSV preview, rider/project validation, file idempotency, exact daily-log update, rider bonus, payroll, and financial consistency")


if __name__ == "__main__":
    main()

"""End-to-end Phase 1 normalization lifecycle test.

Run with DATABASE_URL pointing to an isolated database seeded by seed.py.
The test exercises the live application interfaces rather than inserting business data
straight into the database: operating city -> contract branch -> supervisor -> rider ->
daily eligible orders -> bonus -> adjustment -> payroll preview -> finalization ->
immutable payroll/financial snapshots.
"""
import os
import sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, BASE)

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.entities import Tenant, User, UserRole
from app.routers.auth import hash_password


PASSWORD = "LifecyclePass123"
COMPANY_PHONE = "966581112233"
SUPERVISOR_PHONE = "966599300001"
COURIER_PHONE = "966599300002"


def login_headers(client, phone, password=PASSWORD):
    response = client.post("/auth/login", json={"phone": phone, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def prepare_fixture():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.is_dou_internal.is_(False)).first()
        assert tenant, "Expected a seeded company tenant"
        company = db.query(User).filter(
            User.tenant_id == tenant.id,
            User.phone == COMPANY_PHONE,
        ).first()
        if not company:
            company = db.query(User).filter(
                User.tenant_id == tenant.id,
                User.role == UserRole.COMPANY,
            ).first()
        assert company, "Expected a seeded company account"
        company.password_hash = hash_password(PASSWORD)
        company.is_active = True
        db.commit()
        return {"tenant_id": tenant.id, "company_phone": company.phone}
    finally:
        db.close()


def main():
    fixture = prepare_fixture()
    client = TestClient(app)
    company_headers = login_headers(client, fixture["company_phone"])
    month = date.today().strftime("%Y-%m")
    today = date.today().isoformat()

    supervisor = client.post("/hr/supervisors", headers=company_headers, json={
        "name": "Lifecycle Supervisor", "phone": SUPERVISOR_PHONE, "password": PASSWORD,
    })
    assert supervisor.status_code == 200, supervisor.text
    supervisor_id = supervisor.json()["id"]

    city = client.post("/hr/operating-cities", headers=company_headers, json={
        "name": "Lifecycle City",
    })
    assert city.status_code == 200, city.text
    city_id = city.json()["id"]

    contract = client.post("/hr/contracts", headers=company_headers, json={
        "name": "Lifecycle Commercial Contract",
        "client_name": "Lifecycle Client",
        "client_rate_per_order": 12.0,
        "contract_type": "COMMERCIAL",
        "status": "ACTIVE",
        "start_date": today,
        "cities": [{"city_id": city_id, "supervisor_id": supervisor_id}],
    })
    assert contract.status_code == 200, contract.text
    contract_id = contract.json()["id"]
    contract_row = next(
        row for row in client.get("/hr/contracts", headers=company_headers).json()["rows"]
        if row["id"] == contract_id
    )
    branch = contract_row["branches"][0]
    branch_id = branch["id"]
    project_id = branch["project_id"]

    rider = client.post("/fleet/couriers", headers=company_headers, json={
        "name": "Lifecycle Rider",
        "phone": COURIER_PHONE,
        "password": PASSWORD,
        "country": "SA",
        "courier_type": "COMPANY",
        "contract_id": contract_id,
        "contract_branch_id": branch_id,
        "city_id": city_id,
        "supervisor_id": supervisor_id,
        "base_salary": 1000,
        "per_delivery_rate": 5,
    })
    assert rider.status_code == 200, rider.text
    rider_id = rider.json()["id"]
    rider_headers = login_headers(client, rider.json()["login_phone"])

    daily_log = client.post("/hr/me/log", headers=rider_headers, json={
        "log_date": today,
        "project_id": project_id,
        "orders_count": 120,
        "notes": "Lifecycle eligible orders",
    })
    assert daily_log.status_code == 200, daily_log.text

    bonus = client.post("/hr/bonus", headers=company_headers, json={
        "contract_branch_id": branch_id,
        "target_orders": 100,
        "bonus_amount": 50,
        "over_target_rate": 2,
        "effective_from": today,
    })
    assert bonus.status_code == 200, bonus.text

    overtime = client.post("/hr/adjustments", headers=company_headers, json={
        "courier_id": rider_id, "month": month, "kind": "OVERTIME", "amount": 20,
        "note": "Lifecycle approved overtime",
    })
    assert overtime.status_code == 200, overtime.text
    advance = client.post("/hr/adjustments", headers=company_headers, json={
        "courier_id": rider_id, "month": month, "kind": "ADVANCE", "amount": 10,
        "note": "Lifecycle approved advance",
    })
    assert advance.status_code == 200, advance.text

    preview = client.get(f"/hr/payroll?month={month}", headers=company_headers)
    assert preview.status_code == 200, preview.text
    preview_row = next(row for row in preview.json()["rows"] if row["id"] == rider_id)
    assert preview.json()["finalized"] is False, preview.json()
    assert preview_row["orders"] == 120, preview_row
    assert preview_row["fixed"] == 1000.0, preview_row
    assert preview_row["delivery"] == 600.0, preview_row
    assert preview_row["bonus"] == 90.0, preview_row
    assert preview_row["additions"] == 20.0 and preview_row["deductions"] == 10.0, preview_row
    assert preview_row["total"] == 1700.0, preview_row

    financial_preview = client.get(f"/hr/financial/branches?month={month}", headers=company_headers)
    assert financial_preview.status_code == 200, financial_preview.text
    financial_row = next(row for row in financial_preview.json()["rows"] if row["contract_branch_id"] == branch_id)
    assert financial_preview.json()["finalized"] is False, financial_preview.json()
    assert financial_row["eligible_orders"] == 120, financial_row
    assert financial_row["client_revenue"] == 1440.0, financial_row
    assert financial_row["direct_rider_cost"] == 1700.0, financial_row
    assert financial_row["operational_margin"] == -260.0, financial_row

    finalized = client.post("/hr/payroll/finalize", headers=company_headers, json={"month": month})
    assert finalized.status_code == 200, finalized.text

    finalized_payroll = client.get(f"/hr/payroll?month={month}", headers=company_headers)
    assert finalized_payroll.status_code == 200, finalized_payroll.text
    finalized_row = next(row for row in finalized_payroll.json()["rows"] if row["id"] == rider_id)
    assert finalized_payroll.json()["finalized"] is True, finalized_payroll.json()
    assert finalized_row["total"] == 1700.0, finalized_row

    finalized_financial = client.get(f"/hr/financial/branches?month={month}", headers=company_headers)
    assert finalized_financial.status_code == 200, finalized_financial.text
    finalized_financial_row = next(
        row for row in finalized_financial.json()["rows"] if row["contract_branch_id"] == branch_id
    )
    assert finalized_financial.json()["finalized"] is True, finalized_financial.json()
    assert finalized_financial_row["client_revenue"] == 1440.0, finalized_financial_row
    assert finalized_financial_row["operational_margin"] == -260.0, finalized_financial_row

    post_finalization_adjustment = client.post("/hr/adjustments", headers=company_headers, json={
        "courier_id": rider_id, "month": month, "kind": "OVERTIME", "amount": 999,
        "note": "Must not alter finalized snapshots",
    })
    assert post_finalization_adjustment.status_code == 409, post_finalization_adjustment.text
    next_month = f"{int(month[:4]) + (1 if month[5:] == '12' else 0):04d}-{(int(month[5:]) % 12) + 1:02d}"
    correction = client.post("/hr/payroll/corrections", headers=company_headers, json={
        "courier_id": rider_id, "original_month": month, "target_month": next_month,
        "kind": "OVERTIME", "amount": 999, "note": "Correct after close in the next open period",
    })
    assert correction.status_code == 200, correction.text
    immutable_payroll = client.get(f"/hr/payroll?month={month}", headers=company_headers).json()
    immutable_row = next(row for row in immutable_payroll["rows"] if row["id"] == rider_id)
    assert immutable_row["total"] == 1700.0, immutable_row
    immutable_financial_row = next(
        row for row in client.get(f"/hr/financial/branches?month={month}", headers=company_headers).json()["rows"]
        if row["contract_branch_id"] == branch_id
    )
    assert immutable_financial_row["operational_margin"] == -260.0, immutable_financial_row

    print("PASS: operating city, commercial contract, rider compensation, eligible orders, bonus, adjustments, payroll finalization, and immutable financial snapshots")


if __name__ == "__main__":
    main()

"""Phase 1 analytics/reporting acceptance against actual sources and RBAC."""
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
from app.services.rider_imports import RIDER_IMPORT_HEADERS

PASSWORD = "AnalyticsPass123"
COMPANY_PHONE = "966581112233"
RIDER_A_PHONE = "966599840001"
RIDER_B_PHONE = "966599840002"
RIDER_C_PHONE = "966599840003"


def auth(client, phone, password=PASSWORD):
    result = client.post("/auth/login", json={"phone": phone, "password": password})
    assert result.status_code == 200, result.text
    return {"Authorization": "Bearer " + result.json()["access_token"]}


def company_phone():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.is_dou_internal.is_(False)).first()
        company = db.query(User).filter(User.tenant_id == tenant.id, User.phone == COMPANY_PHONE).first()
        assert tenant and company
        company.password_hash = hash_password(PASSWORD); company.is_active = True; db.commit()
        return company.phone
    finally:
        db.close()


def csv_text(rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=RIDER_IMPORT_HEADERS, lineterminator="\r\n")
    writer.writeheader(); writer.writerows(rows)
    return "\ufeff" + out.getvalue()


def rider(name, mobile, city, contract, branch, supervisor, number):
    return {"name": name, "mobile": mobile, "initial_password": PASSWORD,
            "national_id_or_iqama": f"245840{number:04d}", "nationality": "Egyptian", "city": city,
            "branch": branch, "contract_or_project": contract, "supervisor": supervisor,
            "base_salary": "1000", "employment_status": "ACTIVE", "rider_rate_per_order": "0",
            "vehicle_type": "Motorcycle", "vehicle_plate": f"AN-{number}"}


def report(client, headers, kind, query=""):
    result = client.get(f"/fleet/analytics/{kind}?{query}", headers=headers)
    assert result.status_code == 200, result.text
    return result.json()


def find_row(rows, rider_name):
    found = [row for row in rows if row["rider"] == rider_name]
    assert len(found) == 1, rows
    return found[0]


def main():
    client = TestClient(app)
    company_headers = auth(client, company_phone())
    sup_a = client.post("/hr/supervisors", headers=company_headers, json={"name": "Analytics Ahmed", "phone": "966599840010", "password": PASSWORD})
    sup_b = client.post("/hr/supervisors", headers=company_headers, json={"name": "Analytics Sara", "phone": "966599840011", "password": PASSWORD})
    city_a = client.post("/hr/operating-cities", headers=company_headers, json={"name": "Analytics Riyadh"})
    city_b = client.post("/hr/operating-cities", headers=company_headers, json={"name": "Analytics Jeddah"})
    assert all(item.status_code == 200 for item in (sup_a, sup_b, city_a, city_b))
    contract_a = client.post("/hr/contracts", headers=company_headers, json={
        "name": "Analytics HungerStation", "client_name": "Analytics Client A", "client_rate_per_order": 10,
        "contract_type": "COMMERCIAL", "status": "ACTIVE",
        "cities": [{"city_id": city_a.json()["id"], "supervisor_id": sup_a.json()["id"]}],
    })
    contract_b = client.post("/hr/contracts", headers=company_headers, json={
        "name": "Analytics Jahez", "client_name": "Analytics Client B", "client_rate_per_order": 8,
        "contract_type": "COMMERCIAL", "status": "ACTIVE",
        "cities": [{"city_id": city_b.json()["id"], "supervisor_id": sup_b.json()["id"]}],
    })
    assert contract_a.status_code == 200 and contract_b.status_code == 200
    contracts = client.get("/hr/contracts", headers=company_headers).json()["rows"]
    branch_a = next(row for row in contracts if row["id"] == contract_a.json()["id"])["branches"][0]
    branch_b = next(row for row in contracts if row["id"] == contract_b.json()["id"])["branches"][0]

    preview = client.post("/fleet/imports/riders/preview", headers=company_headers, json={"file_name": "analytics.csv", "csv_text": csv_text([
        rider("Analytics Mohamed", RIDER_A_PHONE, "Analytics Riyadh", "Analytics HungerStation", "Analytics Riyadh", "Analytics Ahmed", 1),
        rider("Analytics Omar", RIDER_B_PHONE, "Analytics Riyadh", "Analytics HungerStation", "Analytics Riyadh", "Analytics Ahmed", 2),
        rider("Analytics Lina", RIDER_C_PHONE, "Analytics Jeddah", "Analytics Jahez", "Analytics Jeddah", "Analytics Sara", 3),
    ])})
    assert preview.status_code == 200 and preview.json()["valid_rows"] == 3, preview.text
    assert client.post(f"/fleet/imports/riders/{preview.json()['id']}/confirm", headers=company_headers).status_code == 200
    couriers = client.get("/fleet/couriers", headers=company_headers).json()
    mohamed = next(row for row in couriers if row["phone"] == RIDER_A_PHONE)
    rider_headers = auth(client, RIDER_A_PHONE)
    sup_a_headers = auth(client, "966599840010")

    first = date.today().replace(day=1)
    second = date.today().replace(day=2)
    third = date.today().replace(day=3)
    fourth = date.today().replace(day=4)
    bonus = client.post("/hr/bonus", headers=company_headers, json={"contract_branch_id": branch_a["id"], "target_orders": 500, "bonus_amount": 1800, "over_target_rate": 5, "effective_from": first.isoformat()})
    assert bonus.status_code == 200, bonus.text
    def log(day, orders):
        response = client.post("/hr/me/log", headers=rider_headers, json={"log_date": day.isoformat(), "project_id": branch_a["project_id"], "orders_count": orders, "notes": "analytics QA"})
        assert response.status_code == 200, response.text
    log(first, 25); log(second, 30)
    period_55 = f"date_from={first.isoformat()}&date_to={second.isoformat()}"

    # The same 55 must appear in Executive, Operations, Workforce, existing payroll consumer, and rider app.
    executive_55 = report(client, company_headers, "executive", period_55)
    operations_55 = report(client, company_headers, "operations", period_55)
    workforce_55 = report(client, company_headers, "workforce", period_55)
    assert executive_55["kpis"]["eligible_orders"] == 55, executive_55
    assert find_row(operations_55["rows"], "Analytics Mohamed")["eligible_orders"] == 55
    assert find_row(workforce_55["rows"], "Analytics Mohamed")["eligible_orders"] == 55
    assert client.get("/hr/me/logs", headers=rider_headers).json()["month_orders"] == 55
    assert next(row for row in client.get(f"/hr/payroll?month={first.strftime('%Y-%m')}", headers=company_headers).json()["rows"] if row["id"] == mohamed["id"])["orders"] == 55

    # Cascading filters only expose relationships valid for selected city/branch/supervisor.
    filters_city_a = client.get(f"/fleet/analytics/filters?city_id={city_a.json()['id']}", headers=company_headers)
    assert filters_city_a.status_code == 200
    data_city_a = filters_city_a.json()
    assert {row["id"] for row in data_city_a["branches"]} == {branch_a["id"]}
    assert {row["id"] for row in data_city_a["supervisors"]} == {sup_a.json()["id"]}
    assert {row["id"] for row in data_city_a["riders"]} == {mohamed["id"], next(row for row in couriers if row["phone"] == RIDER_B_PHONE)["id"]}
    scoped = report(client, company_headers, "operations", period_55 + f"&city_id={city_a.json()['id']}&contract_id={contract_a.json()['id']}&branch_id={branch_a['id']}&supervisor_id={sup_a.json()['id']}&rider_id={mohamed['id']}")
    assert scoped["pagination"]["total"] == 1 and scoped["kpis"]["eligible_orders"] == 55, scoped

    # Page boundaries remain server-side and stable.
    paged = report(client, company_headers, "operations", period_55 + "&page=2&page_size=1")
    assert paged["pagination"]["total"] >= 3 and paged["pagination"]["page"] == 2 and len(paged["rows"]) == 1, paged

    # Monthly target: 500 -> 1,800 and 550 -> 2,050 everywhere financial data is permitted.
    log(third, 445)
    at_target = report(client, company_headers, "financial", f"date_from={first.isoformat()}&date_to={third.isoformat()}&rider_id={mohamed['id']}")
    target_row = find_row(at_target["rows"], "Analytics Mohamed")
    assert target_row["mtd_orders"] == 500 and target_row["bonus"] == 1800 and target_row["client_revenue"] == 5000 and target_row["operational_margin"] == 2200, target_row
    log(fourth, 50)
    final_query = f"date_from={first.isoformat()}&date_to={fourth.isoformat()}&rider_id={mohamed['id']}"
    executive_550 = report(client, company_headers, "executive", final_query)
    financial_550 = report(client, company_headers, "financial", final_query)
    workforce_550 = report(client, company_headers, "workforce", final_query)
    final_financial = find_row(financial_550["rows"], "Analytics Mohamed")
    assert executive_550["kpis"]["eligible_orders"] == 550
    assert find_row(workforce_550["rows"], "Analytics Mohamed")["mtd_orders"] == 550
    assert final_financial["bonus"] == 2050 and final_financial["client_revenue"] == 5500 and final_financial["operational_margin"] == 2450, final_financial

    # Supervisor remains safely scoped even when manually supplying another city/branch/project/rider/supervisor ID.
    supervisor_ok = report(client, sup_a_headers, "operations", period_55)
    assert {row["rider"] for row in supervisor_ok["rows"]} == {"Analytics Mohamed", "Analytics Omar"}
    tampered = client.get(f"/fleet/analytics/operations?{period_55}&city_id={city_b.json()['id']}&branch_id={branch_b['id']}&supervisor_id={sup_b.json()['id']}", headers=sup_a_headers)
    assert tampered.status_code == 200 and tampered.json()["pagination"]["total"] == 0, tampered.text
    assert client.get("/fleet/analytics/financial?" + period_55, headers=sup_a_headers).status_code == 403
    assert client.get("/fleet/analytics/executive?" + period_55, headers=sup_a_headers).status_code == 403
    assert client.get("/fleet/analytics/financial/export?" + period_55, headers=sup_a_headers).status_code == 403
    export = client.get("/fleet/analytics/financial/export?" + final_query, headers=company_headers)
    assert export.status_code == 200 and "client_revenue" in export.text and "operational_margin" in export.text, export.text

    # Closed month uses final snapshots rather than a new calculation path.
    month = first.strftime("%Y-%m")
    assert client.post("/hr/payroll/finalize", headers=company_headers, json={"month": month}).status_code == 200
    closed = report(client, company_headers, "financial", final_query)
    assert closed["financial_finalized"] is True and closed["financial_status"] == "CLOSED_FINAL"
    assert find_row(closed["rows"], "Analytics Mohamed")["bonus"] == 2050
    print("PASS: executive/operations/financial/workforce analytics, cascades, pagination, 55/500/550 reconciliation, financial RBAC, CSV security, and final snapshots")


if __name__ == "__main__":
    main()

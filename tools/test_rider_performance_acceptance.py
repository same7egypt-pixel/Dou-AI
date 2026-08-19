"""Strict DailyLog -> performance -> bonus -> payroll -> report acceptance.

The rider is created through the cleaned CSV flow, then uses only rider-facing APIs.
Run with DATABASE_URL pointing at a fresh SQLite database seeded by seed.py.
"""
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

PASSWORD = "RiderAcceptance123"
COMPANY_PHONE = "966581112233"
RIDER_PHONE = "966599820001"


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


def rider_csv(row):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=RIDER_IMPORT_HEADERS, lineterminator="\r\n")
    writer.writeheader(); writer.writerow(row)
    return "\ufeff" + out.getvalue()


def performance_csv(rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=["rider_phone", "date", "project", "completed_orders", "notes"], lineterminator="\r\n")
    writer.writeheader(); writer.writerows(rows)
    return out.getvalue()


def only_row(rows, name):
    found = [row for row in rows if row.get("المندوب") == name or row.get("السائق") == name]
    assert len(found) == 1, rows
    return found[0]


def main():
    client = TestClient(app)
    company_headers = auth(client, prepare_company())
    supervisor = client.post("/hr/supervisors", headers=company_headers, json={"name": "Ahmed Acceptance", "phone": "966599820010", "password": PASSWORD})
    city = client.post("/hr/operating-cities", headers=company_headers, json={"name": "Riyadh Acceptance"})
    assert supervisor.status_code == 200 and city.status_code == 200
    contract = client.post("/hr/contracts", headers=company_headers, json={
        "name": "HungerStation Riyadh", "client_name": "QA Client", "client_rate_per_order": 10,
        "contract_type": "COMMERCIAL", "status": "ACTIVE",
        "cities": [{"city_id": city.json()["id"], "supervisor_id": supervisor.json()["id"]}],
    })
    assert contract.status_code == 200, contract.text
    contract_row = next(row for row in client.get("/hr/contracts", headers=company_headers).json()["rows"] if row["id"] == contract.json()["id"])
    branch = contract_row["branches"][0]
    project = branch["project"]

    imported_csv = rider_csv({
        "name": "Mohamed Acceptance", "mobile": RIDER_PHONE, "initial_password": PASSWORD,
        "national_id_or_iqama": "2458200001", "nationality": "Egyptian", "city": "Riyadh Acceptance",
        "branch": "Riyadh Acceptance", "contract_or_project": "HungerStation Riyadh", "supervisor": "Ahmed Acceptance",
        "base_salary": "1000", "employment_status": "ACTIVE", "rider_rate_per_order": "0",
        "vehicle_type": "Motorcycle", "vehicle_plate": "QA-8200",
    })
    preview = client.post("/fleet/imports/riders/preview", headers=company_headers, json={"file_name": "mohamed.csv", "csv_text": imported_csv})
    assert preview.status_code == 200 and preview.json()["valid_rows"] == 1 and preview.json()["invalid_rows"] == 0, preview.text
    confirmed = client.post(f"/fleet/imports/riders/{preview.json()['id']}/confirm", headers=company_headers)
    assert confirmed.status_code == 200 and confirmed.json()["result"]["imported"] == 1, confirmed.text
    rider = next(row for row in client.get("/fleet/couriers", headers=company_headers).json() if row["phone"] == RIDER_PHONE)
    rider_id = rider["id"]
    assert rider["city_id"] == city.json()["id"] and rider["contract_branch_id"] == branch["id"] and rider["supervisor_id"] == supervisor.json()["id"], rider
    rider_headers = auth(client, RIDER_PHONE)
    supervisor_headers = auth(client, "966599820010")

    bonus = client.post("/hr/bonus", headers=company_headers, json={
        "contract_branch_id": branch["id"], "target_orders": 500, "bonus_amount": 1800,
        "over_target_rate": 5, "effective_from": date.today().replace(day=1).isoformat(),
    })
    assert bonus.status_code == 200, bonus.text

    day1 = date.today().replace(day=1)
    day2 = date.today().replace(day=2)
    day3 = date.today().replace(day=3)
    day4 = date.today().replace(day=4)
    def log(day, orders, notes="QA manual"):
        response = client.post("/hr/me/log", headers=rider_headers, json={"log_date": day.isoformat(), "project_id": branch["project_id"], "orders_count": orders, "notes": notes})
        assert response.status_code == 200, response.text
        return response

    # Day 1: exact daily persistence and every live consumer has 25, without a frontend formula.
    log(day1, 25)
    logs = client.get("/hr/me/logs", headers=rider_headers)
    assert logs.status_code == 200 and logs.json()["month_orders"] == 25 and logs.json()["bonus_earned"] == 0, logs.text
    assert logs.json()["bonus_details"][0]["orders"] == 25 and logs.json()["bonus_details"][0]["target"] == 500
    company_profile = client.get(f"/fleet/couriers/{rider_id}", headers=company_headers)
    supervisor_profile = client.get(f"/fleet/couriers/{rider_id}", headers=supervisor_headers)
    assert company_profile.status_code == 200 and supervisor_profile.status_code == 200
    assert company_profile.json()["month_orders"] == supervisor_profile.json()["month_orders"] == 25

    # Day 2 must create a separate DailyLog and yield 25 + 30 = 55.
    log(day2, 30)
    logs55 = client.get("/hr/me/logs", headers=rider_headers).json()
    assert logs55["month_orders"] == 55 and {row["date"]: row["orders"] for row in logs55["days"]}[day1.isoformat()] == 25 and {row["date"]: row["orders"] for row in logs55["days"]}[day2.isoformat()] == 30, logs55
    assert logs55["bonus_earned"] == 0 and logs55["bonus_details"][0]["orders"] == 55 and logs55["bonus_details"][0]["remaining_orders"] == 445, logs55
    query = f"date_from={day1.isoformat()}&date_to={day2.isoformat()}&branch_id={branch['id']}"
    company_daily = client.get("/hr/daily-report?" + query, headers=company_headers)
    supervisor_daily = client.get("/hr/daily-report?" + query, headers=supervisor_headers)
    assert company_daily.status_code == 200 and supervisor_daily.status_code == 200
    assert only_row(company_daily.json()["rows"], "Mohamed Acceptance")["طلبات الفترة"] == 55
    assert only_row(supervisor_daily.json()["rows"], "Mohamed Acceptance")["طلبات الفترة"] == 55
    assert client.get(f"/fleet/couriers/{rider_id}", headers=company_headers).json()["month_orders"] == 55
    assert client.get(f"/fleet/couriers/{rider_id}", headers=supervisor_headers).json()["month_orders"] == 55
    bonus55 = only_row(client.get("/fleet/reports?report_type=bonus&" + query, headers=company_headers).json(), "Mohamed Acceptance")
    assert bonus55["طلبات الشهر حتى نهاية الفترة"] == 55 and bonus55["البونص المستحق"] == 0, bonus55
    payroll55 = next(row for row in client.get(f"/hr/payroll?month={date.today().strftime('%Y-%m')}", headers=company_headers).json()["rows"] if row["id"] == rider_id)
    assert payroll55["orders"] == 55 and payroll55["bonus"] == 0, payroll55
    financial55 = next(row for row in client.get(f"/hr/financial/branches?month={date.today().strftime('%Y-%m')}", headers=company_headers).json()["rows"] if row["contract_branch_id"] == branch["id"])
    assert financial55["eligible_orders"] == 55, financial55

    # Replaying Day 1 leaves the monthly total unchanged; correcting Day 2 changes it by exactly +5.
    log(day1, 25, "Retry same day")
    assert client.get("/hr/me/logs", headers=rider_headers).json()["month_orders"] == 55
    log(day2, 35, "Corrected Day 2")
    assert client.get("/hr/me/logs", headers=rider_headers).json()["month_orders"] == 60

    # Existing performance CSV uses the same DailyLog row and cannot double-count the corrected Day 2.
    file_same_day = performance_csv([{"rider_phone": RIDER_PHONE, "date": day2.isoformat(), "project": project, "completed_orders": "35", "notes": "Platform reconciliation"}])
    perf_preview = client.post("/fleet/imports/performance/preview", headers=company_headers, json={"file_name": "day2.csv", "csv_text": file_same_day})
    assert perf_preview.status_code == 200 and perf_preview.json()["warning_rows"] == 1, perf_preview.text
    perf_confirm = client.post(f"/fleet/imports/performance/{perf_preview.json()['id']}/confirm", headers=company_headers)
    assert perf_confirm.status_code == 200 and perf_confirm.json()["result"]["updated"] == 1, perf_confirm.text
    assert client.get("/hr/me/logs", headers=rider_headers).json()["month_orders"] == 60

    # Exact target then 50 orders above target: values must be identical in rider, company, supervisor, report and payroll.
    log(day3, 440)
    target = client.get("/hr/me/logs", headers=rider_headers).json()
    assert target["month_orders"] == 500 and target["bonus_earned"] == 1800 and target["bonus_details"][0]["over_orders"] == 0, target
    payroll500 = next(row for row in client.get(f"/hr/payroll?month={date.today().strftime('%Y-%m')}", headers=company_headers).json()["rows"] if row["id"] == rider_id)
    assert payroll500["orders"] == 500 and payroll500["bonus"] == 1800, payroll500
    log(day4, 50)
    final_logs = client.get("/hr/me/logs", headers=rider_headers).json()
    assert final_logs["month_orders"] == 550 and final_logs["bonus_earned"] == 2050 and final_logs["bonus_details"][0]["over_orders"] == 50, final_logs
    final_company = client.get(f"/fleet/couriers/{rider_id}", headers=company_headers).json()
    final_supervisor = client.get(f"/fleet/couriers/{rider_id}", headers=supervisor_headers).json()
    assert final_company["month_orders"] == final_supervisor["month_orders"] == 550
    assert final_company["bonus_earned"] == final_supervisor["bonus_earned"] == 2050
    end_query = f"date_from={day1.isoformat()}&date_to={day4.isoformat()}&branch_id={branch['id']}"
    final_daily = only_row(client.get("/hr/daily-report?" + end_query, headers=company_headers).json()["rows"], "Mohamed Acceptance")
    final_bonus = only_row(client.get("/fleet/reports?report_type=bonus&" + end_query, headers=company_headers).json(), "Mohamed Acceptance")
    final_payroll = next(row for row in client.get(f"/hr/payroll?month={date.today().strftime('%Y-%m')}", headers=company_headers).json()["rows"] if row["id"] == rider_id)
    final_financial = next(row for row in client.get(f"/hr/financial/branches?month={date.today().strftime('%Y-%m')}", headers=company_headers).json()["rows"] if row["contract_branch_id"] == branch["id"])
    assert final_daily["طلبات الفترة"] == 550 and final_daily["البونص المستحق"] == 2050, final_daily
    assert final_bonus["طلبات الشهر حتى نهاية الفترة"] == 550 and final_bonus["البونص المستحق"] == 2050, final_bonus
    assert final_payroll["orders"] == 550 and final_payroll["bonus"] == 2050, final_payroll
    assert final_financial["eligible_orders"] == 550, final_financial

    # The close writes a rider-visible snapshot; subsequent source changes cannot rewrite it.
    month = date.today().strftime("%Y-%m")
    closed = client.post("/hr/payroll/finalize", headers=company_headers, json={"month": month})
    assert closed.status_code == 200, closed.text
    closed_logs = client.get("/hr/me/logs", headers=rider_headers).json()
    assert closed_logs["payroll"]["finalized"] is True and closed_logs["payroll"]["source"] == "PAYROLL_SNAPSHOT" and closed_logs["payroll"]["bonus_pay"] == 2050, closed_logs
    log(day4, 60, "Post-close source change")
    snapshot_after = client.get("/hr/me/logs", headers=rider_headers).json()["payroll"]
    assert snapshot_after["finalized"] is True and snapshot_after["bonus_pay"] == 2050, snapshot_after

    print("PASS: imported rider -> DailyLog 25+30=55 -> reports/supervisor/company -> 500=1800 -> 550=2050 -> payroll and closed rider snapshot")


if __name__ == "__main__":
    main()

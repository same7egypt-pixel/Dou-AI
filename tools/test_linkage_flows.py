"""Smoke test for courier ↔ supervisor ↔ company linkage."""
from datetime import date

from app.database import Base, SessionLocal, engine
from app.models.entities import (Attendance, BonusPlan, Contract, ContractBranch, Country, Courier, CourierType, DailyLog, Fleet,
    PayrollAdjustment, Project, Tenant, User, UserRole)
from app.routers.hr import (add_daily_log, company_documents, create_employee_request,
    decide_document, decide_employee_request, upload_my_document, create_contract, contract_structure, daily_report,
    create_bonus, list_bonus)
from app.routers.fleet import add_courier, _report_rows
from app.routers.shifts import check_in
from app.routers.auth import create_token, get_current_user, logout_current
from app.schemas.dou import AttendanceIn
from fastapi import HTTPException

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
db = SessionLocal()
t1 = Tenant(name="A", country=Country.SA)
t2 = Tenant(name="B", country=Country.SA)
db.add_all([t1, t2]); db.flush()
fleet = Fleet(tenant_id=t1.id, name="A Fleet")
p1 = Project(tenant_id=t1.id, name="P1")
p2 = Project(tenant_id=t2.id, name="P2")
p3 = Project(tenant_id=t1.id, name="P3")
db.add_all([fleet, p1, p2, p3]); db.flush()
admin = User(phone="1", name="Admin", password_hash="x", role=UserRole.COMPANY,
             country=Country.SA, tenant_id=t1.id, is_active=True)
sup = User(phone="2", name="Sup", password_hash="x", role=UserRole.SUPERVISOR,
           country=Country.SA, tenant_id=t1.id, is_active=True)
db.add_all([admin, sup]); db.flush()
c = Courier(tenant_id=t1.id, fleet_id=fleet.id, name="Driver", phone="3",
            courier_type=CourierType.COMPANY, country=Country.SA,
            supervisor_id=sup.id, primary_project_id=p1.id)
db.add(c); db.flush()
driver = User(phone="3", name="Driver", password_hash="x", role=UserRole.COURIER,
              country=Country.SA, tenant_id=t1.id, courier_id=c.id, is_active=True)
db.add(driver); db.commit()

ct_result=create_contract({"name":"HungerStation","cities":[{"city":"Riyadh","supervisor_id":sup.id}],"end_date":"2027-12-31"},admin,db)
ct=db.get(Contract,ct_result["id"]);branch=db.query(ContractBranch).filter_by(contract_id=ct.id).one()
structure=contract_structure(admin,db);assert structure[0]["branches"][0]["city"]=="Riyadh"
new_c=add_courier({"name":"Branch Driver","phone":"966500009999","country":"SA","courier_type":"COMPANY","password":"StrongPass9!","contract_id":ct.id,"contract_branch_id":branch.id,"supervisor_id":sup.id},admin,db)
linked=db.query(Courier).filter_by(phone="966500009999").one();assert linked.work_city=="Riyadh" and linked.primary_project_id==branch.project_id
bonus=create_bonus({"contract_branch_id":branch.id,"target_orders":5,"bonus_amount":100,"over_target_rate":2},admin,db)
saved=db.get(BonusPlan,bonus["id"]);assert saved.contract_branch_id==branch.id and saved.project_id==branch.project_id
assert list_bonus(admin,db)[0]["contract"]=="HungerStation" and list_bonus(admin,db)[0]["city"]=="Riyadh"
db.add(DailyLog(courier_id=linked.id,tenant_id=t1.id,project_id=branch.project_id,log_date=date.today(),orders_count=10));db.commit()

check_in(AttendanceIn(courier_id=c.id), driver, db)
check_in(AttendanceIn(courier_id=c.id), driver, db)
assert db.query(Attendance).filter_by(courier_id=c.id).count() == 1

add_daily_log({"log_date": date.today().isoformat(), "project_id": p1.id,
               "orders_count": 10}, driver, db)
period=daily_report(date_from=date.today(),date_to=date.today(),user=admin,db=db)
driver_row=next(r for r in period["rows"] if r["المندوب"]=="Driver")
assert period["summary"]["orders"]==20 and driver_row["طلبات الفترة"]==10
db.add(BonusPlan(tenant_id=t1.id,courier_id=c.id,project_id=p1.id,target_orders=5,bonus_amount=100,over_target_rate=2));db.commit()
bonus_rows=_report_rows(db,admin,"bonus",date_from=date.today(),date_to=date.today())
branch_bonus=next(r for r in bonus_rows if r["السائق"]=="Branch Driver")
assert branch_bonus["طلبات الفترة"]==10 and branch_bonus["البونص المستحق"]==110
try:
    add_daily_log({"project_id": p2.id, "orders_count": 99}, driver, db)
    raise AssertionError("cross-tenant project was accepted")
except HTTPException as exc:
    assert exc.status_code in (403, 404)

doc = upload_my_document({"document_type": "IQAMA", "filename": "id.png",
                          "mime_type": "image/png", "file_data": "data:image/png;base64,AA=="}, driver, db)
assert len(company_documents(admin, db)) == 1
assert decide_document(doc["id"], {"action": "approve"}, admin, db)["status"] == "APPROVED"

advance = create_employee_request({"request_type": "ADVANCE", "title": "Advance",
                                   "amount": 100}, driver, db)
assert decide_employee_request(advance["id"], {"action": "approve"}, sup, db)["status"] == "SUPERVISOR_APPROVED"
assert db.query(PayrollAdjustment).count() == 0
assert decide_employee_request(advance["id"], {"action": "approve"}, admin, db)["status"] == "APPROVED"
assert db.query(PayrollAdjustment).count() == 1

transfer = create_employee_request({"request_type": "PROJECT_TRANSFER", "title": "Move",
                                    "project_id": p3.id}, driver, db)
decide_employee_request(transfer["id"], {"action": "approve"}, admin, db)
db.refresh(c)
assert c.primary_project_id == p3.id

shift = create_employee_request({"request_type": "SHIFT_CHANGE", "title": "Night",
                                 "details": "22:00 - 06:00"}, driver, db)
decide_employee_request(shift["id"], {"action": "approve"}, admin, db)
db.refresh(c)
assert c.shift_preference == "22:00 - 06:00"

token = create_token(driver)
assert get_current_user(token, db).id == driver.id
logout_current(driver, db)
try:
    get_current_user(token, db)
    raise AssertionError("logged-out token remained valid")
except HTTPException as exc:
    assert exc.status_code == 401

print("OK: auth/logout, attendance, project scope, documents, approvals")
db.close()

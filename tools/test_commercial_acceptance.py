"""End-to-end acceptance test for the commercial contract operating hierarchy."""
import asyncio
from datetime import date, timedelta

from fastapi import HTTPException

from app.database import Base, SessionLocal, engine
from app.models.entities import BonusPlan, ContractBranch, Courier, DailyLog, Project, User
from app.routers.auth import company_register, get_current_user, login, logout_current
from app.routers.fleet import _report_rows, add_courier, fleet_couriers, fleet_reports_export
from app.routers.hr import (contract_structure, create_bonus, create_contract, create_supervisor,
                            daily_report, daily_report_export, decide_leave, list_bonus, list_leaves,
                            request_leave, transfer_project)
from app.routers.shifts import check_in, check_out
from app.schemas.dou import AttendanceIn, CompanyRegisterIn, LoginIn


def body_text(response):
    async def collect():
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)
    return asyncio.run(collect())


Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
db = SessionLocal()
checks = []


def ok(name, evidence):
    checks.append({"name": name, "status": "PASS", "evidence": evidence})


registered = company_register(CompanyRegisterIn(
    name="شركة اختبار القبول", phone="966500100000", password="AdminPass9!", country="SA"
), db)
admin_login = login(LoginIn(phone="966500100000", password="AdminPass9!"), db)
admin = get_current_user(admin_login.access_token, db)
ok("دخول أدمن الشركة", f"role={admin.role.value}, tenant={registered.company_id}")

sup1_data = create_supervisor({"name": "مشرف الرياض أ", "phone": "0500100001", "password": "SupervisorA9!"}, admin, db)
sup2_data = create_supervisor({"name": "مشرف الرياض ب", "phone": "0500100002", "password": "SupervisorB9!"}, admin, db)
sup1 = db.get(User, sup1_data["id"]); sup2 = db.get(User, sup2_data["id"])
ok("إضافة مشرفين", f"{sup1.name}, {sup2.name}")

contract_result = create_contract({
    "name": "HungerStation", "end_date": "2027-12-31",
    "cities": [{"city": "الرياض", "supervisor_id": sup1.id},
               {"city": "الرياض", "supervisor_id": sup2.id}],
}, admin, db)
structure = contract_structure(admin, db)
branches = structure[0]["branches"]
assert len(branches) == 2 and {b["supervisor_id"] for b in branches} == {sup1.id, sup2.id}
ok("عقد وفريقان في نفس المدينة", "HungerStation / الرياض / مشرف أ + مشرف ب")

driver1_result = add_courier({
    "name": "سائق فريق أ", "phone": "966500200001", "password": "DriverOne9!",
    "country": "SA", "courier_type": "COMPANY", "contract_id": contract_result["id"],
    "contract_branch_id": branches[0]["id"], "supervisor_id": branches[0]["supervisor_id"],
}, admin, db)
driver2_result = add_courier({
    "name": "سائق فريق ب", "phone": "966500200002", "password": "DriverTwo9!",
    "country": "SA", "courier_type": "COMPANY", "contract_id": contract_result["id"],
    "contract_branch_id": branches[1]["id"], "supervisor_id": branches[1]["supervisor_id"],
}, admin, db)
c1 = db.get(Courier, driver1_result["id"]); c2 = db.get(Courier, driver2_result["id"])
assert c1.work_city == c2.work_city == "الرياض" and c1.supervisor_id != c2.supervisor_id
ok("إضافة سائقين وربطهما", f"{c1.name}→{sup1.name}; {c2.name}→{sup2.name}")

create_bonus({"contract_branch_id": c1.contract_branch_id, "target_orders": 20,
              "bonus_amount": 200, "over_target_rate": 5}, admin, db)
create_bonus({"contract_branch_id": c2.contract_branch_id, "target_orders": 15,
              "bonus_amount": 150, "over_target_rate": 4}, admin, db)
plans = list_bonus(admin, db)
assert len(plans) == 2 and all(p["contract"] == "HungerStation" for p in plans)
ok("خطط بونص من فروع العقود", ", ".join(f'{p["city"]}:{p["target_orders"]}' for p in plans))

driver_login = login(LoginIn(phone="966500200001", password="DriverOne9!"), db)
driver_user = get_current_user(driver_login.access_token, db)
check_in(AttendanceIn(courier_id=c1.id, lat=24.7, lng=46.7), driver_user, db)
today = date.today()
for log_day, orders in [(today - timedelta(days=8), 7), (today - timedelta(days=2), 8), (today, 17)]:
    db.add(DailyLog(courier_id=c1.id, tenant_id=c1.tenant_id, project_id=c1.primary_project_id,
                    log_date=log_day, orders_count=orders))
db.commit()
check_out(AttendanceIn(courier_id=c1.id, lat=24.7, lng=46.7), driver_user, db)
ok("حضور وطلبات تطبيق السائق", "check-in/out ناجح؛ 3 سجلات طلبات")

day = daily_report(date_from=today, date_to=today, user=admin, db=db)
week = daily_report(date_from=today - timedelta(days=6), date_to=today, user=admin, db=db)
month = daily_report(date_from=date(today.year, today.month, 1), date_to=today, user=admin, db=db)
day_orders = next(r for r in day["rows"] if r["المندوب"] == c1.name)["طلبات الفترة"]
week_orders = next(r for r in week["rows"] if r["المندوب"] == c1.name)["طلبات الفترة"]
month_orders = next(r for r in month["rows"] if r["المندوب"] == c1.name)["طلبات الفترة"]
assert day_orders == 17 and week_orders == 25 and month_orders >= 25
ok("تقارير يومية/أسبوعية/شهرية", f"day={day_orders}, week={week_orders}, month={month_orders}")

bonus_rows = _report_rows(db, admin, "bonus", date_from=today - timedelta(days=6), date_to=today)
c1_bonus = next(r for r in bonus_rows if r["السائق"] == c1.name)
assert (c1_bonus["طلبات الفترة"] == 25 and c1_bonus["طلبات الشهر حتى نهاية الفترة"] == 32
        and c1_bonus["البونص المستحق"] == 260)
ok("حساب التارجت والبونص", "الأسبوع 25؛ الشهر 32؛ تارجت 20؛ بونص=200+(12×5)=260 ر.س")

sup1_login = login(LoginIn(phone=sup1.phone, password="SupervisorA9!"), db)
sup1_user = get_current_user(sup1_login.access_token, db)
visible = fleet_couriers(sup1_user, db)
assert [x["id"] for x in visible] == [c1.id]
supervisor_day = daily_report(date_from=today, date_to=today, user=sup1_user, db=db)
assert [(r["المندوب"], r["طلبات الفترة"]) for r in supervisor_day["rows"]] == [(c1.name, 17)]
leave_result = request_leave({"from_date": today.isoformat(), "to_date": (today + timedelta(days=2)).isoformat(),
                              "reason": "اختبار ظهور الطلب للمشرف"}, driver_user, db)
assert [x["id"] for x in list_leaves(sup1_user, db)] == [leave_result["id"]]
# فرع العقد هو المصدر الأساسي حتى لو ظل حقل المشرف القديم غير متزامن.
c2.supervisor_id = sup1.id
db.commit()
sup2_scope_login = login(LoginIn(phone=sup2.phone, password="SupervisorB9!"), db)
sup2_scope_user = get_current_user(sup2_scope_login.access_token, db)
assert list_leaves(sup2_scope_user, db) == []
assert decide_leave(leave_result["id"], {"action": "approve"}, sup1_user, db)["status"] == "SUPERVISOR_APPROVED"
assert {x["id"] for x in fleet_couriers(sup2_scope_user, db)} == {c2.id}
assert {x["id"] for x in fleet_couriers(sup1_user, db)} == {c1.id}
c2.supervisor_id = sup2.id
db.commit()
try:
    add_courier({"name": "ممنوع", "phone": "966500299999"}, sup1_user, db)
    raise AssertionError("Supervisor added a courier")
except HTTPException as exc:
    assert exc.status_code == 403
ok("صلاحيات المشرف", f"يرى سائقًا واحدًا فقط؛ إضافة سائق مرفوضة 403")

daily_csv = daily_report_export(date_from=today - timedelta(days=6), date_to=today, user=admin, db=db)
bonus_csv = fleet_reports_export(report_type="bonus", date_from=today - timedelta(days=6),
                                 date_to=today, user=admin, db=db)
daily_text = body_text(daily_csv); bonus_text = body_text(bonus_csv)
assert "طلبات الفترة" in daily_text and c1.name in daily_text
assert "البونص المستحق" in bonus_text and c1.name in bonus_text
ok("تنزيل Excel/CSV", f"daily={len(daily_text)} bytes, bonus={len(bonus_text)} bytes")

target_branch = db.get(ContractBranch, branches[1]["id"])
transfer_project(c1.id, {"project_id": target_branch.project_id, "note": "توزيع الأحمال"}, admin, db)
db.refresh(c1)
assert c1.contract_branch_id == target_branch.id and c1.supervisor_id == sup2.id
assert len(fleet_couriers(sup1_user, db)) == 0
sup2_login = login(LoginIn(phone=sup2.phone, password="SupervisorB9!"), db)
sup2_user = get_current_user(sup2_login.access_token, db)
assert {x["id"] for x in fleet_couriers(sup2_user, db)} == {c1.id, c2.id}
ok("نقل سائق بين فريقين", f"{c1.name} انتقل إلى {sup2.name}; الصلاحيات اتحدثت فورًا")

token = driver_login.access_token
logout_current(driver_user, db)
try:
    get_current_user(token, db)
    raise AssertionError("Logged-out token remained active")
except HTTPException as exc:
    assert exc.status_code == 401
login(LoginIn(phone="966500200001", password="DriverOne9!"), db)
ok("تسجيل الدخول والخروج", "التوكن بطل بعد الخروج؛ إعادة الدخول نجحت")

print("ACCEPTANCE RESULT: PASS")
for index, check in enumerate(checks, 1):
    print(f'{index:02d}. {check["status"]} | {check["name"]} | {check["evidence"]}')
db.close()

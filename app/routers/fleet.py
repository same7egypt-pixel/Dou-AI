from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi import Query
from sqlalchemy.orm import Session
import csv, io
import json
from datetime import date, datetime, timedelta

from ..database import get_db
from ..models.entities import (
    Attendance, AppSetting, Contract, Courier, CourierTask, CourierTaskStatus, Country, CourierType, Merchant,
    Order, OrderStatus, Shift, ShiftStatus, SupportTicket, Tenant, User, UserRole, Fleet,
    Project, DailyLog, BonusPlan, LeaveRequest, SubscriptionPlan,
)
from .auth import get_current_user

router = APIRouter(prefix="/fleet", tags=["fleet"])

COMPANY_ROLES = (
    UserRole.COMPANY, UserRole.COMPANY_ADMIN, UserRole.OPERATIONS,
    UserRole.HR, UserRole.ACCOUNTANT, UserRole.VIEWER,
    UserRole.DOU_OPS, UserRole.DOU_ADMIN,
)
TENANT_ROLES = (
    UserRole.COMPANY, UserRole.COMPANY_ADMIN, UserRole.OPERATIONS,
    UserRole.HR, UserRole.ACCOUNTANT, UserRole.VIEWER, UserRole.SUPERVISOR,
    UserRole.PROJECT_MANAGER,
)

ROLE_PERMISSIONS = {
    UserRole.COMPANY: ["dashboard", "drivers", "attendance", "performance", "tickets", "hr", "payroll", "reports", "export", "users", "settings", "billing", "supervision"],
    UserRole.COMPANY_ADMIN: ["dashboard", "drivers", "attendance", "performance", "tickets", "hr", "payroll", "reports", "export", "users", "settings", "supervision"],
    UserRole.OPERATIONS: ["dashboard", "drivers", "attendance", "performance", "tickets"],
    UserRole.HR: ["dashboard", "drivers", "attendance", "hr", "payroll", "reports", "export"],
    UserRole.ACCOUNTANT: ["dashboard", "payroll", "reports", "export"],
    UserRole.VIEWER: ["dashboard"],
    UserRole.SUPERVISOR: ["dashboard", "drivers", "attendance", "performance", "tickets", "reports", "supervision"],
    UserRole.PROJECT_MANAGER: ["dashboard", "drivers", "attendance", "performance", "reports"],
    UserRole.DOU_OPS: ["*"],
    UserRole.DOU_ADMIN: ["*"],
}


def _require_permission(user: User, permission: str):
    permissions = json.loads(user.custom_permissions) if user.custom_permissions else ROLE_PERMISSIONS.get(user.role, [])
    if "*" not in permissions and permission not in permissions:
        raise HTTPException(403, "You do not have permission for this section")


def _tenant_record(db: Session, model, record_id: int, user: User):
    record = db.get(model, record_id)
    if not record:
        raise HTTPException(404, f"{model.__name__} not found")
    if user.role in TENANT_ROLES and getattr(record, "tenant_id", None) != user.tenant_id:
        raise HTTPException(404, f"{model.__name__} not found")
    return record


def _report_rows(db: Session, user: User, report_type: str,
                 project_id: int = None, doc_status: str = None):
    tenant_id = _scope(user, db)
    q = db.query(Courier)
    if tenant_id is not None:
        q = q.filter(Courier.tenant_id == tenant_id)
    couriers = q.order_by(Courier.name).all()
    today = date.today()

    if report_type == "documents":
        rows = []
        for c in couriers:
            dates = [c.iqama_expiry, c.license_expiry, c.vehicle_license_expiry]
            days = [(d - today).days if d else None for d in dates]
            status = "EXPIRED" if any(v is not None and v < 0 for v in days) else (
                "SOON" if any(v is not None and v <= 30 for v in days) else "OK"
            )
            if doc_status and doc_status != "ALL" and status != doc_status:
                continue
            rows.append({
                "السائق": c.name, "الجوال": c.phone, "المشروع": c.platform or "—",
                "نوع المركبة": c.vehicle_type or "—", "رقم اللوحة": c.vehicle_plate or "—",
                "انتهاء الإقامة": c.iqama_expiry.isoformat() if c.iqama_expiry else "—",
                "انتهاء رخصة القيادة": c.license_expiry.isoformat() if c.license_expiry else "—",
                "انتهاء رخصة المركبة": c.vehicle_license_expiry.isoformat() if c.vehicle_license_expiry else "—",
                "الحالة": status,
            })
        return rows

    start = date(today.year, today.month, 1)
    end = date(today.year + (today.month // 12), today.month % 12 + 1, 1)
    projects = {p.id: p for p in db.query(Project).filter(
        Project.tenant_id == tenant_id if tenant_id is not None else text("1=1")
    ).all()}
    rows = []
    from .hr import calculate_target_bonus
    for c in couriers:
        logs = db.query(DailyLog).filter(
            DailyLog.courier_id == c.id, DailyLog.log_date >= start, DailyLog.log_date < end
        ).all()
        plans = db.query(BonusPlan).filter(
            BonusPlan.tenant_id == c.tenant_id,
            (BonusPlan.courier_id == c.id) | (BonusPlan.courier_id.is_(None)),
        ).all()
        covered = set()
        for plan in sorted(plans, key=lambda x: 1 if x.courier_id is None else 0):
            if plan.project_id in covered or (project_id and plan.project_id != project_id):
                continue
            covered.add(plan.project_id)
            orders = sum(l.orders_count or 0 for l in logs if l.project_id == plan.project_id)
            result = calculate_target_bonus(orders, plan.target_orders, plan.bonus_amount, plan.over_target_rate)
            project = projects.get(plan.project_id)
            rows.append({
                "السائق": c.name, "المشروع": project.name if project else c.platform or "—",
                "طلبات الشهر": orders, "التارجت": plan.target_orders,
                "المتبقي": result["remaining_orders"], "الطلبات الزائدة": result["over_orders"],
                "بونص التارجت": plan.bonus_amount, "سعر الطلب الزائد": plan.over_target_rate,
                "البونص المستحق": result["earned"],
                "الراتب الأساسي": c.base_salary or 0,
                "إجمالي المستحق": round((c.base_salary or 0) + orders * (c.per_delivery_rate or 0) + result["earned"], 2),
            })
    return rows


@router.get("/reports")
def fleet_reports(report_type: str = Query("documents", pattern="^(documents|bonus)$"),
                  project_id: int = None, doc_status: str = None,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    needed = "hr" if report_type == "documents" else "payroll"
    _require_permission(user, needed)
    return _report_rows(db, user, report_type, project_id, doc_status)


@router.get("/reports/export")
def fleet_reports_export(report_type: str = Query("documents", pattern="^(documents|bonus)$"),
                         project_id: int = None, doc_status: str = None,
                         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user,"export")
    needed = "hr" if report_type == "documents" else "payroll"
    _require_permission(user, needed)
    rows = _report_rows(db, user, report_type, project_id, doc_status)
    output = io.StringIO()
    output.write("\ufeff")
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    filename = f"dou-{report_type}-{date.today().isoformat()}.csv"
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _scope(user: User, db: Session):
    """يعيد نطاق البيانات (tenant) حسب نوع الحساب:
    - COMPANY: مناديب وطلبات شركته فقط
    - DOU_OPS/DOU_ADMIN: كل البيانات"""
    if user.role in TENANT_ROLES:
        from .billing import check_active
        check_active(user, db)
        return user.tenant_id
    return None


def _courier_ids(db: Session, tenant_id, supervisor_id=None, project_ids=None):
    if tenant_id is None:
        return {c.id for c in db.query(Courier).all()}
    q = db.query(Courier).filter(Courier.tenant_id == tenant_id)
    if supervisor_id:
        q = q.filter(Courier.supervisor_id == supervisor_id)
    if project_ids is not None: q=q.filter(Courier.primary_project_id.in_(project_ids))
    return {c.id for c in q.all()}


@router.get("/me")
def fleet_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """معلومات حساب الشركة + أساطيلها."""
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None
    fleets = []
    if tenant:
        for f in db.query(Fleet).filter(Fleet.tenant_id == tenant.id).all():
            fleets.append({"id": f.id, "name": f.name, "zone": f.zone or ""})
    permissions = json.loads(user.custom_permissions) if user.custom_permissions else ROLE_PERMISSIONS.get(user.role, [])
    return {
        "role": user.role.value,
        "permissions": permissions,
        "tenant": {"id": tenant.id, "name": tenant.name, "country": tenant.country.value,
                   "market_code": tenant.market_code or tenant.country.value,
                   "default_language": tenant.default_language or "ar",
                   "currency": tenant.currency or "SAR",
                   "timezone": tenant.timezone or "Asia/Riyadh"} if tenant else None,
        "fleets": fleets,
        "name": user.name or (tenant.name if tenant else "شركة"),
    }


MANAGEABLE_ROLES = {
    "COMPANY_ADMIN", "OPERATIONS", "HR", "ACCOUNTANT", "VIEWER", "PROJECT_MANAGER",
}


@router.get("/users")
def fleet_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """مستخدمو الشركة الداخليون. لا يعرض حسابات السائقين."""
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "users")
    rows = db.query(User).filter(
        User.tenant_id == user.tenant_id,
        User.role.in_([UserRole.COMPANY, UserRole.COMPANY_ADMIN, UserRole.OPERATIONS,
                       UserRole.HR, UserRole.ACCOUNTANT, UserRole.VIEWER, UserRole.PROJECT_MANAGER]),
    ).order_by(User.id).all()
    return [{
        "id": row.id, "name": row.name, "phone": row.phone,
        "role": row.role.value, "is_active": row.is_active,
        "is_owner": row.role == UserRole.COMPANY,
        "created_at": row.created_at.isoformat() if row.created_at else None,"custom_permissions":json.loads(row.custom_permissions) if row.custom_permissions else [],"managed_project_ids":json.loads(row.managed_project_ids) if row.managed_project_ids else [],
    } for row in rows]


@router.post("/users")
def fleet_add_user(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "users")
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    password = payload.get("password") or ""
    role_value = payload.get("role") or "VIEWER"
    if not name or not phone:
        raise HTTPException(400, "Name and phone are required")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if role_value not in MANAGEABLE_ROLES:
        raise HTTPException(400, "Invalid company role")
    if db.query(User).filter(User.phone == phone).first():
        raise HTTPException(400, "Phone already registered")
    from .auth import hash_password
    row = User(
        phone=phone, name=name, password_hash=hash_password(password),
        role=UserRole(role_value), tenant_id=user.tenant_id,
        country=user.country, is_active=True,
        custom_permissions=json.dumps(payload.get("permissions")) if payload.get("permissions") else None,managed_project_ids=json.dumps(payload.get("project_ids") or []),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id}


@router.patch("/users/{uid}")
def fleet_update_user(uid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "users")
    row = db.get(User, uid)
    if not row or row.tenant_id != user.tenant_id or row.role == UserRole.COMPANY:
        raise HTTPException(404, "Company user not found")
    if "role" in payload:
        if payload["role"] not in MANAGEABLE_ROLES:
            raise HTTPException(400, "Invalid company role")
        row.role = UserRole(payload["role"])
        row.token_version = (row.token_version or 0) + 1
    if "name" in payload and str(payload["name"]).strip():
        row.name = str(payload["name"]).strip()
    if "is_active" in payload:
        row.is_active = bool(payload["is_active"])
        row.token_version = (row.token_version or 0) + 1
    if payload.get("password"):
        if len(payload["password"]) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")
        from .auth import hash_password
        row.password_hash = hash_password(payload["password"])
        row.token_version = (row.token_version or 0) + 1
    if "permissions" in payload: row.custom_permissions=json.dumps(payload.get("permissions") or [])
    if "project_ids" in payload: row.managed_project_ids=json.dumps(payload.get("project_ids") or [])
    db.commit()
    return {"ok": True}


@router.delete("/users/{uid}")
def fleet_delete_user(uid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "users")
    row = db.get(User, uid)
    if not row or row.tenant_id != user.tenant_id or row.role == UserRole.COMPANY:
        raise HTTPException(404, "Company user not found")
    if row.id == user.id:
        raise HTTPException(400, "You cannot delete your own account")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/overview")
def fleet_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """مؤشرات تشغيلية في نطاق الشركة."""
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "dashboard")
    tenant_id = _scope(user, db)
    managed=json.loads(user.managed_project_ids or "[]") if user.role==UserRole.PROJECT_MANAGER else None
    ids = _courier_ids(db, tenant_id, user.id if user.role == UserRole.SUPERVISOR else None,managed)
    couriers = db.query(Courier).filter(Courier.id.in_(ids)).all() if ids else []

    orders = db.query(Order).filter(Order.courier_id.in_(ids)).all() if ids else []
    orders = [o for o in orders if o.courier_id in ids]
    tasks = db.query(CourierTask).filter(CourierTask.courier_id.in_(ids)).all() if ids else []
    today = date.today()
    expiry_limit = today + timedelta(days=30)
    expiring_documents = 0
    docs_expired=docs_30=docs_60=0
    for courier in couriers:
        dates = (courier.iqama_expiry, courier.license_expiry, courier.vehicle_license_expiry)
        if not courier.documents_valid or any(d and d <= expiry_limit for d in dates):
            expiring_documents += 1
        for d in dates:
            if not d: continue
            days=(d-today).days
            if days<0: docs_expired+=1
            elif days<=30: docs_30+=1
            elif days<=60: docs_60+=1
    active_employees = sum(1 for c in couriers if (c.employment_status or "ACTIVE") == "ACTIVE")
    on_leave = sum(1 for c in couriers if c.is_on_leave)
    day_start=datetime.combine(today,datetime.min.time()); day_end=day_start+timedelta(days=1)
    today_att=db.query(Attendance).filter(Attendance.courier_id.in_(ids),Attendance.check_in>=day_start,Attendance.check_in<day_end).all() if ids else []
    month_start=date(today.year,today.month,1)
    logs=db.query(DailyLog).filter(DailyLog.courier_id.in_(ids),DailyLog.log_date>=month_start,DailyLog.log_date<=today).all() if ids else []

    delivered = [t for t in tasks if t.status == CourierTaskStatus.DELIVERED]
    active_st = {OrderStatus.READY, OrderStatus.ACCEPTED, OrderStatus.ASSIGNED, OrderStatus.IN_TRANSIT, OrderStatus.PICKED_UP}
    unassigned = db.query(Order).filter(Order.courier_id.is_(None), Order.status == OrderStatus.PLACED).count()
    if tenant_id is not None:
        unassigned = 0

    return {
        "couriers_total": len(couriers),
        "couriers_online": sum(1 for c in couriers if c.is_online),
        "active_employees": active_employees,
        "on_leave": on_leave,
        "documents_attention": expiring_documents,
        "documents_expired":docs_expired,"documents_30":docs_30,"documents_60":docs_60,
        "present_today":len({a.courier_id for a in today_att}), "late_today":sum(bool(a.is_late) for a in today_att),
        "absent_today":max(active_employees-len({a.courier_id for a in today_att})-on_leave,0),
        "orders_today":sum(x.orders_count or 0 for x in logs if x.log_date==today), "orders_month":sum(x.orders_count or 0 for x in logs),
        "pending_leaves":db.query(LeaveRequest).filter(LeaveRequest.courier_id.in_(ids),LeaveRequest.status.in_(["PENDING","SUPERVISOR_APPROVED"])).count() if ids else 0,
        "shifts_running": sum(1 for c in couriers if c.shift_active),
        "payroll_total": round(sum((c.base_salary or 0) for c in couriers), 2),
        "orders_total": len(orders),
        "orders_active": sum(1 for o in orders if o.status in active_st),
        "orders_unassigned": unassigned,
        "deliveries_done": len(delivered),
        "revenue_total": round(sum(o.total for o in orders), 2),
        "avg_acceptance": round(sum(c.acceptance_rate for c in couriers) / len(couriers), 1) if couriers else 0,
        "avg_score": round(sum(c.score for c in couriers) / len(couriers), 2) if couriers else 0,
        "on_time_rate": round(sum(c.on_time_rate for c in couriers) / len(couriers), 1) if couriers else 0,
        "company_couriers": sum(1 for c in couriers if c.courier_type.value == "COMPANY"),
        "freelance_couriers": sum(1 for c in couriers if c.courier_type.value == "FREELANCER"),
        "shifts_active": db.query(Shift).filter(Shift.tenant_id == user.tenant_id, Shift.status == ShiftStatus.ACTIVE).count() if user.tenant_id else db.query(Shift).count(),
    }


@router.get("/couriers")
def fleet_couriers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "drivers")
    tenant_id = _scope(user, db)
    q = db.query(Courier)
    if tenant_id is not None:
        q = q.filter(Courier.tenant_id == tenant_id)
    if user.role == UserRole.SUPERVISOR:
        q = q.filter(Courier.supervisor_id == user.id)
    if user.role==UserRole.PROJECT_MANAGER:q=q.filter(Courier.primary_project_id.in_(json.loads(user.managed_project_ids or "[]")))
    couriers = q.all()
    today = date.today()
    month_start = date(today.year, today.month, 1)
    return [
        {
            "id": c.id, "name": c.name, "phone": c.phone,
            "courier_type": c.courier_type.value, "country": c.country.value,
            "is_online": c.is_online, "is_available": c.is_available,
            "current_load": c.current_load, "acceptance_rate": c.acceptance_rate,
            "on_time_rate": c.on_time_rate, "completion_rate": c.completion_rate,
            "score": c.score, "documents_valid": c.documents_valid, "shift_active": c.shift_active,
            "lat": c.lat, "lng": c.lng,
            "base_salary": c.base_salary or 0, "per_delivery_rate": c.per_delivery_rate or 0,
            "bonus_target": c.bonus_target or 0, "employment_status": c.employment_status or "ACTIVE",
            "hired_at": c.hired_at.isoformat() if c.hired_at else None,
            "bank_iban": c.bank_iban,
            "nationality": c.nationality,
            "zone": c.zone,
            "today_orders": sum(x.orders_count or 0 for x in db.query(DailyLog).filter(DailyLog.courier_id == c.id, DailyLog.log_date == today).all()),
            "month_orders": sum(x.orders_count or 0 for x in db.query(DailyLog).filter(DailyLog.courier_id == c.id, DailyLog.log_date >= month_start, DailyLog.log_date <= today).all()),
            "fleet": (db.get(Fleet, c.fleet_id).name if c.fleet_id else None),
            "supervisor_id": c.supervisor_id,
            "supervisor": (db.get(User, c.supervisor_id).name if c.supervisor_id else None),
            "primary_project_id": c.primary_project_id,
            "project": (db.get(Project, c.primary_project_id).name if c.primary_project_id else c.platform),
        }
        for c in couriers
    ]


@router.post("/couriers")
def add_courier(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """إضافة مندوب جديد + إنشاء حساب دخول له في تطبيق السواقين.
    يُرجع كلمة المرور المبدئية (ترسلها الشركة للمندوب)."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "drivers")
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    if not name or not phone:
        raise HTTPException(400, "Name and phone are required")
    if db.query(Courier).filter(Courier.phone == phone).first():
        raise HTTPException(400, "Courier phone already exists")
    country = Country(payload.get("country") or "SA")
    ctype = CourierType(payload.get("courier_type") or "COMPANY")
    tenant_id = user.tenant_id
    tenant=db.get(Tenant,tenant_id) if tenant_id else None
    plan=db.query(SubscriptionPlan).filter(SubscriptionPlan.code==tenant.plan).first() if tenant else None
    if plan and plan.max_couriers and db.query(Courier).filter(Courier.tenant_id==tenant_id).count()>=plan.max_couriers:
        raise HTTPException(403,"تم الوصول للحد الأقصى من السائقين في الباقة")
    fleet = db.query(Fleet).filter(Fleet.tenant_id == tenant_id).first() if tenant_id else None
    try:
        base_salary = float(payload.get("base_salary") or 0)
        per_delivery_rate = float(payload.get("per_delivery_rate") or 0)
        bonus_target = float(payload.get("bonus_target") or 0)
    except (ValueError, TypeError):
        raise HTTPException(400, "قيم رقمية غير صالحة")
    supervisor_id = payload.get("supervisor_id")
    contract_id = payload.get("contract_id")
    supervisor = db.get(User, int(supervisor_id)) if supervisor_id else None
    contract = db.get(Contract, int(contract_id)) if contract_id else None
    if supervisor and (supervisor.role != UserRole.SUPERVISOR or supervisor.tenant_id != tenant_id):
        raise HTTPException(400, "المشرف المختار غير تابع للشركة")
    if contract and contract.tenant_id != tenant_id:
        raise HTTPException(400, "العقد المختار غير تابع للشركة")
    project = None
    if contract:
        project = db.get(Project, contract.project_id) if contract.project_id else None
        if project and project.tenant_id != tenant_id:
            project = None
        if not project:
            project = Project(tenant_id=tenant_id, name=contract.name, is_active=True)
            db.add(project)
            db.flush()
            contract.project_id = project.id
    courier = Courier(
        tenant_id=tenant_id, fleet_id=fleet.id if fleet else None,
        name=name, phone=phone, courier_type=ctype, country=country,
        lat=payload.get("lat"), lng=payload.get("lng"),
        base_salary=base_salary,
        per_delivery_rate=per_delivery_rate,
        bonus_target=bonus_target,
        bank_iban=payload.get("bank_iban"),
        nationality=((payload.get("nationality_other") or "").strip() if payload.get("nationality") == "أخرى" else (payload.get("nationality") or None)),
        iqama_number=(payload.get("iqama_number") or None), emergency_name=(payload.get("emergency_name") or None),
        emergency_phone=(payload.get("emergency_phone") or None),
        supervisor_id=supervisor.id if supervisor else None,
        primary_project_id=project.id if project else None,
        platform=project.name if project else None,
        vehicle_type=(payload.get("vehicle_type") or None),
    )
    db.add(courier)
    db.flush()
    password = str(payload.get("password") or "")
    if len(password) < 8:
        raise HTTPException(400, "كلمة مرور المندوب يجب أن تكون 8 أحرف على الأقل")
    from .auth import hash_password
    db.add(User(
        phone="966" + phone.lstrip("0") if not phone.startswith("966") else phone,
        name=name, password_hash=hash_password(password),
        role=UserRole.COURIER, courier_id=courier.id,
        tenant_id=tenant_id, country=country, is_active=True,
    ))
    db.commit()
    db.refresh(courier)
    login_phone = courier.phone if courier.phone.startswith("966") else "966" + courier.phone.lstrip("0")
    return {"ok": True, "id": courier.id, "login_phone": login_phone, "password": password,
            "supervisor": supervisor.name if supervisor else None, "project": project.name if project else None}


@router.patch("/couriers/{cid}")
def update_courier(cid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """تعديل بيانات مندوب (راتب، بونص، حالة توظيف، مستندات…)."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "drivers")
    courier = _tenant_record(db, Courier, cid, user)
    allowed = {
        "name", "phone", "courier_type", "base_salary", "per_delivery_rate",
        "bonus_target", "employment_status", "bank_iban", "documents_valid",
        "is_online", "is_available", "shift_active", "lat", "lng",
    }
    for k, v in payload.items():
        if k in allowed:
            setattr(courier, k, v)
    db.commit()
    return {"ok": True}


@router.get("/couriers/{cid}")
def courier_profile(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """ملف مندوب كامل: بيانات + مهام + حضور + أرباح (HR)."""
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "drivers")
    courier = _tenant_record(db, Courier, cid, user)
    if user.role == UserRole.SUPERVISOR and courier.supervisor_id != user.id:
        raise HTTPException(404, "Courier not found")
    if user.role==UserRole.PROJECT_MANAGER and courier.primary_project_id not in json.loads(user.managed_project_ids or "[]"):
        raise HTTPException(404,"Courier not found")
    if user.role == UserRole.SUPERVISOR and courier.supervisor_id != user.id:
        raise HTTPException(404, "Courier not found")
    tasks = db.query(CourierTask).filter(CourierTask.courier_id == cid).all()
    delivered = [t for t in tasks if t.status == CourierTaskStatus.DELIVERED]
    attendances = db.query(Attendance).filter(Attendance.courier_id == cid).all()
    today = date.today()
    month_start = date(today.year, today.month, 1)
    daily_logs = db.query(DailyLog).filter(DailyLog.courier_id == cid, DailyLog.log_date >= month_start).all()
    today_orders = sum(x.orders_count or 0 for x in daily_logs if x.log_date == today)
    month_orders = sum(x.orders_count or 0 for x in daily_logs)
    hours = 0.0
    for a in attendances:
        if a.check_in and a.check_out:
            hours += (a.check_out - a.check_in).total_seconds() / 3600
    per_delivery = courier.per_delivery_rate or 0
    bonus = courier.bonus_target or 0
    if bonus and delivered and courier.score and courier.score >= 4.7:
        bonus = round(bonus * 0.8, 2)
    return {
        "id": courier.id, "name": courier.name, "phone": courier.phone,
        "courier_type": courier.courier_type.value, "country": courier.country.value,
        "is_online": courier.is_online, "is_available": courier.is_available,
        "current_load": courier.current_load, "acceptance_rate": courier.acceptance_rate,
        "on_time_rate": courier.on_time_rate, "completion_rate": courier.completion_rate,
        "score": courier.score, "documents_valid": courier.documents_valid,
        "shift_active": courier.shift_active, "lat": courier.lat, "lng": courier.lng,
        "base_salary": courier.base_salary or 0, "per_delivery_rate": per_delivery,
        "bonus_target": courier.bonus_target or 0, "bonus_earned": bonus,
        "employment_status": courier.employment_status or "ACTIVE",
        "hired_at": courier.hired_at.isoformat() if courier.hired_at else None,
        "bank_iban": courier.bank_iban,
        "iqama_expiry": courier.iqama_expiry.isoformat() if courier.iqama_expiry else None,
        "license_expiry": courier.license_expiry.isoformat() if courier.license_expiry else None,
        "vehicle_license_expiry": courier.vehicle_license_expiry.isoformat() if courier.vehicle_license_expiry else None,
        "vehicle_type": courier.vehicle_type, "vehicle_plate": courier.vehicle_plate,
        "iqama_number": courier.iqama_number, "emergency_name": courier.emergency_name,
        "emergency_phone": courier.emergency_phone, "passport_number": courier.passport_number,
        "passport_expiry": courier.passport_expiry.isoformat() if courier.passport_expiry else None,
        "insurance_expiry": courier.insurance_expiry.isoformat() if courier.insurance_expiry else None,
        "inspection_expiry": courier.inspection_expiry.isoformat() if courier.inspection_expiry else None,
        "work_permit_expiry": courier.work_permit_expiry.isoformat() if courier.work_permit_expiry else None,
        "platform": courier.platform, "platform_courier_id": courier.platform_courier_id,
        "zone": courier.zone, "shift_preference": courier.shift_preference, "primary_project_id": courier.primary_project_id,
        "nationality": courier.nationality,
        "today_orders": today_orders, "month_orders": month_orders,
        "deliveries_done": len(delivered),
        "deliveries_total": len(tasks),
        "hours_worked": round(hours, 1),
        "attendance_days": len(attendances),
        "estimated_monthly": round((courier.base_salary or 0) + len(delivered) * per_delivery + bonus, 2),
    }


@router.get("/payouts")
def fleet_payouts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """الرواتب والبونص لكل مندوب في الشركة — بتفصيل (HR Payroll)."""
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "payroll")
    tenant_id = _scope(user, db)
    q = db.query(Courier)
    if tenant_id is not None:
        q = q.filter(Courier.tenant_id == tenant_id)
    rows = []
    for c in q.all():
        done = db.query(CourierTask).filter(
            CourierTask.courier_id == c.id,
            CourierTask.status == CourierTaskStatus.DELIVERED,
        ).count()
        per_delivery = c.per_delivery_rate or 6.0
        fixed = c.base_salary or 0.0
        bonus = c.bonus_target or 0.0
        if bonus and c.score and c.score >= 4.7 and done > 0:
            bonus = round(bonus * 0.8, 2)
        rows.append({
            "id": c.id, "name": c.name,
            "courier_type": c.courier_type.value,
            "employment_status": c.employment_status or "ACTIVE",
            "deliveries": done,
            "fixed": round(fixed, 2),
            "per_delivery_rate": per_delivery,
            "per_delivery_earned": round(done * per_delivery, 2),
            "incentive": round(bonus, 2),
            "estimated_total": round(fixed + done * per_delivery + bonus, 2),
            "bank_iban": c.bank_iban,
        })
    return rows


@router.get("/orders")
def fleet_orders(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant_id = _scope(user, db)
    managed=json.loads(user.managed_project_ids or "[]") if user.role==UserRole.PROJECT_MANAGER else None
    ids = _courier_ids(db, tenant_id, user.id if user.role == UserRole.SUPERVISOR else None,managed)
    orders = db.query(Order).filter(Order.courier_id.in_(ids)).all() if ids else []
    couriers = {c.id: c.name for c in db.query(Courier).all()}
    merchants = {m.id: m.name for m in db.query(Merchant).all()}
    return [
        {
            "id": o.id, "customer_name": o.customer_name, "customer_address": o.customer_address,
            "merchant_name": merchants.get(o.merchant_id),
            "status": o.status.value, "delivery_method": o.delivery_method.value,
            "distance_km": o.distance_km, "total": o.total,
            "courier_name": couriers.get(o.courier_id), "courier_id": o.courier_id,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in sorted(orders, key=lambda x: x.id, reverse=True)
    ]


@router.get("/shifts")
def fleet_shifts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "attendance")
    q = db.query(Shift)
    if user.tenant_id is not None:
        q = q.filter(Shift.tenant_id == user.tenant_id)
    return [
        {
            "id": s.id, "name": s.name, "zone": s.zone or "", "fleet_id": s.fleet_id,
            "fleet": (db.get(Fleet, s.fleet_id).name if s.fleet_id else None),
            "start_time": s.start_time, "end_time": s.end_time,
            "required_couriers": s.required_couriers,
            "status": s.status.value if hasattr(s.status, "value") else s.status,
        }
        for s in q.all()
    ]


@router.post("/shifts")
def fleet_create_shift(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "attendance")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Shift name is required")
    fleet = db.query(Fleet).filter(Fleet.tenant_id == user.tenant_id).first() if user.tenant_id else None
    try:
        required_couriers = int(payload.get("required_couriers") or 0)
    except (ValueError, TypeError):
        raise HTTPException(400, "required_couriers يجب أن يكون رقماً")
    shift = Shift(
        tenant_id=user.tenant_id, fleet_id=fleet.id if fleet else None,
        name=name, zone=payload.get("zone") or "",
        start_time=payload.get("start_time") or "09:00",
        end_time=payload.get("end_time") or "17:00",
        required_couriers=required_couriers,
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return {"ok": True, "id": shift.id, "name": shift.name}


@router.post("/orders/{order_id}/reassign")
def fleet_reassign(order_id: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """إعادة تعيين طلب لمندوب معين من نطاق الشركة."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    tenant_id = _scope(user, db)
    ids = _courier_ids(db, tenant_id, user.id if user.role == UserRole.SUPERVISOR else None)
    courier_id = payload.get("courier_id")
    if courier_id and int(courier_id) not in ids:
        raise HTTPException(403, "Courier not in your fleet")
    order.courier_id = int(courier_id) if courier_id else None
    if order.courier_id:
        order.status = OrderStatus.ASSIGNED
    else:
        order.status = OrderStatus.PLACED
    db.commit()
    return {"ok": True, "order_id": order.id, "courier_id": order.courier_id}


@router.get("/attendance")
def fleet_attendance(attendance_date: date = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "attendance")
    tenant_id = _scope(user, db)
    ids = _courier_ids(db, tenant_id, user.id if user.role == UserRole.SUPERVISOR else None)
    chosen = attendance_date or date.today()
    start = datetime.combine(chosen, datetime.min.time())
    end = start + timedelta(days=1)
    records = db.query(Attendance).filter(
        Attendance.courier_id.in_(ids), Attendance.check_in >= start, Attendance.check_in < end
    ).order_by(Attendance.check_in.desc()).all() if ids else []
    couriers = {c.id: c.name for c in db.query(Courier).all()}
    rows = []
    for a in records:
        hours = None
        if a.check_in and a.check_out:
            hours = round((a.check_out - a.check_in).total_seconds() / 3600, 1)
        rows.append({
            "id": a.id,
            "name": couriers.get(a.courier_id),
            "check_in": a.check_in.isoformat() if a.check_in else None,
            "check_out": a.check_out.isoformat() if a.check_out else None,
            "hours": hours,
            "is_late": a.is_late,
            "check_in_lat": a.check_in_lat, "check_in_lng": a.check_in_lng,
            "check_out_lat": a.check_out_lat, "check_out_lng": a.check_out_lng,
        })
    return rows


@router.get("/performance")
def fleet_performance(start_date: date = None, end_date: date = None, project_id: int = None,
                      supervisor_id: int = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in TENANT_ROLES: raise HTTPException(403,"Not a fleet account")
    _require_permission(user,"performance")
    end_day=end_date or date.today(); start_day=start_date or end_day.replace(day=1)
    if start_day>end_day: raise HTTPException(400,"start_date must be before end_date")
    start=datetime.combine(start_day,datetime.min.time()); end=datetime.combine(end_day+timedelta(days=1),datetime.min.time())
    tenant_id=_scope(user,db); ids=_courier_ids(db,tenant_id,user.id if user.role==UserRole.SUPERVISOR else None)
    q=db.query(Courier).filter(Courier.id.in_(ids)) if ids else db.query(Courier).filter(False)
    if project_id: q=q.filter(Courier.primary_project_id==project_id)
    if supervisor_id: q=q.filter(Courier.supervisor_id==supervisor_id)
    rows=[]
    for c in q.order_by(Courier.name).all():
        tasks=db.query(CourierTask).filter(CourierTask.courier_id==c.id,CourierTask.offered_at>=start,CourierTask.offered_at<end).all()
        offered=len(tasks); accepted=sum(bool(t.accepted_at) for t in tasks)
        delivered=[t for t in tasks if t.status==CourierTaskStatus.DELIVERED or t.delivered_at]
        on_time=[t for t in delivered if t.accepted_at and t.delivered_at and (t.delivered_at-t.accepted_at).total_seconds()<=3600]
        acceptance=round(accepted/offered*100,1) if offered else None
        completion=round(len(delivered)/accepted*100,1) if accepted else None
        punctuality=round(len(on_time)/len(delivered)*100,1) if delivered else None
        rating=max(0,min(5,float(c.score or 0))); available=[x for x in (acceptance,completion,punctuality) if x is not None]
        score=round(((acceptance or 0)*.3+(completion or 0)*.3+(punctuality or 0)*.3+(rating/5*100)*.1)/10,1) if available else None
        project=db.get(Project,c.primary_project_id) if c.primary_project_id else None; supervisor=db.get(User,c.supervisor_id) if c.supervisor_id else None
        rows.append({"id":c.id,"name":c.name,"courier_type":c.courier_type.value,"project_id":c.primary_project_id,"project":project.name if project else "—","supervisor_id":c.supervisor_id,"supervisor":supervisor.name if supervisor else "—","online":c.is_online,"offered":offered,"accepted":accepted,"delivered":len(delivered),"on_time":len(on_time),"acceptance":acceptance,"completion":completion,"punctuality":punctuality,"rating":rating,"score":score})
    scores=[r["score"] for r in rows if r["score"] is not None]; accepts=[r["acceptance"] for r in rows if r["acceptance"] is not None]
    projects=db.query(Project).filter(Project.tenant_id==tenant_id).order_by(Project.name).all()
    supervisors=db.query(User).filter(User.tenant_id==tenant_id,User.role==UserRole.SUPERVISOR).order_by(User.name).all()
    return {"period":{"from":start_day.isoformat(),"to":end_day.isoformat()},"rows":rows,"summary":{"couriers":len(rows),"online":sum(r["online"] for r in rows),"avg_acceptance":round(sum(accepts)/len(accepts),1) if accepts else None,"avg_score":round(sum(scores)/len(scores),1) if scores else None},"filters":{"projects":[{"id":p.id,"name":p.name} for p in projects],"supervisors":[{"id":s.id,"name":s.name} for s in supervisors]}}


@router.get("/attendance/monthly")
def monthly_attendance(month: str = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in TENANT_ROLES: raise HTTPException(403,"Not allowed")
    _require_permission(user,"attendance")
    try:
        chosen=datetime.strptime(month or date.today().strftime("%Y-%m"),"%Y-%m")
    except ValueError: raise HTTPException(400,"month must be YYYY-MM")
    start=chosen; end=datetime(chosen.year+(chosen.month//12),chosen.month%12+1,1)
    ids=_courier_ids(db,user.tenant_id,user.id if user.role==UserRole.SUPERVISOR else None)
    rows=[]
    for c in db.query(Courier).filter(Courier.id.in_(ids)).order_by(Courier.name).all() if ids else []:
        records=db.query(Attendance).filter(Attendance.courier_id==c.id,Attendance.check_in>=start,Attendance.check_in<end).all()
        hours=sum((a.check_out-a.check_in).total_seconds()/3600 for a in records if a.check_out)
        rows.append({"المندوب":c.name,"أيام الحضور":len({a.check_in.date() for a in records}),"مرات التأخير":sum(bool(a.is_late) for a in records),"ساعات العمل":round(hours,1),"الحالة":c.employment_status or "ACTIVE"})
    return {"month":start.strftime("%Y-%m"),"rows":rows}


# ===== العقود (Contracts) =====

@router.get("/contracts")
def fleet_contracts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "hr")
    tenant_id = _scope(user, db)
    q = db.query(Contract)
    if tenant_id is not None:
        q = q.filter(Contract.tenant_id == tenant_id)
    return [
        {
            "id": c.id, "name": c.name, "contract_type": c.contract_type,
            "duration_months": c.duration_months, "couriers_count": c.couriers_count,
            "base_salary": c.base_salary or 0, "per_delivery_rate": c.per_delivery_rate or 0,
            "status": c.status, "fleet": (db.get(Fleet, c.fleet_id).name if c.fleet_id else None),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in q.all()
    ]


@router.post("/contracts")
def fleet_create_contract(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "hr")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Contract name is required")
    tenant_id = _scope(user, db)
    fleet = db.query(Fleet).filter(Fleet.tenant_id == user.tenant_id).first() if user.tenant_id else None
    try:
        duration_months = int(payload.get("duration_months") or 12)
        couriers_count = int(payload.get("couriers_count") or 0)
        base_salary = float(payload.get("base_salary") or 0)
        per_delivery_rate = float(payload.get("per_delivery_rate") or 6)
    except (ValueError, TypeError):
        raise HTTPException(400, "قيم رقمية غير صالحة في العقد")
    project=db.query(Project).filter(Project.tenant_id==(user.tenant_id if user.tenant_id else tenant_id),Project.name==name).first()
    if not project: project=Project(tenant_id=user.tenant_id if user.tenant_id else tenant_id,name=name,is_active=True);db.add(project);db.flush()
    contract = Contract(
        tenant_id=user.tenant_id if user.tenant_id else (tenant_id if tenant_id is not None else None),
        fleet_id=fleet.id if fleet else payload.get("fleet_id"),
        name=name,
        project_id=project.id,
        contract_type=payload.get("contract_type") or "FIXED",
        duration_months=duration_months,
        couriers_count=couriers_count,
        base_salary=base_salary,
        per_delivery_rate=per_delivery_rate,
        status=payload.get("status") or "ACTIVE",
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return {"ok": True, "id": contract.id, "name": contract.name}


@router.patch("/contracts/{cid}")
def fleet_update_contract(cid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "hr")
    contract = _tenant_record(db, Contract, cid, user)
    allowed = {"name", "contract_type", "duration_months", "couriers_count",
               "base_salary", "per_delivery_rate", "status"}
    for k, v in payload.items():
        if k in allowed:
            setattr(contract, k, v)
    db.commit()
    return {"ok": True, "id": contract.id}


# ===== التذاكر (Support Tickets) =====

@router.get("/tickets")
def fleet_tickets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "tickets")
    tenant_id = _scope(user, db)
    q = db.query(SupportTicket)
    if tenant_id is not None:
        q = q.filter(SupportTicket.tenant_id == tenant_id)
    if user.role == UserRole.SUPERVISOR:
        q = q.filter(SupportTicket.courier_id.in_(_courier_ids(db, tenant_id, user.id)))
    couriers = {c.id: c.name for c in db.query(Courier).all()}
    return [
        {
            "id": t.id, "subject": t.subject, "message": t.message, "status": t.status,
            "reply": t.reply, "courier": couriers.get(t.courier_id),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in q.order_by(SupportTicket.id.desc()).all()
    ]


@router.post("/tickets/{tid}/reply")
def fleet_reply_ticket(tid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "tickets")
    ticket = _tenant_record(db, SupportTicket, tid, user)
    if user.role == UserRole.SUPERVISOR and ticket.courier_id not in _courier_ids(db, user.tenant_id, user.id):
        raise HTTPException(404, "Ticket not found")
    reply = (payload.get("reply") or "").strip()
    if not reply:
        raise HTTPException(400, "Reply is required")
    ticket.reply = reply
    ticket.status = "REPLIED"
    db.commit()
    return {"ok": True, "id": ticket.id, "status": ticket.status}


# ===== الإعدادات وقواعد النظام (Settings) =====

@router.get("/settings")
def fleet_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "settings")
    tenant_id = _scope(user, db)
    q = db.query(AppSetting)
    if tenant_id is not None:
        q = q.filter(AppSetting.tenant_id == tenant_id)
    return {s.key: s.value for s in q.all()}


@router.post("/settings")
def fleet_save_settings(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "settings")
    tenant_id = _scope(user, db)
    for key, value in payload.items():
        setting = db.query(AppSetting).filter(
            AppSetting.tenant_id == (user.tenant_id if user.tenant_id else 0),
            AppSetting.key == key,
        ).first()
        if setting:
            setting.value = str(value)
        else:
            db.add(AppSetting(
                tenant_id=user.tenant_id if user.tenant_id else 0,
                key=key, value=str(value),
            ))
    db.commit()
    return {"ok": True}


# ===== طلب اختباري (Test Order) =====

@router.post("/test-order")
def fleet_test_order(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """ينشئ طلباً حقيقياً ويُسنده لمندوب في نطاق الشركة (تحقق من الدورة كاملة)."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant_id = _scope(user, db)
    merchant = db.query(Merchant).filter(Merchant.is_active.is_(True)).first()
    if not merchant:
        raise HTTPException(400, "No active merchant available for a test order")
    customer_name = payload.get("customer_name") or "عميل اختباري"
    from datetime import datetime
    order = Order(
        merchant_id=merchant.id,
        customer_name=customer_name,
        customer_phone=payload.get("customer_phone") or "966500000000",
        customer_lat=payload.get("lat") or merchant.lat or 24.7136,
        customer_lng=payload.get("lng") or merchant.lng or 46.6753,
        customer_address=payload.get("address") or "عنوان اختباري — الرياض",
        delivery_method=merchant.delivery_method,
        subtotal=0, delivery_fee=8.0, total=8.0,
        status=OrderStatus.PLACED,
        created_at=datetime.utcnow(),
    )
    db.add(order)
    db.flush()
    ids = _courier_ids(db, tenant_id)
    courier = None
    if ids:
        courier = db.query(Courier).filter(Courier.id.in_(ids), Courier.is_online.is_(True)).first()
        if not courier:
            courier = db.query(Courier).filter(Courier.id.in_(ids)).first()
    if courier:
        order.courier_id = courier.id
        order.status = OrderStatus.ASSIGNED
        courier.current_load = (courier.current_load or 0) + 1
        db.add(CourierTask(
            courier_id=courier.id, order_id=order.id,
            status=CourierTaskStatus.ACCEPTED,
        ))
    db.commit()
    return {
        "ok": True, "order_id": order.id, "total": order.total,
        "courier": courier.name if courier else None,
        "status": order.status.value,
    }


# ===== تصعيد / بث (Escalate / Broadcast) =====

@router.post("/orders/{order_id}/escalate")
def fleet_escalate(order_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    order.status = OrderStatus.TIMEOUT if hasattr(OrderStatus, "TIMEOUT") else OrderStatus.PLACED
    order.courier_id = None
    db.commit()
    return {"ok": True, "order_id": order.id, "status": order.status.value if hasattr(order.status, "value") else order.status}


@router.post("/orders/{order_id}/broadcast")
def fleet_broadcast(order_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if order.courier_id:
        order.courier_id = None
    order.status = OrderStatus.PLACED
    db.commit()
    return {"ok": True, "order_id": order.id, "broadcast": True}


# ===== تصدير (Export) =====

@router.get("/export/csv")
def fleet_export_csv(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """تصدير رواتب المناديب بصيغة CSV حقيقية."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "payroll")
    tenant_id = _scope(user, db)
    rows = []
    q = db.query(Courier)
    if tenant_id is not None:
        q = q.filter(Courier.tenant_id == tenant_id)
    for c in q.all():
        done = db.query(CourierTask).filter(
            CourierTask.courier_id == c.id,
            CourierTask.status == CourierTaskStatus.DELIVERED,
        ).count()
        per_delivery = c.per_delivery_rate or 6.0
        fixed = c.base_salary or 0.0
        bonus = c.bonus_target or 0.0
        if bonus and c.score and c.score >= 4.7 and done > 0:
            bonus = round(bonus * 0.8, 2)
        rows.append([
            c.name, c.phone, c.courier_type.value, c.employment_status or "ACTIVE",
            done, fixed, per_delivery, round(done * per_delivery, 2), bonus,
            round(fixed + done * per_delivery + bonus, 2), c.bank_iban or "",
        ])
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Name", "Phone", "Type", "Status", "Deliveries", "Fixed", "PerDelivery",
                     "DeliveryEarned", "Incentive", "EstimatedTotal", "IBAN"])
    writer.writerows(rows)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=fleet_payouts.csv"},
    )

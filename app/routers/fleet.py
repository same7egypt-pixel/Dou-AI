from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi import Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, text, select, func
import csv, io
import json
from datetime import date, datetime, timedelta

from ..database import get_db
from ..models.entities import (
    Attendance, AppSetting, Contract, ContractBranch, Courier, CourierTask, CourierTaskStatus, Country, CourierType, Merchant,
    Order, OrderStatus, Shift, ShiftStatus, SupportTicket, Tenant, User, UserRole, Fleet,
    Project, DailyLog, BonusPlan, LeaveRequest, SubscriptionPlan, OperationalImportBatch, AuditLog, AttendanceEvent, PayrollPeriod,
)
from .auth import get_current_user
from .shifts import _assigned_courier_ids, _parse_shift_time, _shift_json, _shift_window
from ..services.financial_calculations import calculate_payroll_preview, financial_rows, payroll_rows
from ..services.reporting import analytics_report, flat_export_rows, report_filter_options
from ..services.rider_management import create_rider_record, apply_branch_assignment
from ..services.rider_imports import confirm_rider_import, preview_rider_import, rider_template_csv
from ..services.performance_imports import confirm_performance_import, performance_template_csv, preview_performance_import

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

# العمليات الحساسة الخاصة بحسابات العاملين لا تُمنح بالصلاحيات المخصصة.
# مالك الشركة ومدير النظام فقط يستطيعان التعطيل أو الحذف.
ACCOUNT_ADMIN_ROLES = (UserRole.COMPANY, UserRole.COMPANY_ADMIN)

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


def _audit(db: Session, user: User, action: str, entity: str, entity_id: int = None):
    db.add(AuditLog(tenant_id=user.tenant_id, actor_id=user.id, actor_name=user.name or "—",
                    actor_role=user.role.value, action=action, entity=entity, entity_id=entity_id))


def _tenant_record(db: Session, model, record_id: int, user: User):
    record = db.get(model, record_id)
    if not record:
        raise HTTPException(404, f"{model.__name__} not found")
    if user.role in TENANT_ROLES and getattr(record, "tenant_id", None) != user.tenant_id:
        raise HTTPException(404, f"{model.__name__} not found")
    return record


def _report_rows(db: Session, user: User, report_type: str,
                 project_id: int = None, contract_id: int = None, branch_id: int = None, supervisor_id: int = None, doc_status: str = None,
                 date_from: date = None, date_to: date = None):
    tenant_id = _scope(user, db)
    q = db.query(Courier)
    if tenant_id is not None:
        q = q.filter(Courier.tenant_id == tenant_id)
    if user.role == UserRole.SUPERVISOR:
        q = q.filter(_supervisor_courier_scope(db, user.id))
    elif user.role == UserRole.PROJECT_MANAGER:
        q = q.filter(Courier.primary_project_id.in_(json.loads(user.managed_project_ids or "[]")))
    if contract_id:
        contract_projects = db.query(ContractBranch.project_id).filter(ContractBranch.contract_id == contract_id)
        q = q.filter(or_(Courier.contract_id == contract_id, Courier.primary_project_id.in_(contract_projects)))
    if branch_id:
        selected_branch = db.get(ContractBranch, branch_id)
        q = q.filter(or_(Courier.contract_branch_id == branch_id,
                         Courier.primary_project_id == selected_branch.project_id)) if selected_branch else q.filter(text("1=0"))
    if supervisor_id: q = q.filter(Courier.supervisor_id == supervisor_id)
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

    period_end = date_to or today
    period_start = date_from or date(period_end.year, period_end.month, 1)
    if period_start > period_end: period_start, period_end = period_end, period_start
    month_start = date(period_end.year, period_end.month, 1)
    projects = {p.id: p for p in db.query(Project).filter(
        Project.tenant_id == tenant_id if tenant_id is not None else text("1=1")
    ).all()}
    rows = []
    calculation_month = period_end.strftime("%Y-%m")
    for c in couriers:
        if project_id and c.primary_project_id != project_id:
            continue
        payroll = calculate_payroll_preview(db, c, calculation_month)
        bonus = payroll["bonus"]
        if not bonus.get("plan_id"):
            continue
        logs = db.query(DailyLog).filter(
            DailyLog.courier_id == c.id,
            DailyLog.log_date >= period_start,
            DailyLog.log_date <= period_end,
        )
        if c.primary_project_id:
            logs = logs.filter(DailyLog.project_id == c.primary_project_id)
        period_orders = sum(max(int(item.orders_count or 0), 0) for item in logs.all())
        project = projects.get(c.primary_project_id)
        rows.append({
            "السائق": c.name, "المشروع": project.name if project else c.platform or "—",
            "طلبات الفترة": period_orders, "طلبات الشهر حتى نهاية الفترة": bonus["orders"], "التارجت الشهري": bonus["target"],
            "المتبقي": bonus["remaining_orders"], "الطلبات الزائدة": bonus["over_orders"],
            "بونص التارجت": bonus["bonus_amount"], "سعر الطلب الزائد": bonus["over_target_rate"],
            "البونص المستحق": bonus["earned"],
            "الراتب الأساسي": payroll["base_salary"],
            "إجمالي الشهر التقديري حتى نهاية الفترة": payroll["net_pay"],
        })
    return rows


def _analytics_filters(city_id: int = None, contract_id: int = None, branch_id: int = None,
                       supervisor_id: int = None, rider_id: int = None, project_id: int = None,
                       employment_status: str = None, online: bool = None, search: str = None) -> dict:
    return {"city_id": city_id, "contract_id": contract_id, "branch_id": branch_id,
            "supervisor_id": supervisor_id, "rider_id": rider_id, "project_id": project_id,
            "employment_status": employment_status, "online": online, "search": search}


@router.get("/analytics/filters")
def analytics_filters(city_id: int = None, contract_id: int = None, branch_id: int = None,
                      supervisor_id: int = None, rider_id: int = None, project_id: int = None,
                      employment_status: str = None, online: bool = None, search: str = None,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "reports")
    _scope(user, db)
    filters = _analytics_filters(city_id, contract_id, branch_id, supervisor_id, rider_id, project_id, employment_status, online, search)
    return report_filter_options(db, user, filters, _supervisor_courier_scope)


@router.get("/analytics/{report_type}")
def analytics_view(report_type: str, date_from: date = None, date_to: date = None,
                   city_id: int = None, contract_id: int = None, branch_id: int = None,
                   supervisor_id: int = None, rider_id: int = None, project_id: int = None,
                   employment_status: str = None, online: bool = None, search: str = None,
                   page: int = 1, page_size: int = 50,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if report_type not in {"executive", "operations", "financial", "workforce"}:
        raise HTTPException(404, "Unknown analytics report")
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "reports")
    _scope(user, db)
    end = date_to or date.today(); start = date_from or date(end.year, end.month, 1)
    filters = _analytics_filters(city_id, contract_id, branch_id, supervisor_id, rider_id, project_id, employment_status, online, search)
    try:
        return analytics_report(db, user, report_type, filters, start, end, page, page_size, _supervisor_courier_scope, ROLE_PERMISSIONS)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@router.get("/analytics/{report_type}/export")
def analytics_export(report_type: str, date_from: date = None, date_to: date = None,
                     city_id: int = None, contract_id: int = None, branch_id: int = None,
                     supervisor_id: int = None, rider_id: int = None, project_id: int = None,
                     employment_status: str = None, online: bool = None, search: str = None,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if report_type not in {"operations", "financial", "workforce"}:
        raise HTTPException(404, "Unknown analytics report")
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "reports"); _require_permission(user, "export")
    _scope(user, db)
    end = date_to or date.today(); start = date_from or date(end.year, end.month, 1)
    filters = _analytics_filters(city_id, contract_id, branch_id, supervisor_id, rider_id, project_id, employment_status, online, search)
    try:
        report = analytics_report(db, user, report_type, filters, start, end, 1, 5000, _supervisor_courier_scope, ROLE_PERMISSIONS)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    permissions = json.loads(user.custom_permissions) if user.custom_permissions else ROLE_PERMISSIONS.get(user.role, [])
    commercial = user.role in ACCOUNT_ADMIN_ROLES
    payroll = "*" in permissions or ("payroll" in permissions and user.role != UserRole.SUPERVISOR)
    rows = flat_export_rows(report, commercial, payroll)
    output = io.StringIO(); output.write("\ufeff")
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys())); writer.writeheader(); writer.writerows(rows)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="dou-{report_type}-{start}-{end}.csv"'})


@router.get("/reports")
def fleet_reports(report_type: str = Query("documents", pattern="^(documents|bonus)$"),
                  project_id: int = None, contract_id: int = None, branch_id: int = None, supervisor_id: int = None, doc_status: str = None, date_from: date = None, date_to: date = None,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "reports")
    return _report_rows(db, user, report_type, project_id, contract_id, branch_id, supervisor_id, doc_status, date_from, date_to)


@router.get("/reports/export")
def fleet_reports_export(report_type: str = Query("documents", pattern="^(documents|bonus)$"),
                         project_id: int = None, contract_id: int = None, branch_id: int = None, supervisor_id: int = None, doc_status: str = None, date_from: date = None, date_to: date = None,
                         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user,"export")
    needed = "hr" if report_type == "documents" else "payroll"
    _require_permission(user, needed)
    rows = _report_rows(db, user, report_type, project_id, contract_id, branch_id, supervisor_id, doc_status, date_from, date_to)
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
        q = q.filter(_supervisor_courier_scope(db, supervisor_id))
    if project_ids is not None: q=q.filter(Courier.primary_project_id.in_(project_ids))
    return {c.id for c in q.all()}


def _supervisor_courier_scope(db: Session, supervisor_id: int):
    """المشرف المباشر هو المرجع؛ فرع العقد احتياطي عند غياب الربط المباشر."""
    branch_ids = db.query(ContractBranch.id).filter(
        ContractBranch.supervisor_id == supervisor_id
    )
    project_ids = db.query(ContractBranch.project_id).filter(
        ContractBranch.supervisor_id == supervisor_id,
        ContractBranch.project_id.isnot(None),
    )
    return or_(
        Courier.supervisor_id == supervisor_id,
        and_(Courier.supervisor_id.is_(None), or_(
            Courier.contract_branch_id.in_(branch_ids),
            Courier.primary_project_id.in_(project_ids),
        )),
    )


def _supervisor_can_access_courier(db: Session, supervisor_id: int, courier: Courier) -> bool:
    if courier.supervisor_id is not None:
        return courier.supervisor_id == supervisor_id
    if courier.contract_branch_id:
        branch = db.get(ContractBranch, courier.contract_branch_id)
        return bool(branch and branch.supervisor_id == supervisor_id)
    if courier.primary_project_id:
        return db.query(ContractBranch.id).filter(
            ContractBranch.supervisor_id == supervisor_id,
            ContractBranch.project_id == courier.primary_project_id,
        ).first() is not None
    return False


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
        if user.role not in ACCOUNT_ADMIN_ROLES:
            raise HTTPException(403, "Only the company admin can activate or deactivate accounts")
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
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Only the company admin can delete accounts")
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
    selected_month = today.strftime("%Y-%m")
    payroll_preview, payroll_finalized = payroll_rows(db, tenant_id, selected_month) if tenant_id is not None else ([], False)
    payroll_preview = [row for row in payroll_preview if row.get("courier_id") in ids]
    financial_preview, financial_finalized = financial_rows(db, tenant_id, selected_month) if tenant_id is not None and user.role != UserRole.SUPERVISOR else ([], False)

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
        "payroll_total": round(sum(float(row.get("net_pay") or 0) for row in payroll_preview), 2),
        "payroll_finalized": payroll_finalized,
        "client_revenue": round(sum(float(row.get("client_revenue") or 0) for row in financial_preview), 2),
        "operational_margin": round(sum(float(row.get("operational_margin") or 0) for row in financial_preview), 2),
        "financial_finalized": financial_finalized,
        "orders_total": len(orders),
        "orders_active": sum(1 for o in orders if o.status in active_st),
        "orders_unassigned": unassigned,
        "deliveries_done": len(delivered),
        # لا نستخدم قيمة طلب العميل النهائية كإيراد عقد؛ الإيراد التجاري يأتي من سعر عقد العميل × الطلبات المؤهلة.
        "revenue_total": round(sum(float(row.get("client_revenue") or 0) for row in financial_preview), 2),
        "legacy_order_value": round(sum(o.total for o in orders), 2),
        "avg_acceptance": round(sum(c.acceptance_rate for c in couriers) / len(couriers), 1) if couriers else 0,
        "avg_score": round(sum(c.score for c in couriers) / len(couriers), 2) if couriers else 0,
        "on_time_rate": round(sum(c.on_time_rate for c in couriers) / len(couriers), 1) if couriers else 0,
        "company_couriers": sum(1 for c in couriers if c.courier_type.value == "COMPANY"),
        "freelance_couriers": sum(1 for c in couriers if c.courier_type.value == "FREELANCER"),
        "shifts_active": (sum(1 for c in couriers if c.shift_active)
                          if user.role in (UserRole.SUPERVISOR, UserRole.PROJECT_MANAGER)
                          else (db.query(Shift).filter(Shift.tenant_id == user.tenant_id, Shift.status == ShiftStatus.ACTIVE).count()
                                if user.tenant_id else db.query(Shift).count())),
    }


@router.get("/needs-attention")
def fleet_needs_attention(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """موجز إجراءات تشغيلية من مصادر الخلفية المعتمدة، لا ينشئ أي حدث عند القراءة."""
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "dashboard")
    tenant_id = _scope(user, db)
    managed = json.loads(user.managed_project_ids or "[]") if user.role == UserRole.PROJECT_MANAGER else None
    ids = _courier_ids(db, tenant_id, user.id if user.role == UserRole.SUPERVISOR else None, managed)
    today = date.today(); month = today.strftime("%Y-%m"); expiry_limit = today + timedelta(days=30)
    if not ids:
        return {"month": month, "items": [], "total": 0}
    courier_rows = db.query(Courier).filter(Courier.id.in_(ids)).all()
    expired_or_soon = [c for c in courier_rows if any(value and value <= expiry_limit for value in (
        c.iqama_expiry, c.license_expiry, c.vehicle_license_expiry, c.passport_expiry,
        c.insurance_expiry, c.inspection_expiry, c.work_permit_expiry,
    )) or not c.documents_valid]
    unassigned = [c for c in courier_rows if not c.supervisor_id or not c.contract_branch_id]
    events = db.query(AttendanceEvent).filter(
        AttendanceEvent.tenant_id == tenant_id, AttendanceEvent.courier_id.in_(ids), AttendanceEvent.event_date == today,
    ).all()
    items = []
    def add(code, title, count, route, severity):
        if count:
            items.append({"code": code, "title": title, "count": count, "route": route, "severity": severity})
    add("ABSENT", "مندوبون غائبون بعد تسوية الحضور", sum(event.event_type == "ABSENCE" for event in events), "attendance", "high")
    add("LATE", "مندوبون متأخرون اليوم", sum(event.event_type == "LATE" for event in events), "attendance", "medium")
    add("UNASSIGNED", "مناديب بلا مشرف أو فرع تشغيل", len(unassigned), "couriers", "high")
    add("DOCUMENTS", "مستندات منتهية أو قريبة الانتهاء", len(expired_or_soon), "couriers", "medium")
    pending_events = db.query(AttendanceEvent).filter(
        AttendanceEvent.tenant_id == tenant_id, AttendanceEvent.courier_id.in_(ids), AttendanceEvent.status == "PENDING_APPROVAL",
    ).count()
    add("DEDUCTION_APPROVALS", "خصومات حضور بانتظار الاعتماد", pending_events, "attendance-events", "medium")
    if user.role != UserRole.SUPERVISOR:
        failed_imports = db.query(OperationalImportBatch).filter(
            OperationalImportBatch.tenant_id == tenant_id, OperationalImportBatch.status == "PREVIEW", OperationalImportBatch.invalid_rows > 0,
        ).count()
        add("IMPORT_ERRORS", "دفعات استيراد تتطلب تصحيحاً", failed_imports, "imports", "medium")
        period = db.query(PayrollPeriod).filter(PayrollPeriod.tenant_id == tenant_id, PayrollPeriod.month == month).first()
        add("PAYROLL_REVIEW", "رواتب الشهر في المعاينة ولم تُقفل", 1 if not period or period.status != "FINALIZED" else 0, "payroll", "low")
    return {"month": month, "items": items, "total": sum(item["count"] for item in items)}


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
        q = q.filter(_supervisor_courier_scope(db, user.id))
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
            "city_id": c.city_id,
            "work_city": c.work_city,
            "contract_id": c.contract_id,
            "contract": (db.get(Contract, c.contract_id).name if c.contract_id else None),
            "contract_branch_id": c.contract_branch_id,
            "branch": (db.get(ContractBranch, c.contract_branch_id).city if c.contract_branch_id else None),
            "today_orders": sum(x.orders_count or 0 for x in db.query(DailyLog).filter(DailyLog.courier_id == c.id, DailyLog.log_date == today).all()),
            "month_orders": sum(x.orders_count or 0 for x in db.query(DailyLog).filter(DailyLog.courier_id == c.id, DailyLog.log_date >= month_start, DailyLog.log_date <= today).all()),
            "fleet": (db.get(Fleet, c.fleet_id).name if c.fleet_id else None),
            "supervisor_id": c.supervisor_id,
            "supervisor": (db.get(User, c.supervisor_id).name if c.supervisor_id else None),
            "primary_project_id": c.primary_project_id,
            "project": (db.get(Project, c.primary_project_id).name if c.primary_project_id else c.platform),
            "account_active": (db.query(User).filter(User.courier_id == c.id, User.role == UserRole.COURIER).first().is_active
                               if db.query(User).filter(User.courier_id == c.id, User.role == UserRole.COURIER).first() else False),
        }
        for c in couriers
    ]


@router.get("/couriers/page")
def paged_couriers(search: str = None, city_id: int = None, branch_id: int = None, supervisor_id: int = None,
                   project_id: int = None, employment_status: str = None, online: bool = None,
                   documents_valid: bool = None, page: int = 1, page_size: int = 50,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """قائمة تشغيل كبيرة مع تصفية SQL وصفحات؛ لا تستبدل المسار القديم المتوافق."""
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "drivers")
    tenant_id = _scope(user, db)
    q = db.query(Courier)
    if tenant_id is not None:
        q = q.filter(Courier.tenant_id == tenant_id)
    if user.role == UserRole.SUPERVISOR:
        q = q.filter(_supervisor_courier_scope(db, user.id))
    elif user.role == UserRole.PROJECT_MANAGER:
        q = q.filter(Courier.primary_project_id.in_(json.loads(user.managed_project_ids or "[]")))
    if search:
        term = "%" + search.strip() + "%"
        q = q.filter(or_(Courier.name.ilike(term), Courier.phone.ilike(term)))
    if city_id: q = q.filter(Courier.city_id == city_id)
    if branch_id: q = q.filter(Courier.contract_branch_id == branch_id)
    if supervisor_id: q = q.filter(Courier.supervisor_id == supervisor_id)
    if project_id: q = q.filter(Courier.primary_project_id == project_id)
    if employment_status: q = q.filter(Courier.employment_status == employment_status.upper())
    if online is not None: q = q.filter(Courier.is_online.is_(online))
    if documents_valid is not None: q = q.filter(Courier.documents_valid.is_(documents_valid))
    total = q.count(); page = max(1, page); page_size = min(max(1, page_size), 200)
    rows = q.order_by(Courier.name, Courier.id).offset((page - 1) * page_size).limit(page_size).all()
    branch_map = {row.id: row for row in db.query(ContractBranch).filter(ContractBranch.id.in_([c.contract_branch_id for c in rows if c.contract_branch_id])).all()}
    supervisor_map = {row.id: row.name for row in db.query(User).filter(User.id.in_([c.supervisor_id for c in rows if c.supervisor_id])).all()}
    project_map = {row.id: row.name for row in db.query(Project).filter(Project.id.in_([c.primary_project_id for c in rows if c.primary_project_id])).all()}
    return {"total": total, "page": page, "page_size": page_size, "rows": [{
        "id": c.id, "name": c.name, "phone": c.phone, "employment_status": c.employment_status or "ACTIVE",
        "is_online": bool(c.is_online), "documents_valid": bool(c.documents_valid), "city_id": c.city_id,
        "work_city": c.work_city, "contract_branch_id": c.contract_branch_id,
        "branch": branch_map.get(c.contract_branch_id).city if c.contract_branch_id in branch_map else None,
        "supervisor_id": c.supervisor_id, "supervisor": supervisor_map.get(c.supervisor_id),
        "project_id": c.primary_project_id, "project": project_map.get(c.primary_project_id),
    } for c in rows]}


@router.get("/imports/riders/template")
def rider_import_template(user: User = Depends(get_current_user)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Company rider-import access required")
    _require_permission(user, "drivers")
    return StreamingResponse(iter([rider_template_csv()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=rider-import-template.csv"})


@router.post("/imports/riders/preview")
def preview_riders_import(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Company rider-import access required")
    _require_permission(user, "drivers")
    try:
        result = preview_rider_import(db, user, str(payload.get("csv_text") or ""), payload.get("file_name"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _audit(db, user, f"عاين استيراد مندوبي الدفعة #{result['id']}", "rider_import", result["id"])
    db.commit()
    return result


@router.post("/imports/riders/{batch_id}/confirm")
def confirm_riders_import(batch_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Company admin required to confirm rider import")
    batch = db.get(OperationalImportBatch, batch_id)
    if not batch or batch.tenant_id != user.tenant_id or batch.import_type != "RIDERS":
        raise HTTPException(404, "Rider import batch not found")
    try:
        result = confirm_rider_import(db, user, batch)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _audit(db, user, f"أكد استيراد {result.get('result', {}).get('imported', 0)} مندوب", "rider_import", batch.id)
    db.commit()
    return result


@router.get("/imports/performance/template")
def performance_import_template(user: User = Depends(get_current_user)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Company performance-import access required")
    _require_permission(user, "performance")
    return StreamingResponse(iter([performance_template_csv()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=performance-import-template.csv"})


@router.post("/imports/performance/preview")
def preview_performance_file(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Company performance-import access required")
    _require_permission(user, "performance")
    try:
        result = preview_performance_import(db, user, str(payload.get("csv_text") or ""), payload.get("file_name"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _audit(db, user, f"عاين استيراد أداء الدفعة #{result['id']}", "performance_import", result["id"])
    db.commit()
    return result


@router.post("/imports/performance/{batch_id}/confirm")
def confirm_performance_file(batch_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Company admin required to confirm performance import")
    batch = db.get(OperationalImportBatch, batch_id)
    if not batch or batch.tenant_id != user.tenant_id or batch.import_type != "PERFORMANCE":
        raise HTTPException(404, "Performance import batch not found")
    try:
        result = confirm_performance_import(db, user, batch)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _audit(db, user, f"أكد استيراد أداء: {result.get('result', {}).get('imported', 0)} جديد و{result.get('result', {}).get('updated', 0)} محدث", "performance_import", batch.id)
    db.commit()
    return result


@router.post("/couriers")
def add_courier(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """إضافة مندوب وحساب دخوله عبر خدمة التعيين المشتركة مع الاستيراد الجماعي."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "drivers")
    try:
        courier, _account = create_rider_record(db, user, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit(); db.refresh(courier)
    return {"ok": True, "id": courier.id, "login_phone": courier.phone, "password": payload.get("password"),
            "supervisor": db.get(User, courier.supervisor_id).name if courier.supervisor_id else None,
            "project": db.get(Project, courier.primary_project_id).name if courier.primary_project_id else None}


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
    if "employment_status" in payload and user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Only the company admin can activate or deactivate couriers")
    for k, v in payload.items():
        if k in allowed:
            setattr(courier, k, v)
    if "employment_status" in payload:
        account = db.query(User).filter(User.courier_id == courier.id, User.role == UserRole.COURIER).first()
        if account:
            account.is_active = payload["employment_status"] == "ACTIVE"
            account.token_version = (account.token_version or 0) + 1
    db.commit()
    return {"ok": True}


@router.post("/couriers/bulk")
def bulk_update_couriers(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """عملية جماعية ذرية؛ تعيين المشرف يتم عبر فرع تشغيلي يملكه المشرف."""
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Company admin required for bulk rider operations")
    raw_ids = payload.get("courier_ids") or []
    try:
        courier_ids = sorted({int(value) for value in raw_ids})
    except (TypeError, ValueError):
        raise HTTPException(400, "معرفات المندوبين غير صالحة")
    if not courier_ids or len(courier_ids) > 1000:
        raise HTTPException(400, "اختر من 1 إلى 1000 مندوب للعملية الواحدة")
    action = str(payload.get("action") or "").upper()
    couriers = db.query(Courier).filter(Courier.tenant_id == user.tenant_id, Courier.id.in_(courier_ids)).order_by(Courier.id).all()
    if len(couriers) != len(courier_ids):
        raise HTTPException(400, "تتضمن العملية مندوباً غير تابع للشركة")
    changed = []
    try:
        if action == "ASSIGN_BRANCH":
            branch_id = int(payload.get("contract_branch_id") or 0)
            branch = db.get(ContractBranch, branch_id)
            if not branch or branch.tenant_id != user.tenant_id:
                raise ValueError("فرع التشغيل غير صالح")
            assignment_payload = {"contract_id": branch.contract_id, "contract_branch_id": branch.id}
            # Validate every rider before applying any update.
            for courier in couriers:
                apply_branch_assignment(db, courier, assignment_payload)
                changed.append(courier.id)
        elif action in {"ACTIVATE", "SUSPEND"}:
            status = "ACTIVE" if action == "ACTIVATE" else "SUSPENDED"
            for courier in couriers:
                courier.employment_status = status
                if status != "ACTIVE":
                    courier.is_online = False; courier.shift_active = False
                account = db.query(User).filter(User.courier_id == courier.id, User.role == UserRole.COURIER).first()
                if account:
                    account.is_active = status == "ACTIVE"
                    account.token_version = (account.token_version or 0) + 1
                changed.append(courier.id)
        else:
            raise ValueError("إجراء جماعي غير مدعوم")
        _audit(db, user, f"عملية جماعية {action} على {len(changed)} مندوب", "courier_bulk_operation", None)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc))
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "action": action, "updated": len(changed), "courier_ids": changed, "transaction": "ALL_OR_NOTHING"}


@router.get("/couriers/export")
def export_couriers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Company export access required")
    _require_permission(user, "export")
    rows = fleet_couriers(user, db)
    output = io.StringIO(); output.write("\\ufeff")
    fields = ["id", "name", "phone", "work_city", "branch", "contract", "project", "supervisor", "employment_status", "today_orders", "month_orders"]
    writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field) for field in fields})
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=couriers-export.csv"})


@router.delete("/couriers/{cid}")
def delete_courier(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """حذف سجل أُنشئ بالخطأ فقط؛ السجلات ذات التاريخ التشغيلي تُعطّل للحفاظ على التقارير."""
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Only the company admin can delete couriers")
    courier = _tenant_record(db, Courier, cid, user)
    blockers = []
    for table in Courier.__table__.metadata.sorted_tables:
        if table.name in ("couriers", "users"):
            continue
        for column in table.columns:
            if any(fk.target_fullname == "couriers.id" for fk in column.foreign_keys):
                count = db.execute(select(func.count()).select_from(table).where(column == cid)).scalar() or 0
                if count:
                    blockers.append(table.name)
                break
    if blockers:
        raise HTTPException(409, "لا يمكن حذف مندوب له سجل تشغيلي؛ اجعله غير نشط للحفاظ على التقارير")
    db.query(User).filter(User.courier_id == cid, User.role == UserRole.COURIER).delete(synchronize_session=False)
    db.delete(courier)
    db.commit()
    return {"ok": True}


@router.get("/couriers/{cid}")
def courier_profile(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """ملف مندوب كامل: بيانات + مهام + حضور + أرباح (HR)."""
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "drivers")
    courier = _tenant_record(db, Courier, cid, user)
    if user.role == UserRole.SUPERVISOR and not _supervisor_can_access_courier(db, user.id, courier):
        raise HTTPException(404, "Courier not found")
    if user.role==UserRole.PROJECT_MANAGER and courier.primary_project_id not in json.loads(user.managed_project_ids or "[]"):
        raise HTTPException(404,"Courier not found")
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
    payroll = calculate_payroll_preview(db, courier, today.strftime("%Y-%m"))
    per_delivery = payroll["per_delivery_rate"]
    bonus = payroll["bonus"]["earned"]
    return {
        "id": courier.id, "name": courier.name, "phone": courier.phone,
        "courier_type": courier.courier_type.value, "country": courier.country.value,
        "is_online": courier.is_online, "is_available": courier.is_available,
        "current_load": courier.current_load, "acceptance_rate": courier.acceptance_rate,
        "on_time_rate": courier.on_time_rate, "completion_rate": courier.completion_rate,
        "score": courier.score, "documents_valid": courier.documents_valid,
        "shift_active": courier.shift_active, "lat": courier.lat, "lng": courier.lng,
        "base_salary": payroll["base_salary"], "per_delivery_rate": per_delivery,
        "bonus_target": payroll["bonus"]["target"], "bonus_earned": bonus,
        "bonus_source": payroll["bonus"]["source"], "bonus_plan_id": payroll["bonus"]["plan_id"],
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
        "zone": courier.zone, "city_id": courier.city_id, "work_city": courier.work_city, "shift_preference": courier.shift_preference,
        "primary_project_id": courier.primary_project_id, "supervisor_id": courier.supervisor_id,
        "contract_id": courier.contract_id, "contract_branch_id": courier.contract_branch_id,
        "nationality": courier.nationality,
        "today_orders": today_orders, "month_orders": month_orders,
        "deliveries_done": len(delivered),
        "deliveries_total": len(tasks),
        "hours_worked": round(hours, 1),
        "attendance_days": len(attendances),
        "estimated_monthly": payroll["net_pay"],
    }


@router.get("/payouts")
def fleet_payouts(month: str = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """عرض الرواتب من خدمة الحساب الموحدة؛ لا ينشئ أي تسوية عند القراءة."""
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "payroll")
    tenant_id = _scope(user, db)
    selected_month = month or date.today().strftime("%Y-%m")
    if tenant_id is None:
        return []
    try:
        calculated, finalized = payroll_rows(db, tenant_id, selected_month)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    couriers = {courier.id: courier for courier in db.query(Courier).filter(Courier.tenant_id == tenant_id).all()}
    rows = []
    for row in calculated:
        courier = couriers.get(row["courier_id"])
        if not courier:
            continue
        bonus = row.get("bonus") or {}
        orders = int(row.get("eligible_orders", bonus.get("orders", 0)) or 0)
        rows.append({
            "id": courier.id, "name": courier.name, "courier_type": courier.courier_type.value,
            "employment_status": courier.employment_status or "ACTIVE", "deliveries": orders,
            "fixed": round(float(row["base_salary"] or 0), 2),
            "per_delivery_rate": round(float(row.get("per_delivery_rate", 0) or 0), 2),
            "per_delivery_earned": round(float(row["delivery_pay"] or 0), 2),
            "incentive": round(float(bonus.get("earned", row.get("bonus_pay", 0)) or 0), 2),
            "deductions": round(float(row["deductions"] or 0), 2),
            "estimated_total": round(float(row["net_pay"] or 0), 2),
            "bank_iban": courier.bank_iban, "finalized": finalized,
        })
    return rows


@router.get("/orders")
def fleet_orders(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "reports")
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
    if user.role not in TENANT_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "attendance")
    q = db.query(Shift)
    if user.tenant_id is not None:
        q = q.filter(Shift.tenant_id == user.tenant_id)
    allowed_ids = None
    if user.role == UserRole.SUPERVISOR:
        allowed_ids = _courier_ids(db, user.tenant_id, user.id)
    elif user.role == UserRole.PROJECT_MANAGER:
        managed = json.loads(user.managed_project_ids or "[]")
        allowed_ids = _courier_ids(db, user.tenant_id, project_ids=managed)
    now = datetime.utcnow()
    rows = []
    for shift in q.order_by(Shift.id.desc()).all():
        assigned = _assigned_courier_ids(shift)
        if allowed_ids is not None and not (assigned & allowed_ids):
            continue
        row = _shift_json(db, shift, now)
        row["fleet"] = db.get(Fleet, shift.fleet_id).name if shift.fleet_id and db.get(Fleet, shift.fleet_id) else None
        row["assigned_count"] = len(assigned)
        rows.append(row)
    return rows


@router.post("/shifts")
def fleet_create_shift(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    _require_permission(user, "attendance")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Shift name is required")
    start_time = str(payload.get("start_time") or "").strip()
    end_time = str(payload.get("end_time") or "").strip()
    start = _parse_shift_time(start_time); end = _parse_shift_time(end_time)
    if start == end:
        raise HTTPException(400, "وقت الانتهاء يجب أن يختلف عن وقت البداية")
    try:
        required_couriers = int(payload.get("required_couriers") or 0)
        courier_ids = {int(x) for x in (payload.get("courier_ids") or [])}
    except (ValueError, TypeError):
        raise HTTPException(400, "بيانات الوردية غير صالحة")
    if required_couriers <= 0:
        raise HTTPException(400, "أدخل عدد المناديب المطلوب")
    if len(courier_ids) > required_couriers:
        raise HTTPException(400, "عدد المناديب المسندين لا يمكن أن يتجاوز السعة المطلوبة")
    valid_ids = _courier_ids(db, user.tenant_id)
    if not courier_ids.issubset(valid_ids):
        raise HTTPException(400, "يوجد مندوب لا يتبع الشركة")
    fleet = db.query(Fleet).filter(Fleet.tenant_id == user.tenant_id).first() if user.tenant_id else None
    shift = Shift(
        tenant_id=user.tenant_id, fleet_id=fleet.id if fleet else None,
        name=name, zone=(payload.get("zone") or "").strip(), start_time=start_time,
        end_time=end_time, required_couriers=required_couriers,
        courier_ids=json.dumps(sorted(courier_ids)),
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    row = _shift_json(db, shift, datetime.utcnow())
    return {"ok": True, **row}


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
    couriers = {c.id: c.name for c in db.query(Courier).filter(Courier.id.in_(ids)).all()} if ids else {}
    rows = []
    for attendance in records:
        shift = db.get(Shift, attendance.shift_id) if attendance.shift_id else None
        scheduled_start = scheduled_end = None
        scheduled_hours = None
        late_minutes = early_leave_minutes = 0
        if shift:
            scheduled_start, scheduled_end, _ = _shift_window(shift, attendance.check_in or start)
            scheduled_hours = round((scheduled_end - scheduled_start).total_seconds() / 3600, 1)
            late_minutes = max(0, int(((attendance.check_in or scheduled_start) - scheduled_start).total_seconds() // 60))
            if attendance.check_out:
                early_leave_minutes = max(0, int((scheduled_end - attendance.check_out).total_seconds() // 60))
        hours = round((attendance.check_out - attendance.check_in).total_seconds() / 3600, 1) if attendance.check_in and attendance.check_out else None
        status = "LATE" if late_minutes else "PRESENT"
        if not attendance.check_out:
            status = "IN_PROGRESS"
        elif early_leave_minutes:
            status = "EARLY_LEAVE"
        rows.append({
            "id": attendance.id, "name": couriers.get(attendance.courier_id), "shift_id": attendance.shift_id,
            "shift": shift.name if shift else None,
            "check_in": attendance.check_in.isoformat() if attendance.check_in else None,
            "check_out": attendance.check_out.isoformat() if attendance.check_out else None,
            "scheduled_start": scheduled_start.isoformat() if scheduled_start else None,
            "scheduled_end": scheduled_end.isoformat() if scheduled_end else None,
            "scheduled_hours": scheduled_hours, "hours": hours, "status": status,
            "late_minutes": late_minutes, "early_leave_minutes": early_leave_minutes, "is_late": late_minutes > 0,
            "check_in_lat": attendance.check_in_lat, "check_in_lng": attendance.check_in_lng,
            "check_out_lat": attendance.check_out_lat, "check_out_lng": attendance.check_out_lng,
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
        late_minutes=0; early_leave_minutes=0
        for attendance in records:
            shift=db.get(Shift,attendance.shift_id) if attendance.shift_id else None
            if not shift: continue
            scheduled_start,scheduled_end,_=_shift_window(shift,attendance.check_in)
            late_minutes+=max(0,int((attendance.check_in-scheduled_start).total_seconds()//60))
            if attendance.check_out: early_leave_minutes+=max(0,int((scheduled_end-attendance.check_out).total_seconds()//60))
        rows.append({"المندوب":c.name,"أيام الحضور":len({a.check_in.date() for a in records}),"مرات التأخير":sum(bool(a.is_late) for a in records),"دقائق التأخير":late_minutes,"دقائق الانصراف المبكر":early_leave_minutes,"ساعات العمل":round(hours,1),"الحالة":c.employment_status or "ACTIVE"})
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

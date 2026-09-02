"""وحدات HR: المشرفون + المناديب + المستندات + السجل اليومي + الإجازات + البونص.
الأدمن يدير كل شيء، والمشرف يدير مناديب مجموعته فقط، والمندوب يخدم نفسه."""

from datetime import datetime, date, timedelta
import csv
import io
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text, or_, and_, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import (
    Attendance,
    AuditLog,
    BonusPlan,
    BroadcastMessage,
    Contract,
    ContractBranch,
    ContractBranchSupervisor,
    Courier,
    CourierRating,
    DailyLog,
    GeoCity,
    LeaveRequest,
    PerformanceNote,
    Project,
    Tenant,
    TenantOperatingCity,
    User,
    UserRole,
    SupervisorAssignmentRequest,
    ProjectTransfer,
    PayrollAdjustment,
    EmployeeRequest,
    CourierDocumentSubmission,
    AttendanceDeductionPolicy,
    AttendanceEvent,
    PayrollPeriod,
    PayrollSnapshot,
)
from .auth import get_current_user, hash_password
from ..services.operating_structure import (
    ensure_tenant_operating_city,
    find_or_create_city,
    operating_city_counts,
    require_active_tenant_city,
    resolve_active_tenant_city_by_name,
)
from ..services.financial_calculations import (
    bonus_plan_for_courier,
    calculate_target_bonus as _calculate_target_bonus,
    calculate_courier_bonus,
    calculate_payroll_preview,
    financial_rows,
    finalize_payroll_period,
    payroll_rows,
)
from ..services.attendance_policy import (
    CALCULATION_METHODS,
    EVENT_TYPES,
    decide_attendance_event,
    finalized_period,
    reconcile_absences_for_date,
)
from ..services.workforce_scope import supervisor_courier_scope

router = APIRouter(prefix="/hr", tags=["hr"])

COMPANY_ROLES = (
    UserRole.COMPANY,
    UserRole.COMPANY_ADMIN,
    UserRole.HR,
    UserRole.DOU_OPS,
    UserRole.DOU_ADMIN,
)
ACCOUNT_ADMIN_ROLES = (UserRole.COMPANY, UserRole.COMPANY_ADMIN)
LEAVE_STATUSES = ("PENDING", "SUPERVISOR_APPROVED", "APPROVED", "REJECTED")
CITY_NAME_ALIASES = {
    "الرياض": "Riyadh",
    "جدة": "Jeddah",
    "الدمام": "Dammam",
    "مكة": "Mecca",
    "مكة المكرمة": "Mecca",
    "المدينة": "Medina",
    "المدينة المنورة": "Medina",
    "الخبر": "Khobar",
}


def _supervisor_courier_scope(db: Session, supervisor_id: int):
    return supervisor_courier_scope(db, supervisor_id)


def calculate_target_bonus(
    orders: int, target: int, target_bonus: float, over_target_rate: float
) -> dict:
    """واجهة متوافقة لمسارات HR؛ المصدر المرجعي هو الخدمة المالية."""
    return _calculate_target_bonus(orders, target, target_bonus, over_target_rate)


def _daily_report_data(
    db: Session,
    user: User,
    selected: date,
    project_id=None,
    contract_id=None,
    branch_id=None,
    nationality=None,
    zone=None,
    supervisor_id=None,
    log_status=None,
    target_status=None,
    attendance_status=None,
    employment_status=None,
    courier_name=None,
    date_from=None,
    date_to=None,
):
    q = db.query(Courier).filter(Courier.tenant_id == user.tenant_id)
    if user.role == UserRole.SUPERVISOR:
        q = q.filter(_supervisor_courier_scope(db, user.id))
    elif user.role == UserRole.PROJECT_MANAGER:
        q = q.filter(
            Courier.primary_project_id.in_(json.loads(user.managed_project_ids or "[]"))
        )
    elif supervisor_id:
        q = q.filter(Courier.supervisor_id == int(supervisor_id))
    if contract_id:
        contract_projects = db.query(ContractBranch.project_id).filter(
            ContractBranch.contract_id == int(contract_id)
        )
        q = q.filter(
            or_(
                Courier.contract_id == int(contract_id),
                Courier.primary_project_id.in_(contract_projects),
            )
        )
    if branch_id:
        selected_branch = db.get(ContractBranch, int(branch_id))
        q = (
            q.filter(
                or_(
                    Courier.contract_branch_id == int(branch_id),
                    Courier.primary_project_id == selected_branch.project_id,
                )
            )
            if selected_branch
            else q.filter(text("1=0"))
        )
    if project_id:
        q = q.filter(Courier.primary_project_id == int(project_id))
    if nationality:
        q = q.filter(Courier.nationality == nationality)
    if zone:
        q = q.filter(or_(Courier.work_city == zone, Courier.zone == zone))
    if employment_status:
        q = q.filter(Courier.employment_status == employment_status)
    if courier_name:
        q = q.filter(Courier.name.ilike(f"%{courier_name}%"))
    period_start = date_from or selected
    period_end = date_to or selected
    if period_start > period_end:
        period_start, period_end = period_end, period_start
    month_start = date(period_end.year, period_end.month, 1)
    range_start = datetime.combine(period_start, datetime.min.time())
    range_end = datetime.combine(period_end + timedelta(days=1), datetime.min.time())
    projects = {
        p.id: p.name
        for p in db.query(Project).filter(Project.tenant_id == user.tenant_id).all()
    }
    supervisors = {
        u.id: u.name
        for u in db.query(User).filter(User.tenant_id == user.tenant_id).all()
    }
    rows = []
    for c in q.order_by(Courier.name).all():
        logs = (
            db.query(DailyLog)
            .filter(
                DailyLog.courier_id == c.id,
                DailyLog.log_date >= month_start,
                DailyLog.log_date <= period_end,
            )
            .all()
        )
        period_logs = [x for x in logs if period_start <= x.log_date <= period_end]
        pid = int(project_id) if project_id else c.primary_project_id
        if pid:
            period_logs = [x for x in period_logs if x.project_id == pid]
            project_logs = [x for x in logs if x.project_id == pid]
        else:
            project_logs = logs
        period_orders = sum(x.orders_count or 0 for x in period_logs)
        month_orders = sum(x.orders_count or 0 for x in project_logs)
        if log_status == "LOGGED" and not period_logs:
            continue
        if log_status == "NOT_LOGGED" and period_logs:
            continue
        attendances = (
            db.query(Attendance)
            .filter(
                Attendance.courier_id == c.id,
                Attendance.check_in >= range_start,
                Attendance.check_in < range_end,
            )
            .all()
        )
        att_status = (
            "حاضر" if attendances else ("إجازة" if c.is_on_leave else "لم يسجل حضور")
        )
        if attendance_status == "PRESENT" and not attendances:
            continue
        if attendance_status == "ABSENT" and (attendances or c.is_on_leave):
            continue
        if attendance_status == "LEAVE" and not c.is_on_leave:
            continue
        # خطط البونص تُختار حصراً من المحرك الموحد: خطة المندوب أولاً ثم خطة الفرع الفعالة.
        plan = (
            bonus_plan_for_courier(db, c, period_end)
            if pid and pid == c.primary_project_id
            else None
        )
        target = plan.target_orders if plan else 0
        result = calculate_target_bonus(
            month_orders,
            target,
            plan.bonus_amount if plan else 0,
            plan.over_target_rate if plan else 0,
        )
        state = (
            "OVER"
            if target and result["achieved"]
            else "PENDING"
            if target
            else "NO_TARGET"
        )
        if target_status and target_status != state:
            continue
        hours = round(
            sum(
                (a.check_out - a.check_in).total_seconds() / 3600
                for a in attendances
                if a.check_out
            ),
            1,
        )
        rows.append(
            {
                "المندوب": c.name,
                "الجنسية": c.nationality or "—",
                "المدينة": c.work_city or c.zone or "—",
                "المشرف": supervisors.get(c.supervisor_id, "—"),
                "المشروع": projects.get(pid, c.platform or "—"),
                "طلبات الفترة": period_orders,
                "أيام التسجيل": len({x.log_date for x in period_logs}),
                "طلبات الشهر": month_orders,
                "التارجت": target or "—",
                "حالة التارجت": (
                    f"زائد {result['over_orders']}"
                    if state == "OVER"
                    else f"متبقي {result['remaining_orders']}"
                    if state == "PENDING"
                    else "بدون تارجت"
                ),
                "البونص المستحق": result["earned"],
                "حالة الحضور": att_status,
                "أيام الحضور": len({a.check_in.date() for a in attendances}),
                "ساعات العمل": hours,
                "ملاحظات الفترة": " | ".join(x.notes for x in period_logs if x.notes)
                or "—",
                "_target_state": state,
            }
        )
    total_orders = sum(r["طلبات الفترة"] for r in rows)
    return {
        "date_from": period_start.isoformat(),
        "date_to": period_end.isoformat(),
        "rows": rows,
        "summary": {
            "couriers": len(rows),
            "logged": sum(r["أيام التسجيل"] > 0 for r in rows),
            "not_logged": sum(r["أيام التسجيل"] == 0 for r in rows),
            "orders": total_orders,
            "average": round(total_orders / len(rows), 1) if rows else 0,
            "top": max(rows, key=lambda r: r["طلبات الفترة"])["المندوب"]
            if rows
            else "—",
        },
    }


@router.get("/daily-report")
def daily_report(
    report_date: date = None,
    project_id: int = None,
    contract_id: int = None,
    branch_id: int = None,
    nationality: str = None,
    zone: str = None,
    supervisor_id: int = None,
    log_status: str = None,
    target_status: str = None,
    attendance_status: str = None,
    employment_status: str = None,
    courier_name: str = None,
    date_from: date = None,
    date_to: date = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in COMPANY_ROLES + (
        UserRole.OPERATIONS,
        UserRole.SUPERVISOR,
        UserRole.PROJECT_MANAGER,
    ):
        raise HTTPException(403, "Not allowed")
    return _daily_report_data(
        db,
        user,
        report_date or date.today(),
        project_id,
        contract_id,
        branch_id,
        nationality,
        zone,
        supervisor_id,
        log_status,
        target_status,
        attendance_status,
        employment_status,
        courier_name,
        date_from,
        date_to,
    )


@router.get("/daily-report/export")
def daily_report_export(
    report_date: date = None,
    project_id: int = None,
    contract_id: int = None,
    branch_id: int = None,
    nationality: str = None,
    zone: str = None,
    supervisor_id: int = None,
    log_status: str = None,
    target_status: str = None,
    attendance_status: str = None,
    employment_status: str = None,
    courier_name: str = None,
    date_from: date = None,
    date_to: date = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in COMPANY_ROLES + (
        UserRole.OPERATIONS,
        UserRole.SUPERVISOR,
        UserRole.PROJECT_MANAGER,
    ):
        raise HTTPException(403, "Not allowed")
    chosen = report_date or date.today()
    data = _daily_report_data(
        db,
        user,
        chosen,
        project_id,
        contract_id,
        branch_id,
        nationality,
        zone,
        supervisor_id,
        log_status,
        target_status,
        attendance_status,
        employment_status,
        courier_name,
        date_from,
        date_to,
    )
    output = io.StringIO()
    output.write("\ufeff")
    rows = [
        {k: v for k, v in row.items() if not k.startswith("_")} for row in data["rows"]
    ]
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="couriers-{data["date_from"]}-{data["date_to"]}.csv"'
        },
    )


def _log(db: Session, user: User, action: str, entity: str, entity_id: int = None):
    db.add(
        AuditLog(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            actor_name=user.name or "—",
            actor_role=user.role.value,
            action=action,
            entity=entity,
            entity_id=entity_id,
        )
    )
    db.commit()


def _tenant_couriers(db: Session, user: User):
    """مناديب ضمن نطاق المستخدم: أدمن → كل شركته، مشرف → مجموعته فقط."""
    if user.role in (UserRole.COMPANY, UserRole.COMPANY_ADMIN, UserRole.HR):
        q = db.query(Courier).filter(Courier.tenant_id == user.tenant_id)
    elif user.role in (
        UserRole.SUPERVISOR,
        UserRole.PROJECT_MANAGER,
        UserRole.DOU_OPS,
        UserRole.DOU_ADMIN,
    ):
        q = db.query(Courier)
        if user.role == UserRole.SUPERVISOR:
            q = q.filter(
                Courier.tenant_id == user.tenant_id,
                _supervisor_courier_scope(db, user.id),
            )
        elif user.role == UserRole.PROJECT_MANAGER:
            q = q.filter(
                Courier.tenant_id == user.tenant_id,
                Courier.primary_project_id.in_(
                    json.loads(user.managed_project_ids or "[]")
                ),
            )
        elif user.tenant_id is not None:
            q = q.filter(Courier.tenant_id == user.tenant_id)
    else:
        raise HTTPException(403, "Not an HR account")
    return q


def _courier_json(c: Courier, db: Session, month: str = None):
    today = date.today()
    days_left = {
        "iqama": (c.iqama_expiry - today).days if c.iqama_expiry else None,
        "license": (c.license_expiry - today).days if c.license_expiry else None,
        "vehicle": (c.vehicle_license_expiry - today).days
        if c.vehicle_license_expiry
        else None,
    }
    month = month or today.strftime("%Y-%m")
    y, m = int(month[:4]), int(month[5:7])
    start = date(y, m, 1)
    end = date(y + (m // 12), m % 12 + 1, 1) if m < 12 else date(y + 1, 1, 1)
    logs = (
        db.query(DailyLog)
        .filter(
            DailyLog.courier_id == c.id,
            DailyLog.log_date >= start,
            DailyLog.log_date < end,
        )
        .all()
    )
    # العدّ التشغيلي العام للتوافق مع الشاشات القديمة؛ البونص نفسه يعتمد فقط على مشروع المندوب الحالي.
    month_orders = sum(log.orders_count or 0 for log in logs)
    calculated_bonus = calculate_courier_bonus(db, c, month)
    project = db.get(Project, c.primary_project_id) if c.primary_project_id else None
    bonus = {
        "total": calculated_bonus["earned"],
        "details": (
            [
                {
                    "project": project.name if project else "—",
                    "target": calculated_bonus["target"],
                    "orders": calculated_bonus["orders"],
                    "earned": calculated_bonus["earned"],
                    "scope": calculated_bonus["source"],
                    "achieved": calculated_bonus["achieved"],
                    "remaining_orders": calculated_bonus["remaining_orders"],
                    "over_orders": calculated_bonus["over_orders"],
                    "over_target_rate": calculated_bonus["over_target_rate"],
                    "plan_id": calculated_bonus["plan_id"],
                }
            ]
            if calculated_bonus["plan_id"]
            else []
        ),
    }
    ratings = db.query(CourierRating).filter(CourierRating.courier_id == c.id).all()
    avg_rating = (
        round(sum(r.score for r in ratings) / len(ratings), 1) if ratings else None
    )
    risks = []
    for k, v in days_left.items():
        if v is not None and v < 0:
            risks.append(f"منتهية: {k}")
        elif v is not None and v <= 7:
            risks.append(f"قرب الانتهاء ({v} يوم)")
    if c.is_on_leave:
        risks.append("في إجازة")
    if c.employment_status == "SUSPENDED":
        risks.append("موقوف")
    return {
        "id": c.id,
        "name": c.name,
        "phone": c.phone,
        "city_id": c.city_id,
        "work_city": c.work_city,
        "supervisor_id": c.supervisor_id,
        "platform": c.platform,
        "platform_courier_id": c.platform_courier_id,
        "iqama_expiry": c.iqama_expiry.isoformat() if c.iqama_expiry else None,
        "license_expiry": c.license_expiry.isoformat() if c.license_expiry else None,
        "vehicle_license_expiry": c.vehicle_license_expiry.isoformat()
        if c.vehicle_license_expiry
        else None,
        "passport_expiry": c.passport_expiry.isoformat() if c.passport_expiry else None,
        "insurance_expiry": c.insurance_expiry.isoformat()
        if c.insurance_expiry
        else None,
        "inspection_expiry": c.inspection_expiry.isoformat()
        if c.inspection_expiry
        else None,
        "work_permit_expiry": c.work_permit_expiry.isoformat()
        if c.work_permit_expiry
        else None,
        "iqama_number": c.iqama_number,
        "passport_number": c.passport_number,
        "emergency_name": c.emergency_name,
        "emergency_phone": c.emergency_phone,
        "vehicle_type": c.vehicle_type,
        "vehicle_plate": c.vehicle_plate,
        "zone": c.zone,
        "shift_preference": c.shift_preference,
        "nationality": c.nationality,
        "photo_url": c.photo_url,
        "doc_days_left": days_left,
        "doc_status": {
            k: (
                "expired"
                if v is not None and v < 0
                else "soon"
                if v is not None and v <= 7
                else "ok"
                if v is not None
                else "n/a"
            )
            for k, v in days_left.items()
        },
        "employment_status": c.employment_status or "ACTIVE",
        "is_on_leave": c.is_on_leave,
        "base_salary": c.base_salary or 0,
        "per_delivery_rate": c.per_delivery_rate or 0,
        "bank_iban": c.bank_iban,
        "hired_at": c.hired_at.isoformat() if c.hired_at else None,
        "is_online": c.is_online,
        "score": c.score,
        "month_orders": month_orders,
        "avg_rating": avg_rating,
        "bonus": bonus,
        "risks": risks,
        "shift_started_at": c.shift_started_at.isoformat()
        if c.shift_started_at
        else None,
    }


# ===================== الشركة: مدن التشغيل =====================


@router.get("/operating-cities")
def list_operating_cities(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Company management required")
    rows = (
        db.query(TenantOperatingCity)
        .filter(
            TenantOperatingCity.tenant_id == user.tenant_id,
        )
        .order_by(TenantOperatingCity.is_active.desc(), TenantOperatingCity.id)
        .all()
    )
    out = []
    for row in rows:
        city = db.get(GeoCity, row.geo_city_id)
        if not city:
            continue
        out.append(
            {
                "id": city.id,
                "name": row.display_name or city.name,
                "reference_name": city.name,
                "active": bool(row.is_active and city.active),
                "counts": operating_city_counts(db, user.tenant_id, city.id),
            }
        )
    return out


@router.post("/operating-cities")
def create_operating_city(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Company management required")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "اسم المدينة مطلوب")
    tenant = db.get(Tenant, user.tenant_id)
    if not tenant:
        raise HTTPException(404, "Company not found")
    try:
        city = find_or_create_city(db, tenant, name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    link = ensure_tenant_operating_city(db, tenant, city, active=True)
    if payload.get("display_name"):
        link.display_name = str(payload["display_name"]).strip() or None
    db.commit()
    _log(
        db,
        user,
        f"فعّل مدينة تشغيل {link.display_name or city.name}",
        "operating_city",
        city.id,
    )
    return {
        "ok": True,
        "id": city.id,
        "name": link.display_name or city.name,
        "active": True,
    }


@router.patch("/operating-cities/{city_id}")
def update_operating_city(
    city_id: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Company management required")
    link = (
        db.query(TenantOperatingCity)
        .filter(
            TenantOperatingCity.tenant_id == user.tenant_id,
            TenantOperatingCity.geo_city_id == city_id,
        )
        .first()
    )
    city = db.get(GeoCity, city_id)
    if not link or not city:
        raise HTTPException(404, "Operating city not found")
    if "name" in payload:
        display = str(payload.get("name") or "").strip()
        if not display:
            raise HTTPException(400, "اسم المدينة مطلوب")
        link.display_name = display
    if "active" in payload:
        link.is_active = bool(payload["active"])
    db.commit()
    _log(
        db,
        user,
        f"عدّل مدينة التشغيل {link.display_name or city.name}",
        "operating_city",
        city.id,
    )
    return {
        "ok": True,
        "id": city.id,
        "name": link.display_name or city.name,
        "active": bool(link.is_active and city.active),
    }


# ===================== الأدمن: مشرفون =====================


@router.get("/supervisors")
def list_supervisors(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in COMPANY_ROLES + (UserRole.SUPERVISOR, UserRole.PROJECT_MANAGER):
        raise HTTPException(403, "Admin only")
    q = db.query(User).filter(User.role == UserRole.SUPERVISOR)
    if user.tenant_id is not None:
        q = q.filter(User.tenant_id == user.tenant_id)
    if user.role == UserRole.SUPERVISOR:
        q = q.filter(User.id == user.id)
    out = []
    for u in q.all():
        team = db.query(Courier).filter(supervisor_courier_scope(db, u.id)).all()
        branches = (
            db.query(ContractBranch)
            .filter(
                ContractBranch.tenant_id == u.tenant_id,
                ContractBranch.supervisor_id == u.id,
                ContractBranch.is_active,
            )
            .order_by(ContractBranch.city)
            .all()
        )
        out.append(
            {
                "id": u.id,
                "name": u.name,
                "phone": u.phone,
                "couriers_count": len(team),
                "is_active": u.is_active,
                "courier_ids": [c.id for c in team],
                "branch_ids": [b.id for b in branches],
                "branches": [
                    {"id": b.id, "city": b.city, "zone": None} for b in branches
                ],
                "zones": sorted({c.zone for c in team if c.zone}),
            }
        )
    return out


@router.post("/supervisors")
def create_supervisor(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    if not name or not phone:
        raise HTTPException(400, "Name and phone are required")
    phone = phone if phone.startswith("966") else "966" + phone.lstrip("0")
    if db.query(User).filter(User.phone == phone).first():
        raise HTTPException(400, "Phone already registered")
    password = str(payload.get("password") or "")
    if len(password) < 8:
        raise HTTPException(400, "كلمة مرور المشرف يجب أن تكون 8 أحرف على الأقل")
    sup = User(
        phone=phone,
        name=name,
        password_hash=hash_password(password),
        role=UserRole.SUPERVISOR,
        tenant_id=user.tenant_id,
        country=None,
        is_active=True,
    )
    db.add(sup)
    db.commit()
    db.refresh(sup)
    _log(db, user, f"أنشأ مشرف {name}", "supervisor", sup.id)
    return {"ok": True, "id": sup.id, "name": name, "login_phone": phone}


@router.patch("/supervisors/{sid}")
def update_supervisor(
    sid: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """تعديل حساب المشرف وربط فروعه/فريقه من إدارة الشركة فقط."""
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Only the company admin can update supervisors")
    sup = db.get(User, sid)
    if not sup or sup.role != UserRole.SUPERVISOR or sup.tenant_id != user.tenant_id:
        raise HTTPException(404, "Supervisor not found")

    changes = []
    selected_branch_ids = None
    if "name" in payload and str(payload["name"] or "").strip():
        value = str(payload["name"]).strip()
        if value != sup.name:
            changes.append(f"الاسم: {sup.name or '—'} → {value}")
            sup.name = value
    if "phone" in payload and str(payload["phone"] or "").strip():
        value = str(payload["phone"]).strip()
        value = value if value.startswith("966") else "966" + value.lstrip("0")
        duplicate = (
            db.query(User)
            .filter(
                User.phone == value, User.role == UserRole.SUPERVISOR, User.id != sup.id
            )
            .first()
        )
        if duplicate:
            raise HTTPException(400, "Phone already registered")
        if value != sup.phone:
            changes.append(f"الجوال: {sup.phone or '—'} → {value}")
            sup.phone = value
    if "password" in payload and payload.get("password"):
        password = str(payload["password"])
        if len(password) < 8:
            raise HTTPException(400, "كلمة مرور المشرف يجب أن تكون 8 أحرف على الأقل")
        sup.password_hash = hash_password(password)
        sup.token_version = (sup.token_version or 0) + 1
        changes.append("إعادة تعيين كلمة المرور")
    if "is_active" in payload:
        value = bool(payload["is_active"])
        if value != bool(sup.is_active):
            changes.append(
                f"الحالة: {'نشط' if sup.is_active else 'موقوف'} → {'نشط' if value else 'موقوف'}"
            )
            sup.is_active = value
            sup.token_version = (sup.token_version or 0) + 1

    if "branch_ids" in payload:
        try:
            branch_ids = {int(x) for x in (payload.get("branch_ids") or [])}
        except (TypeError, ValueError):
            raise HTTPException(400, "branch_ids غير صالحة")
        branches = (
            db.query(ContractBranch)
            .filter(ContractBranch.tenant_id == user.tenant_id)
            .all()
        )
        valid_ids = {b.id for b in branches}
        if not branch_ids.issubset(valid_ids):
            raise HTTPException(400, "يوجد فرع لا يتبع الشركة")
        selected_branch_ids = branch_ids
        previous = {b.id for b in branches if b.supervisor_id == sup.id}
        for branch in branches:
            if branch.id in branch_ids:
                branch.supervisor_id = sup.id
                project = (
                    db.get(Project, branch.project_id) if branch.project_id else None
                )
                if project:
                    project.manager_id = sup.id
                for courier in (
                    db.query(Courier)
                    .filter(Courier.contract_branch_id == branch.id)
                    .all()
                ):
                    courier.supervisor_id = sup.id
                    courier.work_city = branch.city
            elif branch.supervisor_id == sup.id:
                branch.supervisor_id = None
                project = (
                    db.get(Project, branch.project_id) if branch.project_id else None
                )
                if project and project.manager_id == sup.id:
                    project.manager_id = None
                for courier in (
                    db.query(Courier)
                    .filter(
                        Courier.contract_branch_id == branch.id,
                        Courier.supervisor_id == sup.id,
                    )
                    .all()
                ):
                    courier.supervisor_id = None
        if branch_ids != previous:
            changes.append(
                "الفروع: "
                + ", ".join(str(x) for x in sorted(previous))
                + " → "
                + ", ".join(str(x) for x in sorted(branch_ids))
            )

    if "courier_ids" in payload:
        try:
            courier_ids = {int(x) for x in (payload.get("courier_ids") or [])}
        except (TypeError, ValueError):
            raise HTTPException(400, "courier_ids غير صالحة")
        team = db.query(Courier).filter(Courier.tenant_id == user.tenant_id).all()
        valid_ids = {c.id for c in team}
        if not courier_ids.issubset(valid_ids):
            raise HTTPException(400, "يوجد مندوب لا يتبع الشركة")
        if selected_branch_ids:
            courier_ids.update(
                c.id for c in team if c.contract_branch_id in selected_branch_ids
            )
        previous = {c.id for c in team if c.supervisor_id == sup.id}
        for courier in team:
            if courier.id in courier_ids:
                courier.supervisor_id = sup.id
            elif courier.supervisor_id == sup.id:
                courier.supervisor_id = None
        if courier_ids != previous:
            changes.append(
                "الفريق: "
                + ", ".join(str(x) for x in sorted(previous))
                + " → "
                + ", ".join(str(x) for x in sorted(courier_ids))
            )

    db.commit()
    if changes:
        _log(
            db,
            user,
            f"عدّل المشرف {sup.name}: {' | '.join(changes)}",
            "supervisor",
            sup.id,
        )
    return {"ok": True, "updated": changes}


@router.delete("/supervisors/{sid}")
def delete_supervisor(
    sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Only the company admin can delete supervisors")
    sup = db.get(User, sid)
    if not sup or sup.role != UserRole.SUPERVISOR:
        raise HTTPException(404, "Supervisor not found")
    if sup.tenant_id != user.tenant_id and user.role != UserRole.DOU_ADMIN:
        raise HTTPException(403, "Not your supervisor")
    linked = db.query(Courier).filter(Courier.supervisor_id == sid).count()
    if linked:
        raise HTTPException(400, f"Cannot delete: {linked} courier(s) assigned")
    db.delete(sup)
    db.commit()
    _log(db, user, f"حذف مشرف {sup.name}", "supervisor", sid)
    return {"ok": True}


@router.get("/assignment-candidates")
def assignment_candidates(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role != UserRole.SUPERVISOR:
        raise HTTPException(403, "Supervisor only")
    couriers = (
        db.query(Courier)
        .filter(
            Courier.tenant_id == user.tenant_id,
            Courier.supervisor_id.is_(None),
            ~_supervisor_courier_scope(db, user.id),
        )
        .order_by(Courier.name)
        .all()
    )
    return [
        {
            "id": c.id,
            "name": c.name,
            "phone": c.phone,
            "platform": c.platform,
            "current_supervisor": db.get(User, c.supervisor_id).name
            if c.supervisor_id
            else None,
        }
        for c in couriers
    ]


@router.get("/assignment-requests")
def assignment_requests(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    q = db.query(SupervisorAssignmentRequest).filter(
        SupervisorAssignmentRequest.tenant_id == user.tenant_id
    )
    if user.role == UserRole.SUPERVISOR:
        q = q.filter(SupervisorAssignmentRequest.supervisor_id == user.id)
    return [
        {
            "id": r.id,
            "status": r.status,
            "note": r.note,
            "supervisor_id": r.supervisor_id,
            "supervisor": db.get(User, r.supervisor_id).name
            if db.get(User, r.supervisor_id)
            else "—",
            "courier_id": r.courier_id,
            "courier": db.get(Courier, r.courier_id).name
            if db.get(Courier, r.courier_id)
            else "—",
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in q.order_by(SupervisorAssignmentRequest.id.desc()).all()
    ]


@router.post("/assignment-requests")
def request_assignment(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role != UserRole.SUPERVISOR:
        raise HTTPException(403, "Supervisor only")
    courier = db.get(Courier, payload.get("courier_id"))
    if (
        not courier
        or courier.tenant_id != user.tenant_id
        or courier.supervisor_id is not None
        or _tenant_couriers(db, user).filter(Courier.id == courier.id).first()
    ):
        raise HTTPException(404, "Courier not available")
    pending = (
        db.query(SupervisorAssignmentRequest)
        .filter(
            SupervisorAssignmentRequest.supervisor_id == user.id,
            SupervisorAssignmentRequest.courier_id == courier.id,
            SupervisorAssignmentRequest.status == "PENDING",
        )
        .first()
    )
    if pending:
        raise HTTPException(400, "هناك طلب موافقة قائم لهذا السائق")
    row = SupervisorAssignmentRequest(
        tenant_id=user.tenant_id,
        supervisor_id=user.id,
        courier_id=courier.id,
        note=(payload.get("note") or "").strip(),
        status="PENDING",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _log(db, user, f"طلب ضم السائق {courier.name} لمجموعته", "assignment", row.id)
    return {"ok": True, "id": row.id, "status": row.status}


@router.post("/assignment-requests/{rid}/decide")
def decide_assignment(
    rid: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Company admin only")
    row = db.get(SupervisorAssignmentRequest, rid)
    if not row or (user.tenant_id is not None and row.tenant_id != user.tenant_id):
        raise HTTPException(404, "Assignment request not found")
    if row.status != "PENDING":
        raise HTTPException(400, "Request already reviewed")
    action = payload.get("action")
    if action not in ("approve", "reject"):
        raise HTTPException(400, "Invalid action")
    row.status = "APPROVED" if action == "approve" else "REJECTED"
    row.reviewed_by = user.id
    row.reviewed_at = datetime.utcnow()
    courier = db.get(Courier, row.courier_id)
    if action == "approve" and courier:
        courier.supervisor_id = row.supervisor_id
        db.query(SupervisorAssignmentRequest).filter(
            SupervisorAssignmentRequest.courier_id == row.courier_id,
            SupervisorAssignmentRequest.status == "PENDING",
            SupervisorAssignmentRequest.id != row.id,
        ).update({"status": "REJECTED"}, synchronize_session=False)
    db.commit()
    _log(
        db,
        user,
        f"{'وافق على' if action == 'approve' else 'رفض'} طلب إسناد السائق",
        "assignment",
        row.id,
    )
    return {"ok": True, "status": row.status}


# ===================== الأدمن/المشرف: مشاريع =====================


@router.get("/projects")
def list_projects(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in (
        COMPANY_ROLES
        + (UserRole.SUPERVISOR, UserRole.PROJECT_MANAGER, UserRole.COURIER)
    ):
        raise HTTPException(403, "Not allowed")
    tenant_id = user.tenant_id
    c = None
    if user.role == UserRole.COURIER and user.courier_id:
        c = db.get(Courier, user.courier_id)
        tenant_id = c.tenant_id if c else tenant_id
    branch_project_ids = (
        [
            x[0]
            for x in db.query(ContractBranch.project_id)
            .filter(
                ContractBranch.tenant_id == tenant_id,
                ContractBranch.is_active,
                ContractBranch.project_id.isnot(None),
            )
            .all()
        ]
        if tenant_id
        else []
    )
    if c and c.primary_project_id and c.primary_project_id not in branch_project_ids:
        branch_project_ids.append(c.primary_project_id)
    q = (
        db.query(Project).filter(
            Project.tenant_id == tenant_id, Project.id.in_(branch_project_ids)
        )
        if tenant_id
        else db.query(Project).filter(Project.id.in_(branch_project_ids))
    )
    return [
        {
            "id": p.id,
            "name": p.name,
            "is_active": p.is_active,
            "is_current": bool(c and c.primary_project_id == p.id),
            "manager_id": p.manager_id,
            "manager": db.get(User, p.manager_id).name
            if p.manager_id and db.get(User, p.manager_id)
            else None,
        }
        for p in q.all()
    ]


@router.post("/projects")
def create_project(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    raise HTTPException(
        409, "أضف المشروع من خلال عقد تجاري وفرع تشغيل؛ الإنشاء المنفصل متوقف"
    )


@router.post("/couriers/{cid}/transfer-project")
def transfer_project(
    cid: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    c = _tenant_couriers(db, user).filter(Courier.id == cid).first()
    p = db.get(Project, int(payload.get("project_id") or 0))
    branch = (
        db.query(ContractBranch)
        .filter(
            ContractBranch.tenant_id == user.tenant_id,
            ContractBranch.project_id == p.id,
            ContractBranch.is_active,
        )
        .first()
        if p
        else None
    )
    if not c or not p or p.tenant_id != user.tenant_id or not branch:
        raise HTTPException(404, "اختر فريق تشغيل تابعاً لعقد تجاري")
    db.add(
        ProjectTransfer(
            tenant_id=user.tenant_id,
            courier_id=cid,
            from_project_id=c.primary_project_id,
            to_project_id=p.id,
            changed_by=user.id,
            note=payload.get("note"),
        )
    )
    c.primary_project_id = p.id
    c.platform = p.name
    c.contract_id = branch.contract_id
    c.contract_branch_id = branch.id
    c.work_city = branch.city
    c.supervisor_id = branch.supervisor_id
    db.commit()
    return {"ok": True}


@router.get("/couriers/{cid}/project-history")
def project_history(
    cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if not _tenant_couriers(db, user).filter(Courier.id == cid).first():
        raise HTTPException(404, "Courier not found")
    names = {
        p.id: p.name
        for p in db.query(Project).filter(Project.tenant_id == user.tenant_id).all()
    }
    return [
        {
            "from": names.get(x.from_project_id, "—"),
            "to": names.get(x.to_project_id, "—"),
            "note": x.note,
            "date": x.created_at.isoformat(),
        }
        for x in db.query(ProjectTransfer)
        .filter(ProjectTransfer.courier_id == cid)
        .order_by(ProjectTransfer.id.desc())
        .all()
    ]


@router.get("/adjustments")
def adjustments(
    month: str = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not allowed")
    q = db.query(PayrollAdjustment).filter(
        PayrollAdjustment.tenant_id == user.tenant_id
    )
    if month:
        q = q.filter(PayrollAdjustment.month == month)
    return [
        {
            "id": x.id,
            "courier_id": x.courier_id,
            "courier": db.get(Courier, x.courier_id).name,
            "month": x.month,
            "kind": x.kind,
            "amount": x.amount,
            "note": x.note,
        }
        for x in q.order_by(PayrollAdjustment.id.desc()).all()
    ]


@router.post("/adjustments")
def add_adjustment(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Company admin required")
    c = (
        _tenant_couriers(db, user)
        .filter(Courier.id == int(payload.get("courier_id") or 0))
        .first()
    )
    if not c:
        raise HTTPException(404, "Courier not found")
    month = str(payload.get("month") or date.today().strftime("%Y-%m"))
    try:
        date.fromisoformat(month + "-01")
        amount = float(payload.get("amount") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "بيانات التعديل غير صالحة")
    if amount <= 0 or payload.get("kind") not in {
        "OVERTIME",
        "ADVANCE",
        "DEDUCTION",
        "VIOLATION",
    }:
        raise HTTPException(400, "حدد نوع تعديل مدعوماً ومبلغاً موجباً")
    if finalized_period(db, user.tenant_id, month):
        raise HTTPException(
            409, "فترة الرواتب مقفلة؛ استخدم تصحيحاً في فترة مفتوحة لاحقة"
        )
    x = PayrollAdjustment(
        tenant_id=user.tenant_id,
        courier_id=c.id,
        month=month,
        kind=payload.get("kind"),
        amount=amount,
        note=payload.get("note"),
        source_type="MANUAL",
        status="APPROVED",
        created_by=user.id,
    )
    db.add(x)
    db.commit()
    db.refresh(x)
    _log(db, user, f"تعديل راتب يدوي للمندوب {c.name}", "payroll_adjustment", x.id)
    return {"ok": True, "id": x.id}


def _attendance_policy_json(row: AttendanceDeductionPolicy):
    return {
        "id": row.id,
        "name": row.name,
        "event_type": row.event_type,
        "grace_minutes": row.grace_minutes or 0,
        "calculation_method": row.calculation_method,
        "amount_rate": row.amount_rate,
        "maximum_deduction": row.maximum_deduction,
        "requires_approval": bool(row.requires_approval),
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "is_active": bool(row.is_active),
    }


def _attendance_event_json(row: AttendanceEvent, db: Session):
    courier = db.get(Courier, row.courier_id)
    policy = db.get(AttendanceDeductionPolicy, row.policy_id) if row.policy_id else None
    return {
        "id": row.id,
        "courier_id": row.courier_id,
        "courier": courier.name if courier else "—",
        "event_type": row.event_type,
        "event_date": row.event_date.isoformat(),
        "measured_minutes": row.measured_minutes or 0,
        "status": row.status,
        "deduction_amount": round(float(row.deduction_amount or 0), 2),
        "policy_id": row.policy_id,
        "policy": policy.name if policy else None,
        "attendance_id": row.attendance_id,
        "shift_id": row.shift_id,
        "payroll_adjustment_id": row.payroll_adjustment_id,
        "note": row.note,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }


@router.get("/attendance-policies")
def list_attendance_policies(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Company attendance-policy access required")
    rows = (
        db.query(AttendanceDeductionPolicy)
        .filter(
            AttendanceDeductionPolicy.tenant_id == user.tenant_id,
        )
        .order_by(
            AttendanceDeductionPolicy.event_type, AttendanceDeductionPolicy.id.desc()
        )
        .all()
    )
    return [_attendance_policy_json(row) for row in rows]


@router.post("/attendance-policies")
def create_attendance_policy(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Company admin required")
    event_type = str(payload.get("event_type") or "").upper()
    method = str(payload.get("calculation_method") or "FIXED").upper()
    name = str(payload.get("name") or f"سياسة {event_type}").strip()
    if event_type not in EVENT_TYPES:
        raise HTTPException(400, "نوع الحدث غير صالح")
    if method not in CALCULATION_METHODS:
        method = "FIXED"
    if method == "MANUAL_APPROVAL_ONLY" and not bool(
        payload.get("requires_approval", True)
    ):
        raise HTTPException(400, "طريقة الاعتماد اليدوي تتطلب اعتماداً")
    try:
        effective_from = date.fromisoformat(
            str(payload.get("effective_from") or date.today().isoformat())
        )
        effective_to = (
            date.fromisoformat(str(payload["effective_to"]))
            if payload.get("effective_to")
            else None
        )
        grace = max(0, int(payload.get("grace_minutes") or 0))
        rate = (
            float(payload["amount_rate"])
            if payload.get("amount_rate") is not None
            else (
                float(payload["deduction_amount"])
                if payload.get("deduction_amount") is not None
                else 0.0
            )
        )
        maximum = (
            float(payload.get("maximum_deduction"))
            if payload.get("maximum_deduction") not in (None, "")
            else None
        )
    except (TypeError, ValueError):
        raise HTTPException(400, "قيم سياسة الحضور غير صالحة")
    if effective_to and effective_to < effective_from:
        raise HTTPException(400, "تاريخ نهاية السياسة يسبق بدايتها")
    if method != "MANUAL_APPROVAL_ONLY" and (rate is None or rate < 0):
        raise HTTPException(400, "أدخل مبلغاً أو معدلاً غير سالب")
    if maximum is not None and maximum < 0:
        raise HTTPException(400, "الحد الأقصى غير صالح")
    duplicates = (
        db.query(AttendanceDeductionPolicy)
        .filter(
            AttendanceDeductionPolicy.tenant_id == user.tenant_id,
            AttendanceDeductionPolicy.event_type == event_type,
            AttendanceDeductionPolicy.is_active.is_(True),
        )
        .all()
    )
    for d in duplicates:
        d.is_active = False
    row = AttendanceDeductionPolicy(
        tenant_id=user.tenant_id,
        name=name,
        event_type=event_type,
        grace_minutes=grace,
        calculation_method=method,
        amount_rate=rate,
        maximum_deduction=maximum,
        requires_approval=bool(
            payload.get("requires_approval", method == "MANUAL_APPROVAL_ONLY")
        ),
        effective_from=effective_from,
        effective_to=effective_to,
        is_active=bool(payload.get("is_active", True)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _log(db, user, f"أنشأ سياسة حضور {row.name}", "attendance_policy", row.id)
    return _attendance_policy_json(row)


@router.patch("/attendance-policies/{policy_id}")
def update_attendance_policy(
    policy_id: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Company admin required")
    row = db.get(AttendanceDeductionPolicy, policy_id)
    if not row or row.tenant_id != user.tenant_id:
        raise HTTPException(404, "Attendance policy not found")
    if "is_active" in payload:
        row.is_active = bool(payload["is_active"])
    if "name" in payload and str(payload["name"] or "").strip():
        row.name = str(payload["name"]).strip()
    if "grace_minutes" in payload:
        row.grace_minutes = max(0, int(payload["grace_minutes"] or 0))
    if "maximum_deduction" in payload:
        row.maximum_deduction = (
            float(payload["maximum_deduction"])
            if payload["maximum_deduction"] not in (None, "")
            else None
        )
    if "requires_approval" in payload:
        row.requires_approval = bool(payload["requires_approval"])
    if "effective_to" in payload:
        row.effective_to = (
            date.fromisoformat(str(payload["effective_to"]))
            if payload["effective_to"]
            else None
        )
    if row.effective_to and row.effective_to < row.effective_from:
        raise HTTPException(400, "تاريخ نهاية السياسة يسبق بدايتها")
    db.commit()
    _log(db, user, f"حدّث سياسة حضور {row.name}", "attendance_policy", row.id)
    return _attendance_policy_json(row)


@router.get("/attendance-events")
def list_attendance_events(
    month: str = None,
    status: str = None,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in COMPANY_ROLES + (UserRole.SUPERVISOR,):
        raise HTTPException(403, "Attendance-event access required")
    q = db.query(AttendanceEvent).filter(AttendanceEvent.tenant_id == user.tenant_id)
    if user.role == UserRole.SUPERVISOR:
        q = q.filter(
            AttendanceEvent.courier_id.in_(
                _tenant_couriers(db, user).with_entities(Courier.id)
            )
        )
    if month:
        try:
            start = date.fromisoformat(month + "-01")
            end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        except ValueError:
            raise HTTPException(400, "month غير صالح")
        q = q.filter(
            AttendanceEvent.event_date >= start, AttendanceEvent.event_date < end
        )
    if status:
        q = q.filter(AttendanceEvent.status == status)
    total = q.count()
    rows = (
        q.order_by(AttendanceEvent.event_date.desc(), AttendanceEvent.id.desc())
        .offset(max(0, offset))
        .limit(min(max(limit, 1), 500))
        .all()
    )
    return {"total": total, "rows": [_attendance_event_json(row, db) for row in rows]}


@router.post("/attendance-events/reconcile-absences")
def reconcile_absences(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Company admin required")
    try:
        event_date = date.fromisoformat(
            str(payload.get("date") or date.today().isoformat())
        )
    except ValueError:
        raise HTTPException(400, "date غير صالح")
    from .shifts import _shift_window

    result = reconcile_absences_for_date(db, user.tenant_id, event_date, _shift_window)
    db.commit()
    _log(
        db,
        user,
        f"سوّى أحداث الغياب ليوم {event_date.isoformat()}",
        "attendance_reconciliation",
        None,
    )
    return result


@router.post("/attendance-events/{event_id}/decide")
def decide_event(
    event_id: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Company admin required")
    row = db.get(AttendanceEvent, event_id)
    if not row or row.tenant_id != user.tenant_id:
        raise HTTPException(404, "Attendance event not found")
    try:
        decide_attendance_event(
            db,
            row,
            str(payload.get("action") or "").lower(),
            user.id,
            payload.get("note"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    _log(
        db,
        user,
        f"قرار على حدث حضور #{row.id}: {payload.get('action')}",
        "attendance_event",
        row.id,
    )
    return _attendance_event_json(row, db)


@router.post("/payroll/corrections")
def create_payroll_correction(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Company admin required")
    try:
        courier_id = int(payload.get("courier_id") or 0)
        original_month = str(payload.get("original_month") or "")
        target_month = str(payload.get("target_month") or "")
        amount = float(payload.get("amount") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "بيانات التصحيح غير صالحة")
    if amount <= 0 or payload.get("kind") not in {"OVERTIME", "DEDUCTION"}:
        raise HTTPException(400, "حدد مبلغاً موجباً ونوع تصحيح مدعوماً")
    original = finalized_period(db, user.tenant_id, original_month)
    if not original:
        raise HTTPException(400, "الفترة الأصلية يجب أن تكون مقفلة")
    if finalized_period(db, user.tenant_id, target_month):
        raise HTTPException(409, "فترة التصحيح المقصودة مقفلة")
    if target_month <= original_month:
        raise HTTPException(400, "يجب تسجيل التصحيح في فترة مفتوحة لاحقة")
    courier = _tenant_couriers(db, user).filter(Courier.id == courier_id).first()
    note = str(payload.get("note") or "").strip()
    if not courier or not note:
        raise HTTPException(400, "اختر مندوباً تابعاً للشركة وأدخل سبب التصحيح")
    key = f"payroll-correction:{original.id}:{courier.id}:{target_month}:{payload['kind']}:{amount:.2f}"
    existing = (
        db.query(PayrollAdjustment)
        .filter(
            PayrollAdjustment.tenant_id == user.tenant_id,
            PayrollAdjustment.idempotency_key == key,
        )
        .first()
    )
    if existing:
        return {"ok": True, "id": existing.id, "already_exists": True}
    adjustment = PayrollAdjustment(
        tenant_id=user.tenant_id,
        courier_id=courier.id,
        month=target_month,
        kind=payload["kind"],
        amount=amount,
        note=f"تصحيح فترة {original_month}: {note}",
        source_type="PAYROLL_CORRECTION",
        source_id=original.id,
        idempotency_key=key,
        status="APPROVED",
        created_by=user.id,
    )
    db.add(adjustment)
    db.commit()
    db.refresh(adjustment)
    _log(
        db,
        user,
        f"سجل تصحيحاً للفترة {original_month} في {target_month}",
        "payroll_adjustment",
        adjustment.id,
    )
    return {"ok": True, "id": adjustment.id, "already_exists": False}


@router.get("/employee-requests")
def employee_requests(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role == UserRole.COURIER:
        q = db.query(EmployeeRequest).filter(
            EmployeeRequest.courier_id == user.courier_id
        )
    elif user.role in COMPANY_ROLES + (UserRole.SUPERVISOR,):
        q = db.query(EmployeeRequest).filter(
            EmployeeRequest.courier_id.in_(
                [c.id for c in _tenant_couriers(db, user).all()]
            )
        )
    else:
        raise HTTPException(403, "Not allowed")
    rows = []
    for x in q.order_by(EmployeeRequest.id.desc()).all():
        cour = db.get(Courier, x.courier_id) if x.courier_id else None
        rows.append(
            {
                "id": x.id,
                "courier": cour.name if cour else "—",
                "request_type": x.request_type,
                "title": x.title,
                "details": x.details,
                "amount": x.amount,
                "status": x.status,
                "created_at": x.created_at.isoformat() if x.created_at else None,
            }
        )
    return rows


@router.post("/employee-requests")
def create_employee_request(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    c = _my_courier(user, db)
    typ = payload.get("request_type")
    if typ not in (
        "ADVANCE",
        "SHIFT_CHANGE",
        "PROJECT_TRANSFER",
        "MAINTENANCE",
        "INCIDENT",
        "SOS",
        "INSPECTION",
        "COD_SETTLEMENT",
    ):
        raise HTTPException(400, "Invalid request type")
    requested_project_id = payload.get("project_id")
    if typ == "PROJECT_TRANSFER":
        p = db.get(Project, int(requested_project_id or 0))
        if not p or p.tenant_id != c.tenant_id:
            raise HTTPException(400, "اختر مشروعًا صحيحًا تابعًا لشركتك")
        requested_project_id = p.id
    x = EmployeeRequest(
        tenant_id=c.tenant_id,
        courier_id=c.id,
        request_type=typ,
        title=payload.get("title"),
        details=payload.get("details"),
        amount=float(payload.get("amount") or 0) or None,
        requested_project_id=requested_project_id,
    )
    db.add(x)
    db.commit()
    return {"ok": True, "id": x.id}


@router.post("/employee-requests/{rid}/decide")
def decide_employee_request(
    rid: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in COMPANY_ROLES + (UserRole.SUPERVISOR,):
        raise HTTPException(403, "Not allowed")
    x = db.get(EmployeeRequest, rid)
    if (
        not x
        or not _tenant_couriers(db, user).filter(Courier.id == x.courier_id).first()
    ):
        raise HTTPException(404, "Request not found")
    if x.status in ("APPROVED", "REJECTED"):
        raise HTTPException(400, "تم اتخاذ قرار نهائي على هذا الطلب بالفعل")
    approve = payload.get("action") == "approve"
    if (
        approve
        and user.role == UserRole.SUPERVISOR
        and x.request_type in ("ADVANCE", "PROJECT_TRANSFER")
    ):
        x.status = "SUPERVISOR_APPROVED"
        x.reviewed_by = user.id
        x.review_note = payload.get("note")
        x.reviewed_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "status": x.status}
    x.status = "APPROVED" if approve else "REJECTED"
    x.reviewed_by = user.id
    x.review_note = payload.get("note")
    x.reviewed_at = datetime.utcnow()
    if approve:
        courier = db.get(Courier, x.courier_id)
        if x.request_type == "ADVANCE":
            if not x.amount or x.amount <= 0:
                raise HTTPException(400, "طلب السلفة لا يحتوي مبلغًا صحيحًا")
            db.add(
                PayrollAdjustment(
                    tenant_id=x.tenant_id,
                    courier_id=x.courier_id,
                    month=date.today().strftime("%Y-%m"),
                    kind="ADVANCE",
                    amount=x.amount,
                    note=f"سلفة معتمدة — طلب #{x.id}",
                    created_by=user.id,
                )
            )
        elif x.request_type == "PROJECT_TRANSFER":
            project = (
                db.get(Project, x.requested_project_id)
                if x.requested_project_id
                else None
            )
            if not project or project.tenant_id != x.tenant_id:
                raise HTTPException(400, "المشروع المطلوب غير صحيح")
            if courier.primary_project_id != project.id:
                db.add(
                    ProjectTransfer(
                        tenant_id=x.tenant_id,
                        courier_id=courier.id,
                        from_project_id=courier.primary_project_id,
                        to_project_id=project.id,
                        changed_by=user.id,
                        note=f"طلب سائق #{x.id}",
                    )
                )
                courier.primary_project_id = project.id
                courier.platform = project.name
        elif x.request_type == "SHIFT_CHANGE":
            courier.shift_preference = (x.details or x.title or "وردية معدلة")[:120]
        elif x.request_type in ("MAINTENANCE", "INCIDENT"):
            courier.is_available = False
    db.commit()
    return {"ok": True, "status": x.status}


@router.post("/me/documents")
def upload_my_document(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    c = _my_courier(user, db)
    if c.employment_status != "ACTIVE":
        raise HTTPException(403, "المندوب غير نشط لرفع المستندات")
    data = str(payload.get("file_data") or "")
    if not data.startswith("data:") or len(data) > 1_500_000:
        raise HTTPException(400, "الملف غير صالح أو أكبر من 1 ميجابايت")
    typ = payload.get("document_type")
    if typ not in (
        "IQAMA",
        "DRIVING_LICENSE",
        "VEHICLE_LICENSE",
        "PASSPORT",
        "INSURANCE",
        "WORK_PERMIT",
    ):
        raise HTTPException(400, "نوع المستند غير صحيح")
    row = CourierDocumentSubmission(
        tenant_id=c.tenant_id,
        courier_id=c.id,
        document_type=typ,
        filename=(payload.get("filename") or "document")[:180],
        mime_type=(payload.get("mime_type") or "application/octet-stream")[:80],
        file_data=data,
        status="PENDING",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id, "status": row.status}


@router.get("/me/documents")
def my_documents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _my_courier(user, db)
    rows = (
        db.query(CourierDocumentSubmission)
        .filter(CourierDocumentSubmission.courier_id == c.id)
        .order_by(CourierDocumentSubmission.id.desc())
        .all()
    )
    return [_document_json(x, db) for x in rows]


def _document_json(x, db):
    c = db.get(Courier, x.courier_id)
    return {
        "id": x.id,
        "courier": c.name if c else "—",
        "document_type": x.document_type,
        "filename": x.filename,
        "mime_type": x.mime_type,
        "status": x.status,
        "review_note": x.review_note,
        "created_at": x.created_at.isoformat() if x.created_at else None,
    }


@router.get("/documents")
def company_documents(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in COMPANY_ROLES + (UserRole.SUPERVISOR,):
        raise HTTPException(403, "Not allowed")
    ids = [c.id for c in _tenant_couriers(db, user).all()]
    rows = (
        db.query(CourierDocumentSubmission)
        .filter(CourierDocumentSubmission.courier_id.in_(ids))
        .order_by(CourierDocumentSubmission.id.desc())
        .all()
    )
    return [_document_json(x, db) for x in rows]


@router.get("/documents/{did}/content")
def document_content(
    did: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    x = db.get(CourierDocumentSubmission, did)
    if (
        not x
        or not _tenant_couriers(db, user).filter(Courier.id == x.courier_id).first()
    ):
        raise HTTPException(404, "Document not found")
    return {"filename": x.filename, "mime_type": x.mime_type, "file_data": x.file_data}


@router.post("/documents/{did}/decide")
def decide_document(
    did: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Company approval required")
    x = db.get(CourierDocumentSubmission, did)
    if not x or x.tenant_id != user.tenant_id:
        raise HTTPException(404, "Document not found")
    x.status = "APPROVED" if payload.get("action") == "approve" else "REJECTED"
    x.review_note = payload.get("note")
    x.reviewed_by = user.id
    x.reviewed_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "status": x.status}


# ===================== الأدمن/المشرف: بونص =====================


@router.get("/bonus")
def list_bonus(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    q = db.query(BonusPlan)
    if user.tenant_id is not None:
        q = q.filter(BonusPlan.tenant_id == user.tenant_id)
    if user.role == UserRole.SUPERVISOR:
        q = q.filter(BonusPlan.is_active.is_(True))
        team = _tenant_couriers(db, user)
        team_ids = [c.id for c in team.all()]
        team_projects = [
            c.primary_project_id
            for c in _tenant_couriers(db, user).all()
            if c.primary_project_id
        ]
        q = (
            q.filter(
                or_(
                    BonusPlan.courier_id.in_(team_ids),
                    and_(
                        BonusPlan.courier_id.is_(None),
                        BonusPlan.project_id.in_(team_projects),
                    ),
                )
            )
            if team_ids or team_projects
            else q.filter(text("1=0"))
        )
    out = []
    for p in q.order_by(BonusPlan.id.desc()).all():
        c = db.get(Courier, p.courier_id) if p.courier_id else None
        pj = db.get(Project, p.project_id) if p.project_id else None
        branch = (
            db.get(ContractBranch, p.contract_branch_id)
            if p.contract_branch_id
            else None
        )
        contract = (
            db.get(Contract, p.contract_id)
            if p.contract_id
            else (db.get(Contract, branch.contract_id) if branch else None)
        )
        out.append(
            {
                "id": p.id,
                "courier_id": p.courier_id,
                "courier": c.name
                if c
                else (
                    "كل مندوبي الفرع"
                    if branch
                    else ("كل مندوبي العقد" if contract else "كل مناديب الشركة")
                ),
                "project_id": p.project_id,
                "project": pj.name if pj else "—",
                "contract_id": p.contract_id or (contract.id if contract else None),
                "contract": contract.name if contract else "—",
                "contract_branch_id": p.contract_branch_id,
                "city": branch.city
                if branch
                else ("كل الفروع" if contract else "كل المدن"),
                "is_project_plan": p.courier_id is None,
                "plan_type": getattr(p, "plan_type", "TARGET_TIER") or "TARGET_TIER",
                "target_orders": p.target_orders or 0,
                "bonus_amount": p.bonus_amount or 0.0,
                "over_target_rate": p.over_target_rate or 0.0,
                "below_target_rate": getattr(p, "below_target_rate", 0.0) or 0.0,
                "flat_order_rate": getattr(p, "flat_order_rate", 0.0) or 0.0,
                "is_active": bool(p.is_active),
                "effective_from": p.effective_from.isoformat()
                if p.effective_from
                else None,
                "effective_to": p.effective_to.isoformat() if p.effective_to else None,
            }
        )
    return out


@router.post("/bonus")
def create_bonus(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")

    plan_type = str(payload.get("plan_type") or "TARGET_TIER").upper()
    if plan_type not in ("TARGET_TIER", "FLAT_PER_ORDER"):
        raise HTTPException(400, "نوع خطة البونص غير صالح")

    contract_id = payload.get("contract_id")
    branch_id = payload.get("contract_branch_id")
    cid = payload.get("courier_id")

    branch = db.get(ContractBranch, int(branch_id)) if branch_id else None
    contract = (
        db.get(Contract, int(contract_id))
        if contract_id
        else (db.get(Contract, branch.contract_id) if branch else None)
    )

    if branch and (branch.tenant_id != user.tenant_id or not branch.is_active):
        raise HTTPException(404, "فرع العقد غير موجود أو غير نشط")
    if contract and contract.tenant_id != user.tenant_id:
        raise HTTPException(404, "العقد غير موجود")

    pid = (
        branch.project_id
        if branch
        else (contract.project_id if contract and contract.project_id else None)
    )
    if not pid and contract:
        first_b = (
            db.query(ContractBranch)
            .filter(ContractBranch.contract_id == contract.id, ContractBranch.is_active)
            .first()
        )
        if first_b:
            pid = first_b.project_id
    if not pid:
        default_p = (
            db.query(Project)
            .filter(Project.tenant_id == user.tenant_id, Project.is_active)
            .first()
        )
        if default_p:
            pid = default_p.id

    target_orders = int(payload.get("target_orders") or 0)
    bonus_amount = float(payload.get("bonus_amount") or 0.0)
    over_target_rate = float(payload.get("over_target_rate") or 0.0)
    below_target_rate = float(payload.get("below_target_rate") or 0.0)
    flat_order_rate = float(payload.get("flat_order_rate") or 0.0)

    if plan_type == "TARGET_TIER":
        if target_orders <= 0:
            raise HTTPException(400, "التارجت يجب أن يكون أكبر من صفر")
        if bonus_amount < 0 or over_target_rate < 0 or below_target_rate < 0:
            raise HTTPException(400, "مبالغ وأسعار البونص لا يمكن أن تكون سالبة")
    elif plan_type == "FLAT_PER_ORDER":
        if flat_order_rate <= 0:
            raise HTTPException(400, "سعر الطلب الثابت يجب أن يكون أكبر من صفر")

    c = None
    if cid:
        c = db.get(Courier, int(cid))
        if not c or c.tenant_id != user.tenant_id:
            raise HTTPException(404, "Courier not found in your fleet")

    def _bonus_date(value, label):
        if not value:
            return None
        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError):
            raise HTTPException(400, f"{label} غير صالح — استخدم YYYY-MM-DD")

    effective_from = (
        _bonus_date(payload.get("effective_from"), "effective_from") or date.today()
    )
    effective_to = _bonus_date(payload.get("effective_to"), "effective_to")
    if effective_to and effective_to < effective_from:
        raise HTTPException(400, "تاريخ انتهاء الخطة يسبق تاريخ بدايتها")

    p = BonusPlan(
        tenant_id=user.tenant_id,
        contract_id=contract.id if contract else None,
        contract_branch_id=branch.id if branch else None,
        project_id=pid,
        courier_id=c.id if c else None,
        plan_type=plan_type,
        target_orders=target_orders,
        bonus_amount=bonus_amount,
        over_target_rate=over_target_rate,
        below_target_rate=below_target_rate,
        flat_order_rate=flat_order_rate,
        is_active=bool(payload.get("is_active", True)),
        effective_from=effective_from,
        effective_to=effective_to,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    plan_desc = f"خطة بونص {plan_type} لعقد {contract.name if contract else 'عام'}"
    _log(db, user, plan_desc, "bonus", p.id)
    return {"ok": True, "id": p.id}


@router.patch("/bonus/{bid}")
def update_bonus(
    bid: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    p = db.get(BonusPlan, bid)
    if not p or (user.tenant_id is not None and p.tenant_id != user.tenant_id):
        raise HTTPException(404, "Bonus plan not found")

    if "plan_type" in payload and payload["plan_type"]:
        p.plan_type = str(payload["plan_type"]).upper()
    if "target_orders" in payload:
        p.target_orders = int(payload["target_orders"] or 0)
    if "bonus_amount" in payload:
        p.bonus_amount = float(payload["bonus_amount"] or 0)
    if "over_target_rate" in payload:
        p.over_target_rate = float(payload["over_target_rate"] or 0)
    if "below_target_rate" in payload:
        p.below_target_rate = float(payload["below_target_rate"] or 0)
    if "flat_order_rate" in payload:
        p.flat_order_rate = float(payload["flat_order_rate"] or 0)
    if "is_active" in payload:
        p.is_active = bool(payload["is_active"])
    for key in ("effective_from", "effective_to"):
        if key in payload:
            raw = payload.get(key)
            try:
                value = date.fromisoformat(str(raw)) if raw else None
            except (TypeError, ValueError):
                raise HTTPException(400, f"{key} غير صالح — استخدم YYYY-MM-DD")
            setattr(p, key, value)
    if p.effective_from and p.effective_to and p.effective_to < p.effective_from:
        raise HTTPException(400, "تاريخ انتهاء الخطة يسبق تاريخ بدايتها")
    db.commit()
    _log(db, user, f"عدّل خطة بونص #{p.id}", "bonus", p.id)
    return {"ok": True}


@router.delete("/bonus/{bid}")
def delete_bonus(
    bid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    p = db.get(BonusPlan, bid)
    if not p or (user.tenant_id is not None and p.tenant_id != user.tenant_id):
        raise HTTPException(404, "Bonus plan not found")
    p.is_active = False
    if not p.effective_to:
        p.effective_to = date.today()
    db.commit()
    _log(db, user, f"عطّل خطة بونص #{bid}", "bonus", bid)
    return {"ok": True, "status": "INACTIVE"}


# ===================== الأدمن/المشرف: إجازات =====================


@router.get("/leaves")
def list_leaves(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    q = db.query(LeaveRequest)
    if user.role == UserRole.COMPANY:
        q = q.filter(LeaveRequest.tenant_id == user.tenant_id)
    elif user.role == UserRole.SUPERVISOR:
        ids = [c.id for c in _tenant_couriers(db, user).all()]
        q = q.filter(LeaveRequest.courier_id.in_(ids)) if ids else q.filter(text("1=0"))
    elif user.tenant_id is not None:
        q = q.filter(LeaveRequest.tenant_id == user.tenant_id)
    out = []
    for req in q.order_by(LeaveRequest.id.desc()).all():
        c = db.get(Courier, req.courier_id)
        out.append(
            {
                "id": req.id,
                "courier_id": req.courier_id,
                "courier": c.name if c else "—",
                "from_date": req.from_date.isoformat(),
                "to_date": req.to_date.isoformat(),
                "reason": req.reason,
                "status": req.status,
                "supervisor_comment": req.supervisor_comment,
                "admin_comment": req.admin_comment,
                "created_at": req.created_at.isoformat() if req.created_at else None,
            }
        )
    return out


@router.post("/leaves/{lid}/decide")
def decide_leave(
    lid: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """مستويان: المشرف يوافق أولاً، ثم الأدمن يوافق نهائياً."""
    leave = db.get(LeaveRequest, lid)
    if not leave:
        raise HTTPException(404, "Leave not found")
    action = payload.get("action")  # approve / reject
    if action not in ("approve", "reject"):
        raise HTTPException(400, "Action must be approve or reject")
    comment = payload.get("comment") or ""
    if user.role == UserRole.SUPERVISOR:
        if (
            not _tenant_couriers(db, user)
            .filter(Courier.id == leave.courier_id)
            .first()
        ):
            raise HTTPException(404, "Leave request not found in your team")
        if leave.status != "PENDING":
            raise HTTPException(400, "Already reviewed by supervisor")
        leave.status = "SUPERVISOR_APPROVED" if action == "approve" else "REJECTED"
        leave.supervisor_id = user.id
        leave.supervisor_comment = comment
        if action == "reject":
            leave.status = "REJECTED"
    elif user.role in COMPANY_ROLES:
        if leave.status not in ("PENDING", "SUPERVISOR_APPROVED"):
            raise HTTPException(400, "Cannot decide now")
        if action == "approve":
            if leave.status == "SUPERVISOR_APPROVED":
                leave.status = "APPROVED"
                leave.admin_id = user.id
                leave.admin_comment = comment
                c = db.get(Courier, leave.courier_id)
                if c:
                    c.is_on_leave = True
            else:
                leave.status = "SUPERVISOR_APPROVED"
                leave.supervisor_id = user.id
                leave.supervisor_comment = comment
        else:
            leave.status = "REJECTED"
            leave.admin_id = user.id
            leave.admin_comment = comment
    else:
        raise HTTPException(403, "Not allowed")
    db.commit()
    _log(db, user, f"قرار على إجازة #{lid}: {action}", "leave", lid)
    return {"ok": True, "status": leave.status}


# ===================== الأدمن/المشرف: مناديب HR =====================


@router.get("/couriers")
def hr_couriers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    month = date.today().strftime("%Y-%m")
    return [_courier_json(c, db, month) for c in _tenant_couriers(db, user).all()]


@router.patch("/couriers/{cid}")
def hr_update_courier(
    cid: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """تعديل ملف المندوب وإعادة إسناده تشغيلياً مع فرض نطاق الشركة."""
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    c = db.get(Courier, cid)
    if not c:
        raise HTTPException(404, "Courier not found")
    if not _tenant_couriers(db, user).filter(Courier.id == cid).first():
        raise HTTPException(403, "This courier is not in your group")

    company_only = {
        "phone",
        "employment_status",
        "supervisor_id",
        "contract_id",
        "contract_branch_id",
        "work_city",
    }
    if user.role not in COMPANY_ROLES and any(key in payload for key in company_only):
        raise HTTPException(
            403, "Only the company can change assignment or employment data"
        )

    changes = []
    if "phone" in payload and str(payload.get("phone") or "").strip():
        phone = str(payload["phone"]).strip()
        phone = phone if phone.startswith("966") else "966" + phone.lstrip("0")
        duplicate = (
            db.query(Courier).filter(Courier.phone == phone, Courier.id != c.id).first()
        )
        if duplicate:
            raise HTTPException(400, "Courier phone already exists")
        if phone != c.phone:
            changes.append(f"الجوال: {c.phone} → {phone}")
            c.phone = phone
            account = (
                db.query(User)
                .filter(User.courier_id == c.id, User.role == UserRole.COURIER)
                .first()
            )
            if account:
                account.phone = phone

    selected_branch = None
    assignment_fields = {
        "city_id",
        "work_city",
        "contract_id",
        "contract_branch_id",
        "primary_project_id",
        "supervisor_id",
    }
    if "contract_branch_id" in payload:
        branch_id = payload.get("contract_branch_id")
        selected_branch = db.get(ContractBranch, int(branch_id)) if branch_id else None
        if (
            not selected_branch
            or selected_branch.tenant_id != user.tenant_id
            or not selected_branch.is_active
        ):
            raise HTTPException(400, "اختر فرع تشغيل نشط تابعاً للشركة")
        try:
            city = require_active_tenant_city(
                db, user.tenant_id, selected_branch.city_id
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if payload.get("city_id") and int(payload["city_id"]) != city.id:
            raise HTTPException(400, "المدينة المختارة لا تطابق فرع التشغيل")
        contract = db.get(Contract, selected_branch.contract_id)
        project = (
            db.get(Project, selected_branch.project_id)
            if selected_branch.project_id
            else None
        )
        if (
            not contract
            or contract.tenant_id != user.tenant_id
            or not project
            or project.tenant_id != user.tenant_id
        ):
            raise HTTPException(400, "فرع العقد غير مكتمل الربط التشغيلي")
        changes.append(
            f"فرع التشغيل: {c.contract_branch_id or '—'} → {selected_branch.id}"
        )
        old_project_id = c.primary_project_id
        c.contract_branch_id = selected_branch.id
        c.contract_id = contract.id
        c.primary_project_id = project.id
        c.platform = project.name
        c.city_id = city.id
        c.work_city = selected_branch.city or city.name
        c.supervisor_id = selected_branch.supervisor_id
        if old_project_id != project.id:
            db.add(
                ProjectTransfer(
                    tenant_id=user.tenant_id,
                    courier_id=c.id,
                    from_project_id=old_project_id,
                    to_project_id=project.id,
                    changed_by=user.id,
                    note="تعديل فرع/مشرف من ملف السائق",
                )
            )
    elif any(field in payload for field in assignment_fields):
        raise HTTPException(
            400, "حدّد فرع التشغيل لتغيير المدينة أو العقد أو المشروع أو المشرف"
        )

    allowed = {
        "platform_courier_id",
        "iqama_expiry",
        "license_expiry",
        "vehicle_license_expiry",
        "passport_expiry",
        "insurance_expiry",
        "inspection_expiry",
        "work_permit_expiry",
        "vehicle_type",
        "vehicle_plate",
        "zone",
        "nationality",
        "iqama_number",
        "passport_number",
        "emergency_name",
        "emergency_phone",
        "photo_url",
        "is_on_leave",
        "employment_status",
        "base_salary",
        "per_delivery_rate",
        "bank_iban",
        "name",
    }
    date_fields = {
        "iqama_expiry",
        "license_expiry",
        "vehicle_license_expiry",
        "passport_expiry",
        "insurance_expiry",
        "inspection_expiry",
        "work_permit_expiry",
    }
    for key, value in payload.items():
        if key not in allowed or value is None:
            continue
        if key in date_fields:
            try:
                value = date.fromisoformat(value)
            except (ValueError, TypeError):
                raise HTTPException(400, f"{key} غير صالح — استخدم YYYY-MM-DD")
        if key in ("base_salary", "per_delivery_rate"):
            try:
                value = float(value)
            except (ValueError, TypeError):
                raise HTTPException(400, f"{key} يجب أن يكون رقماً")
        if getattr(c, key) != value:
            changes.append(key)
            setattr(c, key, value)
        if key == "employment_status" and value == "SUSPENDED":
            c.is_on_leave = False

    if "employment_status" in payload:
        account = (
            db.query(User)
            .filter(User.courier_id == c.id, User.role == UserRole.COURIER)
            .first()
        )
        if account:
            account.is_active = payload["employment_status"] == "ACTIVE"
            account.token_version = (account.token_version or 0) + 1
    db.commit()
    if changes:
        _log(db, user, f"عدّل مندوب {c.name}: {', '.join(changes)}", "courier", c.id)
    return {"ok": True, "updated": changes}


@router.post("/couriers/{cid}/note")
def add_note(
    cid: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    c = db.get(Courier, cid)
    if not c:
        raise HTTPException(404, "Courier not found")
    if not _tenant_couriers(db, user).filter(Courier.id == cid).first():
        raise HTTPException(403, "This courier is not in your group")
    note = (payload.get("note") or "").strip()
    if not note:
        raise HTTPException(400, "Note required")
    db.add(
        PerformanceNote(
            tenant_id=user.tenant_id,
            courier_id=cid,
            author_id=user.id,
            author_name=user.name or "—",
            note=note,
        )
    )
    db.commit()
    return {"ok": True}


@router.get("/couriers/{cid}/notes")
def courier_notes(
    cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    courier = _tenant_couriers(db, user).filter(Courier.id == cid).first()
    if not courier:
        raise HTTPException(404, "Courier not found")
    notes = (
        db.query(PerformanceNote)
        .filter(PerformanceNote.courier_id == courier.id)
        .order_by(PerformanceNote.id.desc())
        .all()
    )
    return [
        {
            "id": n.id,
            "author_name": n.author_name,
            "note": n.note,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notes
    ]


@router.post("/couriers/{cid}/rating")
def rate_courier(
    cid: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    if not _tenant_couriers(db, user).filter(Courier.id == cid).first():
        raise HTTPException(403, "This courier is not in your group")
    month = payload.get("month") or date.today().strftime("%Y-%m")
    try:
        score = float(payload.get("score") or 0)
    except (ValueError, TypeError):
        raise HTTPException(400, "score يجب أن يكون رقماً")
    if score < 1 or score > 5:
        raise HTTPException(400, "score بين 1 و 5")
    r = (
        db.query(CourierRating)
        .filter(CourierRating.courier_id == cid, CourierRating.month == month)
        .first()
    )
    if r:
        r.score = score
        r.comment = payload.get("comment") or r.comment
        r.author_id = user.id
    else:
        r = CourierRating(
            tenant_id=user.tenant_id,
            courier_id=cid,
            author_id=user.id,
            month=month,
            score=score,
            comment=payload.get("comment"),
        )
        db.add(r)
    db.commit()
    return {"ok": True, "month": month, "score": score}


@router.get("/couriers/{cid}/logs")
def courier_logs(
    cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    courier = _tenant_couriers(db, user).filter(Courier.id == cid).first()
    if not courier:
        raise HTTPException(404, "Courier not found")
    logs = (
        db.query(DailyLog)
        .filter(DailyLog.courier_id == courier.id)
        .order_by(DailyLog.log_date.desc())
        .all()
    )
    projects = {
        p.id: p.name
        for p in db.query(Project).filter(Project.tenant_id == courier.tenant_id).all()
    }
    return [
        {
            "id": log.id,
            "date": log.log_date.isoformat(),
            "project": projects.get(log.project_id),
            "orders": log.orders_count,
            "notes": log.notes,
        }
        for log in logs
    ]


# ===================== الأدمن: لوحات =====================


@router.get("/dashboard")
def hr_dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """شجرة تنظيمية + مقارنة مشرفين + مؤشر مخاطر + تلخيص أسبوعي."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    couriers = _tenant_couriers(db, user).all()
    supervisors = [
        u
        for u in db.query(User).filter(User.role == UserRole.SUPERVISOR).all()
        if u.tenant_id == user.tenant_id or user.tenant_id is None
    ]
    org = [
        {
            "id": s.id,
            "name": s.name,
            "couriers": [
                _courier_json(c, db) for c in couriers if c.supervisor_id == s.id
            ],
        }
        for s in supervisors
    ]
    org.append(
        {
            "id": 0,
            "name": "بدون مشرف",
            "couriers": [_courier_json(c, db) for c in couriers if not c.supervisor_id],
        }
    )
    sup_comp = []
    for s in supervisors:
        team = [c for c in couriers if c.supervisor_id == s.id]
        team_json = [_courier_json(c, db) for c in team]
        orders = sum(t["month_orders"] for t in team_json)
        ratings = [t["avg_rating"] for t in team_json if t["avg_rating"] is not None]
        avg = round(sum(ratings) / len(ratings), 1) if ratings else None
        sup_comp.append(
            {
                "id": s.id,
                "name": s.name,
                "couriers": len(team),
                "month_orders": orders,
                "avg_rating": avg,
            }
        )
    return {
        "org": org,
        "supervisors_compare": sup_comp,
        "couriers_total": len(couriers),
        "on_leave": sum(1 for c in couriers if c.is_on_leave),
        "suspended": sum(1 for c in couriers if c.employment_status == "SUSPENDED"),
        "risk": [
            _courier_json(c, db) for c in couriers if _courier_json(c, db)["risks"]
        ],
    }


# ===================== المشرف: بث + تقرير =====================


@router.post("/broadcast")
def hr_broadcast(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    msg = (payload.get("message") or "").strip()
    if not msg:
        raise HTTPException(400, "Message required")
    couriers = _tenant_couriers(db, user).all()
    for c in couriers:
        db.add(
            BroadcastMessage(
                tenant_id=user.tenant_id,
                sender_id=user.id,
                sender_name=user.name or "—",
                sender_role=user.role.value,
                courier_id=c.id,
                message=msg,
            )
        )
    db.commit()
    _log(db, user, f"بث رسالة إلى {len(couriers)} مندوب", "broadcast")
    return {"ok": True, "sent_to": len(couriers)}


@router.get("/weekly")
def hr_weekly(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    couriers = _tenant_couriers(db, user).all()
    week = {}
    for c in couriers:
        logs = (
            db.query(DailyLog)
            .filter(DailyLog.courier_id == c.id, DailyLog.log_date >= week_start)
            .all()
        )
        week[c.id] = sum(log.orders_count or 0 for log in logs)
    return {
        "week_start": week_start.isoformat(),
        "today": today.isoformat(),
        "couriers": [
            {"id": c.id, "name": c.name, "week_orders": week.get(c.id, 0)}
            for c in couriers
        ],
    }


@router.get("/export")
def hr_export(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """تصدير CSV لبيانات مناديب المجموعة (مستندات + أوردرات)."""
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    rows = []
    for c in _tenant_couriers(db, user).all():
        j = _courier_json(c, db)
        rows.append(
            [
                c.name,
                c.phone,
                c.platform or "",
                c.platform_courier_id or "",
                c.iqama_expiry.isoformat() if c.iqama_expiry else "",
                j["doc_days_left"]["iqama"],
                c.license_expiry.isoformat() if c.license_expiry else "",
                j["doc_days_left"]["license"],
                c.vehicle_license_expiry.isoformat()
                if c.vehicle_license_expiry
                else "",
                j["doc_days_left"]["vehicle"],
                c.vehicle_type or "",
                c.vehicle_plate or "",
                c.zone or "",
                c.employment_status or "ACTIVE",
                j["month_orders"],
                j["bonus"]["total"],
                j["avg_rating"] if j["avg_rating"] is not None else "",
            ]
        )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "Name",
            "Phone",
            "Platform",
            "PlatformID",
            "IqamaExp",
            "IqamaDays",
            "LicenseExp",
            "LicenseDays",
            "VehicleExp",
            "VehicleDays",
            "VehicleType",
            "VehiclePlate",
            "Zone",
            "Status",
            "MonthOrders",
            "BonusEarned",
            "AvgRating",
        ]
    )
    w.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=hr_report.csv"},
    )


# ===================== المشرف/الأدمن: ملفي الشخصي =====================


@router.get("/me/profile")
def hr_my_profile(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """هوية المستخدم للوحات HR (مشرف/أدمن) — تسمح بأي دور في النظام."""
    return {
        "id": user.id,
        "name": user.name or "—",
        "role": user.role.value,
        "phone": user.phone,
        "tenant_id": user.tenant_id,
    }


# ===================== المندوب: سجل يومي =====================


def _my_courier(user: User, db: Session) -> Courier:
    if user.role != UserRole.COURIER or not user.courier_id:
        raise HTTPException(403, "This account is not a courier")
    c = db.get(Courier, user.courier_id)
    if not c:
        raise HTTPException(404, "Courier not found")
    return c


@router.post("/me/log")
def add_daily_log(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    c = _my_courier(user, db)
    if c.employment_status != "ACTIVE":
        raise HTTPException(403, "المندوب غير نشط لتسجيل الأداء")
    dc = payload.get("log_date")
    try:
        log_date = date.fromisoformat(dc) if dc else date.today()
    except ValueError:
        raise HTTPException(400, "log_date غير صالح — استخدم YYYY-MM-DD")
    order_raw = payload.get("orders_count", payload.get("orders"))
    if order_raw is None or str(order_raw).strip() == "":
        raise HTTPException(400, "orders_count مطلوب")
    try:
        orders = int(order_raw)
    except (ValueError, TypeError):
        raise HTTPException(400, "orders_count يجب أن يكون رقماً")
    if orders < 0:
        raise HTTPException(400, "orders_count لا يمكن أن يكون سالباً")
    project_id = payload.get("project_id")
    if project_id is None:
        raise HTTPException(400, "project_id required")
    project = db.get(Project, int(project_id))
    if not project or project.tenant_id != c.tenant_id:
        raise HTTPException(404, "Project not found")
    if c.primary_project_id and project.id != c.primary_project_id:
        raise HTTPException(403, "يمكنك تسجيل الطلبات على مشروعك الحالي فقط")
    row = (
        db.query(DailyLog)
        .filter(
            DailyLog.courier_id == c.id,
            DailyLog.log_date == log_date,
            DailyLog.project_id == project.id,
        )
        .first()
    )
    if row:
        row.orders_count = orders
        row.notes = payload.get("notes") or row.notes
    else:
        row = DailyLog(
            courier_id=c.id,
            tenant_id=c.tenant_id,
            project_id=project.id,
            log_date=log_date,
            orders_count=orders,
            notes=payload.get("notes"),
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id, "date": log_date.isoformat(), "orders": orders}


def _my_payroll_summary(db: Session, courier: Courier, month: str) -> dict:
    period = (
        db.query(PayrollPeriod)
        .filter(
            PayrollPeriod.tenant_id == courier.tenant_id,
            PayrollPeriod.month == month,
            PayrollPeriod.status == "FINALIZED",
        )
        .first()
    )
    if period:
        snapshot = (
            db.query(PayrollSnapshot)
            .filter(
                PayrollSnapshot.payroll_period_id == period.id,
                PayrollSnapshot.courier_id == courier.id,
            )
            .first()
        )
        if snapshot:
            return {
                "month": month,
                "finalized": True,
                "source": "PAYROLL_SNAPSHOT",
                "base_salary": round(float(snapshot.base_salary or 0), 2),
                "delivery_pay": round(float(snapshot.delivery_pay or 0), 2),
                "bonus_pay": round(float(snapshot.bonus_pay or 0), 2),
                "additions": round(float(snapshot.additions or 0), 2),
                "deductions": round(float(snapshot.deductions or 0), 2),
                "net_pay": round(float(snapshot.net_pay or 0), 2),
            }
    row = calculate_payroll_preview(db, courier, month)
    return {
        "month": month,
        "finalized": False,
        "source": "PAYROLL_PREVIEW",
        "base_salary": row["base_salary"],
        "delivery_pay": row["delivery_pay"],
        "bonus_pay": round(float(row["bonus"]["earned"] or 0), 2),
        "additions": row["additions"],
        "deductions": row["deductions"],
        "net_pay": row["net_pay"],
    }


@router.get("/me/logs")
def my_logs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """سجل المندوب: تجميع شهري + تاريخ اليوم + أي شهر سابق."""
    c = _my_courier(user, db)
    today = date.today()
    cur = today.strftime("%Y-%m")
    cur_start = date(today.year, today.month, 1)
    nxt = date(today.year + (today.month // 12), today.month % 12 + 1, 1)
    cur_logs = (
        db.query(DailyLog)
        .filter(
            DailyLog.courier_id == c.id,
            DailyLog.log_date >= cur_start,
            DailyLog.log_date < nxt,
        )
        .all()
    )
    projects = {p.id: p.name for p in db.query(Project).all()}
    month_orders = sum(log.orders_count or 0 for log in cur_logs)
    today_orders = sum(log.orders_count or 0 for log in cur_logs if log.log_date == today)
    calculated_bonus = calculate_courier_bonus(db, c, cur)
    bonus = calculated_bonus["earned"]
    bonus_details = []
    if calculated_bonus["plan_id"]:
        bonus_details.append(
            {
                "project": projects.get(c.primary_project_id, "—"),
                "orders": calculated_bonus["orders"],
                "target": calculated_bonus["target"],
                "target_bonus": calculated_bonus["bonus_amount"],
                "over_target_rate": calculated_bonus["over_target_rate"],
                "achieved": calculated_bonus["achieved"],
                "remaining_orders": calculated_bonus["remaining_orders"],
                "over_orders": calculated_bonus["over_orders"],
                "earned": calculated_bonus["earned"],
            }
        )
    # الشهور السابقة (آخر 6)
    months = []
    for i in range(1, 7):
        y, m = today.year, today.month - i
        while m <= 0:
            y, m = y - 1, m + 12
        s = date(y, m, 1)
        e = date(y + (m // 12), m % 12 + 1, 1)
        logs = (
            db.query(DailyLog)
            .filter(
                DailyLog.courier_id == c.id,
                DailyLog.log_date >= s,
                DailyLog.log_date < e,
            )
            .all()
        )
        total = sum(log.orders_count or 0 for log in logs)
        days = [
            {
                "date": log.log_date.isoformat(),
                "project": projects.get(log.project_id),
                "orders": log.orders_count,
            }
            for log in logs
        ]
        months.append({"month": f"{y:04d}-{m:02d}", "total": total, "days": days})
    return {
        "today": today.isoformat(),
        "month": cur,
        "month_orders": month_orders,
        "today_orders": today_orders,
        "bonus_earned": round(bonus, 2),
        "bonus_details": bonus_details,
        "per_delivery_rate": c.per_delivery_rate or 0,
        "days": [
            {
                "date": log.log_date.isoformat(),
                "project": projects.get(log.project_id),
                "orders": log.orders_count,
                "notes": log.notes,
            }
            for log in cur_logs
        ],
        "previous_months": months,
        "payroll": _my_payroll_summary(db, c, cur),
    }


# ===================== المندوب: إجازة =====================


@router.post("/me/leave")
def request_leave(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    c = _my_courier(user, db)
    try:
        from_date = date.fromisoformat(payload.get("from_date"))
        to_date = date.fromisoformat(payload.get("to_date"))
    except (ValueError, TypeError):
        raise HTTPException(400, "التاريخ غير صالح — استخدم YYYY-MM-DD")
    if to_date < from_date:
        raise HTTPException(400, "to_date before from_date")
    reason = (payload.get("reason") or "").strip() or "إجازة"
    req = LeaveRequest(
        tenant_id=c.tenant_id,
        courier_id=c.id,
        from_date=from_date,
        to_date=to_date,
        reason=reason,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return {"ok": True, "id": req.id, "status": req.status}


@router.get("/me/leaves")
def my_leaves(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _my_courier(user, db)
    rows = (
        db.query(LeaveRequest)
        .filter(LeaveRequest.courier_id == c.id)
        .order_by(LeaveRequest.id.desc())
        .all()
    )
    return [
        {
            "id": req.id,
            "from_date": req.from_date.isoformat(),
            "to_date": req.to_date.isoformat(),
            "reason": req.reason,
            "status": req.status,
            "supervisor_comment": req.supervisor_comment,
            "admin_comment": req.admin_comment,
            "created_at": req.created_at.isoformat() if req.created_at else None,
        }
        for req in rows
    ]


# ===================== المندوب: رسائل + إشعارات =====================


@router.get("/me/messages")
def my_messages(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _my_courier(user, db)
    msgs = (
        db.query(BroadcastMessage)
        .filter(BroadcastMessage.courier_id == c.id)
        .order_by(BroadcastMessage.id.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": m.id,
            "sender_name": m.sender_name,
            "message": m.message,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msgs
    ]


@router.get("/me/hr")
def my_hr(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """ملف HR للمندوب: مستندات + تنبيهات + بونص + تقييمات + ملاحظات."""
    c = _my_courier(user, db)
    j = _courier_json(c, db)
    notes = (
        db.query(PerformanceNote)
        .filter(PerformanceNote.courier_id == c.id)
        .order_by(PerformanceNote.id.desc())
        .limit(10)
        .all()
    )
    ratings = (
        db.query(CourierRating)
        .filter(CourierRating.courier_id == c.id)
        .order_by(CourierRating.month.desc())
        .limit(12)
        .all()
    )
    sup = db.get(User, c.supervisor_id) if c.supervisor_id else None
    j["supervisor_name"] = sup.name if sup else None
    j["notes"] = [
        {
            "author_name": n.author_name,
            "note": n.note,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notes
    ]
    j["ratings"] = [
        {"month": r.month, "score": r.score, "comment": r.comment} for r in ratings
    ]
    today = date.today()
    today_logs = (
        db.query(DailyLog)
        .filter(DailyLog.courier_id == c.id, DailyLog.log_date == today)
        .all()
    )
    j["today_orders"] = sum(log.orders_count or 0 for log in today_logs)
    j["orders_earnings"] = round(j["month_orders"] * (c.per_delivery_rate or 0), 2)
    j["monthly_estimated"] = round(
        (c.base_salary or 0) + j["orders_earnings"] + (j["bonus"]["total"] or 0), 2
    )
    return j


# ===================== المندوب: وردية حية =====================


@router.post("/me/shift/start")
def start_shift(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _my_courier(user, db)
    if c.shift_started_at:
        return {
            "ok": True,
            "already": True,
            "started_at": c.shift_started_at.isoformat(),
        }
    c.shift_started_at = datetime.utcnow()
    c.is_online = True
    db.add(Attendance(courier_id=c.id, check_in=datetime.utcnow()))
    db.commit()
    return {"ok": True, "started_at": c.shift_started_at.isoformat()}


@router.post("/me/shift/stop")
def stop_shift(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _my_courier(user, db)
    if not c.shift_started_at:
        return {"ok": True, "already": False}
    att = (
        db.query(Attendance)
        .filter(Attendance.courier_id == c.id, Attendance.check_out.is_(None))
        .order_by(Attendance.id.desc())
        .first()
    )
    if att:
        att.check_out = datetime.utcnow()
    c.shift_started_at = None
    c.is_online = False
    db.commit()
    return {"ok": True, "stopped": True}


# ===================== الأدمن/المشرف: لوحة المتصدرين (Leaderboard) =====================


@router.get("/leaderboard")
def hr_leaderboard(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """ترتيب المناديب: أوردرات هذا الشهر + البونص + التقييم للتمييز عند التعادل."""
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    rows = []
    for c in _tenant_couriers(db, user).all():
        j = _courier_json(c, db)
        rows.append(
            {
                "name": c.name,
                "phone": c.phone,
                "supervisor": (
                    db.get(User, c.supervisor_id).name if c.supervisor_id else None
                ),
                "month_orders": j["month_orders"],
                "bonus": j["bonus"]["total"],
                "avg_rating": j["avg_rating"],
                "per_delivery_rate": j["per_delivery_rate"],
                "estimated_pay": round(
                    (j["month_orders"] * j["per_delivery_rate"]) + j["bonus"]["total"],
                    2,
                ),
                "zone": c.zone,
            }
        )
    rows.sort(key=lambda r: (-r["month_orders"], -(r["avg_rating"] or 0)))
    for i, r in enumerate(rows[:50], 1):
        r["rank"] = i
    return {"month": date.today().strftime("%Y-%m"), "rows": rows}


# ===================== الأدمن: كشف الرواتب (Payroll) =====================


def _contract_courier_ids(ct, db):
    if ct.scope_type in ("COURIER", "MANUAL") and ct.courier_ids:
        try:
            return [int(x) for x in json.loads(ct.courier_ids)]
        except (ValueError, TypeError, json.JSONDecodeError):
            return []
    if ct.project_id:
        return [
            x[0]
            for x in db.query(Courier.id)
            .filter(
                Courier.tenant_id == ct.tenant_id,
                Courier.primary_project_id == ct.project_id,
            )
            .all()
        ]
    return []


def _effective_contract(courier, contracts, db):
    matches = [ct for ct in contracts if courier.id in _contract_courier_ids(ct, db)]
    priority = {"COURIER": 3, "MANUAL": 2, "PROJECT": 1, "LEGACY": 0}
    return max(
        matches,
        key=lambda x: (
            priority.get(x.scope_type or "LEGACY", 0),
            x.created_at or datetime.min,
        ),
        default=None,
    )


@router.get("/payroll")
def hr_payroll(
    month: str = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """كشف الرواتب من محرك واحد؛ الفترة النهائية تُقرأ من اللقطات المحفوظة."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    selected_month = month or date.today().strftime("%Y-%m")
    try:
        calculated, finalized = payroll_rows(db, user.tenant_id, selected_month)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    period = (
        db.query(PayrollPeriod)
        .filter(
            PayrollPeriod.tenant_id == user.tenant_id,
            PayrollPeriod.month == selected_month,
        )
        .first()
    )
    period_status = period.status if period else "DRAFT"

    couriers = {
        row.id: row
        for row in db.query(Courier).filter(Courier.tenant_id == user.tenant_id).all()
    }
    rows = []
    totals = {
        "fixed": 0.0,
        "delivery": 0.0,
        "bonus": 0.0,
        "additions": 0.0,
        "gross": 0.0,
        "absences": 0.0,
        "late": 0.0,
        "advances": 0.0,
        "other_deductions": 0.0,
        "deductions": 0.0,
        "total": 0.0,
    }
    for row in calculated:
        courier = couriers.get(row.get("courier_id") or row.get("id"))
        if not courier:
            continue
        bonus = float(
            (row.get("bonus") or {}).get("earned", row.get("bonus_pay", 0)) or 0
        )
        fixed = float(row.get("base_salary") or 0)
        delivery = float(row.get("delivery_pay") or 0)
        additions = float(row.get("additions") or 0)
        deductions = float(row.get("deductions") or 0)
        total = float(row.get("net_pay") or row.get("total") or 0)
        gross = float(row.get("gross_pay") or (fixed + delivery + bonus + additions))
        absence_ded = float(row.get("absence_deduction") or 0)
        late_ded = float(row.get("late_deduction") or 0)
        advance_ded = float(row.get("advance_deduction") or 0)
        other_ded = float(
            row.get("other_deduction")
            or (deductions - (absence_ded + late_ded + advance_ded))
        )
        if other_ded < 0:
            other_ded = 0.0

        orders = int(
            row.get("eligible_orders", (row.get("bonus") or {}).get("orders", 0)) or 0
        )
        per_order_rate = float(
            row.get("per_delivery_rate")
            or (round(delivery / orders, 2) if orders else 0)
        )

        rows.append(
            {
                "id": courier.id,
                "name": courier.name,
                "phone": courier.phone,
                "platform": courier.platform or "—",
                "zone": courier.zone,
                "city": getattr(courier, "city", None) or courier.zone or "الرياض",
                "contract_name": getattr(courier, "contract_name", None)
                or courier.courier_type
                or "عقد عام",
                "orders": orders,
                "per_delivery_rate": round(per_order_rate, 2),
                "fixed": round(fixed, 2),
                "delivery": round(delivery, 2),
                "bonus": round(bonus, 2),
                "additions": round(additions, 2),
                "gross": round(gross, 2),
                "absence_deduction": round(absence_ded, 2),
                "late_deduction": round(late_ded, 2),
                "advance_deduction": round(advance_ded, 2),
                "other_deductions": round(other_ded, 2),
                "deductions": round(deductions, 2),
                "total": round(total, 2),
                "average_per_order": round(per_order_rate, 2),
                "itemized_breakdown": row.get("itemized_breakdown"),
                "bank_iban": courier.bank_iban or "—",
                "finalized": finalized,
            }
        )
        totals["fixed"] += fixed
        totals["delivery"] += delivery
        totals["bonus"] += bonus
        totals["additions"] += additions
        totals["gross"] += gross
        totals["absences"] += absence_ded
        totals["late"] += late_ded
        totals["advances"] += advance_ded
        totals["other_deductions"] += other_ded
        totals["deductions"] += deductions
        totals["total"] += total

    return {
        "month": selected_month,
        "status": period_status,
        "finalized": finalized,
        "finalized_at": period.finalized_at.isoformat()
        if (period and period.finalized_at)
        else None,
        "finalized_by": period.finalized_by if period else None,
        "rows": rows,
        "totals": {key: round(value, 2) for key, value in totals.items()},
        "couriers_count": len(rows),
    }


@router.post("/payroll/status")
def set_payroll_status(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Company admin required")
    selected_month = str(payload.get("month") or date.today().strftime("%Y-%m"))
    new_status = str(payload.get("status") or "DRAFT").upper()
    if new_status not in ("DRAFT", "UNDER_REVIEW", "APPROVED"):
        raise HTTPException(
            400, "Invalid status. Must be DRAFT, UNDER_REVIEW, or APPROVED"
        )

    period = (
        db.query(PayrollPeriod)
        .filter(
            PayrollPeriod.tenant_id == user.tenant_id,
            PayrollPeriod.month == selected_month,
        )
        .first()
    )

    if period and period.status == "FINALIZED":
        raise HTTPException(
            400, "Cannot change status of a finalized and locked period"
        )

    if not period:
        period = PayrollPeriod(
            tenant_id=user.tenant_id, month=selected_month, status=new_status
        )
        db.add(period)
    else:
        period.status = new_status
    db.commit()
    _log(
        db,
        user,
        f"عدّل حالة مسير الرواتب لشهر {selected_month} إلى {new_status}",
        "payroll_period",
        period.id,
    )
    return {"period_id": period.id, "month": selected_month, "status": new_status}


@router.get("/payroll/rider/{courier_id}/statement")
def get_rider_payroll_statement(
    courier_id: int,
    month: str = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Access denied")
    selected_month = month or date.today().strftime("%Y-%m")
    courier = (
        db.query(Courier)
        .filter(Courier.tenant_id == user.tenant_id, Courier.id == courier_id)
        .first()
    )
    if not courier:
        raise HTTPException(404, "Courier not found")

    calculated, finalized = payroll_rows(db, user.tenant_id, selected_month)
    row = next(
        (
            r
            for r in calculated
            if (r.get("courier_id") == courier_id or r.get("id") == courier_id)
        ),
        None,
    )
    if not row:
        row = calculate_payroll_preview(db, courier, selected_month)

    period = (
        db.query(PayrollPeriod)
        .filter(
            PayrollPeriod.tenant_id == user.tenant_id,
            PayrollPeriod.month == selected_month,
        )
        .first()
    )
    period_status = period.status if period else "DRAFT"

    adjustments = (
        db.query(PayrollAdjustment)
        .filter(
            PayrollAdjustment.tenant_id == user.tenant_id,
            PayrollAdjustment.courier_id == courier_id,
            PayrollAdjustment.month == selected_month,
            or_(
                PayrollAdjustment.status == "APPROVED",
                PayrollAdjustment.status.is_(None),
            ),
        )
        .all()
    )

    itemized = row.get("itemized_breakdown") or {
        "base_salary": round(float(row.get("base_salary") or 0), 2),
        "orders_count": int(
            row.get("eligible_orders") or (row.get("bonus") or {}).get("orders", 0) or 0
        ),
        "per_delivery_rate": round(float(row.get("per_delivery_rate") or 0), 2),
        "delivery_pay": round(float(row.get("delivery_pay") or 0), 2),
        "target_bonus": round(
            float((row.get("bonus") or {}).get("earned", row.get("bonus_pay", 0)) or 0),
            2,
        ),
        "overtime_pay": round(float(row.get("additions") or 0), 2),
        "other_additions": 0.0,
        "gross_pay": round(
            float(
                row.get("gross_pay")
                or (
                    float(row.get("base_salary") or 0)
                    + float(row.get("delivery_pay") or 0)
                    + float((row.get("bonus") or {}).get("earned", 0) or 0)
                    + float(row.get("additions") or 0)
                )
            ),
            2,
        ),
        "absence_deduction": round(float(row.get("absence_deduction") or 0), 2),
        "late_deduction": round(float(row.get("late_deduction") or 0), 2),
        "advance_deduction": round(float(row.get("advance_deduction") or 0), 2),
        "other_deduction": round(
            float(row.get("other_deduction") or row.get("deductions") or 0), 2
        ),
        "total_deductions": round(float(row.get("deductions") or 0), 2),
        "net_pay": round(float(row.get("net_pay") or row.get("total") or 0), 2),
    }

    return {
        "courier": {
            "id": courier.id,
            "name": courier.name,
            "phone": courier.phone,
            "contract_name": getattr(courier, "contract_name", None)
            or courier.courier_type
            or "عقد عام",
            "city": getattr(courier, "city", None) or courier.zone or "الرياض",
            "bank_iban": courier.bank_iban or "—",
            "employment_status": courier.employment_status or "ACTIVE",
        },
        "period": {
            "month": selected_month,
            "status": period_status,
            "finalized": finalized,
            "finalized_at": period.finalized_at.isoformat()
            if (period and period.finalized_at)
            else None,
        },
        "statement": itemized,
        "bonus_details": row.get("bonus") or {},
        "adjustments": [
            {
                "id": a.id,
                "kind": a.kind,
                "amount": float(a.amount or 0),
                "note": a.note,
                "source_type": a.source_type,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in adjustments
        ],
    }


@router.post("/payroll/finalize")
def finalize_payroll(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Company admin required")
    selected_month = str(payload.get("month") or date.today().strftime("%Y-%m"))
    try:
        result = finalize_payroll_period(db, user.tenant_id, selected_month, user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _log(
        db,
        user,
        f"أقفل فترة الرواتب {selected_month}",
        "payroll_period",
        result["period_id"],
    )
    return result


@router.get("/payroll/wps-export")
def hr_payroll_wps_export(
    month: str = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """تصدير بيانات المسير المقفل للتحضير البنكي؛ ليس صيغة بنك WPS رسمية."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    selected_month = month or date.today().strftime("%Y-%m")
    try:
        calculated, finalized = payroll_rows(db, user.tenant_id, selected_month)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    if not finalized:
        raise HTTPException(409, "Payroll must be finalized before bank export")
    tenant = db.get(Tenant, user.tenant_id)
    couriers = {
        row.id: row
        for row in db.query(Courier).filter(Courier.tenant_id == user.tenant_id).all()
    }
    employer_id = getattr(tenant, "cr_number", None)
    if not employer_id:
        raise HTTPException(
            409, "Company commercial registration is required for bank export"
        )
    missing = []
    for row in calculated:
        courier = couriers.get(row.get("courier_id"))
        if courier and (
            not (
                getattr(courier, "iqama_number", None)
                or getattr(courier, "national_id_or_iqama", None)
            )
            or not courier.bank_iban
        ):
            missing.append(courier.id)
    if missing:
        raise HTTPException(
            409, f"Missing identity or IBAN for {len(missing)} rider(s)"
        )

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "Employer ID / CR",
            "Employee National ID/Iqama",
            "Employee Name",
            "Bank IBAN",
            "Basic Salary (SAR)",
            "Housing Allowance",
            "Other Earnings / Commission",
            "Deductions / Advances",
            "Net Salary (SAR)",
            "Month Period",
        ]
    )
    for row in calculated:
        c = couriers.get(row["courier_id"])
        if not c:
            continue
        basic = float(row["base_salary"] or 0)
        deliveries_and_bonus = (
            float(row["delivery_pay"] or 0)
            + float(
                (row.get("bonus") or {}).get("earned", row.get("bonus_pay", 0)) or 0
            )
            + float(row["additions"] or 0)
        )
        deductions = float(row["deductions"] or 0)
        net = float(row["net_pay"] or 0)
        w.writerow(
            [
                employer_id,
                getattr(c, "iqama_number", None)
                or getattr(c, "national_id_or_iqama", None),
                c.name,
                c.bank_iban,
                f"{basic:.2f}",
                "0.00",
                f"{deliveries_and_bonus:.2f}",
                f"{deductions:.2f}",
                f"{net:.2f}",
                selected_month,
            ]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=Payroll_Bank_Preparation_{selected_month}.csv",
            "X-DOU-Export-Type": "BANK_PREPARATION_NOT_OFFICIAL_WPS",
        },
    )


@router.get("/financial/branches")
def branch_financial_report(
    month: str = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Company financial access required")
    selected_month = month or date.today().strftime("%Y-%m")
    try:
        rows, finalized = financial_rows(db, user.tenant_id, selected_month)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    contracts = {
        row.id: row
        for row in db.query(Contract).filter(Contract.tenant_id == user.tenant_id).all()
    }
    branches = {
        row.id: row
        for row in db.query(ContractBranch)
        .filter(ContractBranch.tenant_id == user.tenant_id)
        .all()
    }
    for row in rows:
        contract = contracts.get(row["contract_id"])
        branch = branches.get(row["contract_branch_id"])
        row["contract"] = contract.name if contract else "—"
        row["client"] = (
            contract.client_name
            if contract and contract.client_name
            else (contract.name if contract else "—")
        )
        row["city"] = branch.city if branch else "—"
    totals = {
        "eligible_orders": sum(int(row["eligible_orders"] or 0) for row in rows),
        "client_revenue": round(
            sum(float(row["client_revenue"] or 0) for row in rows), 2
        ),
        "direct_rider_cost": round(
            sum(float(row["direct_rider_cost"] or 0) for row in rows), 2
        ),
        "operational_margin": round(
            sum(float(row["operational_margin"] or 0) for row in rows), 2
        ),
    }
    return {
        "month": selected_month,
        "finalized": finalized,
        "rows": rows,
        "totals": totals,
        "label": "Operational Margin",
    }


# ===================== الأدمن: عقود التعاقد + التجديد =====================


@router.get("/contracts")
def hr_contracts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """عقود التعاقد مع المناديب/الأساطيل + حالة الانتهاء."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    today = date.today()
    q = db.query(Contract)
    if user.tenant_id is not None:
        q = q.filter(Contract.tenant_id == user.tenant_id)
    rows = []
    for ct in q.all():
        days = (ct.end_date.date() - today).days if ct.end_date else None
        status = ct.status
        if days is not None and days < 0:
            status = "EXPIRED"
        elif days is not None and days <= 30:
            status = "EXPIRING"
        branches = (
            db.query(ContractBranch)
            .filter(
                ContractBranch.contract_id == ct.id,
                ContractBranch.is_active.is_(True),
            )
            .order_by(ContractBranch.city)
            .all()
        )
        ids = [
            x[0]
            for x in db.query(Courier.id).filter(Courier.contract_id == ct.id).all()
        ]
        names = (
            [
                x[0]
                for x in db.query(Courier.name)
                .filter(Courier.id.in_(ids))
                .order_by(Courier.name)
                .all()
            ]
            if ids
            else []
        )
        project = db.get(Project, ct.project_id) if ct.project_id else None
        rows.append(
            {
                "id": ct.id,
                "name": ct.name,
                "contract_type": ct.contract_type,
                "scope_type": ct.scope_type or "LEGACY",
                "project_id": ct.project_id,
                "project": project.name if project else None,
                "courier_ids": ids,
                "courier_names": names,
                "duration_months": ct.duration_months,
                "couriers_count": len(ids),
                "base_salary": ct.base_salary or 0,
                "per_delivery_rate": ct.per_delivery_rate or 0,
                "client_name": ct.client_name or ct.name,
                "client_rate_per_order": ct.client_rate_per_order,
                "client_rate_effective_from": ct.client_rate_effective_from.isoformat()
                if ct.client_rate_effective_from
                else None,
                "status": status,
                "days_left": days,
                "start_date": ct.start_date.isoformat() if ct.start_date else None,
                "end_date": ct.end_date.isoformat() if ct.end_date else None,
            }
        )
        rows[-1]["branches"] = [
            {
                "id": b.id,
                "city_id": b.city_id,
                "city": b.city,
                "project_id": b.project_id,
                "project": db.get(Project, b.project_id).name
                if b.project_id and db.get(Project, b.project_id)
                else None,
                "supervisor_id": b.supervisor_id,
                "supervisor": db.get(User, b.supervisor_id).name
                if b.supervisor_id and db.get(User, b.supervisor_id)
                else None,
                "couriers_count": db.query(Courier)
                .filter(Courier.contract_branch_id == b.id)
                .count(),
            }
            for b in branches
        ]
    rows.sort(key=lambda r: r["days_left"] or 999)
    return {
        "rows": rows,
        "expiring_soon": sum(1 for r in rows if r["status"] in ("EXPIRING", "EXPIRED")),
    }


@router.post("/contracts")
def create_contract(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Contract name required")
    start = payload.get("start_date")
    if start:
        try:
            start_dt = datetime.combine(date.fromisoformat(start), datetime.min.time())
        except (ValueError, TypeError):
            raise HTTPException(400, "start_date غير صالح — استخدم YYYY-MM-DD")
    else:
        start_dt = datetime.combine(date.today(), datetime.min.time())
    end = payload.get("end_date")
    if end:
        try:
            end_dt = date.fromisoformat(end)
        except (ValueError, TypeError):
            raise HTTPException(400, "end_date غير صالح — استخدم YYYY-MM-DD")
    else:
        end_dt = date.today() + timedelta(days=365)
    # حقول التعويض القديمة تبقى للتوافق فقط؛ العقد التجاري لا يحدد راتب أو أجر مندوب.
    try:
        base_salary = float(payload.get("base_salary") or 0)
        per_delivery_rate = float(payload.get("per_delivery_rate") or 0)
        client_rate = (
            float(payload["client_rate_per_order"])
            if payload.get("client_rate_per_order") not in (None, "")
            else None
        )
    except (ValueError, TypeError):
        raise HTTPException(400, "قيم العقد غير صالحة")
    if (
        base_salary < 0
        or per_delivery_rate < 0
        or (client_rate is not None and client_rate < 0)
    ):
        raise HTTPException(400, "قيم العقد لا يمكن أن تكون سالبة")
    contract_type = str(payload.get("contract_type") or "COMMERCIAL").upper()
    if contract_type not in ("COMMERCIAL", "FIXED", "PER_DELIVERY"):
        raise HTTPException(400, "نوع العقد غير صالح")
    status = str(payload.get("status") or "ACTIVE").upper()
    if status not in ("ACTIVE", "SUSPENDED", "EXPIRED"):
        raise HTTPException(400, "حالة العقد غير صالحة")
    cities = payload.get("cities") or []
    if not isinstance(cities, list) or not cities:
        raise HTTPException(400, "أضف مدينة واحدة على الأقل للعقد")
    clean = []
    seen_city_ids = set()
    tenant = db.get(Tenant, user.tenant_id)
    for item in cities:
        item = item if isinstance(item, dict) else {"city": item}
        raw_city = str(item.get("city") or "").strip()
        city_id = item.get("city_id")
        city = None
        if city_id:
            city = db.get(GeoCity, int(city_id))
        if not city and raw_city:
            mapped_name = CITY_NAME_ALIASES.get(raw_city, raw_city)
            city = (
                db.query(GeoCity)
                .filter(func.lower(GeoCity.name) == mapped_name.lower())
                .first()
            )
            if not city and tenant:
                city = find_or_create_city(db, tenant, raw_city)
        if city and tenant:
            ensure_tenant_operating_city(db, tenant, city, active=True)
        else:
            try:
                city = (
                    require_active_tenant_city(db, user.tenant_id, int(city_id))
                    if city_id
                    else resolve_active_tenant_city_by_name(
                        db, user.tenant_id, raw_city
                    )
                )
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, str(exc))

        if city.id in seen_city_ids:
            raise HTTPException(400, "لا يمكن تكرار نفس المدينة داخل العقد")
        seen_city_ids.add(city.id)

        # Support both single supervisor_id and supervisor_ids list
        raw_sids = item.get("supervisor_ids") or (
            [] if item.get("supervisor_id") is None else [item.get("supervisor_id")]
        )
        valid_sids = []
        for sid in raw_sids:
            if sid:
                sup = db.get(User, int(sid))
                if (
                    sup
                    and sup.tenant_id == user.tenant_id
                    and sup.role == UserRole.SUPERVISOR
                    and sup.is_active
                ):
                    valid_sids.append(sup.id)
        clean.append((city, valid_sids))

    if not clean:
        raise HTTPException(400, "أضف مدينة صحيحة")
    ct = Contract(
        tenant_id=user.tenant_id,
        name=name,
        scope_type="COMMERCIAL",
        contract_type=contract_type,
        duration_months=0,
        couriers_count=0,
        base_salary=base_salary,
        per_delivery_rate=per_delivery_rate,
        client_name=(str(payload.get("client_name") or name).strip() or name),
        client_rate_per_order=client_rate,
        client_rate_effective_from=(
            start_dt.date() if client_rate is not None else None
        ),
        status=status,
        start_date=start_dt,
        end_date=end_dt,
    )
    db.add(ct)
    db.flush()
    for city, sids in clean:
        primary_sid = sids[0] if sids else None
        supervisor_name = db.get(User, primary_sid).name if primary_sid else "بدون مشرف"
        project = Project(
            tenant_id=user.tenant_id,
            name=f"{name} — {city.name} — {supervisor_name}",
            is_active=True,
            manager_id=primary_sid,
        )
        db.add(project)
        db.flush()
        branch = ContractBranch(
            tenant_id=user.tenant_id,
            contract_id=ct.id,
            city_id=city.id,
            city=city.name,
            project_id=project.id,
            supervisor_id=primary_sid,
            is_active=True,
        )
        db.add(branch)
        db.flush()
        for sid in sids:
            db.add(
                ContractBranchSupervisor(
                    tenant_id=user.tenant_id,
                    contract_branch_id=branch.id,
                    supervisor_id=sid,
                    is_primary=(sid == primary_sid),
                )
            )
    db.commit()
    db.refresh(ct)
    _log(db, user, f"أنشأ عقد {name} حتى {end_dt}", "contract", ct.id)
    return {"ok": True, "id": ct.id}


@router.patch("/contracts/{cid}")
def update_contract(
    cid: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """تعديل العقد التجاري وفروع التشغيل دون إنشاء عقد بديل."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    ct = db.get(Contract, cid)
    if not ct or ct.tenant_id != user.tenant_id:
        raise HTTPException(404, "Contract not found")
    changes = []
    if "name" in payload and str(payload.get("name") or "").strip():
        value = str(payload["name"]).strip()
        if value != ct.name:
            changes.append(f"الاسم: {ct.name} → {value}")
            ct.name = value
    if "contract_type" in payload and payload.get("contract_type"):
        value = str(payload["contract_type"]).upper()
        if value not in ("COMMERCIAL", "FIXED", "PER_DELIVERY"):
            raise HTTPException(400, "نوع العقد غير صالح")
        if value != ct.contract_type:
            changes.append(f"النوع: {ct.contract_type} → {value}")
            ct.contract_type = value
    # عقود العميل لا تعدل تعويضات المناديب؛ تظل الحقول القديمة قابلة للقراءة فقط.
    if ct.scope_type != "COMMERCIAL":
        for key in ("base_salary", "per_delivery_rate"):
            if key in payload:
                try:
                    value = float(payload[key] or 0)
                except (ValueError, TypeError):
                    raise HTTPException(400, f"{key} يجب أن يكون رقماً")
                if value < 0:
                    raise HTTPException(400, f"{key} لا يمكن أن يكون سالباً")
                if getattr(ct, key) != value:
                    changes.append(key)
                    setattr(ct, key, value)
    elif any(key in payload for key in ("base_salary", "per_delivery_rate")):
        raise HTTPException(
            400,
            "تعويض المندوب يُدار من ملف المندوب أو عقد تعويض مستقل، وليس من عقد العميل",
        )
    if "client_name" in payload:
        value = str(payload.get("client_name") or "").strip()
        if not value:
            raise HTTPException(400, "اسم العميل مطلوب")
        if ct.client_name != value:
            ct.client_name = value
            changes.append("العميل")
    if "client_rate_per_order" in payload:
        try:
            value = float(payload.get("client_rate_per_order"))
        except (ValueError, TypeError):
            raise HTTPException(400, "سعر الطلب من العميل يجب أن يكون رقماً")
        if value < 0:
            raise HTTPException(400, "سعر الطلب من العميل لا يمكن أن يكون سالباً")
        if ct.client_rate_per_order != value:
            ct.client_rate_per_order = value
            ct.client_rate_effective_from = date.today()
            changes.append("سعر الطلب من العميل")
    if "status" in payload:
        value = str(payload["status"] or "").upper()
        if value not in ("ACTIVE", "EXPIRED", "SUSPENDED"):
            raise HTTPException(400, "حالة العقد غير صالحة")
        if ct.status != value:
            changes.append(f"الحالة: {ct.status} → {value}")
            ct.status = value
    if "start_date" in payload:
        raw = payload.get("start_date")
        try:
            value = (
                datetime.combine(date.fromisoformat(raw), datetime.min.time())
                if raw
                else None
            )
        except (ValueError, TypeError):
            raise HTTPException(400, "start_date غير صالح — استخدم YYYY-MM-DD")
        if ct.start_date != value:
            changes.append("تاريخ البداية")
            ct.start_date = value
    if "end_date" in payload:
        raw = payload.get("end_date")
        try:
            value = (
                datetime.combine(date.fromisoformat(raw), datetime.min.time())
                if raw
                else None
            )
        except (ValueError, TypeError):
            raise HTTPException(400, "end_date غير صالح — استخدم YYYY-MM-DD")
        if ct.end_date != value:
            changes.append("تاريخ الانتهاء")
            ct.end_date = value

    if "branches" in payload:
        tenant = db.get(Tenant, user.tenant_id)
        rows = payload.get("branches")
        if not isinstance(rows, list) or not rows:
            raise HTTPException(400, "أضف فرع تشغيل واحداً على الأقل")
        existing = {
            branch.id: branch
            for branch in db.query(ContractBranch)
            .filter(ContractBranch.contract_id == ct.id)
            .all()
        }
        handled = set()
        seen_city_ids = set()
        for item in rows:
            if not isinstance(item, dict):
                raise HTTPException(400, "بيانات الفرع غير صالحة")
            raw_city = str(item.get("city") or "").strip()
            city_id = item.get("city_id")
            city_ref = None
            if city_id:
                city_ref = db.get(GeoCity, int(city_id))
            if not city_ref and raw_city:
                mapped_name = CITY_NAME_ALIASES.get(raw_city, raw_city)
                city_ref = (
                    db.query(GeoCity)
                    .filter(func.lower(GeoCity.name) == mapped_name.lower())
                    .first()
                )
                if not city_ref and tenant:
                    city_ref = find_or_create_city(db, tenant, raw_city)
            if city_ref and tenant:
                ensure_tenant_operating_city(db, tenant, city_ref, active=True)
            else:
                try:
                    city_ref = (
                        require_active_tenant_city(db, user.tenant_id, int(city_id))
                        if city_id
                        else resolve_active_tenant_city_by_name(
                            db, user.tenant_id, raw_city
                        )
                    )
                except (ValueError, TypeError) as exc:
                    raise HTTPException(400, str(exc))
            if city_ref.id in seen_city_ids:
                raise HTTPException(400, "لا يمكن تكرار نفس المدينة داخل العقد")
            seen_city_ids.add(city_ref.id)
            branch_id = item.get("id")
            branch = existing.get(int(branch_id)) if branch_id else None
            if branch_id and not branch:
                raise HTTPException(404, "فرع العقد غير موجود")
            supervisor_id = item.get("supervisor_id")
            supervisor = db.get(User, int(supervisor_id)) if supervisor_id else None
            if supervisor and (
                supervisor.tenant_id != user.tenant_id
                or supervisor.role != UserRole.SUPERVISOR
            ):
                raise HTTPException(400, "مشرف الفرع غير صالح")
            if not branch:
                supervisor_name = supervisor.name if supervisor else "بدون مشرف"
                project = Project(
                    tenant_id=user.tenant_id,
                    name=f"{ct.name} — {city_ref.name} — {supervisor_name}",
                    is_active=True,
                    manager_id=supervisor.id if supervisor else None,
                )
                db.add(project)
                db.flush()
                branch = ContractBranch(
                    tenant_id=user.tenant_id,
                    contract_id=ct.id,
                    city_id=city_ref.id,
                    city=city_ref.name,
                    project_id=project.id,
                    supervisor_id=supervisor.id if supervisor else None,
                    is_active=True,
                )
                db.add(branch)
                db.flush()
                changes.append(f"إضافة فرع {city_ref.name}")
            else:
                old_city, old_supervisor = branch.city, branch.supervisor_id
                branch.city_id = city_ref.id
                branch.city = city_ref.name
                branch.supervisor_id = supervisor.id if supervisor else None
                branch.is_active = True
                if old_city != city_ref.name or old_supervisor != branch.supervisor_id:
                    changes.append(f"فرع {old_city} → {city_ref.name}")
            handled.add(branch.id)
            project = db.get(Project, branch.project_id) if branch.project_id else None
            if project:
                supervisor_name = supervisor.name if supervisor else "بدون مشرف"
                project.name = f"{ct.name} — {city_ref.name} — {supervisor_name}"
                project.manager_id = supervisor.id if supervisor else None
            for courier in (
                db.query(Courier).filter(Courier.contract_branch_id == branch.id).all()
            ):
                courier.contract_id = ct.id
                courier.city_id = city_ref.id
                courier.work_city = city_ref.name
                courier.supervisor_id = supervisor.id if supervisor else None
                if project:
                    courier.primary_project_id = project.id
                    courier.platform = project.name
        for branch_id, branch in existing.items():
            if branch_id not in handled:
                branch.is_active = False
                for courier in (
                    db.query(Courier)
                    .filter(Courier.contract_branch_id == branch.id)
                    .all()
                ):
                    courier.supervisor_id = None
                changes.append(f"تعطيل فرع {branch.city}")

    db.commit()
    if changes:
        _log(db, user, f"عدّل عقد {ct.name}: {' | '.join(changes)}", "contract", ct.id)
    return {"ok": True, "updated": changes}


@router.post("/contracts/{cid}/renew")
def renew_contract(
    cid: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """تجديد عقد: إضافة مدة بالشهور وتحديث تاريخ الانتهاء."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    ct = db.get(Contract, cid)
    if not ct:
        raise HTTPException(404, "Contract not found")
    try:
        months = int(payload.get("months") or 12)
    except (ValueError, TypeError):
        raise HTTPException(400, "months يجب أن يكون رقماً")
    base = ct.end_date or datetime.utcnow()
    if base < datetime.utcnow():
        base = datetime.utcnow()
    new_end = base + timedelta(days=months * 30)
    ct.end_date = new_end
    ct.status = "ACTIVE"
    db.commit()
    _log(db, user, f"جدّد عقد {ct.name} إلى {new_end.date()}", "contract", ct.id)
    return {"ok": True, "end_date": new_end.date().isoformat()}


@router.delete("/contracts/{cid}")
def delete_contract(
    cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Company admin only")
    ct = db.get(Contract, cid)
    if not ct or ct.tenant_id != user.tenant_id:
        raise HTTPException(404, "Contract not found")

    ct.status = "EXPIRED"
    for b in db.query(ContractBranch).filter(ContractBranch.contract_id == ct.id).all():
        b.is_active = False

    db.query(Courier).filter(Courier.contract_id == ct.id).update(
        {"contract_id": None, "contract_branch_id": None}, synchronize_session=False
    )
    db.commit()
    _log(db, user, f"حذف / تعطيل العقد {ct.name}", "contract", ct.id)
    return {"ok": True}


@router.delete("/contract-branches/{bid}")
def delete_contract_branch(
    bid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in ACCOUNT_ADMIN_ROLES:
        raise HTTPException(403, "Company admin only")
    branch = db.get(ContractBranch, bid)
    if not branch or branch.tenant_id != user.tenant_id:
        raise HTTPException(404, "Branch not found")

    if not branch.is_active:
        return {"ok": True, "already_inactive": True}

    assigned_couriers = (
        db.query(Courier)
        .filter(Courier.contract_branch_id == bid)
        .count()
    )
    if assigned_couriers:
        raise HTTPException(
            409,
            f"لا يمكن حذف الفرع لأنه مرتبط بعدد {assigned_couriers} سائق. انقل السائقين إلى فرع آخر أولاً.",
        )

    branch.is_active = False
    db.commit()
    _log(db, user, f"حذف فرع العقد {branch.city}", "contract_branch", bid)
    return {"ok": True}


@router.get("/contract-structure")
def contract_structure(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in COMPANY_ROLES + (UserRole.SUPERVISOR, UserRole.PROJECT_MANAGER):
        raise HTTPException(403, "Not allowed")
    contracts = (
        db.query(Contract)
        .filter(Contract.tenant_id == user.tenant_id, Contract.status == "ACTIVE")
        .order_by(Contract.name)
        .all()
    )
    rows = []
    for ct in contracts:
        branches = []
        for b in (
            db.query(ContractBranch)
            .filter(ContractBranch.contract_id == ct.id, ContractBranch.is_active)
            .order_by(ContractBranch.city)
            .all()
        ):
            sup = db.get(User, b.supervisor_id) if b.supervisor_id else None
            assigned_sups = (
                db.query(ContractBranchSupervisor)
                .filter(ContractBranchSupervisor.contract_branch_id == b.id)
                .all()
            )
            sup_list = []
            if assigned_sups:
                for asup in assigned_sups:
                    u = db.get(User, asup.supervisor_id)
                    if u and u.is_active:
                        sup_list.append(
                            {
                                "id": u.id,
                                "name": u.name,
                                "phone": u.phone,
                                "is_primary": asup.is_primary,
                            }
                        )
            elif sup:
                sup_list.append(
                    {
                        "id": sup.id,
                        "name": sup.name,
                        "phone": sup.phone,
                        "is_primary": True,
                    }
                )

            courier_count = (
                db.query(Courier).filter(Courier.contract_branch_id == b.id).count()
            )
            branches.append(
                {
                    "id": b.id,
                    "city_id": b.city_id,
                    "city": b.city,
                    "project_id": b.project_id,
                    "supervisor_id": b.supervisor_id,
                    "supervisor": sup.name
                    if sup
                    else (sup_list[0]["name"] if sup_list else None),
                    "supervisors": sup_list,
                    "couriers_count": courier_count,
                }
            )
        if branches:
            rows.append(
                {
                    "id": ct.id,
                    "name": ct.name,
                    "client_name": ct.client_name or ct.name,
                    "branches": branches,
                }
            )
    return rows


# ===================== الأدمن/المشرف: كشف التجاوزات =====================


@router.get("/violations")
def hr_violations(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """كل المندوبين المتجاوزين: مستندات منتهية/قرب الانتهاء، موقوف، في إجازة، تقييم منخفض."""
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    date.today()
    cols = [
        "documents_expired",
        "documents_soon",
        "suspended",
        "on_leave",
        "low_rating",
    ]
    rows = []
    doc_fields = {
        "iqama": ("الإقامة", "iqama_expiry"),
        "license": ("رخصة القيادة", "license_expiry"),
        "vehicle": ("رخصة المركبة", "vehicle_license_expiry"),
        "passport": ("جواز السفر", "passport_expiry"),
        "insurance": ("التأمين", "insurance_expiry"),
        "inspection": ("الفحص الدوري", "inspection_expiry"),
        "work_permit": ("تصريح العمل", "work_permit_expiry"),
    }
    for c in _tenant_couriers(db, user).all():
        j = _courier_json(c, db)
        flags = {k: False for k in cols}
        expired = [k for k, v in j["doc_days_left"].items() if v is not None and v < 0]
        soon = [
            k for k, v in j["doc_days_left"].items() if v is not None and 0 <= v <= 30
        ]
        flags["documents_expired"] = bool(expired)
        flags["documents_soon"] = bool(soon)
        flags["suspended"] = c.employment_status == "SUSPENDED"
        flags["on_leave"] = c.is_on_leave
        flags["low_rating"] = j["avg_rating"] is not None and j["avg_rating"] < 3.5
        if any(flags.values()):
            docs = []
            for key, days in j["doc_days_left"].items():
                if key in doc_fields and days is not None and days <= 30:
                    label, field = doc_fields[key]
                    value = getattr(c, field, None)
                    docs.append(
                        {
                            "type": label,
                            "expiry": value.isoformat() if value else None,
                            "days": days,
                            "status": "EXPIRED" if days < 0 else "SOON",
                        }
                    )
            project = (
                db.get(Project, c.primary_project_id) if c.primary_project_id else None
            )
            rows.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "phone": c.phone,
                    "flags": flags,
                    "details": j["risks"],
                    "documents": docs,
                    "city": c.work_city or c.zone,
                    "project": project.name if project else c.platform,
                    "rating": j["avg_rating"],
                    "orders": j["month_orders"],
                    "supervisor": (
                        db.get(User, c.supervisor_id).name if c.supervisor_id else None
                    ),
                }
            )
    counts = {k: sum(1 for r in rows if r["flags"][k]) for k in cols}
    return {"rows": rows, "counts": counts, "total": len(rows)}

"""وحدات HR: المشرفون + المناديب + المستندات + السجل اليومي + الإجازات + البونص.
الأدمن يدير كل شيء، والمشرف يدير مناديب مجموعته فقط، والمندوب يخدم نفسه."""
from datetime import datetime, date, timedelta
import csv, io
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import (
    Attendance, AuditLog, BonusPlan, BroadcastMessage, Contract, ContractBranch, Courier, CourierRating,
    DailyLog, LeaveRequest, PerformanceNote, Project, Tenant, User, UserRole,
    SupervisorAssignmentRequest, ProjectTransfer, PayrollAdjustment, EmployeeRequest, CourierDocumentSubmission,
)
from .auth import get_current_user, hash_password

router = APIRouter(prefix="/hr", tags=["hr"])

COMPANY_ROLES = (
    UserRole.COMPANY, UserRole.COMPANY_ADMIN, UserRole.HR,
    UserRole.DOU_OPS, UserRole.DOU_ADMIN,
)
LEAVE_STATUSES = ("PENDING", "SUPERVISOR_APPROVED", "APPROVED", "REJECTED")


def calculate_target_bonus(orders: int, target: int, target_bonus: float,
                           over_target_rate: float) -> dict:
    """حساب بونص مشروع شهري.

    أقل من التارجت = صفر. عند بلوغ التارجت يستحق المبلغ الأساسي كاملًا،
    ثم يضاف سعر كل طلب منفذ فوق التارجت.
    """
    orders = max(int(orders or 0), 0)
    target = max(int(target or 0), 0)
    target_bonus = max(float(target_bonus or 0), 0.0)
    over_target_rate = max(float(over_target_rate or 0), 0.0)
    achieved = target > 0 and orders >= target
    over_orders = max(orders - target, 0) if achieved else 0
    earned = target_bonus + over_orders * over_target_rate if achieved else 0.0
    return {
        "achieved": achieved,
        "remaining_orders": max(target - orders, 0),
        "over_orders": over_orders,
        "earned": round(earned, 2),
    }


def _daily_report_data(db: Session, user: User, selected: date, project_id=None,
                       nationality=None, zone=None, supervisor_id=None,
                       log_status=None, target_status=None, attendance_status=None,
                       employment_status=None, courier_name=None, date_from=None, date_to=None):
    q = db.query(Courier).filter(Courier.tenant_id == user.tenant_id)
    if user.role == UserRole.SUPERVISOR:
        q = q.filter(Courier.supervisor_id == user.id)
    elif user.role==UserRole.PROJECT_MANAGER:
        q=q.filter(Courier.primary_project_id.in_(json.loads(user.managed_project_ids or "[]")))
    elif supervisor_id:
        q = q.filter(Courier.supervisor_id == int(supervisor_id))
    if project_id: q = q.filter(Courier.primary_project_id == int(project_id))
    if nationality: q = q.filter(Courier.nationality == nationality)
    if zone: q = q.filter(or_(Courier.work_city == zone, Courier.zone == zone))
    if employment_status: q = q.filter(Courier.employment_status == employment_status)
    if courier_name: q = q.filter(Courier.name.ilike(f"%{courier_name}%"))
    period_start = date_from or selected
    period_end = date_to or selected
    if period_start > period_end: period_start, period_end = period_end, period_start
    month_start = date(period_end.year, period_end.month, 1)
    range_start = datetime.combine(period_start, datetime.min.time())
    range_end = datetime.combine(period_end + timedelta(days=1), datetime.min.time())
    projects = {p.id: p.name for p in db.query(Project).filter(Project.tenant_id == user.tenant_id).all()}
    supervisors = {u.id: u.name for u in db.query(User).filter(User.tenant_id == user.tenant_id).all()}
    rows = []
    for c in q.order_by(Courier.name).all():
        logs = db.query(DailyLog).filter(DailyLog.courier_id == c.id, DailyLog.log_date >= month_start,
                                         DailyLog.log_date <= period_end).all()
        period_logs = [x for x in logs if period_start <= x.log_date <= period_end]
        pid = int(project_id) if project_id else c.primary_project_id
        if pid:
            period_logs = [x for x in period_logs if x.project_id == pid]
            project_logs = [x for x in logs if x.project_id == pid]
        else:
            project_logs = logs
        period_orders = sum(x.orders_count or 0 for x in period_logs)
        month_orders = sum(x.orders_count or 0 for x in project_logs)
        if log_status == "LOGGED" and not period_logs: continue
        if log_status == "NOT_LOGGED" and period_logs: continue
        attendances = db.query(Attendance).filter(Attendance.courier_id == c.id,
                                                  Attendance.check_in >= range_start,
                                                  Attendance.check_in < range_end).all()
        att_status = "حاضر" if attendances else ("إجازة" if c.is_on_leave else "لم يسجل حضور")
        if attendance_status == "PRESENT" and not attendances: continue
        if attendance_status == "ABSENT" and (attendances or c.is_on_leave): continue
        if attendance_status == "LEAVE" and not c.is_on_leave: continue
        plan = None
        if pid:
            plan = db.query(BonusPlan).filter(BonusPlan.tenant_id == c.tenant_id,
                BonusPlan.project_id == pid, BonusPlan.courier_id == c.id).first()
            if not plan:
                plan = db.query(BonusPlan).filter(BonusPlan.tenant_id == c.tenant_id,
                    BonusPlan.project_id == pid, BonusPlan.courier_id.is_(None)).first()
        target = plan.target_orders if plan else 0
        result = calculate_target_bonus(month_orders, target, plan.bonus_amount if plan else 0,
                                        plan.over_target_rate if plan else 0)
        state = "OVER" if target and result["achieved"] else "PENDING" if target else "NO_TARGET"
        if target_status and target_status != state: continue
        hours = round(sum((a.check_out-a.check_in).total_seconds()/3600 for a in attendances if a.check_out),1)
        rows.append({
            "المندوب": c.name, "الجنسية": c.nationality or "—", "المدينة": c.work_city or c.zone or "—",
            "المشرف": supervisors.get(c.supervisor_id, "—"), "المشروع": projects.get(pid, c.platform or "—"),
            "طلبات الفترة": period_orders, "أيام التسجيل": len({x.log_date for x in period_logs}),
            "طلبات الشهر": month_orders, "التارجت": target or "—",
            "حالة التارجت": (f"زائد {result['over_orders']}" if state == "OVER" else f"متبقي {result['remaining_orders']}" if state == "PENDING" else "بدون تارجت"),
            "البونص المستحق": result["earned"], "حالة الحضور": att_status,
            "أيام الحضور": len({a.check_in.date() for a in attendances}),
            "ساعات العمل": hours, "ملاحظات الفترة": " | ".join(x.notes for x in period_logs if x.notes) or "—",
            "_target_state": state,
        })
    total_orders = sum(r["طلبات الفترة"] for r in rows)
    return {"date_from": period_start.isoformat(), "date_to": period_end.isoformat(), "rows": rows, "summary": {
        "couriers": len(rows), "logged": sum(r["أيام التسجيل"] > 0 for r in rows),
        "not_logged": sum(r["أيام التسجيل"] == 0 for r in rows),
        "orders": total_orders, "average": round(total_orders / len(rows), 1) if rows else 0,
        "top": max(rows, key=lambda r: r["طلبات الفترة"])["المندوب"] if rows else "—",
    }}


@router.get("/daily-report")
def daily_report(report_date: date = None, project_id: int = None, nationality: str = None,
                 zone: str = None, supervisor_id: int = None, log_status: str = None,
                 target_status: str = None, attendance_status: str = None,
                 employment_status: str = None, courier_name: str = None,
                 date_from: date = None, date_to: date = None,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES + (UserRole.OPERATIONS, UserRole.SUPERVISOR, UserRole.PROJECT_MANAGER):
        raise HTTPException(403, "Not allowed")
    return _daily_report_data(db, user, report_date or date.today(), project_id, nationality, zone,
                              supervisor_id, log_status, target_status, attendance_status,
                              employment_status, courier_name, date_from, date_to)


@router.get("/daily-report/export")
def daily_report_export(report_date: date = None, project_id: int = None, nationality: str = None,
                        zone: str = None, supervisor_id: int = None, log_status: str = None,
                        target_status: str = None, attendance_status: str = None,
                        employment_status: str = None, courier_name: str = None,
                        date_from: date = None, date_to: date = None,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES + (UserRole.OPERATIONS, UserRole.SUPERVISOR, UserRole.PROJECT_MANAGER):
        raise HTTPException(403, "Not allowed")
    chosen = report_date or date.today()
    data = _daily_report_data(db, user, chosen, project_id, nationality, zone, supervisor_id,
                              log_status, target_status, attendance_status, employment_status, courier_name, date_from, date_to)
    output = io.StringIO(); output.write("\ufeff")
    rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in data["rows"]]
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys())); writer.writeheader(); writer.writerows(rows)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="couriers-{data["date_from"]}-{data["date_to"]}.csv"'})


def _log(db: Session, user: User, action: str, entity: str, entity_id: int = None):
    db.add(AuditLog(
        tenant_id=user.tenant_id, actor_id=user.id, actor_name=user.name or "—",
        actor_role=user.role.value, action=action, entity=entity, entity_id=entity_id,
    ))
    db.commit()


def _tenant_couriers(db: Session, user: User):
    """مناديب ضمن نطاق المستخدم: أدمن → كل شركته، مشرف → مجموعته فقط."""
    if user.role in (UserRole.COMPANY, UserRole.COMPANY_ADMIN, UserRole.HR):
        q = db.query(Courier).filter(Courier.tenant_id == user.tenant_id)
    elif user.role in (UserRole.SUPERVISOR, UserRole.PROJECT_MANAGER, UserRole.DOU_OPS, UserRole.DOU_ADMIN):
        q = db.query(Courier)
        if user.role == UserRole.SUPERVISOR:
            q = q.filter(Courier.supervisor_id == user.id)
        elif user.role==UserRole.PROJECT_MANAGER:
            q=q.filter(Courier.tenant_id==user.tenant_id,Courier.primary_project_id.in_(json.loads(user.managed_project_ids or "[]")))
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
        "vehicle": (c.vehicle_license_expiry - today).days if c.vehicle_license_expiry else None,
    }
    month = month or today.strftime("%Y-%m")
    y, m = int(month[:4]), int(month[5:7])
    start = date(y, m, 1)
    end = date(y + (m // 12), m % 12 + 1, 1) if m < 12 else date(y + 1, 1, 1)
    logs = db.query(DailyLog).filter(
        DailyLog.courier_id == c.id, DailyLog.log_date >= start, DailyLog.log_date < end
    ).all()
    month_orders = sum(l.orders_count or 0 for l in logs)
    plans = db.query(BonusPlan).filter(
        BonusPlan.tenant_id == c.tenant_id,
        (BonusPlan.courier_id == c.id) | (BonusPlan.courier_id.is_(None))
    ).all()
    bonus = {"total": 0.0, "details": []}
    # خطط المندوب الخاصة تتفوق على العامة لنفس المشروع
    covered = set()
    for p in sorted(plans, key=lambda x: 1 if x.courier_id is None else 0):
        po = sum(l.orders_count or 0 for l in logs if l.project_id == p.project_id)
        pj = db.get(Project, p.project_id)
        result = calculate_target_bonus(po, p.target_orders, p.bonus_amount, p.over_target_rate)
        b = result["earned"]
        if p.project_id in covered:
            continue
        covered.add(p.project_id)
        bonus["total"] += b
        bonus["details"].append({
            "project": pj.name if pj else "—", "target": p.target_orders, "orders": po,
            "earned": b, "scope": "courier" if p.courier_id else "project",
            "achieved": result["achieved"], "remaining_orders": result["remaining_orders"],
            "over_orders": result["over_orders"], "over_target_rate": p.over_target_rate,
        })
    ratings = db.query(CourierRating).filter(CourierRating.courier_id == c.id).all()
    avg_rating = round(sum(r.score for r in ratings) / len(ratings), 1) if ratings else None
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
        "id": c.id, "name": c.name, "phone": c.phone,
        "supervisor_id": c.supervisor_id,
        "platform": c.platform, "platform_courier_id": c.platform_courier_id,
        "iqama_expiry": c.iqama_expiry.isoformat() if c.iqama_expiry else None,
        "license_expiry": c.license_expiry.isoformat() if c.license_expiry else None,
        "vehicle_license_expiry": c.vehicle_license_expiry.isoformat() if c.vehicle_license_expiry else None,
        "passport_expiry": c.passport_expiry.isoformat() if c.passport_expiry else None,
        "insurance_expiry": c.insurance_expiry.isoformat() if c.insurance_expiry else None,
        "inspection_expiry": c.inspection_expiry.isoformat() if c.inspection_expiry else None,
        "work_permit_expiry": c.work_permit_expiry.isoformat() if c.work_permit_expiry else None,
        "iqama_number": c.iqama_number, "passport_number": c.passport_number,
        "emergency_name": c.emergency_name, "emergency_phone": c.emergency_phone,
        "vehicle_type": c.vehicle_type, "vehicle_plate": c.vehicle_plate,
        "zone": c.zone, "shift_preference": c.shift_preference, "nationality": c.nationality, "photo_url": c.photo_url,
        "doc_days_left": days_left,
        "doc_status": {k: ("expired" if v is not None and v < 0 else "soon" if v is not None and v <= 7 else "ok" if v is not None else "n/a") for k, v in days_left.items()},
        "employment_status": c.employment_status or "ACTIVE",
        "is_on_leave": c.is_on_leave,
        "base_salary": c.base_salary or 0, "per_delivery_rate": c.per_delivery_rate or 0,
        "bank_iban": c.bank_iban, "hired_at": c.hired_at.isoformat() if c.hired_at else None,
        "is_online": c.is_online, "score": c.score,
        "month_orders": month_orders, "avg_rating": avg_rating,
        "bonus": bonus, "risks": risks,
        "shift_started_at": c.shift_started_at.isoformat() if c.shift_started_at else None,
    }


# ===================== الأدمن: مشرفون =====================

@router.get("/supervisors")
def list_supervisors(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES + (UserRole.SUPERVISOR, UserRole.PROJECT_MANAGER):
        raise HTTPException(403, "Admin only")
    q = db.query(User).filter(User.role == UserRole.SUPERVISOR)
    if user.tenant_id is not None:
        q = q.filter(User.tenant_id == user.tenant_id)
    out = []
    for u in q.all():
        cnt = db.query(Courier).filter(Courier.supervisor_id == u.id).count()
        out.append({"id": u.id, "name": u.name, "phone": u.phone, "couriers_count": cnt,
                    "is_active": u.is_active})
    return out


@router.post("/supervisors")
def create_supervisor(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    sup = User(phone=phone, name=name, password_hash=hash_password(password),
               role=UserRole.SUPERVISOR, tenant_id=user.tenant_id,
               country=None, is_active=True)
    db.add(sup)
    db.commit()
    db.refresh(sup)
    _log(db, user, f"أنشأ مشرف {name}", "supervisor", sup.id)
    return {"ok": True, "id": sup.id, "name": name, "login_phone": phone, "password": password}


@router.patch("/supervisors/{sid}")
def update_supervisor(sid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    sup = db.get(User, sid)
    if not sup or sup.role != UserRole.SUPERVISOR:
        raise HTTPException(404, "Supervisor not found")
    for k, v in payload.items():
        if k in ("name", "is_active") and v is not None:
            setattr(sup, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/supervisors/{sid}")
def delete_supervisor(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
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
def assignment_candidates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != UserRole.SUPERVISOR:
        raise HTTPException(403, "Supervisor only")
    couriers = db.query(Courier).filter(
        Courier.tenant_id == user.tenant_id,
        Courier.supervisor_id.is_(None) | (Courier.supervisor_id != user.id),
    ).order_by(Courier.name).all()
    return [{
        "id": c.id, "name": c.name, "phone": c.phone,
        "platform": c.platform, "current_supervisor": db.get(User, c.supervisor_id).name if c.supervisor_id else None,
    } for c in couriers]


@router.get("/assignment-requests")
def assignment_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    q = db.query(SupervisorAssignmentRequest).filter(SupervisorAssignmentRequest.tenant_id == user.tenant_id)
    if user.role == UserRole.SUPERVISOR:
        q = q.filter(SupervisorAssignmentRequest.supervisor_id == user.id)
    return [{
        "id": r.id, "status": r.status, "note": r.note,
        "supervisor_id": r.supervisor_id,
        "supervisor": db.get(User, r.supervisor_id).name if db.get(User, r.supervisor_id) else "—",
        "courier_id": r.courier_id,
        "courier": db.get(Courier, r.courier_id).name if db.get(Courier, r.courier_id) else "—",
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in q.order_by(SupervisorAssignmentRequest.id.desc()).all()]


@router.post("/assignment-requests")
def request_assignment(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != UserRole.SUPERVISOR:
        raise HTTPException(403, "Supervisor only")
    courier = db.get(Courier, payload.get("courier_id"))
    if not courier or courier.tenant_id != user.tenant_id or courier.supervisor_id == user.id:
        raise HTTPException(404, "Courier not available")
    pending = db.query(SupervisorAssignmentRequest).filter(
        SupervisorAssignmentRequest.supervisor_id == user.id,
        SupervisorAssignmentRequest.courier_id == courier.id,
        SupervisorAssignmentRequest.status == "PENDING",
    ).first()
    if pending:
        raise HTTPException(400, "هناك طلب موافقة قائم لهذا السائق")
    row = SupervisorAssignmentRequest(
        tenant_id=user.tenant_id, supervisor_id=user.id, courier_id=courier.id,
        note=(payload.get("note") or "").strip(), status="PENDING",
    )
    db.add(row); db.commit(); db.refresh(row)
    _log(db, user, f"طلب ضم السائق {courier.name} لمجموعته", "assignment", row.id)
    return {"ok": True, "id": row.id, "status": row.status}


@router.post("/assignment-requests/{rid}/decide")
def decide_assignment(rid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    row.reviewed_by = user.id; row.reviewed_at = datetime.utcnow()
    courier = db.get(Courier, row.courier_id)
    if action == "approve" and courier:
        courier.supervisor_id = row.supervisor_id
        db.query(SupervisorAssignmentRequest).filter(
            SupervisorAssignmentRequest.courier_id == row.courier_id,
            SupervisorAssignmentRequest.status == "PENDING",
            SupervisorAssignmentRequest.id != row.id,
        ).update({"status": "REJECTED"}, synchronize_session=False)
    db.commit()
    _log(db, user, f"{'وافق على' if action == 'approve' else 'رفض'} طلب إسناد السائق", "assignment", row.id)
    return {"ok": True, "status": row.status}


# ===================== الأدمن/المشرف: مشاريع =====================

@router.get("/projects")
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR, UserRole.PROJECT_MANAGER, UserRole.COURIER)):
        raise HTTPException(403, "Not allowed")
    tenant_id = user.tenant_id
    c = None
    if user.role == UserRole.COURIER and user.courier_id:
        c = db.get(Courier, user.courier_id)
        tenant_id = c.tenant_id if c else tenant_id
    q = db.query(Project).filter(Project.tenant_id == tenant_id) if tenant_id else db.query(Project)
    return [{"id": p.id, "name": p.name, "is_active": p.is_active,"is_current":bool(c and c.primary_project_id==p.id),"manager_id":p.manager_id,"manager":db.get(User,p.manager_id).name if p.manager_id and db.get(User,p.manager_id) else None} for p in q.all()]


@router.post("/projects")
def create_project(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Project name required")
    manager_id=payload.get("manager_id")
    manager=db.get(User,int(manager_id)) if manager_id else None
    if manager and manager.tenant_id!=user.tenant_id: raise HTTPException(400,"مدير المشروع غير تابع للشركة")
    p = Project(tenant_id=user.tenant_id, name=name, manager_id=manager.id if manager else None)
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"ok": True, "id": p.id, "name": p.name}

@router.post("/couriers/{cid}/transfer-project")
def transfer_project(cid:int,payload:dict,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if user.role not in COMPANY_ROLES: raise HTTPException(403,"Admin only")
    c=_tenant_couriers(db,user).filter(Courier.id==cid).first(); p=db.get(Project,int(payload.get("project_id") or 0))
    if not c or not p or p.tenant_id!=user.tenant_id: raise HTTPException(404,"Courier or project not found")
    db.add(ProjectTransfer(tenant_id=user.tenant_id,courier_id=cid,from_project_id=c.primary_project_id,to_project_id=p.id,changed_by=user.id,note=payload.get("note")))
    c.primary_project_id=p.id;c.platform=p.name;db.commit();return {"ok":True}

@router.get("/couriers/{cid}/project-history")
def project_history(cid:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if not _tenant_couriers(db,user).filter(Courier.id==cid).first(): raise HTTPException(404,"Courier not found")
    names={p.id:p.name for p in db.query(Project).filter(Project.tenant_id==user.tenant_id).all()}
    return [{"from":names.get(x.from_project_id,"—"),"to":names.get(x.to_project_id,"—"),"note":x.note,"date":x.created_at.isoformat()} for x in db.query(ProjectTransfer).filter(ProjectTransfer.courier_id==cid).order_by(ProjectTransfer.id.desc()).all()]

@router.get("/adjustments")
def adjustments(month:str=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if user.role not in COMPANY_ROLES: raise HTTPException(403,"Not allowed")
    q=db.query(PayrollAdjustment).filter(PayrollAdjustment.tenant_id==user.tenant_id)
    if month:q=q.filter(PayrollAdjustment.month==month)
    return [{"id":x.id,"courier_id":x.courier_id,"courier":db.get(Courier,x.courier_id).name,"month":x.month,"kind":x.kind,"amount":x.amount,"note":x.note} for x in q.order_by(PayrollAdjustment.id.desc()).all()]

@router.post("/adjustments")
def add_adjustment(payload:dict,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if user.role not in COMPANY_ROLES: raise HTTPException(403,"Not allowed")
    c=_tenant_couriers(db,user).filter(Courier.id==int(payload.get("courier_id") or 0)).first()
    if not c:raise HTTPException(404,"Courier not found")
    x=PayrollAdjustment(tenant_id=user.tenant_id,courier_id=c.id,month=payload.get("month") or date.today().strftime("%Y-%m"),kind=payload.get("kind"),amount=float(payload.get("amount") or 0),note=payload.get("note"),created_by=user.id);db.add(x);db.commit();return {"ok":True}

@router.get("/employee-requests")
def employee_requests(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if user.role==UserRole.COURIER:q=db.query(EmployeeRequest).filter(EmployeeRequest.courier_id==user.courier_id)
    elif user.role in COMPANY_ROLES+(UserRole.SUPERVISOR,):q=db.query(EmployeeRequest).filter(EmployeeRequest.courier_id.in_([c.id for c in _tenant_couriers(db,user).all()]))
    else:raise HTTPException(403,"Not allowed")
    return [{"id":x.id,"courier":db.get(Courier,x.courier_id).name,"request_type":x.request_type,"title":x.title,"details":x.details,"amount":x.amount,"status":x.status,"created_at":x.created_at.isoformat()} for x in q.order_by(EmployeeRequest.id.desc()).all()]

@router.post("/employee-requests")
def create_employee_request(payload:dict,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=_my_courier(user,db); typ=payload.get("request_type")
    if typ not in ("ADVANCE","SHIFT_CHANGE","PROJECT_TRANSFER","MAINTENANCE","INCIDENT"):raise HTTPException(400,"Invalid request type")
    requested_project_id=payload.get("project_id")
    if typ=="PROJECT_TRANSFER":
        p=db.get(Project,int(requested_project_id or 0))
        if not p or p.tenant_id!=c.tenant_id:raise HTTPException(400,"اختر مشروعًا صحيحًا تابعًا لشركتك")
        requested_project_id=p.id
    x=EmployeeRequest(tenant_id=c.tenant_id,courier_id=c.id,request_type=typ,title=payload.get("title"),details=payload.get("details"),amount=float(payload.get("amount") or 0) or None,requested_project_id=requested_project_id);db.add(x);db.commit();return {"ok":True,"id":x.id}

@router.post("/employee-requests/{rid}/decide")
def decide_employee_request(rid:int,payload:dict,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if user.role not in COMPANY_ROLES+(UserRole.SUPERVISOR,):raise HTTPException(403,"Not allowed")
    x=db.get(EmployeeRequest,rid)
    if not x or not _tenant_couriers(db,user).filter(Courier.id==x.courier_id).first():raise HTTPException(404,"Request not found")
    if x.status in ("APPROVED","REJECTED"):raise HTTPException(400,"تم اتخاذ قرار نهائي على هذا الطلب بالفعل")
    approve=payload.get("action")=="approve"
    if approve and user.role==UserRole.SUPERVISOR and x.request_type in ("ADVANCE","PROJECT_TRANSFER"):
        x.status="SUPERVISOR_APPROVED";x.reviewed_by=user.id;x.review_note=payload.get("note");x.reviewed_at=datetime.utcnow();db.commit();return {"ok":True,"status":x.status}
    x.status="APPROVED" if approve else "REJECTED";x.reviewed_by=user.id;x.review_note=payload.get("note");x.reviewed_at=datetime.utcnow()
    if approve:
        courier=db.get(Courier,x.courier_id)
        if x.request_type=="ADVANCE":
            if not x.amount or x.amount<=0:raise HTTPException(400,"طلب السلفة لا يحتوي مبلغًا صحيحًا")
            db.add(PayrollAdjustment(tenant_id=x.tenant_id,courier_id=x.courier_id,month=date.today().strftime("%Y-%m"),kind="ADVANCE",amount=x.amount,note=f"سلفة معتمدة — طلب #{x.id}",created_by=user.id))
        elif x.request_type=="PROJECT_TRANSFER":
            project=db.get(Project,x.requested_project_id) if x.requested_project_id else None
            if not project or project.tenant_id!=x.tenant_id:raise HTTPException(400,"المشروع المطلوب غير صحيح")
            if courier.primary_project_id!=project.id:db.add(ProjectTransfer(tenant_id=x.tenant_id,courier_id=courier.id,from_project_id=courier.primary_project_id,to_project_id=project.id,changed_by=user.id,note=f"طلب سائق #{x.id}"));courier.primary_project_id=project.id;courier.platform=project.name
        elif x.request_type=="SHIFT_CHANGE":
            courier.shift_preference=(x.details or x.title or "وردية معدلة")[:120]
        elif x.request_type in ("MAINTENANCE","INCIDENT"):
            courier.is_available=False
    db.commit();return {"ok":True,"status":x.status}


@router.post("/me/documents")
def upload_my_document(payload:dict,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=_my_courier(user,db);data=str(payload.get("file_data") or "")
    if not data.startswith("data:") or len(data)>1_500_000:raise HTTPException(400,"الملف غير صالح أو أكبر من 1 ميجابايت")
    typ=payload.get("document_type")
    if typ not in ("IQAMA","DRIVING_LICENSE","VEHICLE_LICENSE","PASSPORT","INSURANCE","WORK_PERMIT"):raise HTTPException(400,"نوع المستند غير صحيح")
    row=CourierDocumentSubmission(tenant_id=c.tenant_id,courier_id=c.id,document_type=typ,filename=(payload.get("filename") or "document")[:180],mime_type=(payload.get("mime_type") or "application/octet-stream")[:80],file_data=data,status="PENDING")
    db.add(row);db.commit();db.refresh(row);return {"ok":True,"id":row.id,"status":row.status}


@router.get("/me/documents")
def my_documents(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=_my_courier(user,db);rows=db.query(CourierDocumentSubmission).filter(CourierDocumentSubmission.courier_id==c.id).order_by(CourierDocumentSubmission.id.desc()).all();return [_document_json(x,db) for x in rows]


def _document_json(x,db):
    c=db.get(Courier,x.courier_id);return {"id":x.id,"courier":c.name if c else "—","document_type":x.document_type,"filename":x.filename,"mime_type":x.mime_type,"status":x.status,"review_note":x.review_note,"created_at":x.created_at.isoformat() if x.created_at else None}


@router.get("/documents")
def company_documents(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if user.role not in COMPANY_ROLES+(UserRole.SUPERVISOR,):raise HTTPException(403,"Not allowed")
    ids=[c.id for c in _tenant_couriers(db,user).all()];rows=db.query(CourierDocumentSubmission).filter(CourierDocumentSubmission.courier_id.in_(ids)).order_by(CourierDocumentSubmission.id.desc()).all();return [_document_json(x,db) for x in rows]


@router.get("/documents/{did}/content")
def document_content(did:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    x=db.get(CourierDocumentSubmission,did)
    if not x or not _tenant_couriers(db,user).filter(Courier.id==x.courier_id).first():raise HTTPException(404,"Document not found")
    return {"filename":x.filename,"mime_type":x.mime_type,"file_data":x.file_data}


@router.post("/documents/{did}/decide")
def decide_document(did:int,payload:dict,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if user.role not in COMPANY_ROLES:raise HTTPException(403,"Company approval required")
    x=db.get(CourierDocumentSubmission,did)
    if not x or x.tenant_id!=user.tenant_id:raise HTTPException(404,"Document not found")
    x.status="APPROVED" if payload.get("action")=="approve" else "REJECTED";x.review_note=payload.get("note");x.reviewed_by=user.id;x.reviewed_at=datetime.utcnow();db.commit();return {"ok":True,"status":x.status}


# ===================== الأدمن/المشرف: بونص =====================

@router.get("/bonus")
def list_bonus(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    q = db.query(BonusPlan)
    if user.tenant_id is not None:
        q = q.filter(BonusPlan.tenant_id == user.tenant_id)
    out = []
    for p in q.all():
        c = db.get(Courier, p.courier_id) if p.courier_id else None
        pj = db.get(Project, p.project_id)
        out.append({
            "id": p.id, "courier_id": p.courier_id, "courier": c.name if c else "كل مندوبي المشروع",
            "project_id": p.project_id, "project": pj.name if pj else "—",
            "is_project_plan": p.courier_id is None,
            "target_orders": p.target_orders, "bonus_amount": p.bonus_amount,
            "over_target_rate": p.over_target_rate,
        })
    return out


@router.post("/bonus")
def create_bonus(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    pid = payload.get("project_id")
    if not pid:
        raise HTTPException(400, "project_id required")
    pj = db.get(Project, pid)
    if not pj or pj.tenant_id != user.tenant_id:
        raise HTTPException(404, "Project not found in your fleet")
    try:
        target_orders = int(payload.get("target_orders") or 0)
        bonus_amount = float(payload.get("bonus_amount") or 0)
        over_target_rate = float(payload.get("over_target_rate") or 0)
    except (ValueError, TypeError):
        raise HTTPException(400, "قيم رقمية غير صالحة في خطة البونص")
    if target_orders <= 0:
        raise HTTPException(400, "التارجت يجب أن يكون أكبر من صفر")
    if bonus_amount < 0 or over_target_rate < 0:
        raise HTTPException(400, "مبالغ البونص لا يمكن أن تكون سالبة")
    cid = payload.get("courier_id")
    if cid:
        c = db.get(Courier, cid)
        if not c or c.tenant_id != user.tenant_id:
            raise HTTPException(404, "Courier not found in your fleet")
        # خطة مندوب محدد: فريد لكل (مندوب, مشروع)
        dup = db.query(BonusPlan).filter(BonusPlan.courier_id == cid, BonusPlan.project_id == pid).first()
        if dup:
            raise HTTPException(400, "هناك خطة بونص لهذا المندوب على هذا المشروع")
    else:
        # خطة مشروع عامة: واحدة لكل (مشروع)
        dup = db.query(BonusPlan).filter(BonusPlan.courier_id.is_(None), BonusPlan.project_id == pid).first()
        if dup:
            raise HTTPException(400, "هناك خطة بونص عامة لهذا المشروع")
    p = BonusPlan(
        tenant_id=user.tenant_id, courier_id=cid, project_id=pid,
        target_orders=target_orders,
        bonus_amount=bonus_amount,
        over_target_rate=over_target_rate,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    _log(db, user, f"خطة بونص للمشروع {pj.name}" if not cid else f"خطة بونص للمندوب {c.name}", "bonus", p.id)
    return {"ok": True, "id": p.id}


@router.patch("/bonus/{bid}")
def update_bonus(bid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    p = db.get(BonusPlan, bid)
    if not p or (user.tenant_id is not None and p.tenant_id != user.tenant_id):
        raise HTTPException(404, "Bonus plan not found")
    try:
        target = int(payload.get("target_orders", p.target_orders))
        amount = float(payload.get("bonus_amount", p.bonus_amount))
        rate = float(payload.get("over_target_rate", p.over_target_rate))
    except (ValueError, TypeError):
        raise HTTPException(400, "قيم رقمية غير صالحة في خطة البونص")
    if target <= 0 or amount < 0 or rate < 0:
        raise HTTPException(400, "راجع التارجت ومبالغ البونص")
    p.target_orders, p.bonus_amount, p.over_target_rate = target, amount, rate
    db.commit()
    return {"ok": True}


@router.delete("/bonus/{bid}")
def delete_bonus(bid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    p = db.get(BonusPlan, bid)
    if not p or (user.tenant_id is not None and p.tenant_id != user.tenant_id):
        raise HTTPException(404, "Bonus plan not found")
    db.delete(p)
    db.commit()
    _log(db, user, f"حذف خطة بونص #{bid}", "bonus", bid)
    return {"ok": True}


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
    for l in q.order_by(LeaveRequest.id.desc()).all():
        c = db.get(Courier, l.courier_id)
        out.append({
            "id": l.id, "courier_id": l.courier_id, "courier": c.name if c else "—",
            "from_date": l.from_date.isoformat(), "to_date": l.to_date.isoformat(),
            "reason": l.reason, "status": l.status,
            "supervisor_comment": l.supervisor_comment, "admin_comment": l.admin_comment,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        })
    return out


@router.post("/leaves/{lid}/decide")
def decide_leave(lid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """مستويان: المشرف يوافق أولاً، ثم الأدمن يوافق نهائياً."""
    leave = db.get(LeaveRequest, lid)
    if not leave:
        raise HTTPException(404, "Leave not found")
    action = payload.get("action")  # approve / reject
    comment = payload.get("comment") or ""
    if user.role == UserRole.SUPERVISOR:
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
    month = "2026-%02d" % date.today().month
    return [_courier_json(c, db, month) for c in _tenant_couriers(db, user).all()]


@router.patch("/couriers/{cid}")
def hr_update_courier(cid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """تعديل بيانات HR للمندوب (مستندات، منصّة، مركبة، مشرف، تعليق/إجازة)."""
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    c = db.get(Courier, cid)
    if not c:
        raise HTTPException(404, "Courier not found")
    mine = _tenant_couriers(db, user).filter(Courier.id == cid).first()
    if not mine:
        raise HTTPException(403, "This courier is not in your group")
    if "primary_project_id" in payload:
        project_id = payload.get("primary_project_id")
        project = db.get(Project, int(project_id)) if project_id else None
        if project and project.tenant_id != user.tenant_id:
            raise HTTPException(400, "المشروع غير تابع للشركة")
        if user.role == UserRole.SUPERVISOR and project_id:
            raise HTTPException(403, "تغيير مشروع السائق يحتاج موافقة إدارة الشركة")
        old_project_id = c.primary_project_id
        if project and old_project_id != project.id:
            db.add(ProjectTransfer(tenant_id=user.tenant_id, courier_id=c.id,
                                   from_project_id=old_project_id, to_project_id=project.id,
                                   changed_by=user.id, note="تعديل من ملف السائق"))
        c.primary_project_id = project.id if project else None
        c.platform = project.name if project else None
    allowed = {
        "platform", "platform_courier_id", "iqama_expiry", "license_expiry",
        "vehicle_license_expiry", "passport_expiry", "insurance_expiry", "inspection_expiry", "work_permit_expiry",
        "vehicle_type", "vehicle_plate", "zone", "nationality", "iqama_number", "passport_number",
        "emergency_name", "emergency_phone",
        "photo_url", "is_on_leave", "supervisor_id", "employment_status",
        "base_salary", "per_delivery_rate", "bank_iban", "name",
    }
    changed = []
    for k, v in payload.items():
        if k in allowed and v is not None:
            if k in ("iqama_expiry", "license_expiry", "vehicle_license_expiry", "passport_expiry", "insurance_expiry", "inspection_expiry", "work_permit_expiry"):
                try:
                    v = date.fromisoformat(v)
                except (ValueError, TypeError):
                    raise HTTPException(400, f"{k} غير صالح — استخدم YYYY-MM-DD")
            if k in ("base_salary", "per_delivery_rate"):
                try:
                    v = float(v)
                except (ValueError, TypeError):
                    raise HTTPException(400, f"{k} يجب أن يكون رقماً")
            if k == "employment_status" and v == "SUSPENDED":
                c.is_on_leave = False
            setattr(c, k, v)
            changed.append(k)
    db.commit()
    _log(db, user, f"عدّل مندوب {c.name}: {', '.join(changed)}", "courier", c.id)
    return {"ok": True, "updated": changed}


@router.post("/couriers/{cid}/note")
def add_note(cid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    db.add(PerformanceNote(tenant_id=user.tenant_id, courier_id=cid,
                           author_id=user.id, author_name=user.name or "—", note=note))
    db.commit()
    return {"ok": True}


@router.get("/couriers/{cid}/notes")
def courier_notes(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    notes = db.query(PerformanceNote).filter(PerformanceNote.courier_id == cid).order_by(PerformanceNote.id.desc()).all()
    return [{"id": n.id, "author_name": n.author_name, "note": n.note,
             "created_at": n.created_at.isoformat() if n.created_at else None} for n in notes]


@router.post("/couriers/{cid}/rating")
def rate_courier(cid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    r = db.query(CourierRating).filter(CourierRating.courier_id == cid, CourierRating.month == month).first()
    if r:
        r.score = score
        r.comment = payload.get("comment") or r.comment
        r.author_id = user.id
    else:
        r = CourierRating(tenant_id=user.tenant_id, courier_id=cid, author_id=user.id,
                          month=month, score=score, comment=payload.get("comment"))
        db.add(r)
    db.commit()
    return {"ok": True, "month": month, "score": score}


@router.get("/couriers/{cid}/logs")
def courier_logs(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    logs = db.query(DailyLog).filter(DailyLog.courier_id == cid).order_by(DailyLog.log_date.desc()).all()
    projects = {p.id: p.name for p in db.query(Project).all()}
    return [{"id": l.id, "date": l.log_date.isoformat(), "project": projects.get(l.project_id),
             "orders": l.orders_count, "notes": l.notes} for l in logs]


# ===================== الأدمن: لوحات =====================

@router.get("/dashboard")
def hr_dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """شجرة تنظيمية + مقارنة مشرفين + مؤشر مخاطر + تلخيص أسبوعي."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    couriers = _tenant_couriers(db, user).all()
    supervisors = [u for u in db.query(User).filter(User.role == UserRole.SUPERVISOR).all() if u.tenant_id == user.tenant_id or user.tenant_id is None]
    org = [{"id": s.id, "name": s.name, "couriers": [_courier_json(c, db) for c in couriers if c.supervisor_id == s.id]} for s in supervisors]
    org.append({"id": 0, "name": "بدون مشرف", "couriers": [_courier_json(c, db) for c in couriers if not c.supervisor_id]})
    sup_comp = []
    for s in supervisors:
        team = [c for c in couriers if c.supervisor_id == s.id]
        team_json = [_courier_json(c, db) for c in team]
        orders = sum(t["month_orders"] for t in team_json)
        ratings = [t["avg_rating"] for t in team_json if t["avg_rating"] is not None]
        avg = round(sum(ratings) / len(ratings), 1) if ratings else None
        sup_comp.append({"id": s.id, "name": s.name, "couriers": len(team), "month_orders": orders, "avg_rating": avg})
    return {
        "org": org,
        "supervisors_compare": sup_comp,
        "couriers_total": len(couriers),
        "on_leave": sum(1 for c in couriers if c.is_on_leave),
        "suspended": sum(1 for c in couriers if c.employment_status == "SUSPENDED"),
        "risk": [_courier_json(c, db) for c in couriers if _courier_json(c, db)["risks"]],
    }


# ===================== المشرف: بث + تقرير =====================

@router.post("/broadcast")
def hr_broadcast(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    msg = (payload.get("message") or "").strip()
    if not msg:
        raise HTTPException(400, "Message required")
    couriers = _tenant_couriers(db, user).all()
    for c in couriers:
        db.add(BroadcastMessage(tenant_id=user.tenant_id, sender_id=user.id,
                                sender_name=user.name or "—", sender_role=user.role.value,
                                courier_id=c.id, message=msg))
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
        logs = db.query(DailyLog).filter(DailyLog.courier_id == c.id, DailyLog.log_date >= week_start).all()
        week[c.id] = sum(l.orders_count or 0 for l in logs)
    return {
        "week_start": week_start.isoformat(), "today": today.isoformat(),
        "couriers": [{"id": c.id, "name": c.name, "week_orders": week.get(c.id, 0)} for c in couriers],
    }


@router.get("/export")
def hr_export(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """تصدير CSV لبيانات مناديب المجموعة (مستندات + أوردرات)."""
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    rows = []
    for c in _tenant_couriers(db, user).all():
        j = _courier_json(c, db)
        rows.append([c.name, c.phone, c.platform or "", c.platform_courier_id or "",
                     c.iqama_expiry.isoformat() if c.iqama_expiry else "", j["doc_days_left"]["iqama"],
                     c.license_expiry.isoformat() if c.license_expiry else "", j["doc_days_left"]["license"],
                     c.vehicle_license_expiry.isoformat() if c.vehicle_license_expiry else "", j["doc_days_left"]["vehicle"],
                     c.vehicle_type or "", c.vehicle_plate or "", c.zone or "",
                     c.employment_status or "ACTIVE", j["month_orders"], j["bonus"]["total"],
                     j["avg_rating"] if j["avg_rating"] is not None else ""])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Phone", "Platform", "PlatformID", "IqamaExp", "IqamaDays", "LicenseExp", "LicenseDays",
                "VehicleExp", "VehicleDays", "VehicleType", "VehiclePlate", "Zone", "Status",
                "MonthOrders", "BonusEarned", "AvgRating"])
    w.writerows(rows)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=hr_report.csv"})


# ===================== المشرف/الأدمن: ملفي الشخصي =====================

@router.get("/me/profile")
def hr_my_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """هوية المستخدم للوحات HR (مشرف/أدمن) — تسمح بأي دور في النظام."""
    return {"id": user.id, "name": user.name or "—", "role": user.role.value,
            "phone": user.phone, "tenant_id": user.tenant_id}


# ===================== المندوب: سجل يومي =====================

def _my_courier(user: User, db: Session) -> Courier:
    if user.role != UserRole.COURIER or not user.courier_id:
        raise HTTPException(403, "This account is not a courier")
    c = db.get(Courier, user.courier_id)
    if not c:
        raise HTTPException(404, "Courier not found")
    return c


@router.post("/me/log")
def add_daily_log(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _my_courier(user, db)
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
    project=db.get(Project, int(project_id))
    if not project or project.tenant_id!=c.tenant_id:
        raise HTTPException(404, "Project not found")
    if c.primary_project_id and project.id!=c.primary_project_id:
        raise HTTPException(403,"يمكنك تسجيل الطلبات على مشروعك الحالي فقط")
    row = db.query(DailyLog).filter(DailyLog.courier_id == c.id, DailyLog.log_date == log_date,
                                    DailyLog.project_id == project.id).first()
    if row:
        row.orders_count = orders
        row.notes = payload.get("notes") or row.notes
    else:
        row = DailyLog(courier_id=c.id, tenant_id=c.tenant_id, project_id=project.id,
                       log_date=log_date, orders_count=orders, notes=payload.get("notes"))
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id, "date": log_date.isoformat(), "orders": orders}


@router.get("/me/logs")
def my_logs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """سجل المندوب: تجميع شهري + تاريخ اليوم + أي شهر سابق."""
    c = _my_courier(user, db)
    today = date.today()
    cur = today.strftime("%Y-%m")
    cur_start = date(today.year, today.month, 1)
    nxt = date(today.year + (today.month // 12), today.month % 12 + 1, 1)
    cur_logs = db.query(DailyLog).filter(DailyLog.courier_id == c.id, DailyLog.log_date >= cur_start, DailyLog.log_date < nxt).all()
    projects = {p.id: p.name for p in db.query(Project).all()}
    month_orders = sum(l.orders_count or 0 for l in cur_logs)
    today_orders = sum(l.orders_count or 0 for l in cur_logs if l.log_date == today)
    plans = db.query(BonusPlan).filter(
        BonusPlan.tenant_id == c.tenant_id,
        (BonusPlan.courier_id == c.id) | (BonusPlan.courier_id.is_(None))
    ).all()
    bonus = 0.0
    bonus_details = []
    covered = set()
    for p in sorted(plans, key=lambda x: 1 if x.courier_id is None else 0):
        if p.project_id in covered:
            continue
        covered.add(p.project_id)
        po = sum(l.orders_count or 0 for l in cur_logs if l.project_id == p.project_id)
        result = calculate_target_bonus(po, p.target_orders, p.bonus_amount, p.over_target_rate)
        bonus += result["earned"]
        bonus_details.append({
            "project": projects.get(p.project_id, "—"), "orders": po,
            "target": p.target_orders, "target_bonus": p.bonus_amount,
            "over_target_rate": p.over_target_rate, **result,
        })
    # الشهور السابقة (آخر 6)
    months = []
    for i in range(1, 7):
        y, m = today.year, today.month - i
        while m <= 0:
            y, m = y - 1, m + 12
        s = date(y, m, 1)
        e = date(y + (m // 12), m % 12 + 1, 1)
        logs = db.query(DailyLog).filter(DailyLog.courier_id == c.id, DailyLog.log_date >= s, DailyLog.log_date < e).all()
        total = sum(l.orders_count or 0 for l in logs)
        days = [{"date": l.log_date.isoformat(), "project": projects.get(l.project_id), "orders": l.orders_count} for l in logs]
        months.append({"month": f"{y:04d}-{m:02d}", "total": total, "days": days})
    return {
        "today": today.isoformat(), "month": cur, "month_orders": month_orders,
        "today_orders": today_orders, "bonus_earned": round(bonus, 2),
        "bonus_details": bonus_details,
        "per_delivery_rate": c.per_delivery_rate or 0,
        "days": [{"date": l.log_date.isoformat(), "project": projects.get(l.project_id),
                  "orders": l.orders_count, "notes": l.notes} for l in cur_logs],
        "previous_months": months,
    }


# ===================== المندوب: إجازة =====================

@router.post("/me/leave")
def request_leave(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _my_courier(user, db)
    try:
        from_date = date.fromisoformat(payload.get("from_date"))
        to_date = date.fromisoformat(payload.get("to_date"))
    except (ValueError, TypeError):
        raise HTTPException(400, "التاريخ غير صالح — استخدم YYYY-MM-DD")
    if to_date < from_date:
        raise HTTPException(400, "to_date before from_date")
    reason = (payload.get("reason") or "").strip() or "إجازة"
    l = LeaveRequest(tenant_id=c.tenant_id, courier_id=c.id, from_date=from_date,
                     to_date=to_date, reason=reason)
    db.add(l)
    db.commit()
    db.refresh(l)
    return {"ok": True, "id": l.id, "status": l.status}


@router.get("/me/leaves")
def my_leaves(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _my_courier(user, db)
    rows = db.query(LeaveRequest).filter(LeaveRequest.courier_id == c.id).order_by(LeaveRequest.id.desc()).all()
    return [{"id": l.id, "from_date": l.from_date.isoformat(), "to_date": l.to_date.isoformat(),
             "reason": l.reason, "status": l.status,
             "supervisor_comment": l.supervisor_comment, "admin_comment": l.admin_comment,
             "created_at": l.created_at.isoformat() if l.created_at else None} for l in rows]


# ===================== المندوب: رسائل + إشعارات =====================

@router.get("/me/messages")
def my_messages(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _my_courier(user, db)
    msgs = db.query(BroadcastMessage).filter(BroadcastMessage.courier_id == c.id).order_by(BroadcastMessage.id.desc()).limit(20).all()
    return [{"id": m.id, "sender_name": m.sender_name, "message": m.message,
             "created_at": m.created_at.isoformat() if m.created_at else None} for m in msgs]


@router.get("/me/hr")
def my_hr(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """ملف HR للمندوب: مستندات + تنبيهات + بونص + تقييمات + ملاحظات."""
    c = _my_courier(user, db)
    j = _courier_json(c, db)
    notes = db.query(PerformanceNote).filter(PerformanceNote.courier_id == c.id).order_by(PerformanceNote.id.desc()).limit(10).all()
    ratings = db.query(CourierRating).filter(CourierRating.courier_id == c.id).order_by(CourierRating.month.desc()).limit(12).all()
    sup = db.get(User, c.supervisor_id) if c.supervisor_id else None
    j["supervisor_name"] = sup.name if sup else None
    j["notes"] = [{"author_name": n.author_name, "note": n.note,
                   "created_at": n.created_at.isoformat() if n.created_at else None} for n in notes]
    j["ratings"] = [{"month": r.month, "score": r.score, "comment": r.comment} for r in ratings]
    today = date.today()
    today_logs = db.query(DailyLog).filter(DailyLog.courier_id == c.id, DailyLog.log_date == today).all()
    j["today_orders"] = sum(l.orders_count or 0 for l in today_logs)
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
        return {"ok": True, "already": True, "started_at": c.shift_started_at.isoformat()}
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
    att = db.query(Attendance).filter(Attendance.courier_id == c.id, Attendance.check_out.is_(None)).order_by(Attendance.id.desc()).first()
    if att:
        att.check_out = datetime.utcnow()
    c.shift_started_at = None
    c.is_online = False
    db.commit()
    return {"ok": True, "stopped": True}


# ===================== الأدمن/المشرف: لوحة المتصدرين (Leaderboard) =====================

@router.get("/leaderboard")
def hr_leaderboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """ترتيب المناديب: أوردرات هذا الشهر + البونص + التقييم للتمييز عند التعادل."""
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    rows = []
    for c in _tenant_couriers(db, user).all():
        j = _courier_json(c, db)
        rows.append({"name": c.name, "phone": c.phone, "supervisor": (db.get(User, c.supervisor_id).name if c.supervisor_id else None),
                     "month_orders": j["month_orders"], "bonus": j["bonus"]["total"],
                     "avg_rating": j["avg_rating"], "per_delivery_rate": j["per_delivery_rate"],
                     "estimated_pay": round((j["month_orders"] * j["per_delivery_rate"]) + j["bonus"]["total"], 2),
                     "zone": c.zone})
    rows.sort(key=lambda r: (-r["month_orders"], -(r["avg_rating"] or 0)))
    for i, r in enumerate(rows[:50], 1):
        r["rank"] = i
    return {"month": date.today().strftime("%Y-%m"), "rows": rows}


# ===================== الأدمن: كشف الرواتب (Payroll) =====================

def _contract_courier_ids(ct, db):
    if ct.scope_type in ("COURIER", "MANUAL") and ct.courier_ids:
        try: return [int(x) for x in json.loads(ct.courier_ids)]
        except (ValueError, TypeError, json.JSONDecodeError): return []
    if ct.project_id:
        return [x[0] for x in db.query(Courier.id).filter(Courier.tenant_id==ct.tenant_id, Courier.primary_project_id==ct.project_id).all()]
    return []

def _effective_contract(courier, contracts, db):
    matches=[ct for ct in contracts if courier.id in _contract_courier_ids(ct,db)]
    priority={"COURIER":3,"MANUAL":2,"PROJECT":1,"LEGACY":0}
    return max(matches,key=lambda x:(priority.get(x.scope_type or "LEGACY",0),x.created_at or datetime.min),default=None)

@router.get("/payroll")
def hr_payroll(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """كشف رواتب شهر محدد: راتب ثابت + (أوردرات × أجر التوصيلة) + بونص."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    rows = []
    grand = {"fixed": 0.0, "delivery": 0.0, "bonus": 0.0, "total": 0.0}
    contracts=db.query(Contract).filter(Contract.tenant_id==user.tenant_id,Contract.status=="ACTIVE").all()
    for c in _tenant_couriers(db, user).all():
        j = _courier_json(c, db)
        ct=_effective_contract(c,contracts,db)
        fixed = (ct.base_salary if ct else c.base_salary) or 0
        rate = (ct.per_delivery_rate if ct else c.per_delivery_rate) or 0
        delivery = (j["month_orders"] * rate)
        bonus = j["bonus"]["total"]
        adjs=db.query(PayrollAdjustment).filter(PayrollAdjustment.courier_id==c.id,PayrollAdjustment.month==date.today().strftime("%Y-%m")).all()
        additions=sum(x.amount or 0 for x in adjs if x.kind=="OVERTIME"); deductions=sum(x.amount or 0 for x in adjs if x.kind!="OVERTIME")
        total = round(fixed + delivery + bonus + additions - deductions, 2)
        rows.append({"id": c.id, "name": c.name, "phone": c.phone, "platform": c.platform or "—",
                     "zone": c.zone, "orders": j["month_orders"], "fixed": round(fixed, 2), "contract":ct.name if ct else "—",
                     "delivery": round(delivery, 2), "bonus": round(bonus, 2), "additions":round(additions,2),"deductions":round(deductions,2), "total": total,
                     "average_per_order": round(delivery / j["month_orders"], 2) if j["month_orders"] else 0,
                     "bank_iban": c.bank_iban or "—"})
        grand["fixed"] += fixed; grand["delivery"] += delivery
        grand["bonus"] += bonus; grand["total"] += total
    return {"month": date.today().strftime("%Y-%m"), "rows": rows, "totals": {k: round(v, 2) for k, v in grand.items()},
            "couriers_count": len(rows)}


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
        branches=db.query(ContractBranch).filter(ContractBranch.contract_id==ct.id).order_by(ContractBranch.city).all()
        ids=[x[0] for x in db.query(Courier.id).filter(Courier.contract_id==ct.id).all()]; names=[x[0] for x in db.query(Courier.name).filter(Courier.id.in_(ids)).order_by(Courier.name).all()] if ids else []
        project=db.get(Project,ct.project_id) if ct.project_id else None
        rows.append({"id": ct.id, "name": ct.name, "contract_type": ct.contract_type,
                     "scope_type":ct.scope_type or "LEGACY","project_id":ct.project_id,"project":project.name if project else None,
                     "courier_ids":ids,"courier_names":names,"duration_months": ct.duration_months, "couriers_count": len(ids),
                     "base_salary": ct.base_salary or 0, "per_delivery_rate": ct.per_delivery_rate or 0,
                     "status": status, "days_left": days,
                     "end_date": ct.end_date.isoformat() if ct.end_date else None})
        rows[-1]["branches"]=[{"id":b.id,"city":b.city,"project_id":b.project_id,"project":db.get(Project,b.project_id).name if b.project_id and db.get(Project,b.project_id) else None,"supervisor_id":b.supervisor_id,"supervisor":db.get(User,b.supervisor_id).name if b.supervisor_id and db.get(User,b.supervisor_id) else None,"couriers_count":db.query(Courier).filter(Courier.contract_branch_id==b.id).count()} for b in branches]
    rows.sort(key=lambda r: (r["days_left"] or 999))
    return {"rows": rows, "expiring_soon": sum(1 for r in rows if r["status"] in ("EXPIRING", "EXPIRED"))}


@router.post("/contracts")
def create_contract(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Admin only")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Contract name required")
    end = payload.get("end_date")
    if end:
        try:
            end_dt = date.fromisoformat(end)
        except (ValueError, TypeError):
            raise HTTPException(400, "end_date غير صالح — استخدم YYYY-MM-DD")
    else:
        end_dt = date.today() + timedelta(days=365)
    cities=payload.get("cities") or []
    if not isinstance(cities,list) or not cities: raise HTTPException(400,"أضف مدينة واحدة على الأقل للعقد")
    clean=[]
    for item in cities:
        city=(item.get("city") if isinstance(item,dict) else item or "").strip()
        sid=item.get("supervisor_id") if isinstance(item,dict) else None
        if not city: continue
        sup=db.get(User,int(sid)) if sid else None
        if sup and (sup.tenant_id!=user.tenant_id or sup.role!=UserRole.SUPERVISOR): raise HTTPException(400,"مشرف الفرع غير صالح")
        clean.append((city,sup.id if sup else None))
    if not clean: raise HTTPException(400,"أضف مدينة صحيحة")
    ct = Contract(
        tenant_id=user.tenant_id, name=name,
        scope_type="COMMERCIAL", contract_type="COMMERCIAL", duration_months=0,
        couriers_count=0, base_salary=0, per_delivery_rate=0,
        status="ACTIVE", end_date=end_dt,
    )
    db.add(ct);db.flush()
    for city,sid in clean:
        project=Project(tenant_id=user.tenant_id,name=f"{name} — {city}",is_active=True,manager_id=sid);db.add(project);db.flush()
        db.add(ContractBranch(tenant_id=user.tenant_id,contract_id=ct.id,city=city,project_id=project.id,supervisor_id=sid,is_active=True))
    db.commit(); db.refresh(ct)
    _log(db, user, f"أنشأ عقد {name} حتى {end_dt}", "contract", ct.id)
    return {"ok": True, "id": ct.id}


@router.post("/contracts/{cid}/renew")
def renew_contract(cid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    if (base < datetime.utcnow()):
        base = datetime.utcnow()
    new_end = base + timedelta(days=months * 30)
    ct.end_date = new_end
    ct.status = "ACTIVE"
    db.commit()
    _log(db, user, f"جدّد عقد {ct.name} إلى {new_end.date()}", "contract", ct.id)
    return {"ok": True, "end_date": new_end.date().isoformat()}

@router.get("/contract-structure")
def contract_structure(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES + (UserRole.SUPERVISOR,UserRole.PROJECT_MANAGER): raise HTTPException(403,"Not allowed")
    contracts=db.query(Contract).filter(Contract.tenant_id==user.tenant_id,Contract.status=="ACTIVE").order_by(Contract.name).all()
    rows=[]
    for ct in contracts:
        if not db.query(ContractBranch).filter(ContractBranch.contract_id==ct.id).first() and ct.project_id:
            db.add(ContractBranch(tenant_id=user.tenant_id,contract_id=ct.id,city="غير محدد",project_id=ct.project_id,is_active=True));db.flush()
        branches=[]
        for b in db.query(ContractBranch).filter(ContractBranch.contract_id==ct.id,ContractBranch.is_active==True).order_by(ContractBranch.city).all():
            sup=db.get(User,b.supervisor_id) if b.supervisor_id else None
            branches.append({"id":b.id,"city":b.city,"project_id":b.project_id,"supervisor_id":b.supervisor_id,"supervisor":sup.name if sup else None})
        if branches: rows.append({"id":ct.id,"name":ct.name,"branches":branches})
    db.commit();return rows


# ===================== الأدمن/المشرف: كشف التجاوزات =====================

@router.get("/violations")
def hr_violations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """كل المندوبين المتجاوزين: مستندات منتهية/قرب الانتهاء، موقوف، في إجازة، تقييم منخفض."""
    if user.role not in (COMPANY_ROLES + (UserRole.SUPERVISOR,)):
        raise HTTPException(403, "Not allowed")
    today = date.today()
    cols = ["documents_expired", "documents_soon", "suspended", "on_leave", "low_rating"]
    rows = []
    doc_fields={"iqama":("الإقامة", "iqama_expiry"),"license":("رخصة القيادة","license_expiry"),"vehicle":("رخصة المركبة","vehicle_license_expiry"),"passport":("جواز السفر","passport_expiry"),"insurance":("التأمين","insurance_expiry"),"inspection":("الفحص الدوري","inspection_expiry"),"work_permit":("تصريح العمل","work_permit_expiry")}
    for c in _tenant_couriers(db, user).all():
        j = _courier_json(c, db)
        flags = {k: False for k in cols}
        expired = [k for k, v in j["doc_days_left"].items() if v is not None and v < 0]
        soon = [k for k, v in j["doc_days_left"].items() if v is not None and 0 <= v <= 30]
        flags["documents_expired"] = bool(expired)
        flags["documents_soon"] = bool(soon)
        flags["suspended"] = c.employment_status == "SUSPENDED"
        flags["on_leave"] = c.is_on_leave
        flags["low_rating"] = j["avg_rating"] is not None and j["avg_rating"] < 3.5
        if any(flags.values()):
            docs=[]
            for key,days in j["doc_days_left"].items():
                if key in doc_fields and days is not None and days<=30:
                    label,field=doc_fields[key];value=getattr(c,field,None)
                    docs.append({"type":label,"expiry":value.isoformat() if value else None,"days":days,"status":"EXPIRED" if days<0 else "SOON"})
            project=db.get(Project,c.primary_project_id) if c.primary_project_id else None
            rows.append({"id": c.id, "name": c.name, "phone": c.phone, "flags": flags,
                         "details": j["risks"],"documents":docs,"city":c.work_city or c.zone,"project":project.name if project else c.platform,
                         "rating": j["avg_rating"], "orders": j["month_orders"],
                         "supervisor": (db.get(User, c.supervisor_id).name if c.supervisor_id else None)})
    counts = {k: sum(1 for r in rows if r["flags"][k]) for k in cols}
    return {"rows": rows, "counts": counts, "total": len(rows)}

"""Supervisor operational experience endpoints (Batch 1)."""

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import entities as ent
from ..services.workforce_scope import supervisor_courier_scope
from .auth import get_current_user
from .shifts import _assigned_courier_ids, _shift_json

router = APIRouter(prefix="/supervisor", tags=["supervisor"])

SUPERVISOR_ROLES = {
    ent.UserRole.SUPERVISOR,
    ent.UserRole.DOU_OPS,
    ent.UserRole.DOU_ADMIN,
}


# ---------- helpers ----------


def _supervisor_only(user: ent.User) -> int:
    if user.role not in SUPERVISOR_ROLES or not user.tenant_id:
        raise HTTPException(403, "Supervisor workspace access required")
    return user.tenant_id


def _scoped_courier_ids(db, tenant_id: int, supervisor_id: int):
    rows = (
        db.query(ent.Courier.id)
        .filter(supervisor_courier_scope(db, supervisor_id))
        .all()
    )
    return {row[0] for row in rows}


# ---------- supervisor overview ----------


@router.get("/overview")
def supervisor_overview(
    user: ent.User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Key operational metrics scoped to the supervisor's workforce."""
    tenant_id = _supervisor_only(user)
    courier_ids = _scoped_courier_ids(db, tenant_id, user.id)
    today = date.today()

    if not courier_ids:
        return {
            "assigned_riders": 0,
            "active_riders": 0,
            "attendance_today": 0,
            "absent_today": 0,
            "below_target": 0,
            "incomplete_onboarding": 0,
            "period": today.isoformat(),
        }

    active_riders = (
        db.query(func.count(ent.Courier.id))
        .filter(
            ent.Courier.id.in_(courier_ids),
            ent.Courier.employment_status == "ACTIVE",
        )
        .scalar()
        or 0
    )

    attended_today = (
        db.query(func.count(func.distinct(ent.Attendance.courier_id)))
        .filter(
            ent.Attendance.courier_id.in_(courier_ids),
            ent.Attendance.check_in >= datetime.combine(today, datetime.min.time()),
        )
        .scalar()
        or 0
    )

    below_target = (
        db.query(func.count(ent.Target.id))
        .filter(
            ent.Target.tenant_id == tenant_id,
            ent.Target.scope_type == "RIDER",
            ent.Target.scope_id.in_(courier_ids),
            ent.Target.period == today.strftime("%Y-%m"),
            ent.Target.achievement_percentage < 80,
        )
        .scalar()
        or 0
    )

    incomplete_onboarding = (
        db.query(func.count(ent.OperationalReadinessState.courier_id))
        .filter(
            ent.OperationalReadinessState.tenant_id == tenant_id,
            ent.OperationalReadinessState.courier_id.in_(courier_ids),
            ent.OperationalReadinessState.onboarding_status != "READY_TO_WORK",
        )
        .scalar()
        or 0
    )

    return {
        "assigned_riders": len(courier_ids),
        "active_riders": active_riders,
        "attendance_today": attended_today,
        "absent_today": max(0, active_riders - attended_today),
        "below_target": below_target,
        "incomplete_onboarding": incomplete_onboarding,
        "period": today.isoformat(),
    }


# ---------- my riders ----------


@router.get("/riders")
def supervisor_riders(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the supervisor's scoped riders with search and status filters."""
    _supervisor_only(user)
    query = db.query(ent.Courier).filter(supervisor_courier_scope(db, user.id))

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            ent.Courier.name.ilike(term) | ent.Courier.phone.ilike(term)
        )
    if status:
        query = query.filter(ent.Courier.employment_status == status.upper())

    riders = query.order_by(ent.Courier.name).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "phone": r.phone,
            "employment_status": r.employment_status,
            "is_online": r.is_online,
            "city_id": r.city_id,
            "work_city": r.work_city,
        }
        for r in riders
    ]


# ---------- attendance ----------


@router.get("/attendance")
def supervisor_attendance(
    attendance_date: Optional[date] = Query(None),
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """View team attendance for a given date (defaults to today)."""
    tenant_id = _supervisor_only(user)
    courier_ids = _scoped_courier_ids(db, tenant_id, user.id)
    target_date = attendance_date or date.today()
    if hasattr(target_date, "default"):
        target_date = target_date.default
    if target_date is None:
        target_date = date.today()
    if not courier_ids:
        return []

    rows = (
        db.query(ent.Attendance)
        .filter(
            ent.Attendance.courier_id.in_(courier_ids),
            ent.Attendance.check_in
            >= datetime.combine(target_date, datetime.min.time()),
            ent.Attendance.check_in
            < datetime.combine(target_date + timedelta(days=1), datetime.min.time()),
        )
        .all()
    )

    courier_map = {
        c.id: c
        for c in db.query(ent.Courier).filter(ent.Courier.id.in_(courier_ids)).all()
    }

    return [
        {
            "courier_id": row.courier_id,
            "courier_name": courier_map[row.courier_id].name
            if row.courier_id in courier_map
            else None,
            "check_in": row.check_in.isoformat() if row.check_in else None,
            "check_out": row.check_out.isoformat() if row.check_out else None,
            "is_late": row.is_late,
            "shift_id": row.shift_id,
        }
        for row in rows
    ]


# ---------- performance ----------


@router.get("/performance")
def supervisor_performance(
    period: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """View rider performance scoped to the supervisor's workforce."""
    tenant_id = _supervisor_only(user)
    courier_ids = _scoped_courier_ids(db, tenant_id, user.id)
    today = date.today()
    if not period:
        period = today.strftime("%Y-%m")
    if not courier_ids:
        return {"period": period, "riders": []}

    rows = (
        db.query(ent.DailyLog)
        .filter(
            ent.DailyLog.tenant_id == tenant_id,
            ent.DailyLog.courier_id.in_(courier_ids),
            func.strftime("%Y-%m", ent.DailyLog.log_date) == period,
        )
        .all()
    )

    orders_by_courier = {}
    for log in rows:
        orders_by_courier[log.courier_id] = orders_by_courier.get(log.courier_id, 0) + (
            log.orders_count or 0
        )

    courier_map = {
        c.id: c
        for c in db.query(ent.Courier).filter(ent.Courier.id.in_(courier_ids)).all()
    }

    riders = []
    for courier_id, orders in orders_by_courier.items():
        courier = courier_map.get(courier_id)
        riders.append(
            {
                "courier_id": courier_id,
                "courier_name": courier.name if courier else None,
                "completed_orders": orders,
                "employment_status": courier.employment_status if courier else None,
            }
        )

    return {"period": period, "riders": riders}


# ---------- needs attention ----------


@router.get("/needs-attention")
def supervisor_needs_attention(
    user: ent.User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Operational exceptions scoped to the supervisor's workforce."""
    tenant_id = _supervisor_only(user)
    courier_ids = _scoped_courier_ids(db, tenant_id, user.id)
    today = date.today()
    items = []

    if not courier_ids:
        return {"items": [], "total": 0, "period": today.isoformat()}

    # Absent riders (active but not checked in today)
    active_ids = {
        c.id
        for c in db.query(ent.Courier)
        .filter(
            ent.Courier.id.in_(courier_ids),
            ent.Courier.employment_status == "ACTIVE",
        )
        .all()
    }
    attended_ids = {
        row[0]
        for row in db.query(func.distinct(ent.Attendance.courier_id))
        .filter(
            ent.Attendance.courier_id.in_(courier_ids),
            ent.Attendance.check_in >= datetime.combine(today, datetime.min.time()),
        )
        .all()
    }
    absent_count = len(active_ids - attended_ids)
    if absent_count:
        items.append(
            {
                "signal": "absent_riders",
                "severity": "high" if absent_count > 5 else "medium",
                "count": absent_count,
                "title_ar": f"{absent_count} مندوب غائب اليوم",
                "title_en": f"{absent_count} riders absent today",
            }
        )

    # Incomplete onboarding
    incomplete = (
        db.query(func.count(ent.OperationalReadinessState.courier_id))
        .filter(
            ent.OperationalReadinessState.tenant_id == tenant_id,
            ent.OperationalReadinessState.courier_id.in_(courier_ids),
            ent.OperationalReadinessState.onboarding_status != "READY_TO_WORK",
        )
        .scalar()
        or 0
    )
    if incomplete:
        items.append(
            {
                "signal": "incomplete_onboarding",
                "severity": "medium",
                "count": incomplete,
                "title_ar": f"{incomplete} مندوب غير مكتمل التمهيد",
                "title_en": f"{incomplete} riders with incomplete onboarding",
            }
        )

    # Below-target riders
    below = (
        db.query(func.count(ent.Target.id))
        .filter(
            ent.Target.tenant_id == tenant_id,
            ent.Target.scope_type == "RIDER",
            ent.Target.scope_id.in_(courier_ids),
            ent.Target.period == today.strftime("%Y-%m"),
            ent.Target.achievement_percentage < 80,
        )
        .scalar()
        or 0
    )
    if below:
        items.append(
            {
                "signal": "below_target",
                "severity": "medium",
                "count": below,
                "title_ar": f"{below} مندوب تحت التارجت",
                "title_en": f"{below} riders below target",
            }
        )

    return {"items": items, "total": len(items), "period": today.isoformat()}


# ---------- shifts ----------


@router.get("/shifts")
def supervisor_shifts(
    user: ent.User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """View shifts relevant to the supervisor's scoped workforce."""
    tenant_id = _supervisor_only(user)
    courier_ids = _scoped_courier_ids(db, tenant_id, user.id)
    if not courier_ids:
        return []

    shifts = db.query(ent.Shift).filter(ent.Shift.tenant_id == tenant_id).all()
    result = []
    now = datetime.utcnow()
    for shift in shifts:
        assigned = _assigned_courier_ids(shift)
        if not (assigned & courier_ids):
            continue
        serialized = _shift_json(db, shift, now)
        serialized["relevant_riders"] = sorted(assigned & courier_ids)
        result.append(serialized)
    return result

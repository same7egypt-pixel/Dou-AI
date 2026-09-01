"""W7: Operations Command Center — server-side dashboard aggregation."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func

from ..database import get_db
from ..models import entities as ent
from .auth import get_current_user


router = APIRouter(prefix="/analytics/dashboard", tags=["dashboard"])

READ_ROLES = {
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.OPERATIONS,
    ent.UserRole.HR,
    ent.UserRole.SUPERVISOR,
    ent.UserRole.ACCOUNTANT,
    ent.UserRole.VIEWER,
    ent.UserRole.PROJECT_MANAGER,
}


def _tenant_id(user: ent.User) -> int:
    if user.role not in READ_ROLES or not user.tenant_id:
        raise HTTPException(403, "Dashboard access required")
    return user.tenant_id


@router.get("/summary")
def dashboard_summary(
    operator_id: Optional[int] = Query(None),
    city_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Aggregated operational summary for the Command Center."""
    tenant_id = _tenant_id(user)
    today = date.today()

    # Handle Query objects (when called directly in tests without FastAPI)
    if hasattr(operator_id, "default"):
        operator_id = operator_id.default
    if hasattr(city_id, "default"):
        city_id = city_id.default
    if hasattr(branch_id, "default"):
        branch_id = branch_id.default

    # Base courier query
    couriers_q = db.query(ent.Courier).filter(ent.Courier.tenant_id == tenant_id)
    if operator_id is not None:
        couriers_q = couriers_q.filter(ent.Courier.primary_project_id == operator_id)
    if city_id is not None:
        couriers_q = couriers_q.filter(ent.Courier.city_id == city_id)
    if branch_id is not None:
        couriers_q = couriers_q.filter(ent.Courier.contract_branch_id == branch_id)

    total_riders = couriers_q.count()
    active_riders = couriers_q.filter(ent.Courier.employment_status == "ACTIVE").count()

    # Today's attendance
    courier_ids = [c.id for c in couriers_q.all()]
    attended_today = 0
    if courier_ids:
        attended_today = (
            db.query(func.count(func.distinct(ent.Attendance.courier_id)))
            .filter(
                ent.Attendance.courier_id.in_(courier_ids),
                ent.Attendance.check_in >= datetime.combine(today, datetime.min.time()),
            )
            .scalar()
            or 0
        )

    # Active leave today
    on_leave = 0
    if courier_ids:
        on_leave = (
            db.query(func.count(func.distinct(ent.LeaveRequest.courier_id)))
            .filter(
                ent.LeaveRequest.tenant_id == tenant_id,
                ent.LeaveRequest.courier_id.in_(courier_ids),
                ent.LeaveRequest.status == "APPROVED",
                ent.LeaveRequest.from_date <= today,
                ent.LeaveRequest.to_date >= today,
            )
            .scalar()
            or 0
        )

    # Readiness issues
    not_ready = 0
    if courier_ids:
        not_ready = (
            db.query(
                func.count(func.distinct(ent.OperationalReadinessState.courier_id))
            )
            .filter(
                ent.OperationalReadinessState.tenant_id == tenant_id,
                ent.OperationalReadinessState.courier_id.in_(courier_ids),
                ent.OperationalReadinessState.overall_status != "READY",
            )
            .scalar()
            or 0
        )

    # Vehicle assignments
    vehicle_assigned = 0
    if courier_ids:
        vehicle_assigned = (
            db.query(func.count(func.distinct(ent.RiderVehicleAssignment.courier_id)))
            .filter(
                ent.RiderVehicleAssignment.tenant_id == tenant_id,
                ent.RiderVehicleAssignment.courier_id.in_(courier_ids),
                ent.RiderVehicleAssignment.effective_to.is_(None),
            )
            .scalar()
            or 0
        )

    # Orders today
    orders_today = (
        db.query(func.count(ent.NormalizedDeliveryFact.id))
        .filter(
            ent.NormalizedDeliveryFact.tenant_id == tenant_id,
            ent.NormalizedDeliveryFact.created_at
            >= datetime.combine(today, datetime.min.time()),
        )
        .scalar()
        or 0
    )

    # Failed imports (last 7 days)
    failed_imports = (
        db.query(func.count(ent.OperationalImportBatch.id))
        .filter(
            ent.OperationalImportBatch.tenant_id == tenant_id,
            ent.OperationalImportBatch.status == "FAILED",
            ent.OperationalImportBatch.created_at
            >= datetime.combine(today - timedelta(days=7), datetime.min.time()),
        )
        .scalar()
        or 0
    )

    # Expiring documents (next 30 days)
    expiring_docs = (
        db.query(func.count(ent.Document.id))
        .filter(
            ent.Document.tenant_id == tenant_id,
            ent.Document.expiry_date <= today + timedelta(days=30),
            ent.Document.expiry_date >= today,
        )
        .scalar()
        or 0
    )

    return {
        "total_riders": total_riders,
        "active_riders": active_riders,
        "attended_today": attended_today,
        "absent_today": max(0, active_riders - attended_today - on_leave),
        "on_leave": on_leave,
        "not_ready": not_ready,
        "vehicle_assigned": vehicle_assigned,
        "orders_today": orders_today,
        "failed_imports": failed_imports,
        "expiring_docs": expiring_docs,
        "period": today.isoformat(),
    }


@router.get("/needs-attention")
def needs_attention(
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Actionable operational exceptions requiring attention."""
    tenant_id = _tenant_id(user)
    today = date.today()
    items = []

    # Absent riders (active but not checked in today)
    active_couriers = (
        db.query(ent.Courier)
        .filter(
            ent.Courier.tenant_id == tenant_id,
            ent.Courier.employment_status == "ACTIVE",
        )
        .all()
    )

    if active_couriers:
        courier_ids = [c.id for c in active_couriers]
        attended_ids = set(
            r[0]
            for r in db.query(func.distinct(ent.Attendance.courier_id))
            .filter(
                ent.Attendance.courier_id.in_(courier_ids),
                ent.Attendance.check_in >= datetime.combine(today, datetime.min.time()),
            )
            .all()
        )
        absent_count = len([c_id for c_id in courier_ids if c_id not in attended_ids])
        if absent_count > 0:
            items.append(
                {
                    "signal": "absent_riders",
                    "severity": "high" if absent_count > 5 else "medium",
                    "count": absent_count,
                    "title_ar": f"{absent_count} مندوب غائب اليوم",
                    "title_en": f"{absent_count} riders absent today",
                    "drill_down": {"view": "attendance", "filter": "absent"},
                }
            )

    # Readiness failures
    not_ready = (
        db.query(func.count(ent.OperationalReadinessState.courier_id))
        .filter(
            ent.OperationalReadinessState.tenant_id == tenant_id,
            ent.OperationalReadinessState.overall_status != "READY",
        )
        .scalar()
        or 0
    )
    if not_ready > 0:
        items.append(
            {
                "signal": "readiness_failures",
                "severity": "high",
                "count": not_ready,
                "title_ar": f"{not_ready} مندوب غير جاهز تشغيلياً",
                "title_en": f"{not_ready} riders not operationally ready",
                "drill_down": {"view": "readiness", "filter": "not_ready"},
            }
        )

    # Expiring documents
    expiring = (
        db.query(func.count(ent.Document.id))
        .filter(
            ent.Document.tenant_id == tenant_id,
            ent.Document.expiry_date <= today + timedelta(days=30),
            ent.Document.expiry_date >= today,
        )
        .scalar()
        or 0
    )
    if expiring > 0:
        items.append(
            {
                "signal": "expiring_documents",
                "severity": "medium",
                "count": expiring,
                "title_ar": f"{expiring} مستند ينتهي قريباً",
                "title_en": f"{expiring} documents expiring soon",
                "drill_down": {"view": "documents", "filter": "expiring"},
            }
        )

    # Failed imports
    failed = (
        db.query(func.count(ent.OperationalImportBatch.id))
        .filter(
            ent.OperationalImportBatch.tenant_id == tenant_id,
            ent.OperationalImportBatch.status == "FAILED",
            ent.OperationalImportBatch.created_at
            >= datetime.combine(today - timedelta(days=7), datetime.min.time()),
        )
        .scalar()
        or 0
    )
    if failed > 0:
        items.append(
            {
                "signal": "failed_imports",
                "severity": "medium",
                "count": failed,
                "title_ar": f"{failed} عملية استيراد فاشلة",
                "title_en": f"{failed} failed imports",
                "drill_down": {"view": "importHistory", "filter": "failed"},
            }
        )

    # On-leave riders
    on_leave = (
        db.query(func.count(func.distinct(ent.LeaveRequest.courier_id)))
        .filter(
            ent.LeaveRequest.tenant_id == tenant_id,
            ent.LeaveRequest.status == "APPROVED",
            ent.LeaveRequest.from_date <= today,
            ent.LeaveRequest.to_date >= today,
        )
        .scalar()
        or 0
    )
    if on_leave > 0:
        items.append(
            {
                "signal": "on_leave",
                "severity": "low",
                "count": on_leave,
                "title_ar": f"{on_leave} مندوب في إجازة اليوم",
                "title_en": f"{on_leave} riders on leave today",
                "drill_down": {"view": "leave", "filter": "active"},
            }
        )

    return {"items": items, "total": len(items), "period": today.isoformat()}


@router.get("/workforce-trend")
def workforce_trend(
    days: int = Query(7, ge=1, le=30),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Daily attendance trend for the last N days."""
    tenant_id = _tenant_id(user)
    today = date.today()
    start_date = today - timedelta(days=days - 1)

    records = (
        db.query(
            ent.Attendance.courier_id,
            ent.Attendance.check_in,
        )
        .join(ent.Courier, ent.Attendance.courier_id == ent.Courier.id)
        .filter(
            ent.Courier.tenant_id == tenant_id,
            ent.Attendance.check_in
            >= datetime.combine(start_date, datetime.min.time()),
            ent.Attendance.check_in
            < datetime.combine(today + timedelta(days=1), datetime.min.time()),
        )
        .all()
    )

    attended_by_day = defaultdict(set)
    for courier_id, check_in in records:
        if check_in:
            attended_by_day[check_in.date()].add(courier_id)

    trend = []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        trend.append(
            {"date": day.isoformat(), "attended": len(attended_by_day.get(day, set()))}
        )

    return {"trend": trend, "period_days": days}

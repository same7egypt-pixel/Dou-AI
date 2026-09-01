"""Capacity management, attendance correction, needs-attention engine, data health, rider 360 (Batch 2+3)."""

import json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import entities as ent
from ..services.workforce_scope import supervisor_courier_scope
from .auth import get_current_user


router = APIRouter(prefix="/analytics", tags=["analytics"])

MANAGE_ROLES = {
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.OPERATIONS,
    ent.UserRole.HR,
}
STAFF_ROLES = MANAGE_ROLES | {ent.UserRole.SUPERVISOR}
READ_ROLES = STAFF_ROLES | {
    ent.UserRole.ACCOUNTANT,
    ent.UserRole.VIEWER,
    ent.UserRole.PROJECT_MANAGER,
}


# ---------- helpers ----------


def _tenant_id(user: ent.User, manage: bool = False) -> int:
    allowed = MANAGE_ROLES if manage else READ_ROLES
    if user.role not in allowed or not user.tenant_id:
        raise HTTPException(403, "Analytics access required")
    return user.tenant_id


def _convert_query_objects(*args):
    result = []
    for value in args:
        if value is None:
            result.append(None)
        elif hasattr(value, "default"):
            result.append(value.default)
        elif type(value).__name__ == "Query" or hasattr(value, "deprecated"):
            result.append(None)
        else:
            result.append(value)
    return result


# ============================================================
# CAPACITY MANAGEMENT
# ============================================================


class CapacityRequirementCreate(BaseModel):
    scope_type: str
    scope_id: int
    shift_id: Optional[int] = None
    required_riders: int
    effective_from: date
    effective_to: Optional[date] = None


@router.post("/capacity/requirements", status_code=201)
def create_capacity_requirement(
    payload: CapacityRequirementCreate,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Configure required rider capacity for a scope (branch, project, operator)."""
    tenant_id = _tenant_id(user, manage=True)
    if payload.required_riders < 0:
        raise HTTPException(400, "required_riders cannot be negative")
    existing = (
        db.query(ent.CapacityRequirement)
        .filter(
            ent.CapacityRequirement.tenant_id == tenant_id,
            ent.CapacityRequirement.scope_type == payload.scope_type,
            ent.CapacityRequirement.scope_id == payload.scope_id,
            ent.CapacityRequirement.shift_id == payload.shift_id,
            ent.CapacityRequirement.effective_from == payload.effective_from,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Capacity requirement already exists")
    row = ent.CapacityRequirement(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "required_riders": row.required_riders}


@router.get("/capacity/status")
def capacity_status(
    scope_type: Optional[str] = Query(None),
    scope_id: Optional[int] = None,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Compute required / assigned / available riders by scope with shortage/surplus."""
    tenant_id = _tenant_id(user)
    today = date.today()

    # Determine scope couriers
    couriers_q = db.query(ent.Courier).filter(
        ent.Courier.tenant_id == tenant_id,
        ent.Courier.employment_status == "ACTIVE",
    )
    if scope_type == "BRANCH" and scope_id:
        couriers_q = couriers_q.filter(ent.Courier.contract_branch_id == scope_id)
    elif scope_type == "PROJECT" and scope_id:
        couriers_q = couriers_q.filter(ent.Courier.primary_project_id == scope_id)
    elif scope_type == "OPERATOR" and scope_id:
        couriers_q = couriers_q.join(
            ent.RiderAssignment,
            ent.RiderAssignment.courier_id == ent.Courier.id,
        ).filter(
            ent.RiderAssignment.operator_id == scope_id,
            ent.RiderAssignment.status == "ACTIVE",
        )

    total_available = couriers_q.count()

    # Count assigned riders (those with an active/scheduled shift)
    assigned_ids = set()
    shifts = (
        db.query(ent.Shift)
        .filter(
            ent.Shift.tenant_id == tenant_id,
            ent.Shift.status.in_(["ACTIVE", "SCHEDULED"]),
        )
        .all()
    )
    for shift in shifts:
        try:
            ids = json.loads(shift.courier_ids or "[]")
            assigned_ids.update(ids)
        except (json.JSONDecodeError, TypeError):
            continue
    assigned = (
        couriers_q.filter(ent.Courier.id.in_(assigned_ids)).count()
        if assigned_ids
        else 0
    )

    # Active (checked-in today)
    start_of_day = datetime.combine(today, datetime.min.time())
    end_of_day = datetime.combine(today + timedelta(days=1), datetime.min.time())
    active = (
        db.query(func.count(func.distinct(ent.Attendance.courier_id)))
        .filter(
            ent.Attendance.courier_id.in_([c.id for c in couriers_q.all()])
            if total_available
            else False,
            ent.Attendance.check_in >= start_of_day,
            ent.Attendance.check_in < end_of_day,
        )
        .scalar()
        or 0
    )

    # Required from configuration
    req_q = db.query(func.sum(ent.CapacityRequirement.required_riders)).filter(
        ent.CapacityRequirement.tenant_id == tenant_id,
        ent.CapacityRequirement.effective_from <= today,
        (
            ent.CapacityRequirement.effective_to.is_(None)
            | (ent.CapacityRequirement.effective_to >= today)
        ),
    )
    if scope_type and scope_id:
        req_q = req_q.filter(
            ent.CapacityRequirement.scope_type == scope_type,
            ent.CapacityRequirement.scope_id == scope_id,
        )
    required = req_q.scalar() or 0

    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "required": required,
        "available": total_available,
        "assigned": assigned,
        "active": active,
        "shortage": max(0, required - assigned),
        "surplus": max(0, assigned - required),
        "period": today.isoformat(),
    }


# ============================================================
# ATTENDANCE CORRECTION
# ============================================================


class AttendanceCorrectionCreate(BaseModel):
    attendance_id: int
    corrected_check_in: Optional[datetime] = None
    corrected_check_out: Optional[datetime] = None
    reason: str


class AttendanceCorrectionDecision(BaseModel):
    decision: str  # APPROVED / REJECTED
    note: Optional[str] = None


@router.post("/attendance/corrections", status_code=201)
def create_attendance_correction(
    payload: AttendanceCorrectionCreate,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Request an attendance correction. Requires review before applying."""
    tenant_id = _tenant_id(user)
    attendance = (
        db.query(ent.Attendance)
        .filter(
            ent.Attendance.id == payload.attendance_id,
        )
        .first()
    )
    if not attendance:
        raise HTTPException(404, "Attendance not found")
    courier = db.get(ent.Courier, attendance.courier_id)
    if not courier or courier.tenant_id != tenant_id:
        raise HTTPException(404, "Attendance not found")

    # Check for existing pending correction
    existing = (
        db.query(ent.AttendanceCorrection)
        .filter(
            ent.AttendanceCorrection.attendance_id == payload.attendance_id,
            ent.AttendanceCorrection.status == "PENDING",
        )
        .first()
    )
    if existing:
        raise HTTPException(
            409, "A pending correction already exists for this attendance"
        )

    row = ent.AttendanceCorrection(
        tenant_id=tenant_id,
        attendance_id=payload.attendance_id,
        courier_id=attendance.courier_id,
        requested_by=user.id,
        original_check_in=attendance.check_in,
        original_check_out=attendance.check_out,
        corrected_check_in=payload.corrected_check_in,
        corrected_check_out=payload.corrected_check_out,
        reason=payload.reason,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "status": row.status}


@router.get("/attendance/corrections")
def list_attendance_corrections(
    status_filter: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List attendance corrections. Filter by status."""
    tenant_id = _tenant_id(user)
    query = db.query(ent.AttendanceCorrection).filter(
        ent.AttendanceCorrection.tenant_id == tenant_id,
    )
    if status_filter and status_filter.upper() != "ALL":
        query = query.filter(ent.AttendanceCorrection.status == status_filter.upper())
    rows = query.order_by(ent.AttendanceCorrection.requested_at.desc()).all()
    courier_ids = list({r.courier_id for r in rows if r.courier_id})
    courier_map = (
        {
            c.id: c.name
            for c in db.query(ent.Courier).filter(ent.Courier.id.in_(courier_ids)).all()
        }
        if courier_ids
        else {}
    )
    return [
        {
            "id": r.id,
            "attendance_id": r.attendance_id,
            "courier_id": r.courier_id,
            "courier_name": courier_map.get(r.courier_id) or f"سائق #{r.courier_id}",
            "status": r.status,
            "reason": r.reason,
            "original_check_in": r.original_check_in.isoformat()
            if r.original_check_in
            else None,
            "original_check_out": r.original_check_out.isoformat()
            if r.original_check_out
            else None,
            "corrected_check_in": r.corrected_check_in.isoformat()
            if r.corrected_check_in
            else None,
            "corrected_check_out": r.corrected_check_out.isoformat()
            if r.corrected_check_out
            else None,
            "requested_at": r.requested_at.isoformat() if r.requested_at else None,
            "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
            "review_note": r.review_note,
        }
        for r in rows
    ]


@router.post("/attendance/corrections/{correction_id}/review")
def review_attendance_correction(
    correction_id: int,
    payload: AttendanceCorrectionDecision,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Review an attendance correction. APPROVED applies the correction; REJECTED leaves original."""
    tenant_id = _tenant_id(user, manage=True)
    correction = (
        db.query(ent.AttendanceCorrection)
        .filter(
            ent.AttendanceCorrection.id == correction_id,
            ent.AttendanceCorrection.tenant_id == tenant_id,
        )
        .first()
    )
    if not correction:
        raise HTTPException(404, "Correction not found")
    if correction.status != "PENDING":
        raise HTTPException(409, f"Correction is already {correction.status}")

    if payload.decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(400, "decision must be APPROVED or REJECTED")

    correction.status = payload.decision
    correction.reviewed_by = user.id
    correction.reviewed_at = datetime.utcnow()
    correction.review_note = payload.note

    if payload.decision == "APPROVED":
        attendance = db.get(ent.Attendance, correction.attendance_id)
        if attendance and correction.corrected_check_in:
            attendance.check_in = correction.corrected_check_in
        if attendance and correction.corrected_check_out:
            attendance.check_out = correction.corrected_check_out

    db.commit()
    db.refresh(correction)
    return {"id": correction.id, "status": correction.status}


# ============================================================
# NEEDS ATTENTION ENGINE
# ============================================================


@router.get("/needs-attention/deterministic")
def needs_attention_deterministic(
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deterministic operational exceptions requiring attention. No LLM."""
    tenant_id = _tenant_id(user)
    today = date.today()
    items = []

    # Capacity shortages
    capacity = capacity_status(user=user, db=db)
    if capacity.get("shortage", 0) > 0:
        items.append(
            {
                "signal": "capacity_shortage",
                "severity": "high" if capacity["shortage"] > 5 else "medium",
                "count": capacity["shortage"],
                "title_ar": f"{capacity['shortage']} نقص في السائقين",
                "title_en": f"{capacity['shortage']} rider shortage",
            }
        )

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
        active_ids = [c.id for c in active_couriers]
        attended_ids = {
            row[0]
            for row in db.query(func.distinct(ent.Attendance.courier_id))
            .filter(
                ent.Attendance.courier_id.in_(active_ids),
                ent.Attendance.check_in >= datetime.combine(today, datetime.min.time()),
            )
            .all()
        }
        absent_count = len([c_id for c_id in active_ids if c_id not in attended_ids])
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

    # Below-target riders
    below = (
        db.query(func.count(ent.Target.id))
        .filter(
            ent.Target.tenant_id == tenant_id,
            ent.Target.scope_type == "RIDER",
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

    # Incomplete onboarding
    incomplete = (
        db.query(func.count(ent.OperationalReadinessState.courier_id))
        .filter(
            ent.OperationalReadinessState.tenant_id == tenant_id,
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
    if expiring:
        items.append(
            {
                "signal": "expiring_documents",
                "severity": "medium",
                "count": expiring,
                "title_ar": f"{expiring} مستند ينتهي قريباً",
                "title_en": f"{expiring} documents expiring soon",
            }
        )

    # Pending attendance corrections
    pending_corrections = (
        db.query(func.count(ent.AttendanceCorrection.id))
        .filter(
            ent.AttendanceCorrection.tenant_id == tenant_id,
            ent.AttendanceCorrection.status == "PENDING",
        )
        .scalar()
        or 0
    )
    if pending_corrections:
        items.append(
            {
                "signal": "pending_attendance_corrections",
                "severity": "low",
                "count": pending_corrections,
                "title_ar": f"{pending_corrections} تصحيح حضور بانتظار المراجعة",
                "title_en": f"{pending_corrections} pending attendance corrections",
            }
        )

    # Platform mode specific exceptions
    tenant = db.get(ent.Tenant, tenant_id)
    if (
        tenant
        and getattr(tenant, "customer_type", "LOGISTICS_OPERATOR")
        == "DELIVERY_PLATFORM"
    ):
        from app.models.entities import RiderAssignment, CommercialSettlement

        unassigned = (
            db.query(func.count(ent.Courier.id))
            .filter(
                ent.Courier.tenant_id == tenant_id,
                ent.Courier.employment_status == "ACTIVE",
                ~ent.Courier.id.in_(
                    db.query(RiderAssignment.courier_id).filter(
                        RiderAssignment.tenant_id == tenant_id,
                        RiderAssignment.status == "ACTIVE",
                    )
                ),
            )
            .scalar()
            or 0
        )
        if unassigned:
            items.append(
                {
                    "signal": "unassigned_platform_riders",
                    "severity": "high",
                    "count": unassigned,
                    "title_ar": f"{unassigned} سائق بانتظار تعيين مشغل في المنظومة",
                    "title_en": f"{unassigned} platform riders unassigned to operator",
                }
            )

        pending_settlements = (
            db.query(func.count(CommercialSettlement.id))
            .filter(
                CommercialSettlement.tenant_id == tenant_id,
                CommercialSettlement.status.in_(["DRAFT", "NEEDS_REVIEW"]),
            )
            .scalar()
            or 0
        )
        if pending_settlements:
            items.append(
                {
                    "signal": "pending_b2b_settlements",
                    "severity": "medium",
                    "count": pending_settlements,
                    "title_ar": f"{pending_settlements} تسوية B2B لمشغلي المنصة بانتظار الاعتماد",
                    "title_en": f"{pending_settlements} operator settlements pending approval",
                }
            )

    return {"items": items, "total": len(items), "period": today.isoformat()}


# ============================================================
# RIDER 360 PROFILE
# ============================================================


@router.get("/riders/{courier_id}/profile")
def rider_360_profile(
    courier_id: int,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Unified rider profile. Authorized access only."""
    tenant_id = _tenant_id(user)
    courier = (
        db.query(ent.Courier)
        .filter(
            ent.Courier.id == courier_id,
            ent.Courier.tenant_id == tenant_id,
        )
        .first()
    )
    if not courier:
        raise HTTPException(404, "Rider not found")

    # Supervisor scope check
    if user.role == ent.UserRole.SUPERVISOR:
        matches = (
            db.query(ent.Courier.id)
            .filter(
                ent.Courier.id == courier_id,
                supervisor_courier_scope(db, user.id),
            )
            .first()
        )
        if not matches:
            raise HTTPException(404, "Rider not found")

    today = date.today()
    month_start = date(today.year, today.month, 1)

    # Attendance summary
    month_attendance = (
        db.query(func.count(func.distinct(ent.Attendance.courier_id)))
        .filter(
            ent.Attendance.courier_id == courier_id,
            ent.Attendance.check_in
            >= datetime.combine(month_start, datetime.min.time()),
        )
        .scalar()
        or 0
    )

    # Performance
    month_orders = (
        db.query(func.sum(ent.DailyLog.orders_count))
        .filter(
            ent.DailyLog.courier_id == courier_id,
            ent.DailyLog.log_date >= month_start,
        )
        .scalar()
        or 0
    )

    # Target achievement
    target = (
        db.query(ent.Target)
        .filter(
            ent.Target.tenant_id == tenant_id,
            ent.Target.scope_type == "RIDER",
            ent.Target.scope_id == courier_id,
            ent.Target.period == today.strftime("%Y-%m"),
        )
        .first()
    )

    # Onboarding status
    readiness = (
        db.query(ent.OperationalReadinessState)
        .filter(
            ent.OperationalReadinessState.tenant_id == tenant_id,
            ent.OperationalReadinessState.courier_id == courier_id,
        )
        .first()
    )

    # Documents summary
    total_docs = (
        db.query(func.count(ent.Document.id))
        .filter(
            ent.Document.tenant_id == tenant_id,
            ent.Document.owner_type == "RIDER",
            ent.Document.owner_id == courier_id,
        )
        .scalar()
        or 0
    )
    valid_docs = (
        db.query(func.count(ent.Document.id))
        .filter(
            ent.Document.tenant_id == tenant_id,
            ent.Document.owner_type == "RIDER",
            ent.Document.owner_id == courier_id,
            ent.Document.status == "VALID",
        )
        .scalar()
        or 0
    )

    # Current shift
    current_shift = None
    for shift in (
        db.query(ent.Shift)
        .filter(
            ent.Shift.tenant_id == tenant_id,
            ent.Shift.status.in_(["ACTIVE", "SCHEDULED"]),
        )
        .all()
    ):
        try:
            ids = json.loads(shift.courier_ids or "[]")
            if courier_id in ids:
                current_shift = shift.name
                break
        except (json.JSONDecodeError, TypeError):
            continue

    return {
        "id": courier.id,
        "name": courier.name,
        "phone": courier.phone,
        "employment_status": courier.employment_status,
        "onboarding_status": readiness.onboarding_status if readiness else "NEW",
        "supervisor_id": courier.supervisor_id,
        "project_id": courier.primary_project_id,
        "branch_id": courier.contract_branch_id,
        "city_id": courier.city_id,
        "current_shift": current_shift,
        "month_attendance_days": month_attendance,
        "month_orders": month_orders,
        "target_achievement": target.achievement_percentage if target else None,
        "documents_total": total_docs,
        "documents_valid": valid_docs,
        "vehicle_type": courier.vehicle_type,
        "vehicle_plate": courier.vehicle_plate,
    }


# ============================================================
# DATA HEALTH
# ============================================================


class DataHealthUpdate(BaseModel):
    source: str
    last_successful_sync: Optional[datetime] = None
    last_failed_sync: Optional[datetime] = None
    last_sync_status: str = "UNKNOWN"
    rows_processed: Optional[int] = None
    error_message: Optional[str] = None
    freshness_seconds: Optional[int] = None


@router.post("/data-health", status_code=201)
def update_data_health(
    payload: DataHealthUpdate,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record data health snapshot for a source. Idempotent per (tenant, source)."""
    tenant_id = _tenant_id(user, manage=True)
    existing = (
        db.query(ent.DataHealthSnapshot)
        .filter(
            ent.DataHealthSnapshot.tenant_id == tenant_id,
            ent.DataHealthSnapshot.source == payload.source,
        )
        .first()
    )
    if not existing:
        existing = ent.DataHealthSnapshot(tenant_id=tenant_id, source=payload.source)
        db.add(existing)
    existing.last_successful_sync = payload.last_successful_sync
    existing.last_failed_sync = payload.last_failed_sync
    existing.last_sync_status = payload.last_sync_status
    existing.rows_processed = payload.rows_processed
    existing.error_message = payload.error_message
    existing.freshness_seconds = payload.freshness_seconds
    db.commit()
    db.refresh(existing)
    return {
        "id": existing.id,
        "source": existing.source,
        "status": existing.last_sync_status,
    }


@router.get("/data-health")
def list_data_health(
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List data health snapshots for all configured sources."""
    tenant_id = _tenant_id(user)
    rows = (
        db.query(ent.DataHealthSnapshot)
        .filter(
            ent.DataHealthSnapshot.tenant_id == tenant_id,
        )
        .all()
    )
    return [
        {
            "source": r.source,
            "last_successful_sync": r.last_successful_sync.isoformat()
            if r.last_successful_sync
            else None,
            "last_failed_sync": r.last_failed_sync.isoformat()
            if r.last_failed_sync
            else None,
            "last_sync_status": r.last_sync_status,
            "rows_processed": r.rows_processed,
            "freshness_seconds": r.freshness_seconds,
        }
        for r in rows
    ]

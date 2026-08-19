"""Attendance-policy domain service.

The service is the sole controlled bridge from authoritative attendance facts to
optional payroll deductions. Reports never call mutation functions; events are
created only from check-in/check-out or an explicit company reconciliation action.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..models.entities import (
    Attendance, AttendanceDeductionPolicy, AttendanceEvent, ContractBranch,
    Courier, PayrollAdjustment, PayrollPeriod, Shift,
)

EVENT_TYPES = {"ABSENCE", "LATE", "EARLY_LEAVE"}
CALCULATION_METHODS = {"FIXED", "PER_MINUTE", "PER_HOUR", "MANUAL_APPROVAL_ONLY"}


def month_of(value: date) -> str:
    return value.strftime("%Y-%m")


def finalized_period(db: Session, tenant_id: int, month: str) -> Optional[PayrollPeriod]:
    return db.query(PayrollPeriod).filter(
        PayrollPeriod.tenant_id == tenant_id,
        PayrollPeriod.month == month,
        PayrollPeriod.status == "FINALIZED",
    ).first()


def active_policy_for(db: Session, tenant_id: int, event_type: str, event_date: date) -> Optional[AttendanceDeductionPolicy]:
    if event_type not in EVENT_TYPES:
        raise ValueError("نوع حدث الحضور غير صالح")
    return db.query(AttendanceDeductionPolicy).filter(
        AttendanceDeductionPolicy.tenant_id == tenant_id,
        AttendanceDeductionPolicy.event_type == event_type,
        AttendanceDeductionPolicy.is_active.is_(True),
        AttendanceDeductionPolicy.effective_from <= event_date,
        (AttendanceDeductionPolicy.effective_to.is_(None) | (AttendanceDeductionPolicy.effective_to >= event_date)),
    ).order_by(AttendanceDeductionPolicy.id.desc()).first()


def deduction_for(policy: AttendanceDeductionPolicy, measured_minutes: int) -> tuple[int, float]:
    """Returns eligible minutes and a capped non-negative deduction.

    Daily-salary proportion is deliberately not exposed: it needs a company-defined
    salary-day denominator, which does not yet exist in the product.
    """
    minutes = max(0, int(measured_minutes or 0) - max(0, int(policy.grace_minutes or 0)))
    if not minutes or policy.calculation_method == "MANUAL_APPROVAL_ONLY":
        return minutes, 0.0
    rate = float(policy.amount_rate or 0)
    if policy.calculation_method == "FIXED":
        amount = rate
    elif policy.calculation_method == "PER_MINUTE":
        amount = minutes * rate
    elif policy.calculation_method == "PER_HOUR":
        amount = (minutes / 60) * rate
    else:
        raise ValueError("طريقة الخصم غير مدعومة")
    if policy.maximum_deduction is not None:
        amount = min(amount, float(policy.maximum_deduction))
    return minutes, round(max(0.0, amount), 2)


def _event_key(event_type: str, attendance_id: Optional[int], shift_id: Optional[int], courier_id: int, event_date: date) -> str:
    source = f"attendance:{attendance_id}" if attendance_id else f"shift:{shift_id}"
    return f"{source}:{event_type}:{courier_id}:{event_date.isoformat()}"


def _adjustment_kind(event_type: str) -> str:
    return {"ABSENCE": "ABSENCE", "LATE": "LATE", "EARLY_LEAVE": "EARLY_LEAVE"}[event_type]


def create_adjustment_for_event(db: Session, event: AttendanceEvent, actor_id: Optional[int] = None) -> PayrollAdjustment:
    """Create exactly one approved adjustment from an approved attendance event."""
    existing = db.query(PayrollAdjustment).filter(
        PayrollAdjustment.tenant_id == event.tenant_id,
        PayrollAdjustment.idempotency_key == f"attendance-event:{event.id}",
    ).first()
    if existing:
        event.payroll_adjustment_id = existing.id
        return existing
    if finalized_period(db, event.tenant_id, month_of(event.event_date)):
        raise ValueError("لا يمكن إنشاء خصم في فترة رواتب مقفلة")
    adjustment = PayrollAdjustment(
        tenant_id=event.tenant_id,
        courier_id=event.courier_id,
        month=month_of(event.event_date),
        kind=_adjustment_kind(event.event_type),
        amount=float(event.deduction_amount or 0),
        note=event.note or f"خصم حضور معتمد — حدث #{event.id}",
        source_type="ATTENDANCE_EVENT",
        source_id=event.id,
        idempotency_key=f"attendance-event:{event.id}",
        status="APPROVED",
        created_by=actor_id,
    )
    db.add(adjustment)
    db.flush()
    event.payroll_adjustment_id = adjustment.id
    event.status = "APPLIED"
    return adjustment


def record_attendance_event(
    db: Session,
    courier: Courier,
    event_type: str,
    event_date: date,
    measured_minutes: int,
    attendance_id: Optional[int] = None,
    shift_id: Optional[int] = None,
    actor_id: Optional[int] = None,
    note: Optional[str] = None,
) -> AttendanceEvent:
    """Record an authoritative event and optionally create a single payroll adjustment.

    A missing policy creates a persisted NO_POLICY event. It never creates a
    financial row. Finalized months are explicitly blocked from mutation.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError("نوع حدث الحضور غير صالح")
    key = _event_key(event_type, attendance_id, shift_id, courier.id, event_date)
    existing = db.query(AttendanceEvent).filter(
        AttendanceEvent.tenant_id == courier.tenant_id,
        AttendanceEvent.idempotency_key == key,
    ).first()
    if existing:
        return existing

    policy = active_policy_for(db, courier.tenant_id, event_type, event_date)
    event = AttendanceEvent(
        tenant_id=courier.tenant_id,
        courier_id=courier.id,
        attendance_id=attendance_id,
        shift_id=shift_id,
        policy_id=policy.id if policy else None,
        event_type=event_type,
        event_date=event_date,
        measured_minutes=max(0, int(measured_minutes or 0)),
        idempotency_key=key,
        note=note,
    )
    db.add(event)
    db.flush()

    if not policy:
        event.status = "NO_POLICY"
        return event
    eligible_minutes, amount = deduction_for(policy, event.measured_minutes)
    event.measured_minutes = eligible_minutes
    event.deduction_amount = amount
    if finalized_period(db, courier.tenant_id, month_of(event_date)):
        event.status = "BLOCKED_CLOSED_PERIOD"
        return event
    if policy.calculation_method == "MANUAL_APPROVAL_ONLY" or policy.requires_approval:
        event.status = "PENDING_APPROVAL"
        return event
    if amount <= 0:
        event.status = "NO_DEDUCTION"
        return event
    create_adjustment_for_event(db, event, actor_id)
    return event


def decide_attendance_event(db: Session, event: AttendanceEvent, action: str, actor_id: int, note: Optional[str] = None) -> AttendanceEvent:
    if event.status != "PENDING_APPROVAL":
        raise ValueError("هذا الحدث ليس بانتظار اعتماد")
    if action not in {"approve", "reject"}:
        raise ValueError("قرار الاعتماد غير صالح")
    event.decided_by = actor_id
    event.decided_at = datetime.utcnow()
    if note:
        event.note = note
    if action == "reject":
        event.status = "REJECTED"
        return event
    if event.deduction_amount <= 0:
        event.status = "NO_DEDUCTION"
        return event
    create_adjustment_for_event(db, event, actor_id)
    return event


def reconcile_absences_for_date(db: Session, tenant_id: int, event_date: date, shift_window) -> dict:
    """Create absence events only through this explicit company-controlled action.

    `shift_window` is injected from the shift domain to preserve overnight logic
    without duplicating its date calculation in this service.
    """
    created = 0
    skipped_active = 0
    shifts = db.query(Shift).filter(Shift.tenant_id == tenant_id).all()
    reference = datetime.combine(event_date, datetime.min.time()).replace(hour=12)
    for shift in shifts:
        scheduled_start, scheduled_end, _ = shift_window(shift, reference)
        if scheduled_end > datetime.utcnow():
            skipped_active += 1
            continue
        try:
            assigned_ids = {int(value) for value in __import__("json").loads(shift.courier_ids or "[]")}
        except (TypeError, ValueError):
            assigned_ids = set()
        for courier_id in assigned_ids:
            courier = db.get(Courier, courier_id)
            if not courier or courier.tenant_id != tenant_id:
                continue
            present = db.query(Attendance).filter(
                Attendance.courier_id == courier.id,
                Attendance.shift_id == shift.id,
                Attendance.check_in >= scheduled_start,
                Attendance.check_in <= scheduled_end,
            ).first()
            if present:
                continue
            before = db.query(AttendanceEvent).filter(
                AttendanceEvent.tenant_id == tenant_id,
                AttendanceEvent.idempotency_key == _event_key("ABSENCE", None, shift.id, courier.id, event_date),
            ).first()
            record_attendance_event(
                db, courier, "ABSENCE", event_date,
                int((scheduled_end - scheduled_start).total_seconds() // 60),
                shift_id=shift.id,
                note=f"غياب عن الوردية: {shift.name or shift.id}",
            )
            if not before:
                created += 1
    return {"date": event_date.isoformat(), "created": created, "skipped_active_shifts": skipped_active}

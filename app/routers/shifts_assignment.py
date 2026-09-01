"""Shift-rider assignment endpoints with conflict detection (Batch 1)."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import entities as ent
from ..services.workforce_scope import supervisor_courier_scope
from .auth import get_current_user
from .shifts import (
    _assigned_courier_ids,
    _has_overlap,
    _shift_json,
)


router = APIRouter(prefix="/shifts", tags=["shifts"])

STAFF_ROLES = (
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.OPERATIONS,
    ent.UserRole.HR,
    ent.UserRole.SUPERVISOR,
    ent.UserRole.DOU_OPS,
    ent.UserRole.DOU_ADMIN,
)


# ---------- helpers ----------


def _shift_by_id(db, user, shift_id: int) -> ent.Shift:
    shift = db.get(ent.Shift, shift_id)
    if not shift:
        raise HTTPException(404, "Shift not found")
    if user.role in (ent.UserRole.DOU_OPS, ent.UserRole.DOU_ADMIN):
        return shift
    if shift.tenant_id != user.tenant_id:
        raise HTTPException(404, "Shift not found")
    if user.role == ent.UserRole.SUPERVISOR:
        allowed = _assigned_courier_ids(shift)
        supervisor_ids = (
            db.query(ent.Courier.id).filter(supervisor_courier_scope(db, user.id)).all()
        )
        supervisor_ids = {row[0] for row in supervisor_ids}
        if not (allowed & supervisor_ids) and allowed:
            raise HTTPException(404, "Shift not found")
    return shift


def _courier_in_user_scope(db, user, courier_id: int) -> ent.Courier:
    courier = db.get(ent.Courier, courier_id)
    if not courier:
        raise HTTPException(404, "Courier not found")
    if user.role in (ent.UserRole.DOU_OPS, ent.UserRole.DOU_ADMIN):
        return courier
    if courier.tenant_id != user.tenant_id:
        raise HTTPException(404, "Courier not found")
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
            raise HTTPException(404, "Courier not found")
    return courier


# ---------- schemas ----------


class ShiftAssignmentIn(BaseModel):
    courier_id: int


# ---------- endpoints ----------


@router.post("/{shift_id}/assign", status_code=200)
def assign_rider(
    shift_id: int,
    payload: ShiftAssignmentIn,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assign a rider to a shift with scope, readiness, operator, and conflict checks."""
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Not authorized")

    shift = _shift_by_id(db, user, shift_id)
    courier = _courier_in_user_scope(db, user, payload.courier_id)
    tenant_id = shift.tenant_id

    # Cross-operator isolation for delivery-platform tenants
    tenant = db.get(ent.Tenant, tenant_id)
    if tenant and tenant.customer_type == "DELIVERY_PLATFORM":
        active_assignment = (
            db.query(ent.RiderAssignment)
            .filter(
                ent.RiderAssignment.tenant_id == tenant_id,
                ent.RiderAssignment.courier_id == courier.id,
                ent.RiderAssignment.status == "ACTIVE",
            )
            .first()
        )
        operator_id = active_assignment.operator_id if active_assignment else None
        if user.role == ent.UserRole.SUPERVISOR:
            supervisor_scope = (
                db.query(ent.Courier.id)
                .filter(supervisor_courier_scope(db, user.id))
                .all()
            )
            supervisor_scope = {row[0] for row in supervisor_scope}
            if courier.id not in supervisor_scope:
                raise HTTPException(409, "Cross-operator assignment is not allowed")
            # Check if shift already has riders from a different operator
            existing_riders = _assigned_courier_ids(shift)
            for existing_id in existing_riders:
                existing_assignment = (
                    db.query(ent.RiderAssignment)
                    .filter(
                        ent.RiderAssignment.tenant_id == tenant_id,
                        ent.RiderAssignment.courier_id == existing_id,
                        ent.RiderAssignment.status == "ACTIVE",
                    )
                    .first()
                )
                if (
                    existing_assignment
                    and existing_assignment.operator_id != operator_id
                ):
                    raise HTTPException(409, "Cross-operator assignment is not allowed")
        if operator_id is None:
            raise HTTPException(
                409, "Rider must be assigned to an operator before shift assignment"
            )

    # Readiness / employment gate
    state = (
        db.query(ent.OperationalReadinessState)
        .filter(
            ent.OperationalReadinessState.tenant_id == tenant_id,
            ent.OperationalReadinessState.courier_id == courier.id,
        )
        .first()
    )
    onboarding = (state.onboarding_status or "NEW") if state else "NEW"
    if courier.employment_status == "ONBOARDING" or onboarding != "READY_TO_WORK":
        raise HTTPException(409, "Rider is not ready to work (onboarding incomplete)")

    assigned = _assigned_courier_ids(shift)
    if courier.id in assigned:
        raise HTTPException(409, "Rider already assigned to this shift")

    if _has_overlap(db, tenant_id, courier.id, shift, exclude_shift_id=shift.id):
        raise HTTPException(409, "Rider has an overlapping shift assignment")

    assigned.add(courier.id)
    shift.courier_ids = json.dumps(sorted(assigned))
    db.commit()
    return {
        "ok": True,
        "assigned": True,
        "shift_id": shift.id,
        "courier_id": courier.id,
    }


@router.post("/{shift_id}/remove", status_code=200)
def remove_rider(
    shift_id: int,
    payload: ShiftAssignmentIn,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a rider from a shift."""
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Not authorized")
    shift = _shift_by_id(db, user, shift_id)
    _courier_in_user_scope(db, user, payload.courier_id)

    assigned = _assigned_courier_ids(shift)
    if payload.courier_id not in assigned:
        raise HTTPException(409, "Rider not assigned to this shift")
    assigned.discard(payload.courier_id)
    shift.courier_ids = json.dumps(sorted(assigned))
    db.commit()
    return {
        "ok": True,
        "assigned": False,
        "shift_id": shift.id,
        "courier_id": payload.courier_id,
    }


@router.get("/{shift_id}/riders")
def list_shift_riders(
    shift_id: int,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List riders assigned to a shift."""
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Not authorized")
    shift = _shift_by_id(db, user, shift_id)
    assigned = sorted(_assigned_courier_ids(shift))
    if not assigned:
        return []
    couriers = db.query(ent.Courier).filter(ent.Courier.id.in_(assigned)).all()
    by_id = {c.id: c for c in couriers}
    result = []
    for courier_id in assigned:
        courier = by_id.get(courier_id)
        if courier:
            result.append(
                {
                    "id": courier.id,
                    "name": courier.name,
                    "phone": courier.phone,
                    "employment_status": courier.employment_status,
                }
            )
    return result


@router.get("/riders/{courier_id}/shifts")
def list_rider_shifts(
    courier_id: int,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List shifts assigned to a rider."""
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Not authorized")
    _courier_in_user_scope(db, user, courier_id)
    shifts = db.query(ent.Shift).filter(ent.Shift.tenant_id == user.tenant_id).all()
    return [
        _shift_json(db, s, datetime.utcnow())
        for s in shifts
        if courier_id in _assigned_courier_ids(s)
    ]

"""Operational readiness state with onboarding workflow (Batch 1)."""

import json
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..database import get_db
from ..models import entities as ent
from ..services.workforce_scope import supervisor_courier_scope
from .auth import get_current_user

router = APIRouter(prefix="/readiness", tags=["readiness"])

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

VALID_TRANSITIONS = {
    "NEW": {"SUBMIT_FOR_REVIEW"},
    "INCOMPLETE": {"SUBMIT_FOR_REVIEW"},
    "READY_FOR_REVIEW": {"ACTIVATE", "REJECT"},
    "READY_TO_WORK": set(),
    "BLOCKED": set(),
}

NEXT_STATUS = {
    ("NEW", "SUBMIT_FOR_REVIEW"): "READY_FOR_REVIEW",
    ("INCOMPLETE", "SUBMIT_FOR_REVIEW"): "READY_FOR_REVIEW",
    ("READY_FOR_REVIEW", "ACTIVATE"): "READY_TO_WORK",
    ("READY_FOR_REVIEW", "REJECT"): "INCOMPLETE",
}


# ---------- helpers ----------


def _tenant_id(user: ent.User, manage: bool = False) -> int:
    allowed = MANAGE_ROLES if manage else READ_ROLES
    if user.role not in allowed or not user.tenant_id:
        raise HTTPException(403, "Readiness access required")
    return user.tenant_id


def _same_tenant(db, model, record_id: int, tenant_id: int):
    row = (
        db.query(model)
        .filter(model.id == record_id, model.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(404, f"{model.__name__} not found")
    return row


def _active_operator_id(db, tenant_id: int, courier_id: int) -> Optional[int]:
    assignment = (
        db.query(ent.RiderAssignment)
        .filter(
            ent.RiderAssignment.tenant_id == tenant_id,
            ent.RiderAssignment.courier_id == courier_id,
            ent.RiderAssignment.status == "ACTIVE",
        )
        .first()
    )
    return assignment.operator_id if assignment else None


# ---------- schemas ----------


class ReadinessTransition(BaseModel):
    action: str
    note: Optional[str] = None


# ---------- readiness computation ----------


def _compute_readiness(
    db, tenant_id: int, courier_id: int
) -> ent.OperationalReadinessState:
    """Compute operational readiness state from separate dimensions."""
    courier = (
        db.query(ent.Courier)
        .filter(
            ent.Courier.tenant_id == tenant_id,
            ent.Courier.id == courier_id,
        )
        .first()
    )
    if not courier:
        raise HTTPException(404, "Courier not found")

    blockers = []
    dimensions = {}

    emp_status = courier.employment_status or "UNKNOWN"
    dimensions["employment"] = emp_status
    if emp_status != "ACTIVE":
        blockers.append(f"employment:{emp_status}")

    account_status = "ACTIVE" if courier.is_online else "INACTIVE"
    if not courier.is_online and not courier.is_available:
        account_status = "INACTIVE"
    dimensions["account"] = account_status
    if account_status != "ACTIVE":
        blockers.append(f"account:{account_status}")

    today = date.today()
    attendance = (
        db.query(ent.Attendance)
        .filter(
            ent.Attendance.courier_id == courier_id,
            ent.Attendance.check_in >= datetime.combine(today, datetime.min.time()),
        )
        .first()
    )
    attendance_status = "COMPLIANT" if attendance else "NON_COMPLIANT"
    dimensions["attendance"] = attendance_status
    if attendance_status != "COMPLIANT":
        blockers.append(f"attendance:{attendance_status}")

    shift = db.query(ent.Shift).filter(ent.Shift.tenant_id == tenant_id).all()
    assigned = False
    for s in shift:
        try:
            courier_ids = json.loads(s.courier_ids or "[]")
            if courier_id in courier_ids:
                assigned = True
                break
        except (json.JSONDecodeError, TypeError):
            continue
    shift_status = "ASSIGNED" if assigned else "UNASSIGNED"
    dimensions["shift"] = shift_status
    if not assigned:
        blockers.append(f"shift:{shift_status}")

    active_leave = (
        db.query(ent.LeaveRequest)
        .filter(
            ent.LeaveRequest.tenant_id == tenant_id,
            ent.LeaveRequest.courier_id == courier_id,
            ent.LeaveRequest.status == "APPROVED",
            ent.LeaveRequest.from_date <= today,
            ent.LeaveRequest.to_date >= today,
        )
        .first()
    )
    if active_leave:
        availability_status = "ON_LEAVE"
    elif courier.shift_active:
        availability_status = "AVAILABLE"
    else:
        availability_status = "UNAVAILABLE"
    dimensions["availability"] = availability_status
    if availability_status == "ON_LEAVE":
        blockers.append(f"availability:{availability_status}")

    pending_leave = (
        db.query(ent.LeaveRequest)
        .filter(
            ent.LeaveRequest.tenant_id == tenant_id,
            ent.LeaveRequest.courier_id == courier_id,
            ent.LeaveRequest.status == "PENDING",
        )
        .first()
    )
    if active_leave:
        leave_status = "ON_LEAVE"
    elif pending_leave:
        leave_status = "PENDING"
    else:
        leave_status = "NONE"
    dimensions["leave"] = leave_status
    if leave_status == "PENDING":
        blockers.append(f"leave:{leave_status}")

    kyc = (
        db.query(ent.KYCStatus)
        .filter(
            ent.KYCStatus.tenant_id == tenant_id,
            ent.KYCStatus.courier_id == courier_id,
        )
        .first()
    )
    if kyc:
        documents_status = (
            kyc.status
            if kyc.status in ("VERIFIED", "PENDING", "IN_REVIEW", "REJECTED")
            else "MISSING"
        )
    else:
        documents_status = "MISSING"
    dimensions["documents"] = documents_status
    if documents_status != "VERIFIED":
        blockers.append(f"documents:{documents_status}")

    vehicle_assignment = (
        db.query(ent.RiderVehicleAssignment)
        .filter(
            ent.RiderVehicleAssignment.tenant_id == tenant_id,
            ent.RiderVehicleAssignment.courier_id == courier_id,
            ent.RiderVehicleAssignment.effective_to.is_(None),
        )
        .first()
    )
    if vehicle_assignment:
        vehicle = db.query(ent.Vehicle).get(vehicle_assignment.vehicle_id)
        vehicle_status = (
            vehicle.compliance_status or "UNKNOWN" if vehicle else "NOT_APPLICABLE"
        )
    else:
        vehicle_status = "NOT_APPLICABLE"
    dimensions["vehicle_compliance"] = vehicle_status
    if vehicle_status not in ("COMPLIANT", "NOT_APPLICABLE"):
        blockers.append(f"vehicle_compliance:{vehicle_status}")

    if not blockers:
        overall_status = "READY"
    elif any(b.startswith(("employment:", "account:")) for b in blockers):
        overall_status = "NOT_READY"
    else:
        overall_status = "RESTRICTED"

    state = (
        db.query(ent.OperationalReadinessState)
        .filter(
            ent.OperationalReadinessState.tenant_id == tenant_id,
            ent.OperationalReadinessState.courier_id == courier_id,
        )
        .first()
    )

    if not state:
        state = ent.OperationalReadinessState(
            tenant_id=tenant_id, courier_id=courier_id
        )
        db.add(state)

    state.overall_status = overall_status
    state.employment_status = emp_status
    state.account_status = account_status
    state.attendance_status = attendance_status
    state.shift_status = shift_status
    state.availability_status = availability_status
    state.leave_status = leave_status
    state.documents_status = documents_status
    state.vehicle_compliance_status = vehicle_status
    state.blockers = json.dumps(blockers)
    state.computed_at = datetime.utcnow()

    if state.onboarding_status is None:
        state.onboarding_status = "NEW"

    db.flush()
    return state


# ---------- endpoints ----------


@router.get("/{courier_id}")
def get_readiness(
    courier_id: int, user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    """Get operational readiness state for a courier."""
    tenant_id = _tenant_id(user)
    _same_tenant(db, ent.Courier, courier_id, tenant_id)
    if user.role == ent.UserRole.SUPERVISOR:
        in_scope = (
            db.query(ent.Courier.id)
            .filter(
                ent.Courier.id == courier_id,
                supervisor_courier_scope(db, user.id),
            )
            .first()
        )
        if not in_scope:
            raise HTTPException(404, "Courier not found")

    state = _compute_readiness(db, tenant_id, courier_id)
    db.commit()

    blockers = json.loads(state.blockers) if state.blockers else []

    return {
        "courier_id": state.courier_id,
        "overall_status": state.overall_status,
        "onboarding_status": state.onboarding_status or "NEW",
        "dimensions": {
            "employment": state.employment_status,
            "account": state.account_status,
            "attendance": state.attendance_status,
            "shift": state.shift_status,
            "availability": state.availability_status,
            "leave": state.leave_status,
            "documents": state.documents_status,
            "vehicle_compliance": state.vehicle_compliance_status,
        },
        "blockers": blockers,
        "computed_at": state.computed_at.isoformat(),
    }


@router.post("/{courier_id}/recompute", status_code=200)
def recompute_readiness(
    courier_id: int, user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    """Recompute and return operational readiness state."""
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.Courier, courier_id, tenant_id)

    state = _compute_readiness(db, tenant_id, courier_id)
    db.commit()

    blockers = json.loads(state.blockers) if state.blockers else []

    return {
        "courier_id": state.courier_id,
        "overall_status": state.overall_status,
        "onboarding_status": state.onboarding_status or "NEW",
        "blockers": blockers,
        "computed_at": state.computed_at.isoformat(),
    }


@router.get("/")
def list_readiness(
    status_filter: Optional[str] = Query(None),
    onboarding_filter: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """List readiness states for all couriers in the tenant."""
    # Convert FastAPI Query objects to their default values when called directly in tests
    if hasattr(status_filter, "default"):
        status_filter = status_filter.default
    if hasattr(onboarding_filter, "default"):
        onboarding_filter = onboarding_filter.default
    tenant_id = _tenant_id(user)
    q = db.query(ent.OperationalReadinessState).filter(
        ent.OperationalReadinessState.tenant_id == tenant_id,
    )
    if user.role == ent.UserRole.SUPERVISOR:
        scoped_ids = db.query(ent.Courier.id).filter(
            supervisor_courier_scope(db, user.id)
        )
        q = q.filter(ent.OperationalReadinessState.courier_id.in_(scoped_ids))
    if status_filter is not None and status_filter != "":
        q = q.filter(ent.OperationalReadinessState.overall_status == status_filter)
    if onboarding_filter is not None and onboarding_filter != "":
        q = q.filter(
            ent.OperationalReadinessState.onboarding_status == onboarding_filter
        )

    return [
        {
            "id": r.id,
            "courier_id": r.courier_id,
            "overall_status": r.overall_status,
            "onboarding_status": r.onboarding_status or "NEW",
            "computed_at": r.computed_at.isoformat(),
        }
        for r in q.order_by(ent.OperationalReadinessState.computed_at.desc()).all()
    ]


@router.post("/{courier_id}/transition", status_code=200)
def transition_readiness(
    courier_id: int,
    payload: ReadinessTransition,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Perform an onboarding transition for a rider.

    Workflow:
        NEW / INCOMPLETE → SUBMIT_FOR_REVIEW → READY_FOR_REVIEW → ACTIVATE → READY_TO_WORK
        READY_FOR_REVIEW → REJECT → INCOMPLETE
    """
    tenant_id = _tenant_id(user, manage=True)
    courier = _same_tenant(db, ent.Courier, courier_id, tenant_id)

    state = _compute_readiness(db, tenant_id, courier_id)
    current = state.onboarding_status or "NEW"

    allowed = VALID_TRANSITIONS.get(current, set())
    if payload.action not in allowed:
        raise HTTPException(
            409,
            f"Invalid transition '{payload.action}' from '{current}'. Allowed: {sorted(allowed)}",
        )

    # Validate customer-type-specific requirements before allowing submission.
    if payload.action == "SUBMIT_FOR_REVIEW":
        tenant = db.get(ent.Tenant, tenant_id)
        if courier.supervisor_id is None:
            raise HTTPException(409, "Cannot submit for review: supervisor is required")
        if tenant and tenant.customer_type == "DELIVERY_PLATFORM":
            operator_id = _active_operator_id(db, tenant_id, courier_id)
            if operator_id is None:
                raise HTTPException(
                    409,
                    "Cannot submit for review: delivery-platform riders must be assigned to an operator",
                )

    # Validate activation requirements.
    if payload.action == "ACTIVATE":
        # Activation is blocked only by onboarding-specific requirements,
        # not by operational dimensions (attendance, shift, documents) which
        # are resolved during actual operations.
        if courier.supervisor_id is None:
            raise HTTPException(409, "Cannot activate: supervisor is required")
        tenant = db.get(ent.Tenant, tenant_id)
        if tenant and tenant.customer_type == "DELIVERY_PLATFORM":
            operator_id = _active_operator_id(db, tenant_id, courier_id)
            if operator_id is None:
                raise HTTPException(
                    409,
                    "Cannot activate: delivery-platform riders must be assigned to an operator",
                )

    next_status = NEXT_STATUS.get((current, payload.action))
    if next_status is None:
        raise HTTPException(
            409, f"Transition '{payload.action}' from '{current}' is not supported"
        )

    state.onboarding_status = next_status
    if next_status == "READY_TO_WORK":
        courier.employment_status = "ACTIVE"
    elif next_status == "INCOMPLETE":
        courier.employment_status = "ONBOARDING"

    db.commit()
    db.refresh(state)

    return {
        "courier_id": state.courier_id,
        "overall_status": state.overall_status,
        "onboarding_status": state.onboarding_status,
        "previous_status": current,
        "action": payload.action,
        "computed_at": state.computed_at.isoformat(),
    }

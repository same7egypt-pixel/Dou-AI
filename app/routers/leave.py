"""Leave policy and requests — W1-E5."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_

from ..database import get_db
from ..models import entities as ent
from .auth import get_current_user

router = APIRouter(prefix="/leave", tags=["leave"])

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
        raise HTTPException(403, "Leave access required")
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


def _date_range_days(from_date: date, to_date: date) -> int:
    """Calculate number of days in a date range (inclusive)."""
    if to_date < from_date:
        raise HTTPException(400, "to_date must be after from_date")
    return (to_date - from_date).days + 1


# ---------- schemas ----------


class LeaveTypeCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name_ar: str
    name_en: Optional[str] = None
    description_ar: Optional[str] = None
    description_en: Optional[str] = None
    is_paid: bool = True
    max_days_per_year: Optional[int] = None
    requires_document: bool = False


class LeaveTypeUpdate(BaseModel):
    name_ar: Optional[str] = None
    name_en: Optional[str] = None
    description_ar: Optional[str] = None
    description_en: Optional[str] = None
    is_paid: Optional[bool] = None
    max_days_per_year: Optional[int] = None
    requires_document: Optional[bool] = None
    is_active: Optional[bool] = None


class LeavePolicyCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    leave_type_id: int
    entitlement_days: int = 0
    carryover_limit: int = 0
    max_consecutive_days: Optional[int] = None
    min_days_notice: int = 0
    accrual_frequency: str = "YEARLY"
    effective_from: date
    effective_to: Optional[date] = None


class LeavePolicyUpdate(BaseModel):
    entitlement_days: Optional[int] = None
    carryover_limit: Optional[int] = None
    max_consecutive_days: Optional[int] = None
    min_days_notice: Optional[int] = None
    accrual_frequency: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    is_active: Optional[bool] = None


class LeaveRequestCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    courier_id: int
    leave_type_id: int
    from_date: date
    to_date: date
    reason: Optional[str] = None


class LeaveDecision(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    decision: str  # APPROVED / REJECTED
    comment: Optional[str] = None


# ---------- leave types ----------


@router.post("/types", status_code=201)
def create_leave_type(
    payload: LeaveTypeCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    existing = (
        db.query(ent.LeaveType)
        .filter(
            ent.LeaveType.tenant_id == tenant_id,
            ent.LeaveType.code == payload.code,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Leave type code already exists")
    row = ent.LeaveType(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


@router.get("/types")
def list_leave_types(
    active_only: bool = Query(True),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.LeaveType).filter(ent.LeaveType.tenant_id == tenant_id)
    if active_only:
        q = q.filter(ent.LeaveType.is_active.is_(True))
    return [
        {
            "id": r.id,
            "code": r.code,
            "name_ar": r.name_ar,
            "name_en": r.name_en,
            "is_paid": r.is_paid,
            "max_days_per_year": r.max_days_per_year,
            "requires_document": r.requires_document,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.LeaveType.code).all()
    ]


@router.patch("/types/{type_id}")
def update_leave_type(
    type_id: int,
    payload: LeaveTypeUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.LeaveType, type_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


# ---------- leave policies ----------


@router.post("/policies", status_code=201)
def create_leave_policy(
    payload: LeavePolicyCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.LeaveType, payload.leave_type_id, tenant_id)
    existing = (
        db.query(ent.LeavePolicy)
        .filter(
            ent.LeavePolicy.tenant_id == tenant_id,
            ent.LeavePolicy.leave_type_id == payload.leave_type_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Leave policy already exists for this leave type")
    row = ent.LeavePolicy(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "leave_type_id": row.leave_type_id,
        "entitlement_days": row.entitlement_days,
    }


@router.get("/policies")
def list_leave_policies(
    active_only: bool = Query(True),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.LeavePolicy).filter(ent.LeavePolicy.tenant_id == tenant_id)
    if active_only:
        q = q.filter(ent.LeavePolicy.is_active.is_(True))
    return [
        {
            "id": r.id,
            "leave_type_id": r.leave_type_id,
            "entitlement_days": r.entitlement_days,
            "carryover_limit": r.carryover_limit,
            "max_consecutive_days": r.max_consecutive_days,
            "min_days_notice": r.min_days_notice,
            "accrual_frequency": r.accrual_frequency,
            "effective_from": r.effective_from.isoformat(),
            "effective_to": r.effective_to.isoformat() if r.effective_to else None,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.LeavePolicy.id).all()
    ]


@router.patch("/policies/{policy_id}")
def update_leave_policy(
    policy_id: int,
    payload: LeavePolicyUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.LeavePolicy, policy_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "leave_type_id": row.leave_type_id,
        "entitlement_days": row.entitlement_days,
    }


# ---------- leave requests ----------


@router.post("/requests", status_code=201)
def create_leave_request(
    payload: LeaveRequestCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.Courier, payload.courier_id, tenant_id)
    _same_tenant(db, ent.LeaveType, payload.leave_type_id, tenant_id)

    days = _date_range_days(payload.from_date, payload.to_date)

    # Check for overlapping leave requests
    overlapping = (
        db.query(ent.LeaveRequest)
        .filter(
            ent.LeaveRequest.tenant_id == tenant_id,
            ent.LeaveRequest.courier_id == payload.courier_id,
            ent.LeaveRequest.status.in_(["PENDING", "SUPERVISOR_APPROVED", "APPROVED"]),
            ent.LeaveRequest.from_date <= payload.to_date,
            ent.LeaveRequest.to_date >= payload.from_date,
        )
        .first()
    )
    if overlapping:
        raise HTTPException(409, "Overlapping leave request exists")

    # Check entitlement
    entitlement = (
        db.query(ent.LeaveEntitlement)
        .filter(
            ent.LeaveEntitlement.tenant_id == tenant_id,
            ent.LeaveEntitlement.courier_id == payload.courier_id,
            ent.LeaveEntitlement.leave_type_id == payload.leave_type_id,
            ent.LeaveEntitlement.year == payload.from_date.year,
        )
        .first()
    )

    if entitlement:
        from sqlalchemy import update

        # H4 FIX: Atomic UPDATE with balance check in WHERE clause
        result = db.execute(
            update(ent.LeaveEntitlement)
            .where(
                ent.LeaveEntitlement.tenant_id == tenant_id,
                ent.LeaveEntitlement.courier_id == payload.courier_id,
                ent.LeaveEntitlement.leave_type_id == payload.leave_type_id,
                ent.LeaveEntitlement.year == payload.from_date.year,
                ent.LeaveEntitlement.entitled_days
                + ent.LeaveEntitlement.carried_over_days
                - ent.LeaveEntitlement.used_days
                - ent.LeaveEntitlement.pending_days
                >= days,
            )
            .values(pending_days=ent.LeaveEntitlement.pending_days + days)
        )
        if result.rowcount == 0:
            available = (
                entitlement.entitled_days
                + entitlement.carried_over_days
                - entitlement.used_days
                - entitlement.pending_days
            )
            raise HTTPException(
                400,
                f"Insufficient leave balance. Available: {available} days, Requested: {days} days",
            )
    else:
        # Check if there's a policy with entitlement
        policy = (
            db.query(ent.LeavePolicy)
            .filter(
                ent.LeavePolicy.tenant_id == tenant_id,
                ent.LeavePolicy.leave_type_id == payload.leave_type_id,
                ent.LeavePolicy.is_active.is_(True),
                ent.LeavePolicy.effective_from <= payload.from_date,
                or_(
                    ent.LeavePolicy.effective_to.is_(None),
                    ent.LeavePolicy.effective_to >= payload.from_date,
                ),
            )
            .first()
        )
        if policy and days > policy.entitlement_days:
            raise HTTPException(
                400,
                f"Insufficient leave balance. Available: {policy.entitlement_days} days, Requested: {days} days",
            )

    row = ent.LeaveRequest(
        tenant_id=tenant_id,
        courier_id=payload.courier_id,
        leave_type_id=payload.leave_type_id,
        from_date=payload.from_date,
        to_date=payload.to_date,
        reason=payload.reason,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "courier_id": row.courier_id,
        "status": row.status,
        "days": days,
    }


@router.get("/requests")
def list_leave_requests(
    status_filter: Optional[str] = Query(None),
    courier_id: Optional[int] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.LeaveRequest).filter(ent.LeaveRequest.tenant_id == tenant_id)
    if status_filter and status_filter != "ALL":
        q = q.filter(ent.LeaveRequest.status == status_filter)
    if courier_id:
        q = q.filter(ent.LeaveRequest.courier_id == courier_id)

    rows = q.order_by(ent.LeaveRequest.created_at.desc()).all()
    courier_ids = {r.courier_id for r in rows if r.courier_id}
    type_ids = {r.leave_type_id for r in rows if r.leave_type_id}

    courier_map = (
        {
            c.id: c.name
            for c in db.query(ent.Courier).filter(ent.Courier.id.in_(courier_ids)).all()
        }
        if courier_ids
        else {}
    )
    type_map = (
        {
            t.id: t.name_ar
            for t in db.query(ent.LeaveType)
            .filter(ent.LeaveType.id.in_(type_ids))
            .all()
        }
        if type_ids
        else {}
    )

    return [
        {
            "id": r.id,
            "courier_id": r.courier_id,
            "courier_name": courier_map.get(r.courier_id, f"سائق #{r.courier_id}"),
            "leave_type_id": r.leave_type_id,
            "leave_type_name": type_map.get(r.leave_type_id, "إجازة سنوية"),
            "from_date": r.from_date.isoformat(),
            "to_date": r.to_date.isoformat(),
            "reason": r.reason,
            "status": r.status,
            "days": (r.to_date - r.from_date).days + 1,
            "supervisor_comment": r.supervisor_comment,
            "admin_comment": r.admin_comment,
        }
        for r in rows
    ]


@router.post("/requests/{request_id}/supervisor-decide", status_code=200)
def supervisor_decide(
    request_id: int,
    payload: LeaveDecision,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.LeaveRequest, request_id, tenant_id)
    if row.status != "PENDING":
        raise HTTPException(409, "Request already decided by supervisor")
    if payload.decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(400, "decision must be APPROVED or REJECTED")

    if payload.decision == "REJECTED":
        row.status = "REJECTED"
        row.supervisor_comment = payload.comment
        row.supervisor_id = user.id
        # Release pending days
        _release_pending_days(db, row)
    else:
        row.status = "SUPERVISOR_APPROVED"
        row.supervisor_comment = payload.comment
        row.supervisor_id = user.id

    db.commit()
    db.refresh(row)
    return {"id": row.id, "status": row.status}


@router.post("/requests/{request_id}/admin-decide", status_code=200)
def admin_decide(
    request_id: int,
    payload: LeaveDecision,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.LeaveRequest, request_id, tenant_id)
    if row.status not in ("SUPERVISOR_APPROVED", "PENDING"):
        raise HTTPException(409, "Request already decided")
    if payload.decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(400, "decision must be APPROVED or REJECTED")

    if payload.decision == "REJECTED":
        row.status = "REJECTED"
        row.admin_comment = payload.comment
        row.admin_id = user.id
        # Release pending days
        _release_pending_days(db, row)
    else:
        row.status = "APPROVED"
        row.admin_comment = payload.comment
        row.admin_id = user.id
        # Move from pending to used
        _approve_pending_days(db, row)

    db.commit()
    db.refresh(row)
    return {"id": row.id, "status": row.status}


def _release_pending_days(db, request: ent.LeaveRequest):
    """Release pending days when a request is rejected — uses atomic UPDATE."""
    days = (request.to_date - request.from_date).days + 1
    from sqlalchemy import case, update

    new_pending = case(
        (ent.LeaveEntitlement.pending_days - days < 0, 0),
        else_=ent.LeaveEntitlement.pending_days - days,
    )
    db.execute(
        update(ent.LeaveEntitlement)
        .where(
            ent.LeaveEntitlement.tenant_id == request.tenant_id,
            ent.LeaveEntitlement.courier_id == request.courier_id,
            ent.LeaveEntitlement.leave_type_id == request.leave_type_id,
            ent.LeaveEntitlement.year == request.from_date.year,
        )
        .values(pending_days=new_pending)
    )


def _approve_pending_days(db, request: ent.LeaveRequest):
    """Move pending days to used when a request is approved — uses atomic UPDATE."""
    days = (request.to_date - request.from_date).days + 1
    from sqlalchemy import case, update

    new_pending = case(
        (ent.LeaveEntitlement.pending_days - days < 0, 0),
        else_=ent.LeaveEntitlement.pending_days - days,
    )
    db.execute(
        update(ent.LeaveEntitlement)
        .where(
            ent.LeaveEntitlement.tenant_id == request.tenant_id,
            ent.LeaveEntitlement.courier_id == request.courier_id,
            ent.LeaveEntitlement.leave_type_id == request.leave_type_id,
            ent.LeaveEntitlement.year == request.from_date.year,
        )
        .values(
            pending_days=new_pending,
            used_days=ent.LeaveEntitlement.used_days + days,
        )
    )


# ---------- leave entitlements ----------


@router.post("/entitlements", status_code=201)
def create_entitlement(
    payload: dict, user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    """Create or update a leave entitlement for a courier."""
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.Courier, payload["courier_id"], tenant_id)
    _same_tenant(db, ent.LeaveType, payload["leave_type_id"], tenant_id)

    existing = (
        db.query(ent.LeaveEntitlement)
        .filter(
            ent.LeaveEntitlement.tenant_id == tenant_id,
            ent.LeaveEntitlement.courier_id == payload["courier_id"],
            ent.LeaveEntitlement.leave_type_id == payload["leave_type_id"],
            ent.LeaveEntitlement.year == payload["year"],
        )
        .first()
    )

    if existing:
        for k, v in payload.items():
            if hasattr(existing, k):
                setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return {
            "id": existing.id,
            "courier_id": existing.courier_id,
            "year": existing.year,
        }

    row = ent.LeaveEntitlement(tenant_id=tenant_id, **payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "courier_id": row.courier_id, "year": row.year}


@router.get("/entitlements/{courier_id}")
def get_entitlements(
    courier_id: int,
    year: Optional[int] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    _same_tenant(db, ent.Courier, courier_id, tenant_id)
    q = db.query(ent.LeaveEntitlement).filter(
        ent.LeaveEntitlement.tenant_id == tenant_id,
        ent.LeaveEntitlement.courier_id == courier_id,
    )
    if year:
        q = q.filter(ent.LeaveEntitlement.year == year)
    return [
        {
            "id": r.id,
            "leave_type_id": r.leave_type_id,
            "year": r.year,
            "entitled_days": r.entitled_days,
            "carried_over_days": r.carried_over_days,
            "used_days": r.used_days,
            "pending_days": r.pending_days,
            "available_days": r.entitled_days
            + r.carried_over_days
            - r.used_days
            - r.pending_days,
        }
        for r in q.order_by(ent.LeaveEntitlement.year.desc()).all()
    ]

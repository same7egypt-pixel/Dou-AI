"""W10.5: Operator domain and commercial settlement router."""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import entities as ent
from ..services.entitlements import require_capability
from ..services.vendor_scorecard import eligible_orders_for_operator
from .auth import get_current_user

router = APIRouter(prefix="/analytics/operators", tags=["operators"])

READ_ROLES = {
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.OPERATIONS,
    ent.UserRole.HR,
    ent.UserRole.ACCOUNTANT,
    ent.UserRole.SUPERVISOR,
    ent.UserRole.PROJECT_MANAGER,
}

MANAGE_ROLES = {
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.OPERATIONS,
}

# Currency precision for SAR
TWO_PLACES = Decimal("0.01")


def _tenant_id(user: ent.User, db=None) -> int:
    """The tenant whose vendor settlements this user may reach.

    Role was the only check, so a logistics account — which buys neither
    MANAGE_OPERATORS nor OPERATOR_SETTLEMENTS — could calculate, save and
    approve B2B settlements. Same defect as payroll: the capability existed and
    only the sidebar read it. `db` is optional so nothing that already calls
    this has to change shape.
    """
    if user.role not in READ_ROLES or not user.tenant_id:
        raise HTTPException(403, "Operator access required")
    if db is not None:
        require_capability(db, user, ent.Capability.OPERATOR_SETTLEMENTS.value)
    return user.tenant_id


def _quantize(value: Decimal) -> Decimal:
    """Quantize to 2 decimal places (SAR currency precision)."""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@router.post("/settlement/calculate")
def calculate_operator_settlement(
    operator_id: int,
    period_month: str,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Calculate commercial settlement for an operator."""
    tenant_id = _tenant_id(user, db)

    # Validate operator is linked to this platform
    from app.models.entities import PlatformOperator

    link = (
        db.query(PlatformOperator)
        .filter(
            PlatformOperator.tenant_id == tenant_id,
            PlatformOperator.operator_tenant_id == operator_id,
            PlatformOperator.is_active,
        )
        .first()
    )
    if not link:
        raise HTTPException(404, "Operator not found")

    # Get active agreement for this operator
    agreement = (
        db.query(ent.OperatorAgreement)
        .filter(
            ent.OperatorAgreement.tenant_id == tenant_id,
            ent.OperatorAgreement.operator_id == operator_id,
            ent.OperatorAgreement.effective_from <= date.today(),
            (
                ent.OperatorAgreement.effective_to.is_(None)
                | (ent.OperatorAgreement.effective_to >= date.today())
            ),
            ent.OperatorAgreement.status == "ACTIVE",
        )
        .first()
    )

    if not agreement:
        raise HTTPException(404, "No active agreement for operator")

    # Same source and same grouping as the vendor scorecard. Counting inside
    # the operator's own tenant would be a cross-tenant read with no grant
    # behind it, and it pointed at a table nothing fills, so every settlement
    # came out zero while the scorecard showed real orders.
    eligible_orders = eligible_orders_for_operator(
        db, tenant_id, operator_id, period_month
    )
    # Calculate amounts using Decimal
    base_amount = Decimal(str(eligible_orders)) * agreement.rate

    # Apply bonus/penalty rules
    bonus_amount = Decimal("0")
    penalty_amount = Decimal("0")

    if agreement.bonus_threshold > 0 and eligible_orders >= agreement.bonus_threshold:
        bonus_amount = Decimal(str(eligible_orders)) * agreement.bonus_rate

    if (
        agreement.penalty_threshold > 0
        and eligible_orders < agreement.penalty_threshold
    ):
        penalty_amount = Decimal(str(eligible_orders)) * agreement.penalty_rate

    net_amount = base_amount + bonus_amount - penalty_amount

    return {
        "operator_id": operator_id,
        "period_month": period_month,
        "agreement_id": agreement.id,
        "eligible_orders": eligible_orders,
        "base_amount": float(_quantize(base_amount)),
        "bonus_amount": float(_quantize(bonus_amount)),
        "penalty_amount": float(_quantize(penalty_amount)),
        "net_amount": float(_quantize(net_amount)),
        "currency": agreement.currency,
    }


@router.post("/settlement/save")
def save_operator_settlement(
    operator_id: int,
    period_month: str,
    adjustment: Optional[Decimal] = None,
    adjustment_reason: Optional[str] = None,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save a commercial settlement (DRAFT or APPROVED)."""
    tenant_id = _tenant_id(user, db)

    # Calculate settlement
    calc = calculate_operator_settlement(operator_id, period_month, user, db)

    # Find existing settlement or create new record
    settlement = (
        db.query(ent.CommercialSettlement)
        .filter(
            ent.CommercialSettlement.tenant_id == tenant_id,
            ent.CommercialSettlement.operator_id == operator_id,
            ent.CommercialSettlement.period_month == period_month,
        )
        .first()
    )

    if settlement:
        settlement.agreement_id = calc["agreement_id"]
        settlement.eligible_orders = calc["eligible_orders"]
        settlement.base_amount = Decimal(str(calc["base_amount"]))
        settlement.bonus_amount = Decimal(str(calc["bonus_amount"]))
        settlement.penalty_amount = Decimal(str(calc["penalty_amount"]))
        settlement.manual_adjustment = adjustment or Decimal("0")
        settlement.adjustment_reason = adjustment_reason
        settlement.net_amount = Decimal(str(calc["net_amount"])) + (
            adjustment or Decimal("0")
        )
        settlement.currency = calc["currency"]
        settlement.status = "DRAFT"
    else:
        settlement = ent.CommercialSettlement(
            tenant_id=tenant_id,
            operator_id=operator_id,
            agreement_id=calc["agreement_id"],
            period_month=period_month,
            eligible_orders=calc["eligible_orders"],
            base_amount=Decimal(str(calc["base_amount"])),
            bonus_amount=Decimal(str(calc["bonus_amount"])),
            penalty_amount=Decimal(str(calc["penalty_amount"])),
            manual_adjustment=adjustment or Decimal("0"),
            adjustment_reason=adjustment_reason,
            net_amount=Decimal(str(calc["net_amount"])) + (adjustment or Decimal("0")),
            currency=calc["currency"],
            status="DRAFT",
            created_by=user.id,
        )
        db.add(settlement)
    db.commit()
    db.refresh(settlement)

    return {
        "id": settlement.id,
        "operator_id": operator_id,
        "period_month": period_month,
        "status": settlement.status,
        "net_amount": float(_quantize(settlement.net_amount)),
    }


@router.get("/settlements")
def list_operator_settlements(
    operator_id: Optional[int] = Query(None),
    period_month: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List commercial settlements for the platform."""
    tenant_id = _tenant_id(user, db)
    q = db.query(ent.CommercialSettlement).filter(
        ent.CommercialSettlement.tenant_id == tenant_id
    )
    if operator_id:
        q = q.filter(ent.CommercialSettlement.operator_id == operator_id)
    if period_month:
        q = q.filter(ent.CommercialSettlement.period_month == period_month)
    rows = q.order_by(ent.CommercialSettlement.created_at.desc()).all()
    results = []
    for s in rows:
        op_tenant = db.get(ent.Tenant, s.operator_id)
        results.append(
            {
                "id": s.id,
                "operator_id": s.operator_id,
                "operator_name": op_tenant.name
                if op_tenant
                else f"مشغل #{s.operator_id}",
                "period_month": s.period_month,
                "eligible_orders": s.eligible_orders,
                "base_amount": float(s.base_amount),
                "bonus_amount": float(s.bonus_amount),
                "penalty_amount": float(s.penalty_amount),
                "manual_adjustment": float(s.manual_adjustment),
                "net_amount": float(s.net_amount),
                "currency": s.currency,
                "status": s.status,
                "approved_by": s.approved_by,
                "approved_at": s.approved_at.isoformat() if s.approved_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
        )
    return results


@router.get("/settlement/{settlement_id}")
def get_operator_settlement(
    settlement_id: int,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific settlement."""
    tenant_id = _tenant_id(user, db)

    settlement = (
        db.query(ent.CommercialSettlement)
        .filter(
            ent.CommercialSettlement.id == settlement_id,
            ent.CommercialSettlement.tenant_id == tenant_id,
        )
        .first()
    )

    if not settlement:
        raise HTTPException(404, "Settlement not found")

    return {
        "id": settlement.id,
        "operator_id": settlement.operator_id,
        "period_month": settlement.period_month,
        "eligible_orders": settlement.eligible_orders,
        "base_amount": float(settlement.base_amount),
        "bonus_amount": float(settlement.bonus_amount),
        "penalty_amount": float(settlement.penalty_amount),
        "manual_adjustment": float(settlement.manual_adjustment),
        "net_amount": float(settlement.net_amount),
        "status": settlement.status,
        "approved_by": settlement.approved_by,
        "approved_at": settlement.approved_at.isoformat()
        if settlement.approved_at
        else None,
    }


@router.post("/settlement/{settlement_id}/approve")
def approve_operator_settlement(
    settlement_id: int,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Approve a commercial settlement."""
    tenant_id = _tenant_id(user, db)
    if user.role not in {
        ent.UserRole.COMPANY,
        ent.UserRole.COMPANY_ADMIN,
        ent.UserRole.ACCOUNTANT,
    }:
        raise HTTPException(
            403, "Only company admin or accountant can approve commercial settlements"
        )

    settlement = (
        db.query(ent.CommercialSettlement)
        .filter(
            ent.CommercialSettlement.id == settlement_id,
            ent.CommercialSettlement.tenant_id == tenant_id,
        )
        .first()
    )

    if not settlement:
        raise HTTPException(404, "Settlement not found")

    if settlement.status not in ("DRAFT", "CALCULATED", "NEEDS_REVIEW"):
        raise HTTPException(
            400, f"Cannot approve settlement in {settlement.status} status"
        )

    settlement.status = "APPROVED"
    settlement.approved_by = user.id
    settlement.approved_at = datetime.utcnow()
    db.commit()

    return {"id": settlement.id, "status": settlement.status}


@router.post("/rider/assign")
def assign_rider_to_operator(
    courier_id: int,
    operator_id: int,
    effective_from: date,
    supervisor_id: Optional[int] = None,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assign a rider to an operator with effective dating."""
    tenant_id = _tenant_id(user, db)

    # Validate courier belongs to this tenant
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

    # Validate operator is linked to this platform
    from app.models.entities import PlatformOperator

    link = (
        db.query(PlatformOperator)
        .filter(
            PlatformOperator.tenant_id == tenant_id,
            PlatformOperator.operator_tenant_id == operator_id,
            PlatformOperator.is_active,
        )
        .first()
    )
    if not link:
        raise HTTPException(404, "Operator not found")

    # Check for overlapping active assignments
    overlapping = (
        db.query(ent.RiderAssignment)
        .filter(
            ent.RiderAssignment.tenant_id == tenant_id,
            ent.RiderAssignment.courier_id == courier_id,
            ent.RiderAssignment.effective_from <= effective_from,
            (
                ent.RiderAssignment.effective_to.is_(None)
                | (ent.RiderAssignment.effective_to >= effective_from)
            ),
            ent.RiderAssignment.status == "ACTIVE",
        )
        .first()
    )

    if overlapping:
        raise HTTPException(409, "Overlapping assignment exists")

    # End current assignment if any
    current = (
        db.query(ent.RiderAssignment)
        .filter(
            ent.RiderAssignment.tenant_id == tenant_id,
            ent.RiderAssignment.courier_id == courier_id,
            ent.RiderAssignment.effective_to.is_(None),
            ent.RiderAssignment.status == "ACTIVE",
        )
        .first()
    )

    if current:
        current.effective_to = effective_from
        current.status = "ENDED"

    # Create new assignment
    assignment = ent.RiderAssignment(
        tenant_id=tenant_id,
        courier_id=courier_id,
        operator_id=operator_id,
        supervisor_id=supervisor_id,
        effective_from=effective_from,
        status="ACTIVE",
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    return {
        "id": assignment.id,
        "courier_id": courier_id,
        "operator_id": operator_id,
        "effective_from": effective_from.isoformat(),
        "status": assignment.status,
    }


@router.get("/rider/{courier_id}/history")
def get_rider_assignment_history(
    courier_id: int,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get rider assignment history."""
    tenant_id = _tenant_id(user, db)

    assignments = (
        db.query(ent.RiderAssignment)
        .filter(
            ent.RiderAssignment.tenant_id == tenant_id,
            ent.RiderAssignment.courier_id == courier_id,
        )
        .order_by(ent.RiderAssignment.effective_from.desc())
        .all()
    )

    return {
        "courier_id": courier_id,
        "assignments": [
            {
                "id": a.id,
                "operator_id": a.operator_id,
                "effective_from": a.effective_from.isoformat(),
                "effective_to": a.effective_to.isoformat() if a.effective_to else None,
                "status": a.status,
            }
            for a in assignments
        ],
    }


@router.get("/health")
def operator_health(
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Operator health indicators for the platform dashboard."""
    tenant_id = _tenant_id(user, db)

    # Count operators
    operator_count = (
        db.query(func.count(ent.PlatformOperator.id))
        .filter(
            ent.PlatformOperator.tenant_id == tenant_id,
            ent.PlatformOperator.is_active,
        )
        .scalar()
        or 0
    )

    # Count riders without assignments
    riders_without_assignment = (
        db.query(func.count(ent.Courier.id))
        .filter(
            ent.Courier.tenant_id == tenant_id,
            ent.Courier.employment_status == "ACTIVE",
            ~ent.Courier.id.in_(
                db.query(ent.RiderAssignment.courier_id).filter(
                    ent.RiderAssignment.tenant_id == tenant_id,
                    ent.RiderAssignment.status == "ACTIVE",
                )
            ),
        )
        .scalar()
        or 0
    )

    # Count pending settlements
    pending_settlements = (
        db.query(func.count(ent.CommercialSettlement.id))
        .filter(
            ent.CommercialSettlement.tenant_id == tenant_id,
            ent.CommercialSettlement.status.in_(["DRAFT", "NEEDS_REVIEW"]),
        )
        .scalar()
        or 0
    )

    return {
        "total_operators": operator_count,
        "riders_without_assignment": riders_without_assignment,
        "pending_settlements": pending_settlements,
    }


def _end_of_month(period_month: str) -> date:
    """Get the first day of the next month."""
    year, month = map(int, period_month.split("-"))
    if month == 12:
        return date(year + 1, 1, 1)
    return date(year, month + 1, 1)

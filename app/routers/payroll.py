"""W9: Payroll & Financial Operations — server-side payroll aggregation."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func

from ..database import get_db
from ..models import entities as ent
from .auth import get_current_user


router = APIRouter(prefix="/analytics/payroll", tags=["payroll"])

READ_ROLES = {
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.OPERATIONS,
    ent.UserRole.HR,
    ent.UserRole.ACCOUNTANT,
}

# Currency precision for SAR
TWO_PLACES = Decimal("0.01")


def _tenant_id(user: ent.User) -> int:
    if user.role not in READ_ROLES or not user.tenant_id:
        raise HTTPException(403, "Payroll access required")
    return user.tenant_id


def _convert_query_objects(*args):
    """Convert FastAPI Query objects to their default values."""
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


def _to_decimal(value) -> Decimal:
    """Convert a value to Decimal, handling float, int, str, Decimal, None."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, int):
        return Decimal(value)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _quantize(value) -> Decimal:
    """Quantize to 2 decimal places (SAR currency precision)."""
    if not isinstance(value, Decimal):
        value = _to_decimal(value)
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@router.get("/summary")
def payroll_summary(
    period: Optional[str] = Query(None),
    operator_id: Optional[int] = Query(None),
    city_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Payroll operations summary for the selected period and hierarchy."""
    tenant_id = _tenant_id(user)
    period, operator_id, city_id, branch_id = _convert_query_objects(
        period, operator_id, city_id, branch_id
    )

    today = date.today()
    if not period:
        period = today.strftime("%Y-%m")

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

    # Payroll inputs for this period (exclude VOID and REVERSAL)
    inputs_q = db.query(ent.PayrollInputRecord).filter(
        ent.PayrollInputRecord.tenant_id == tenant_id,
        ent.PayrollInputRecord.month == period,
        ent.PayrollInputRecord.status == "APPROVED",
    )
    if operator_id is not None:
        inputs_q = inputs_q.join(
            ent.Courier, ent.PayrollInputRecord.courier_id == ent.Courier.id
        ).filter(ent.Courier.primary_project_id == operator_id)
    if city_id is not None:
        inputs_q = inputs_q.join(
            ent.Courier, ent.PayrollInputRecord.courier_id == ent.Courier.id
        ).filter(ent.Courier.city_id == city_id)
    if branch_id is not None:
        inputs_q = inputs_q.join(
            ent.Courier, ent.PayrollInputRecord.courier_id == ent.Courier.id
        ).filter(ent.Courier.contract_branch_id == branch_id)

    inputs = inputs_q.all()

    # Calculate totals using Decimal for precision
    # Earnings: EARNING type, non-MANUAL, non-REVERSAL
    total_earnings = sum(
        _to_decimal(i.amount)
        for i in inputs
        if i.input_type == "EARNING" and i.source_type not in ("MANUAL", "REVERSAL")
    )
    # Deductions: DEDUCTION type, non-MANUAL, non-REVERSAL
    total_deductions = sum(
        _to_decimal(i.amount)
        for i in inputs
        if i.input_type == "DEDUCTION" and i.source_type not in ("MANUAL", "REVERSAL")
    )
    # Manual adjustments: signed (EARNING positive, DEDUCTION negative)
    total_adjustments = sum(
        _to_decimal(i.amount) if i.input_type == "EARNING" else -_to_decimal(i.amount)
        for i in inputs
        if i.source_type == "MANUAL"
    )
    # Reversals: displayed separately, NOT subtracted (original already VOID)
    total_reversals = sum(1 for i in inputs if i.reversal_of_id is not None)

    net_amount = total_earnings - total_deductions + total_adjustments

    # Count by source type
    source_counts = {}
    for i in inputs:
        source_counts[i.source_type] = source_counts.get(i.source_type, 0) + 1

    # Records requiring review
    records_needing_review = sum(1 for i in inputs if i.source_type == "MANUAL")

    # Exceptions
    exceptions = []

    # Active riders without payroll inputs
    riders_with_inputs = set(i.courier_id for i in inputs)
    active_courier_ids = set(
        c.id for c in couriers_q.filter(ent.Courier.employment_status == "ACTIVE").all()
    )
    riders_without_inputs = active_courier_ids - riders_with_inputs
    if riders_without_inputs:
        exceptions.append(
            {
                "signal": "missing_payroll_inputs",
                "severity": "medium",
                "count": len(riders_without_inputs),
                "title_ar": f"{len(riders_without_inputs)} مندوب بدون إدخالات راتب",
                "title_en": f"{len(riders_without_inputs)} riders without payroll inputs",
            }
        )

    # High deductions
    high_deductions = [
        i
        for i in inputs
        if i.input_type == "DEDUCTION"
        and _to_decimal(i.amount) > Decimal("500")
        and i.source_type != "MANUAL"
    ]
    if high_deductions:
        exceptions.append(
            {
                "signal": "high_deductions",
                "severity": "medium",
                "count": len(high_deductions),
                "title_ar": f"{len(high_deductions)} خصم عالي",
                "title_en": f"{len(high_deductions)} high deductions",
            }
        )

    return {
        "period": period,
        "total_riders": total_riders,
        "active_riders": active_riders,
        "total_earnings": float(_quantize(total_earnings)),
        "total_deductions": float(_quantize(total_deductions)),
        "total_adjustments": float(_quantize(total_adjustments)),
        "total_reversals": total_reversals,
        "net_amount": float(_quantize(net_amount)),
        "average_cost_per_rider": float(_quantize(net_amount / active_riders))
        if active_riders > 0
        else 0,
        "source_counts": source_counts,
        "records_needing_review": records_needing_review,
        "exceptions": exceptions,
        "readiness": _calculate_readiness(
            total_riders, len(riders_without_inputs), records_needing_review
        ),
    }


@router.get("/ledger")
def payroll_ledger(
    period: Optional[str] = Query(None),
    operator_id: Optional[int] = Query(None),
    city_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    rider_id: Optional[int] = Query(None),
    input_type: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("created_at"),
    sort_dir: Optional[str] = Query("desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Payroll ledger with filtering, sorting, and pagination."""
    tenant_id = _tenant_id(user)
    (
        period,
        operator_id,
        city_id,
        branch_id,
        rider_id,
        input_type,
        source_type,
        status_filter,
        sort_by,
        sort_dir,
        limit,
        offset,
    ) = _convert_query_objects(
        period,
        operator_id,
        city_id,
        branch_id,
        rider_id,
        input_type,
        source_type,
        status_filter,
        sort_by,
        sort_dir,
        limit,
        offset,
    )

    today = date.today()
    if not period:
        period = today.strftime("%Y-%m")

    # Base query
    q = db.query(ent.PayrollInputRecord).filter(
        ent.PayrollInputRecord.tenant_id == tenant_id,
        ent.PayrollInputRecord.month == period,
    )

    # Apply filters
    if rider_id is not None:
        q = q.filter(ent.PayrollInputRecord.courier_id == rider_id)
    if input_type:
        q = q.filter(ent.PayrollInputRecord.input_type == input_type)
    if source_type:
        q = q.filter(ent.PayrollInputRecord.source_type == source_type)
    if status_filter:
        q = q.filter(ent.PayrollInputRecord.status == status_filter)

    # Hierarchy filters
    if operator_id is not None or city_id is not None or branch_id is not None:
        q = q.join(ent.Courier, ent.PayrollInputRecord.courier_id == ent.Courier.id)
        if operator_id is not None:
            q = q.filter(ent.Courier.primary_project_id == operator_id)
        if city_id is not None:
            q = q.filter(ent.Courier.city_id == city_id)
        if branch_id is not None:
            q = q.filter(ent.Courier.contract_branch_id == branch_id)

    total = q.count()

    # Apply sorting
    if sort_by == "amount":
        if sort_dir == "desc":
            q = q.order_by(ent.PayrollInputRecord.amount.desc())
        else:
            q = q.order_by(ent.PayrollInputRecord.amount.asc())
    elif sort_by == "status":
        if sort_dir == "desc":
            q = q.order_by(ent.PayrollInputRecord.status.desc())
        else:
            q = q.order_by(ent.PayrollInputRecord.status.asc())
    else:  # created_at
        if sort_dir == "desc":
            q = q.order_by(ent.PayrollInputRecord.created_at.desc())
        else:
            q = q.order_by(ent.PayrollInputRecord.created_at.asc())

    records = q.limit(limit).offset(offset).all()

    # Build rows
    rows = []
    for record in records:
        courier = (
            db.query(ent.Courier).filter(ent.Courier.id == record.courier_id).first()
        )

        # Get source name
        source_name = None
        if record.source_type == "RULE":
            rule = (
                db.query(ent.IncentiveRule)
                .filter(ent.IncentiveRule.id == record.source_id)
                .first()
            )
            if rule:
                source_name = rule.name_ar
        elif record.source_type == "MANUAL":
            source_name = "إدخال يدوي"
        elif record.source_type == "ATTENDANCE":
            source_name = "حضور"
        elif record.source_type == "LEAVE":
            source_name = "إجازة"
        elif record.source_type == "DELIVERY_FACT":
            source_name = "حقيقة توصيل"
        elif record.source_type == "REVERSAL":
            source_name = "عكسي"

        rows.append(
            {
                "id": record.id,
                "courier_id": record.courier_id,
                "courier_name": courier.name if courier else "–",
                "input_type": record.input_type,
                "source_type": record.source_type,
                "source_name": source_name,
                "description": record.description,
                "amount": record.amount,
                "status": record.status,
                "reversal_of_id": record.reversal_of_id,
                "created_at": record.created_at.isoformat()
                if record.created_at
                else None,
            }
        )

    return {
        "rows": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "period": period,
    }


@router.get("/breakdown/{courier_id}")
def rider_payroll_breakdown(
    courier_id: int,
    period: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Detailed payroll breakdown for a single rider."""
    tenant_id = _tenant_id(user)
    period = _convert_query_objects(period)[0]

    today = date.today()
    if not period:
        period = today.strftime("%Y-%m")

    # Verify courier belongs to tenant
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

    # Get all payroll inputs for this rider and period (APPROVED only, exclude REVERSAL)
    inputs = (
        db.query(ent.PayrollInputRecord)
        .filter(
            ent.PayrollInputRecord.tenant_id == tenant_id,
            ent.PayrollInputRecord.courier_id == courier_id,
            ent.PayrollInputRecord.month == period,
            ent.PayrollInputRecord.status == "APPROVED",
        )
        .all()
    )

    # Categorize inputs
    base_inputs = [i for i in inputs if i.source_type == "ATTENDANCE"]
    incentive_inputs = [
        i for i in inputs if i.source_type == "RULE" and i.input_type == "EARNING"
    ]
    deduction_inputs = [
        i
        for i in inputs
        if i.input_type == "DEDUCTION" and i.source_type not in ("MANUAL", "REVERSAL")
    ]
    manual_earnings = [
        i for i in inputs if i.source_type == "MANUAL" and i.input_type == "EARNING"
    ]
    manual_deductions = [
        i for i in inputs if i.source_type == "MANUAL" and i.input_type == "DEDUCTION"
    ]
    reversal_inputs = [i for i in inputs if i.reversal_of_id is not None]

    # Calculate totals using Decimal
    base_total = sum(_to_decimal(i.amount) for i in base_inputs)
    incentive_total = sum(_to_decimal(i.amount) for i in incentive_inputs)
    deduction_total = sum(_to_decimal(i.amount) for i in deduction_inputs)
    manual_total = sum(_to_decimal(i.amount) for i in manual_earnings) - sum(
        _to_decimal(i.amount) for i in manual_deductions
    )
    reversal_total = sum(_to_decimal(i.amount) for i in reversal_inputs)
    net_amount = base_total + incentive_total - deduction_total + manual_total

    # Previous period comparison
    prev_period = _previous_period(period)
    prev_inputs = (
        db.query(ent.PayrollInputRecord)
        .filter(
            ent.PayrollInputRecord.tenant_id == tenant_id,
            ent.PayrollInputRecord.courier_id == courier_id,
            ent.PayrollInputRecord.month == prev_period,
            ent.PayrollInputRecord.status == "APPROVED",
            ent.PayrollInputRecord.source_type != "REVERSAL",
        )
        .all()
    )
    prev_net = sum(
        _to_decimal(i.amount) for i in prev_inputs if i.input_type == "EARNING"
    ) - sum(_to_decimal(i.amount) for i in prev_inputs if i.input_type == "DEDUCTION")

    return {
        "courier_id": courier_id,
        "courier_name": courier.name,
        "period": period,
        "previous_period": prev_period,
        "base_salary": courier.base_salary or 0,
        "base_inputs": [
            {
                "id": i.id,
                "amount": float(i.amount),
                "description": i.description,
                "source_type": i.source_type,
            }
            for i in base_inputs
        ],
        "incentive_inputs": [
            {
                "id": i.id,
                "amount": float(i.amount),
                "description": i.description,
                "source_type": i.source_type,
            }
            for i in incentive_inputs
        ],
        "deduction_inputs": [
            {
                "id": i.id,
                "amount": float(i.amount),
                "description": i.description,
                "source_type": i.source_type,
            }
            for i in deduction_inputs
        ],
        "manual_inputs": [
            {
                "id": i.id,
                "amount": float(i.amount),
                "description": i.description,
                "source_type": i.source_type,
            }
            for i in manual_earnings + manual_deductions
        ],
        "reversal_inputs": [
            {
                "id": i.id,
                "amount": float(i.amount),
                "description": i.description,
                "source_type": i.source_type,
            }
            for i in reversal_inputs
        ],
        "totals": {
            "base": float(_quantize(base_total)),
            "incentives": float(_quantize(incentive_total)),
            "deductions": float(_quantize(deduction_total)),
            "manual": float(_quantize(manual_total)),
            "reversals": float(_quantize(reversal_total)),
            "net": float(_quantize(net_amount)),
            "previous_net": float(_quantize(prev_net)),
            "change": float(_quantize(net_amount - prev_net)),
        },
    }


@router.get("/incentives")
def payroll_incentives(
    period: Optional[str] = Query(None),
    input_type: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Incentives and deductions visibility."""
    tenant_id = _tenant_id(user)
    period, input_type, source_type = _convert_query_objects(
        period, input_type, source_type
    )

    today = date.today()
    if not period:
        period = today.strftime("%Y-%m")

    q = db.query(ent.PayrollInputRecord).filter(
        ent.PayrollInputRecord.tenant_id == tenant_id,
        ent.PayrollInputRecord.month == period,
        ent.PayrollInputRecord.source_type == "RULE",
        ent.PayrollInputRecord.status == "APPROVED",
    )
    if input_type:
        q = q.filter(ent.PayrollInputRecord.input_type == input_type)

    inputs = q.all()

    incentives = []
    for inp in inputs:
        rule = (
            db.query(ent.IncentiveRule)
            .filter(ent.IncentiveRule.id == inp.source_id)
            .first()
        )
        courier = db.query(ent.Courier).filter(ent.Courier.id == inp.courier_id).first()

        incentives.append(
            {
                "id": inp.id,
                "courier_id": inp.courier_id,
                "courier_name": courier.name if courier else "–",
                "input_type": inp.input_type,
                "amount": inp.amount,
                "rule_name": rule.name_ar if rule else "–",
                "rule_type": rule.rule_type if rule else "–",
                "description": inp.description,
                "status": inp.status,
            }
        )

    return {
        "incentives": incentives,
        "period": period,
        "total_earnings": float(
            _quantize(
                sum(
                    _to_decimal(i["amount"])
                    for i in incentives
                    if i["input_type"] == "EARNING"
                )
            )
        ),
        "total_deductions": float(
            _quantize(
                sum(
                    _to_decimal(i["amount"])
                    for i in incentives
                    if i["input_type"] == "DEDUCTION"
                )
            )
        ),
    }


@router.get("/readiness")
def payroll_readiness(
    period: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Payroll readiness assessment."""
    tenant_id = _tenant_id(user)
    period = _convert_query_objects(period)[0]

    today = date.today()
    if not period:
        period = today.strftime("%Y-%m")

    # Active riders
    active_riders = (
        db.query(ent.Courier)
        .filter(
            ent.Courier.tenant_id == tenant_id,
            ent.Courier.employment_status == "ACTIVE",
        )
        .all()
    )
    active_ids = [r.id for r in active_riders]

    # Riders with payroll inputs (APPROVED, non-REVERSAL)
    riders_with_inputs = set(
        r[0]
        for r in db.query(ent.PayrollInputRecord.courier_id)
        .filter(
            ent.PayrollInputRecord.tenant_id == tenant_id,
            ent.PayrollInputRecord.month == period,
            ent.PayrollInputRecord.status == "APPROVED",
            ent.PayrollInputRecord.source_type != "REVERSAL",
        )
        .distinct()
        .all()
    )

    # Missing riders
    missing_riders = [r for r in active_ids if r not in riders_with_inputs]

    # Failed imports
    failed_imports = (
        db.query(func.count(ent.OperationalImportBatch.id))
        .filter(
            ent.OperationalImportBatch.tenant_id == tenant_id,
            ent.OperationalImportBatch.status == "FAILED",
        )
        .scalar()
        or 0
    )

    # Reversed records
    reversed_count = (
        db.query(func.count(ent.PayrollInputRecord.id))
        .filter(
            ent.PayrollInputRecord.tenant_id == tenant_id,
            ent.PayrollInputRecord.month == period,
            ent.PayrollInputRecord.reversal_of_id.isnot(None),
        )
        .scalar()
        or 0
    )

    # Determine readiness
    if not missing_riders and failed_imports == 0 and reversed_count == 0:
        readiness = "READY"
    elif missing_riders:
        needs_review = len(missing_riders)
        readiness = (
            "NEEDS_REVIEW" if needs_review < len(active_ids) * 0.2 else "INCOMPLETE"
        )
    else:
        readiness = "NEEDS_REVIEW"

    return {
        "period": period,
        "total_active_riders": len(active_ids),
        "riders_with_inputs": len(riders_with_inputs),
        "missing_riders": len(missing_riders),
        "failed_imports": failed_imports,
        "reversed_records": reversed_count,
        "readiness": readiness,
    }


@router.get("/cost-summary")
def cost_summary(
    period: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Cost and financial operations summary."""
    tenant_id = _tenant_id(user)
    period = _convert_query_objects(period)[0]

    today = date.today()
    if not period:
        period = today.strftime("%Y-%m")

    # Get all payroll inputs for period (APPROVED, non-REVERSAL)
    inputs = (
        db.query(ent.PayrollInputRecord)
        .filter(
            ent.PayrollInputRecord.tenant_id == tenant_id,
            ent.PayrollInputRecord.month == period,
            ent.PayrollInputRecord.status == "APPROVED",
            ent.PayrollInputRecord.source_type != "REVERSAL",
        )
        .all()
    )

    # Calculate totals by type (exclude MANUAL/REVERSAL from earnings/deductions)
    total_earnings = sum(
        _to_decimal(i.amount)
        for i in inputs
        if i.input_type == "EARNING" and i.source_type not in ("MANUAL", "REVERSAL")
    )
    total_deductions = sum(
        _to_decimal(i.amount)
        for i in inputs
        if i.input_type == "DEDUCTION" and i.source_type not in ("MANUAL", "REVERSAL")
    )
    total_adjustments = sum(
        _to_decimal(i.amount) if i.input_type == "EARNING" else -_to_decimal(i.amount)
        for i in inputs
        if i.source_type == "MANUAL"
    )
    net_amount = total_earnings - total_deductions + total_adjustments

    # Cost by project/city/branch
    cost_by_project = {}
    cost_by_branch = {}
    for inp in inputs:
        courier = db.query(ent.Courier).filter(ent.Courier.id == inp.courier_id).first()
        if courier:
            project_id = courier.primary_project_id or 0
            branch_id = courier.contract_branch_id or 0
            cost_by_project[project_id] = cost_by_project.get(
                project_id, Decimal("0")
            ) + _to_decimal(inp.amount)
            cost_by_branch[branch_id] = cost_by_branch.get(
                branch_id, Decimal("0")
            ) + _to_decimal(inp.amount)

    # Previous period comparison
    prev_period = _previous_period(period)
    prev_inputs = (
        db.query(ent.PayrollInputRecord)
        .filter(
            ent.PayrollInputRecord.tenant_id == tenant_id,
            ent.PayrollInputRecord.month == prev_period,
            ent.PayrollInputRecord.status == "APPROVED",
            ent.PayrollInputRecord.source_type != "REVERSAL",
        )
        .all()
    )
    prev_net = sum(
        _to_decimal(i.amount) for i in prev_inputs if i.input_type == "EARNING"
    ) - sum(_to_decimal(i.amount) for i in prev_inputs if i.input_type == "DEDUCTION")

    return {
        "period": period,
        "previous_period": prev_period,
        "total_earnings": float(_quantize(total_earnings)),
        "total_deductions": float(_quantize(total_deductions)),
        "total_adjustments": float(_quantize(total_adjustments)),
        "net_amount": float(_quantize(net_amount)),
        "previous_net": float(_quantize(prev_net)),
        "change": float(_quantize(net_amount - prev_net)),
        "change_percentage": float(
            _quantize((net_amount - prev_net) / prev_net * Decimal("100"))
        )
        if prev_net != 0
        else 0,
        "cost_by_project": {
            str(k): float(_quantize(v)) for k, v in cost_by_project.items()
        },
        "cost_by_branch": {
            str(k): float(_quantize(v)) for k, v in cost_by_branch.items()
        },
    }


def _previous_period(period: str) -> str:
    """Get the previous period string."""
    year, month = int(period[:4]), int(period[5:7])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def _calculate_readiness(
    total_riders: int, missing_riders: int, needs_review: int
) -> str:
    """Calculate payroll readiness status."""
    if total_riders == 0:
        return "READY"
    if missing_riders == 0 and needs_review == 0:
        return "READY"
    if missing_riders > total_riders * 0.2:
        return "INCOMPLETE"
    return "NEEDS_REVIEW"

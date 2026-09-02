"""W8: Performance Management — server-side aggregation and scorecards."""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func

from ..database import get_db
from ..models import entities as ent
from .auth import get_current_user

router = APIRouter(prefix="/analytics/performance", tags=["performance"])

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
        raise HTTPException(403, "Performance access required")
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


@router.get("/summary")
def performance_summary(
    operator_id: Optional[int] = Query(None),
    city_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    period: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Aggregated performance summary for the hierarchy level."""
    tenant_id = _tenant_id(user)
    operator_id, city_id, branch_id, period = _convert_query_objects(
        operator_id, city_id, branch_id, period
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

    courier_ids = [c.id for c in couriers_q.all()]
    total_riders = len(courier_ids)

    if total_riders == 0:
        return {
            "total_riders": 0,
            "period": period,
            "kpis": [],
            "targets": [],
            "exceptions": [],
        }

    # KPI results for this period
    kpi_results = (
        db.query(ent.KPIResult)
        .filter(
            ent.KPIResult.tenant_id == tenant_id,
            ent.KPIResult.period == period,
        )
        .all()
    )

    # Targets for this period
    targets = (
        db.query(ent.Target)
        .filter(
            ent.Target.tenant_id == tenant_id,
            ent.Target.period == period,
        )
        .all()
    )

    # Performance exceptions
    exceptions = []

    # Riders with low attendance
    attended_count = (
        db.query(func.count(func.distinct(ent.Attendance.courier_id)))
        .join(ent.Courier, ent.Attendance.courier_id == ent.Courier.id)
        .filter(
            ent.Courier.tenant_id == tenant_id,
            ent.Attendance.check_in >= datetime.combine(today, datetime.min.time()),
        )
        .scalar()
        or 0
    )

    if attended_count < total_riders:
        exceptions.append(
            {
                "signal": "low_attendance",
                "severity": "high" if attended_count < total_riders * 0.7 else "medium",
                "count": total_riders - attended_count,
                "title_ar": f"{total_riders - attended_count} مندوب غائب اليوم",
                "title_en": f"{total_riders - attended_count} riders absent today",
            }
        )

    # Below-target performers
    below_target = 0
    for target in targets:
        if target.achievement_percentage < 80:
            below_target += 1
    if below_target > 0:
        exceptions.append(
            {
                "signal": "below_target",
                "severity": "medium",
                "count": below_target,
                "title_ar": f"{below_target} هدف لم يحقق",
                "title_en": f"{below_target} targets missed",
            }
        )

    return {
        "total_riders": total_riders,
        "period": period,
        "attendance_rate": round(attended_count / total_riders * 100, 1)
        if total_riders > 0
        else 0,
        "kpi_results": len(kpi_results),
        "targets_configured": len(targets),
        "exceptions": exceptions,
    }


@router.get("/scorecard/{scope_type}/{scope_id}")
def performance_scorecard(
    scope_type: str,
    scope_id: int,
    period: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Performance scorecard for a rider/team/branch/project."""
    tenant_id = _tenant_id(user)
    period = _convert_query_objects(period)[0]
    today = date.today()
    if not period:
        period = today.strftime("%Y-%m")

    # Get KPI results for this scope
    kpi_results = (
        db.query(ent.KPIResult)
        .filter(
            ent.KPIResult.tenant_id == tenant_id,
            ent.KPIResult.scope_type == scope_type,
            ent.KPIResult.scope_id == scope_id,
            ent.KPIResult.period == period,
        )
        .all()
    )

    # Get targets for this scope
    targets = (
        db.query(ent.Target)
        .filter(
            ent.Target.tenant_id == tenant_id,
            ent.Target.scope_type == scope_type,
            ent.Target.scope_id == scope_id,
            ent.Target.period == period,
        )
        .all()
    )

    # Previous period comparison
    prev_period = _previous_period(period)
    prev_results = (
        db.query(ent.KPIResult)
        .filter(
            ent.KPIResult.tenant_id == tenant_id,
            ent.KPIResult.scope_type == scope_type,
            ent.KPIResult.scope_id == scope_id,
            ent.KPIResult.period == prev_period,
        )
        .all()
    )

    # Build scorecard
    kpi_data = []
    for result in kpi_results:
        kpi_def = (
            db.query(ent.KPIDefinition)
            .filter(ent.KPIDefinition.id == result.kpi_definition_id)
            .first()
        )

        target = next((t for t in targets if t.target_type == kpi_def.code), None)
        prev_result = next(
            (
                r
                for r in prev_results
                if r.kpi_definition_id == result.kpi_definition_id
            ),
            None,
        )

        kpi_data.append(
            {
                "kpi_id": result.kpi_definition_id,
                "code": kpi_def.code if kpi_def else None,
                "name_ar": kpi_def.name_ar if kpi_def else None,
                "name_en": kpi_def.name_en if kpi_def else None,
                "unit": kpi_def.unit if kpi_def else None,
                "result_value": result.result_value,
                "target_value": target.target_value if target else None,
                "achievement_percentage": target.achievement_percentage
                if target
                else None,
                "previous_value": prev_result.result_value if prev_result else None,
                "trend": _calculate_trend(
                    result.result_value,
                    prev_result.result_value if prev_result else None,
                ),
                "freshness_at": result.freshness_at.isoformat()
                if result.freshness_at
                else None,
            }
        )

    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "period": period,
        "previous_period": prev_period,
        "kpis": kpi_data,
        "targets": [
            {
                "id": t.id,
                "target_type": t.target_type,
                "target_value": t.target_value,
                "actual_value": t.actual_value,
                "achievement_percentage": t.achievement_percentage,
            }
            for t in targets
        ],
    }


@router.get("/explorer")
def performance_explorer(
    operator_id: Optional[int] = Query(None),
    city_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    period: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(
        None
    ),  # all / above_target / below_target / no_target
    sort_by: Optional[str] = Query("name"),  # name / achievement / trend
    sort_dir: Optional[str] = Query("asc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Performance explorer with filtering, sorting, and pagination."""
    tenant_id = _tenant_id(user)
    (
        operator_id,
        city_id,
        branch_id,
        period,
        status_filter,
        sort_by,
        sort_dir,
        limit,
        offset,
    ) = _convert_query_objects(
        operator_id,
        city_id,
        branch_id,
        period,
        status_filter,
        sort_by,
        sort_dir,
        limit,
        offset,
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

    total = couriers_q.count()
    couriers = couriers_q.order_by(ent.Courier.name).limit(limit).offset(offset).all()

    # Get targets for this period
    targets = (
        db.query(ent.Target)
        .filter(
            ent.Target.tenant_id == tenant_id,
            ent.Target.period == period,
            ent.Target.scope_type == "RIDER",
        )
        .all()
    )
    targets_map = {t.scope_id: t for t in targets}

    # Get KPI results for this period
    kpi_results = (
        db.query(ent.KPIResult)
        .filter(
            ent.KPIResult.tenant_id == tenant_id,
            ent.KPIResult.period == period,
            ent.KPIResult.scope_type == "RIDER",
        )
        .all()
    )
    kpi_map = {r.scope_id: r for r in kpi_results}

    # Build rider performance rows
    rows = []
    for courier in couriers:
        target = targets_map.get(courier.id)
        kpi = kpi_map.get(courier.id)

        # Attendance today
        attended_today = (
            db.query(func.count(ent.Attendance.id))
            .filter(
                ent.Attendance.courier_id == courier.id,
                ent.Attendance.check_in >= datetime.combine(today, datetime.min.time()),
            )
            .scalar()
            or 0
        )

        row = {
            "courier_id": courier.id,
            "name": courier.name,
            "phone": courier.phone,
            "employment_status": courier.employment_status,
            "target_value": target.target_value if target else None,
            "actual_value": target.actual_value if target else None,
            "achievement_percentage": target.achievement_percentage if target else None,
            "attended_today": attended_today > 0,
            "kpi_result_value": kpi.result_value if kpi else None,
            "status": _rider_status(target, attended_today > 0),
        }
        rows.append(row)

    # Apply status filter
    if status_filter and status_filter != "all":
        rows = [r for r in rows if r["status"] == status_filter]

    # Apply sorting
    if sort_by == "achievement":
        rows.sort(
            key=lambda x: x["achievement_percentage"] or 0, reverse=(sort_dir == "desc")
        )
    elif sort_by == "trend":
        rows.sort(
            key=lambda x: x["kpi_result_value"] or 0, reverse=(sort_dir == "desc")
        )
    else:  # name
        rows.sort(key=lambda x: x["name"], reverse=(sort_dir == "desc"))

    return {
        "rows": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "period": period,
    }


@router.get("/trends")
def performance_trends(
    scope_type: str = Query("RIDER"),
    scope_id: int = Query(...),
    months: int = Query(6, ge=1, le=12),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Performance trends over multiple periods."""
    tenant_id = _tenant_id(user)
    scope_type, scope_id, months = _convert_query_objects(scope_type, scope_id, months)
    today = date.today()

    trends = []
    for i in range(months - 1, -1, -1):
        period = _add_months(today, -i).strftime("%Y-%m")

        kpi_results = (
            db.query(ent.KPIResult)
            .filter(
                ent.KPIResult.tenant_id == tenant_id,
                ent.KPIResult.scope_type == scope_type,
                ent.KPIResult.scope_id == scope_id,
                ent.KPIResult.period == period,
            )
            .all()
        )

        targets = (
            db.query(ent.Target)
            .filter(
                ent.Target.tenant_id == tenant_id,
                ent.Target.scope_type == scope_type,
                ent.Target.scope_id == scope_id,
                ent.Target.period == period,
            )
            .all()
        )

        trends.append(
            {
                "period": period,
                "kpi_count": len(kpi_results),
                "avg_result": sum(r.result_value for r in kpi_results)
                / len(kpi_results)
                if kpi_results
                else 0,
                "targets_count": len(targets),
                "avg_achievement": sum(t.achievement_percentage for t in targets)
                / len(targets)
                if targets
                else 0,
            }
        )

    return {"trends": trends, "scope_type": scope_type, "scope_id": scope_id}


@router.get("/incentives")
def performance_incentives(
    courier_id: Optional[int] = Query(None),
    period: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Incentive/deduction visibility linked to performance."""
    tenant_id = _tenant_id(user)
    courier_id, period = _convert_query_objects(courier_id, period)
    today = date.today()
    if not period:
        period = today.strftime("%Y-%m")

    incentives = []

    # Get payroll inputs for this period
    inputs_q = db.query(ent.PayrollInputRecord).filter(
        ent.PayrollInputRecord.tenant_id == tenant_id,
        ent.PayrollInputRecord.month == period,
    )
    if courier_id:
        inputs_q = inputs_q.filter(ent.PayrollInputRecord.courier_id == courier_id)

    inputs = inputs_q.all()

    for inp in inputs:
        incentive = {
            "id": inp.id,
            "courier_id": inp.courier_id,
            "input_type": inp.input_type,
            "amount": inp.amount,
            "source_type": inp.source_type,
            "status": inp.status,
            "description": inp.description,
        }

        # Link to performance where applicable
        if inp.source_type == "RULE":
            rule = (
                db.query(ent.IncentiveRule)
                .filter(ent.IncentiveRule.id == inp.source_id)
                .first()
            )
            if rule:
                incentive["rule_name"] = rule.name_ar
                incentive["rule_type"] = rule.rule_type

        incentives.append(incentive)

    return {
        "incentives": incentives,
        "period": period,
        "total_earnings": sum(
            i["amount"] for i in incentives if i["input_type"] == "EARNING"
        ),
        "total_deductions": sum(
            i["amount"] for i in incentives if i["input_type"] == "DEDUCTION"
        ),
    }


def _previous_period(period: str) -> str:
    """Get the previous period string."""
    year, month = int(period[:4]), int(period[5:7])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def _add_months(d: date, months: int) -> date:
    """Add months to a date, clamping day to the last valid day of the target month."""
    import calendar

    month = d.month + months
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    # Clamp day to last day of target month (e.g., Jan 31 -> Feb 28)
    last_day = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day)
    return d.replace(year=year, month=month, day=day)


def _calculate_trend(current: float, previous: Optional[float]) -> str:
    """Calculate trend direction."""
    if previous is None:
        return "stable"
    if current > previous * 1.05:
        return "up"
    if current < previous * 0.95:
        return "down"
    return "stable"


def _rider_status(target: Optional[ent.Target], attended: bool) -> str:
    """Determine rider performance status."""
    if target is None:
        return "no_target"
    if not attended:
        return "absent"
    if target.achievement_percentage >= 100:
        return "above_target"
    if target.achievement_percentage >= 80:
        return "near_target"
    return "below_target"

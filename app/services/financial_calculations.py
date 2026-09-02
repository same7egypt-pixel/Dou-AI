"""Authoritative Phase 1 financial calculations.

The module deliberately separates client revenue from rider compensation.  It uses
DailyLog as the existing eligible-performance source for Phase 1 and never creates
attendance deductions because no company deduction policy exists yet.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import json
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models.entities import (
    BonusPlan,
    Contract,
    ContractBranch,
    Courier,
    DailyLog,
    OperationalFinancialSnapshot,
    PayrollAdjustment,
    PayrollPeriod,
    PayrollSnapshot,
)


def month_bounds(month: str) -> tuple[date, date]:
    try:
        year, number = (int(part) for part in month.split("-", 1))
        start = date(year, number, 1)
    except (AttributeError, TypeError, ValueError):
        raise ValueError("صيغة الشهر يجب أن تكون YYYY-MM")
    end = date(year + 1, 1, 1) if number == 12 else date(year, number + 1, 1)
    return start, end


def calculate_plan_earnings(orders: int, plan: BonusPlan) -> dict:
    orders = max(int(orders or 0), 0)
    plan_type = getattr(plan, "plan_type", "TARGET_TIER") or "TARGET_TIER"

    if plan_type == "FLAT_PER_ORDER":
        rate = max(float(getattr(plan, "flat_order_rate", 0.0) or 0.0), 0.0)
        return {
            "plan_type": "FLAT_PER_ORDER",
            "achieved": True,
            "target": 0,
            "bonus_amount": 0.0,
            "over_target_rate": 0.0,
            "below_target_rate": 0.0,
            "flat_order_rate": rate,
            "remaining_orders": 0,
            "over_orders": orders,
            "earned": 0.0,
        }

    # TARGET_TIER
    target = max(int(getattr(plan, "target_orders", 0) or 0), 0)
    target_bonus = max(float(getattr(plan, "bonus_amount", 0.0) or 0.0), 0.0)
    over_target_rate = max(float(getattr(plan, "over_target_rate", 0.0) or 0.0), 0.0)
    below_target_rate = max(float(getattr(plan, "below_target_rate", 0.0) or 0.0), 0.0)

    achieved = target > 0 and orders >= target
    if achieved:
        over_orders = max(orders - target, 0)
        earned = target_bonus + (over_orders * over_target_rate)
        remaining_orders = 0
    else:
        over_orders = 0
        remaining_orders = max(target - orders, 0)
        earned = orders * below_target_rate if below_target_rate > 0 else 0.0

    return {
        "plan_type": "TARGET_TIER",
        "achieved": achieved,
        "target": target,
        "bonus_amount": round(target_bonus, 2),
        "over_target_rate": round(over_target_rate, 2),
        "below_target_rate": round(below_target_rate, 2),
        "flat_order_rate": 0.0,
        "remaining_orders": remaining_orders,
        "over_orders": over_orders,
        "earned": round(earned, 2),
    }


def calculate_target_bonus(
    orders: int,
    target: int,
    target_bonus: float,
    over_target_rate: float,
    below_target_rate: float = 0.0,
) -> dict:
    orders = max(int(orders or 0), 0)
    target = max(int(target or 0), 0)
    target_bonus = max(float(target_bonus or 0), 0.0)
    over_target_rate = max(float(over_target_rate or 0), 0.0)
    below_target_rate = max(float(below_target_rate or 0), 0.0)
    achieved = target > 0 and orders >= target
    if achieved:
        over_orders = max(orders - target, 0)
        earned = target_bonus + over_orders * over_target_rate
        remaining_orders = 0
    else:
        over_orders = 0
        remaining_orders = max(target - orders, 0)
        earned = orders * below_target_rate if below_target_rate > 0 else 0.0
    return {
        "achieved": achieved,
        "remaining_orders": remaining_orders,
        "over_orders": over_orders,
        "earned": round(earned, 2),
    }


def _plan_is_effective(plan: BonusPlan, as_of: date) -> bool:
    return bool(
        plan.is_active
        and (not plan.effective_from or plan.effective_from <= as_of)
        and (not plan.effective_to or plan.effective_to >= as_of)
    )


def bonus_plan_for_courier(
    db: Session, courier: Courier, as_of: date
) -> Optional[BonusPlan]:
    """Explicit rider override wins; otherwise branch -> contract -> project -> company-wide."""
    base = db.query(BonusPlan).filter(
        BonusPlan.tenant_id == courier.tenant_id,
        BonusPlan.is_active.is_(True),
    )
    plans = [plan for plan in base.all() if _plan_is_effective(plan, as_of)]
    overrides = [p for p in plans if p.courier_id == courier.id]
    if overrides:
        return max(overrides, key=lambda p: (p.effective_from or date.min, p.id))

    branch_plans = [
        p
        for p in plans
        if p.contract_branch_id
        and p.contract_branch_id == courier.contract_branch_id
        and p.courier_id is None
    ]
    if branch_plans:
        return max(branch_plans, key=lambda p: (p.effective_from or date.min, p.id))

    contract_plans = [
        p
        for p in plans
        if p.contract_id
        and p.contract_id == courier.contract_id
        and p.courier_id is None
    ]
    if contract_plans:
        return max(contract_plans, key=lambda p: (p.effective_from or date.min, p.id))

    project_plans = [
        p
        for p in plans
        if p.project_id
        and p.project_id == courier.primary_project_id
        and p.courier_id is None
    ]
    if project_plans:
        return max(project_plans, key=lambda p: (p.effective_from or date.min, p.id))

    company_plans = [
        p
        for p in plans
        if p.project_id is None
        and p.contract_id is None
        and p.contract_branch_id is None
        and p.courier_id is None
    ]
    if company_plans:
        return max(company_plans, key=lambda p: (p.effective_from or date.min, p.id))

    return None


def eligible_orders_for_courier(db: Session, courier: Courier, month: str) -> int:
    start, end = month_bounds(month)
    query = db.query(DailyLog).filter(
        DailyLog.courier_id == courier.id,
        DailyLog.log_date >= start,
        DailyLog.log_date < end,
    )
    if courier.primary_project_id:
        query = query.filter(DailyLog.project_id == courier.primary_project_id)
    return sum(max(int(row.orders_count or 0), 0) for row in query.all())


def calculate_courier_bonuses(
    db: Session,
    couriers: list[Courier],
    month: str,
    orders_override: Optional[dict[int, int]] = None,
) -> dict[int, dict]:
    """Apply bonus rules supporting Target-Tier and Flat Per-Order plans with accountant override support."""
    if not couriers:
        return {}
    start, period_end = month_bounds(month)
    as_of = period_end.fromordinal(period_end.toordinal() - 1)
    tenant_id = couriers[0].tenant_id
    if any(courier.tenant_id != tenant_id for courier in couriers):
        raise ValueError("Batch bonus calculation requires one tenant")
    ids = [courier.id for courier in couriers]
    all_plans = [
        p
        for p in db.query(BonusPlan)
        .filter(BonusPlan.tenant_id == tenant_id, BonusPlan.is_active.is_(True))
        .all()
        if _plan_is_effective(p, as_of)
    ]

    logs_by_courier: dict[int, list[DailyLog]] = defaultdict(list)
    for row in (
        db.query(DailyLog)
        .filter(
            DailyLog.courier_id.in_(ids),
            DailyLog.log_date >= start,
            DailyLog.log_date < period_end,
        )
        .all()
    ):
        logs_by_courier[row.courier_id].append(row)

    results: dict[int, dict] = {}
    for courier in couriers:
        # Match resolution
        overrides = [p for p in all_plans if p.courier_id == courier.id]
        branch_plans = [
            p
            for p in all_plans
            if p.contract_branch_id
            and p.contract_branch_id == courier.contract_branch_id
            and p.courier_id is None
        ]
        contract_plans = [
            p
            for p in all_plans
            if p.contract_id
            and p.contract_id == courier.contract_id
            and p.courier_id is None
        ]
        project_plans = [
            p
            for p in all_plans
            if p.project_id
            and p.project_id == courier.primary_project_id
            and p.courier_id is None
        ]
        company_plans = [
            p
            for p in all_plans
            if p.project_id is None
            and p.contract_id is None
            and p.contract_branch_id is None
            and p.courier_id is None
        ]

        plan = None
        source = None
        if overrides:
            plan = max(overrides, key=lambda p: (p.effective_from or date.min, p.id))
            source = "rider_override"
        elif branch_plans:
            plan = max(branch_plans, key=lambda p: (p.effective_from or date.min, p.id))
            source = "branch"
        elif contract_plans:
            plan = max(
                contract_plans, key=lambda p: (p.effective_from or date.min, p.id)
            )
            source = "contract"
        elif project_plans:
            plan = max(
                project_plans, key=lambda p: (p.effective_from or date.min, p.id)
            )
            source = "project"
        elif company_plans:
            plan = max(
                company_plans, key=lambda p: (p.effective_from or date.min, p.id)
            )
            source = "company"

        raw_driver_orders = sum(
            max(int(row.orders_count or 0), 0)
            for row in logs_by_courier.get(courier.id, [])
            if not courier.primary_project_id
            or row.project_id == courier.primary_project_id
        )

        is_overridden = orders_override is not None and courier.id in orders_override
        approved_orders = orders_override[courier.id] if is_overridden else raw_driver_orders

        if not plan:
            results[courier.id] = {
                "plan_id": None,
                "source": None,
                "orders": approved_orders,
                "driver_orders": raw_driver_orders,
                "is_overridden": is_overridden,
                "target": 0,
                "earned": 0.0,
                "achieved": False,
                "remaining_orders": 0,
                "over_orders": 0,
                "over_target_rate": 0.0,
                "below_target_rate": 0.0,
                "flat_order_rate": 0.0,
                "bonus_amount": 0.0,
                "plan_type": "NONE",
            }
            continue

        calc = calculate_plan_earnings(approved_orders, plan)
        results[courier.id] = {
            "plan_id": plan.id,
            "source": source,
            "orders": approved_orders,
            "driver_orders": raw_driver_orders,
            "is_overridden": is_overridden,
            **calc,
        }
    return results


def calculate_courier_bonus(db: Session, courier: Courier, month: str) -> dict:
    return calculate_courier_bonuses(db, [courier], month)[courier.id]


def _legacy_compensation_contract(db: Session, courier: Courier) -> Optional[Contract]:
    """Retain pre-existing explicit rider-contract compensation without using commercial terms."""
    candidates = (
        db.query(Contract)
        .filter(
            Contract.tenant_id == courier.tenant_id,
            Contract.status == "ACTIVE",
            Contract.scope_type.in_(("COURIER", "MANUAL", "PROJECT")),
        )
        .all()
    )
    for contract in candidates:
        if (
            contract.scope_type == "PROJECT"
            and contract.project_id == courier.primary_project_id
        ):
            return contract
        if contract.scope_type in ("COURIER", "MANUAL"):
            try:
                if courier.id in {
                    int(value) for value in json.loads(contract.courier_ids or "[]")
                }:
                    return contract
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
    return None


def calculate_payroll_preview(db: Session, courier: Courier, month: str) -> dict:
    month_bounds(month)
    compensation = _legacy_compensation_contract(db, courier)
    base_salary = float(
        (
            compensation.base_salary
            if (compensation and compensation.base_salary)
            else courier.base_salary
        )
        or 0
    )
    per_delivery_rate = float(
        (
            compensation.per_delivery_rate
            if (compensation and compensation.per_delivery_rate)
            else courier.per_delivery_rate
        )
        or 0
    )
    bonus = calculate_courier_bonus(db, courier, month)
    delivery_pay = round(bonus["orders"] * per_delivery_rate, 2)
    adjustments = (
        db.query(PayrollAdjustment)
        .filter(
            PayrollAdjustment.tenant_id == courier.tenant_id,
            PayrollAdjustment.courier_id == courier.id,
            PayrollAdjustment.month == month,
            or_(
                PayrollAdjustment.status == "APPROVED",
                PayrollAdjustment.status.is_(None),
            ),
        )
        .all()
    )

    # Itemize additions and deductions
    overtime_pay = round(
        sum(float(item.amount or 0) for item in adjustments if item.kind == "OVERTIME"),
        2,
    )
    other_additions = round(
        sum(
            float(item.amount or 0)
            for item in adjustments
            if item.kind in ("BONUS", "ALLOWANCE", "OTHER_EARNING")
        ),
        2,
    )
    additions = round(overtime_pay + other_additions, 2)

    absence_deduction = round(
        sum(float(item.amount or 0) for item in adjustments if item.kind == "ABSENCE"),
        2,
    )
    late_deduction = round(
        sum(
            float(item.amount or 0)
            for item in adjustments
            if item.kind in ("LATE", "EARLY_LEAVE")
        ),
        2,
    )
    advance_deduction = round(
        sum(
            float(item.amount or 0)
            for item in adjustments
            if item.kind in ("ADVANCE", "LOAN")
        ),
        2,
    )
    other_deduction = round(
        sum(
            float(item.amount or 0)
            for item in adjustments
            if item.kind
            in ("PENALTY", "DAMAGE", "VIOLATION", "DEDUCTION", "OTHER_DEDUCTION")
            or item.kind
            not in (
                "OVERTIME",
                "BONUS",
                "ALLOWANCE",
                "OTHER_EARNING",
                "ABSENCE",
                "LATE",
                "EARLY_LEAVE",
                "ADVANCE",
                "LOAN",
            )
        ),
        2,
    )
    deductions = round(
        absence_deduction + late_deduction + advance_deduction + other_deduction, 2
    )

    gross_pay = round(
        base_salary + delivery_pay + float(bonus.get("earned", 0) or 0) + additions, 2
    )
    net_pay = round(gross_pay - deductions, 2)

    itemized = {
        "base_salary": round(base_salary, 2),
        "orders_count": bonus["orders"],
        "per_delivery_rate": round(per_delivery_rate, 2),
        "delivery_pay": delivery_pay,
        "target_bonus": round(float(bonus.get("earned", 0) or 0), 2),
        "overtime_pay": overtime_pay,
        "other_additions": other_additions,
        "gross_pay": gross_pay,
        "absence_deduction": absence_deduction,
        "late_deduction": late_deduction,
        "advance_deduction": advance_deduction,
        "other_deduction": other_deduction,
        "total_deductions": deductions,
        "net_pay": net_pay,
    }

    return {
        "courier_id": courier.id,
        "project_id": courier.primary_project_id,
        "contract_branch_id": courier.contract_branch_id,
        "base_salary": round(base_salary, 2),
        "per_delivery_rate": round(per_delivery_rate, 2),
        "eligible_orders": bonus["orders"],
        "delivery_pay": delivery_pay,
        "bonus": bonus,
        "additions": additions,
        "deductions": deductions,
        "gross_pay": gross_pay,
        "absence_deduction": absence_deduction,
        "late_deduction": late_deduction,
        "advance_deduction": advance_deduction,
        "other_deduction": other_deduction,
        "net_pay": net_pay,
        "itemized_breakdown": itemized,
        "compensation_source": "legacy_rider_contract"
        if compensation
        else "rider_profile",
    }


def calculate_payroll_previews(
    db: Session,
    couriers: list[Courier],
    month: str,
    orders_override: Optional[dict[int, int]] = None,
) -> list[dict]:
    """Batch existing preview calculations with itemized breakdown and accountant override support."""
    if not couriers:
        return []
    month_bounds(month)
    tenant_id = couriers[0].tenant_id
    if any(courier.tenant_id != tenant_id for courier in couriers):
        raise ValueError("Batch payroll calculation requires one tenant")
    candidates = (
        db.query(Contract)
        .filter(
            Contract.tenant_id == tenant_id,
            Contract.status == "ACTIVE",
            Contract.scope_type.in_(("COURIER", "MANUAL", "PROJECT")),
        )
        .all()
    )
    members: dict[int, set[int]] = {}
    for contract in candidates:
        if contract.scope_type in ("COURIER", "MANUAL"):
            try:
                members[contract.id] = {
                    int(value) for value in json.loads(contract.courier_ids or "[]")
                }
            except (TypeError, ValueError, json.JSONDecodeError):
                members[contract.id] = set()
    ids = [courier.id for courier in couriers]
    adjustments_by_courier: dict[int, list[PayrollAdjustment]] = defaultdict(list)
    for adjustment in (
        db.query(PayrollAdjustment)
        .filter(
            PayrollAdjustment.tenant_id == tenant_id,
            PayrollAdjustment.courier_id.in_(ids),
            PayrollAdjustment.month == month,
            or_(
                PayrollAdjustment.status == "APPROVED",
                PayrollAdjustment.status.is_(None),
            ),
        )
        .all()
    ):
        adjustments_by_courier[adjustment.courier_id].append(adjustment)
    bonuses = calculate_courier_bonuses(
        db, couriers, month, orders_override=orders_override
    )
    rows = []
    for courier in couriers:
        compensation = next(
            (
                contract
                for contract in candidates
                if (
                    contract.scope_type == "PROJECT"
                    and contract.project_id == courier.primary_project_id
                )
                or (
                    contract.scope_type in ("COURIER", "MANUAL")
                    and courier.id in members.get(contract.id, set())
                )
            ),
            None,
        )
        base_salary = float(
            (
                compensation.base_salary
                if (compensation and compensation.base_salary)
                else courier.base_salary
            )
            or 0
        )
        per_delivery_rate = float(
            (
                compensation.per_delivery_rate
                if (compensation and compensation.per_delivery_rate)
                else courier.per_delivery_rate
            )
            or 0
        )
        bonus = bonuses[courier.id]
        adjustments = adjustments_by_courier.get(courier.id, [])

        overtime_pay = round(
            sum(
                float(item.amount or 0)
                for item in adjustments
                if item.kind == "OVERTIME"
            ),
            2,
        )
        other_additions = round(
            sum(
                float(item.amount or 0)
                for item in adjustments
                if item.kind in ("BONUS", "ALLOWANCE", "OTHER_EARNING")
            ),
            2,
        )
        additions = round(overtime_pay + other_additions, 2)

        absence_deduction = round(
            sum(
                float(item.amount or 0)
                for item in adjustments
                if item.kind == "ABSENCE"
            ),
            2,
        )
        late_deduction = round(
            sum(
                float(item.amount or 0)
                for item in adjustments
                if item.kind in ("LATE", "EARLY_LEAVE")
            ),
            2,
        )
        advance_deduction = round(
            sum(
                float(item.amount or 0)
                for item in adjustments
                if item.kind in ("ADVANCE", "LOAN")
            ),
            2,
        )
        other_deduction = round(
            sum(
                float(item.amount or 0)
                for item in adjustments
                if item.kind
                in ("PENALTY", "DAMAGE", "VIOLATION", "DEDUCTION", "OTHER_DEDUCTION")
                or item.kind
                not in (
                    "OVERTIME",
                    "BONUS",
                    "ALLOWANCE",
                    "OTHER_EARNING",
                    "ABSENCE",
                    "LATE",
                    "EARLY_LEAVE",
                    "ADVANCE",
                    "LOAN",
                )
            ),
            2,
        )
        deductions = round(
            absence_deduction + late_deduction + advance_deduction + other_deduction, 2
        )

        effective_orders = bonus.get("orders", 0)
        driver_orders = bonus.get("driver_orders", effective_orders)
        is_overridden = bonus.get("is_overridden", False)

        # Prevent accidental double-counting of per-order rate + flat bonus
        if bonus.get("plan_type") == "FLAT_PER_ORDER" and float(bonus.get("flat_order_rate", 0) or 0) > 0:
            effective_rate = float(bonus["flat_order_rate"])
            delivery_pay = round(effective_orders * effective_rate, 2)
            target_bonus_earned = 0.0
        else:
            delivery_pay = round(effective_orders * per_delivery_rate, 2)
            target_bonus_earned = float(bonus.get("earned", 0) or 0)

        gross_pay = round(
            base_salary + delivery_pay + target_bonus_earned + additions,
            2,
        )
        net_pay = round(gross_pay - deductions, 2)

        itemized = {
            "base_salary": round(base_salary, 2),
            "orders_count": effective_orders,
            "driver_orders": driver_orders,
            "approved_orders": effective_orders,
            "is_overridden": is_overridden,
            "per_delivery_rate": round(per_delivery_rate, 2),
            "delivery_pay": delivery_pay,
            "target_bonus": round(target_bonus_earned, 2),
            "overtime_pay": overtime_pay,
            "other_additions": other_additions,
            "gross_pay": gross_pay,
            "absence_deduction": absence_deduction,
            "late_deduction": late_deduction,
            "advance_deduction": advance_deduction,
            "other_deduction": other_deduction,
            "total_deductions": deductions,
            "net_pay": net_pay,
        }

        rows.append(
            {
                "courier_id": courier.id,
                "project_id": courier.primary_project_id,
                "contract_branch_id": courier.contract_branch_id,
                "base_salary": round(base_salary, 2),
                "per_delivery_rate": round(per_delivery_rate, 2),
                "eligible_orders": effective_orders,
                "driver_orders": driver_orders,
                "approved_orders": effective_orders,
                "is_overridden": is_overridden,
                "delivery_pay": delivery_pay,
                "bonus": bonus,
                "additions": additions,
                "deductions": deductions,
                "gross_pay": gross_pay,
                "absence_deduction": absence_deduction,
                "late_deduction": late_deduction,
                "advance_deduction": advance_deduction,
                "other_deduction": other_deduction,
                "net_pay": net_pay,
                "itemized_breakdown": itemized,
                "compensation_source": "legacy_rider_contract"
                if compensation
                else "rider_profile",
            }
        )
    return rows


def branch_financial_preview(
    db: Session,
    tenant_id: int,
    branch: ContractBranch,
    month: str,
    payroll_rows: Optional[list[dict]] = None,
) -> dict:
    month_bounds(month)
    contract = db.get(Contract, branch.contract_id)
    couriers = (
        db.query(Courier)
        .filter(
            Courier.tenant_id == tenant_id,
            Courier.contract_branch_id == branch.id,
        )
        .all()
    )
    rows = (
        payroll_rows
        if payroll_rows is not None
        else [calculate_payroll_preview(db, courier, month) for courier in couriers]
    )
    rows = [row for row in rows if row.get("contract_branch_id") == branch.id]
    eligible_orders = sum(int(row["eligible_orders"]) for row in rows)
    rate = float((contract.client_rate_per_order if contract else 0) or 0)
    client_revenue = round(eligible_orders * rate, 2)
    direct_rider_cost = round(sum(float(row["net_pay"]) for row in rows), 2)
    return {
        "contract_id": branch.contract_id,
        "contract_branch_id": branch.id,
        "project_id": branch.project_id,
        "eligible_orders": eligible_orders,
        "client_rate_per_order": round(rate, 2),
        "client_revenue": client_revenue,
        "direct_rider_cost": direct_rider_cost,
        "operational_margin": round(client_revenue - direct_rider_cost, 2),
        "rate_configured": bool(
            contract and contract.client_rate_per_order is not None
        ),
    }


def payroll_rows(db: Session, tenant_id: int, month: str) -> tuple[list[dict], bool]:
    period = (
        db.query(PayrollPeriod)
        .filter(PayrollPeriod.tenant_id == tenant_id, PayrollPeriod.month == month)
        .first()
    )
    if period and period.status == "FINALIZED":
        snapshots = (
            db.query(PayrollSnapshot)
            .filter(PayrollSnapshot.payroll_period_id == period.id)
            .all()
        )
        result_rows = []
        for item in snapshots:
            c_data = json.loads(item.calculation_data or "{}")
            itemized = c_data.get("itemized_breakdown") or {
                "base_salary": round(float(item.base_salary or 0), 2),
                "orders_count": int(c_data.get("eligible_orders", 0) or 0),
                "driver_orders": int(c_data.get("driver_orders", c_data.get("eligible_orders", 0)) or 0),
                "approved_orders": int(c_data.get("approved_orders", c_data.get("eligible_orders", 0)) or 0),
                "is_overridden": bool(c_data.get("is_overridden", False)),
                "per_delivery_rate": round(
                    float(c_data.get("per_delivery_rate", 0) or 0), 2
                ),
                "delivery_pay": round(float(item.delivery_pay or 0), 2),
                "target_bonus": round(float(item.bonus_pay or 0), 2),
                "overtime_pay": round(float(item.additions or 0), 2),
                "other_additions": 0.0,
                "gross_pay": round(
                    float(item.base_salary or 0)
                    + float(item.delivery_pay or 0)
                    + float(item.bonus_pay or 0)
                    + float(item.additions or 0),
                    2,
                ),
                "absence_deduction": 0.0,
                "late_deduction": 0.0,
                "advance_deduction": 0.0,
                "other_deduction": round(float(item.deductions or 0), 2),
                "total_deductions": round(float(item.deductions or 0), 2),
                "net_pay": round(float(item.net_pay or 0), 2),
            }
            result_rows.append(
                {
                    "courier_id": item.courier_id,
                    "project_id": item.project_id,
                    "contract_branch_id": item.contract_branch_id,
                    "base_salary": round(float(item.base_salary or 0), 2),
                    "delivery_pay": round(float(item.delivery_pay or 0), 2),
                    "bonus": c_data.get("bonus", {}),
                    "eligible_orders": int(c_data.get("eligible_orders", 0) or 0),
                    "driver_orders": int(c_data.get("driver_orders", c_data.get("eligible_orders", 0)) or 0),
                    "approved_orders": int(c_data.get("approved_orders", c_data.get("eligible_orders", 0)) or 0),
                    "is_overridden": bool(c_data.get("is_overridden", False)),
                    "per_delivery_rate": round(
                        float(c_data.get("per_delivery_rate", 0) or 0), 2
                    ),
                    "additions": round(float(item.additions or 0), 2),
                    "deductions": round(float(item.deductions or 0), 2),
                    "gross_pay": itemized.get(
                        "gross_pay",
                        round(
                            float(item.base_salary or 0)
                            + float(item.delivery_pay or 0)
                            + float(item.bonus_pay or 0)
                            + float(item.additions or 0),
                            2,
                        ),
                    ),
                    "absence_deduction": itemized.get("absence_deduction", 0.0),
                    "late_deduction": itemized.get("late_deduction", 0.0),
                    "advance_deduction": itemized.get("advance_deduction", 0.0),
                    "other_deduction": itemized.get(
                        "other_deduction", round(float(item.deductions or 0), 2)
                    ),
                    "net_pay": round(float(item.net_pay or 0), 2),
                    "itemized_breakdown": itemized,
                    "finalized": True,
                }
            )
        return result_rows, True

    orders_override = None
    if period and period.draft_overrides:
        try:
            parsed = json.loads(period.draft_overrides)
            if isinstance(parsed, dict) and "orders" in parsed:
                orders_override = {int(k): int(v) for k, v in parsed["orders"].items()}
            elif isinstance(parsed, dict):
                orders_override = {int(k): int(v) for k, v in parsed.items()}
        except Exception:
            orders_override = None

    couriers = (
        db.query(Courier)
        .filter(Courier.tenant_id == tenant_id)
        .order_by(Courier.name)
        .all()
    )
    return calculate_payroll_previews(
        db, couriers, month, orders_override=orders_override
    ), False


def finalize_payroll_period(
    db: Session, tenant_id: int, month: str, actor_id: int
) -> dict:
    month_bounds(month)
    period = (
        db.query(PayrollPeriod)
        .filter(PayrollPeriod.tenant_id == tenant_id, PayrollPeriod.month == month)
        .with_for_update()
        .first()
    )
    if period and period.status == "FINALIZED":
        return {
            "period_id": period.id,
            "month": month,
            "status": "FINALIZED",
            "already_finalized": True,
        }
    if not period:
        period = PayrollPeriod(tenant_id=tenant_id, month=month, status="DRAFT")
        db.add(period)
        db.flush()
    orders_override = None
    if period and period.draft_overrides:
        try:
            parsed = json.loads(period.draft_overrides)
            if isinstance(parsed, dict) and "orders" in parsed:
                orders_override = {int(k): int(v) for k, v in parsed["orders"].items()}
            elif isinstance(parsed, dict):
                orders_override = {int(k): int(v) for k, v in parsed.items()}
        except Exception:
            orders_override = None

    couriers = (
        db.query(Courier)
        .filter(Courier.tenant_id == tenant_id)
        .order_by(Courier.id)
        .all()
    )
    rows = calculate_payroll_previews(
        db, couriers, month, orders_override=orders_override
    )
    for row in rows:
        db.add(
            PayrollSnapshot(
                payroll_period_id=period.id,
                tenant_id=tenant_id,
                courier_id=row["courier_id"],
                project_id=row["project_id"],
                contract_branch_id=row["contract_branch_id"],
                base_salary=row["base_salary"],
                delivery_pay=row["delivery_pay"],
                bonus_pay=row["bonus"]["earned"],
                additions=row["additions"],
                deductions=row["deductions"],
                net_pay=row["net_pay"],
                calculation_data=json.dumps(
                    {
                        "bonus": row["bonus"],
                        "eligible_orders": row["eligible_orders"],
                        "driver_orders": row.get("driver_orders", row["eligible_orders"]),
                        "approved_orders": row.get("approved_orders", row["eligible_orders"]),
                        "is_overridden": row.get("is_overridden", False),
                        "per_delivery_rate": row["per_delivery_rate"],
                        "compensation_source": row["compensation_source"],
                        "itemized_breakdown": row.get("itemized_breakdown"),
                    }
                ),
            )
        )
    branches = (
        db.query(ContractBranch)
        .filter(
            ContractBranch.tenant_id == tenant_id, ContractBranch.is_active.is_(True)
        )
        .all()
    )
    for branch in branches:
        financial = branch_financial_preview(db, tenant_id, branch, month, rows)
        db.add(
            OperationalFinancialSnapshot(
                payroll_period_id=period.id,
                tenant_id=tenant_id,
                contract_id=financial["contract_id"],
                contract_branch_id=branch.id,
                project_id=financial["project_id"],
                eligible_orders=financial["eligible_orders"],
                client_rate_per_order=financial["client_rate_per_order"],
                client_revenue=financial["client_revenue"],
                direct_rider_cost=financial["direct_rider_cost"],
                operational_margin=financial["operational_margin"],
                calculation_data=json.dumps(
                    {"rate_configured": financial["rate_configured"]}
                ),
            )
        )
    period.status = "FINALIZED"
    period.finalized_by = actor_id
    period.finalized_at = datetime.utcnow()
    db.commit()
    return {
        "period_id": period.id,
        "month": month,
        "status": "FINALIZED",
        "snapshots": len(rows),
        "already_finalized": False,
    }


def financial_rows(
    db: Session, tenant_id: int, month: str, payroll_data: Optional[list[dict]] = None
) -> tuple[list[dict], bool]:
    period = (
        db.query(PayrollPeriod)
        .filter(PayrollPeriod.tenant_id == tenant_id, PayrollPeriod.month == month)
        .first()
    )
    if period and period.status == "FINALIZED":
        rows = (
            db.query(OperationalFinancialSnapshot)
            .filter(OperationalFinancialSnapshot.payroll_period_id == period.id)
            .all()
        )
        return [
            {
                "contract_id": row.contract_id,
                "contract_branch_id": row.contract_branch_id,
                "project_id": row.project_id,
                "eligible_orders": row.eligible_orders,
                "client_rate_per_order": round(
                    float(row.client_rate_per_order or 0), 2
                ),
                "client_revenue": round(float(row.client_revenue or 0), 2),
                "direct_rider_cost": round(float(row.direct_rider_cost or 0), 2),
                "operational_margin": round(float(row.operational_margin or 0), 2),
                "rate_configured": bool(
                    json.loads(row.calculation_data or "{}").get("rate_configured")
                ),
                "finalized": True,
            }
            for row in rows
        ], True
    branches = (
        db.query(ContractBranch)
        .filter(
            ContractBranch.tenant_id == tenant_id, ContractBranch.is_active.is_(True)
        )
        .all()
    )
    return [
        branch_financial_preview(db, tenant_id, branch, month, payroll_data)
        for branch in branches
    ], False


def courier_financial_rows(
    db: Session, tenant_id: int, month: str
) -> tuple[list[dict], bool]:
    """Authoritative rider-level reporting rows derived from existing payroll/branch outputs.

    This is intentionally a read composition inside the financial service: payroll
    values come from ``payroll_rows`` and commercial rate/snapshot state comes
    from ``financial_rows``. It does not alter a bonus, payroll, revenue, or margin rule.
    """
    payroll, payroll_finalized = payroll_rows(db, tenant_id, month)
    branch_rows, financial_finalized = financial_rows(db, tenant_id, month, payroll)
    by_branch = {
        row["contract_branch_id"]: row
        for row in branch_rows
        if row.get("contract_branch_id")
    }
    rows = []
    for row in payroll:
        branch_id = row.get("contract_branch_id")
        branch = by_branch.get(branch_id, {})
        orders = int(
            row.get("eligible_orders") or (row.get("bonus") or {}).get("orders") or 0
        )
        rate = float(branch.get("client_rate_per_order") or 0)
        payroll_cost = round(float(row.get("net_pay") or 0), 2)
        client_revenue = round(orders * rate, 2)
        rows.append(
            {
                "courier_id": row["courier_id"],
                "project_id": row.get("project_id"),
                "contract_branch_id": branch_id,
                "eligible_orders": orders,
                "base_salary": round(float(row.get("base_salary") or 0), 2),
                "delivery_pay": round(float(row.get("delivery_pay") or 0), 2),
                "bonus": round(
                    float((row.get("bonus") or {}).get("earned", 0) or 0), 2
                ),
                "additions": round(float(row.get("additions") or 0), 2),
                "deductions": round(float(row.get("deductions") or 0), 2),
                "payroll_cost": payroll_cost,
                "client_rate_per_order": round(rate, 2),
                "client_revenue": client_revenue,
                "operational_margin": round(client_revenue - payroll_cost, 2),
                "finalized": bool(payroll_finalized and financial_finalized),
            }
        )
    return rows, bool(payroll_finalized and financial_finalized)

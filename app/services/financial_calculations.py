"""Authoritative Phase 1 financial calculations.

The module deliberately separates client revenue from rider compensation.  It uses
DailyLog as the existing eligible-performance source for Phase 1 and never creates
attendance deductions because no company deduction policy exists yet.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models.entities import (
    BonusPlan,
    Contract,
    ContractBranch,
    Courier,
    CourierDebt,
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


def open_debts_for(
    db: Session, tenant_id: int, courier_ids: list[int], month: str
) -> dict[int, list[CourierDebt]]:
    """Unsettled debt carried in from months strictly before ``month``.

    ``origin_month`` is a zero-padded ``YYYY-MM`` string, so lexical ordering
    matches chronological ordering.
    """
    if not courier_ids:
        return {}
    grouped: dict[int, list[CourierDebt]] = defaultdict(list)
    for row in (
        db.query(CourierDebt)
        .filter(
            CourierDebt.tenant_id == tenant_id,
            CourierDebt.courier_id.in_(courier_ids),
            CourierDebt.status == "OPEN",
            CourierDebt.remaining > 0,
            CourierDebt.origin_month < month,
        )
        .order_by(CourierDebt.origin_month, CourierDebt.id)
        .all()
    ):
        grouped[row.courier_id].append(row)
    return grouped


def apply_debt_settlement(net_before_debt: float, carried_debt: float) -> dict:
    """Split a month's raw net into what is paid, what settles old debt, and what rolls over.

    A rider is never paid a negative amount: the shortfall becomes debt that is
    deducted automatically from later months.
    """
    net_before_debt = round(float(net_before_debt or 0.0), 2)
    carried_debt = max(round(float(carried_debt or 0.0), 2), 0.0)
    applied = round(min(max(net_before_debt, 0.0), carried_debt), 2)
    net_after = round(net_before_debt - applied, 2)
    generated = round(-net_after, 2) if net_after < 0 else 0.0
    net_pay = round(max(net_after, 0.0), 2)
    return {
        "carried_debt_total": carried_debt,
        "carried_debt_applied": applied,
        "debt_generated": generated,
        "debt_balance": round(carried_debt - applied + generated, 2),
        "net_before_debt": net_before_debt,
        "net_pay": net_pay,
    }


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


# Money keys on a payroll row, zeroed for a rider this tenant does not pay.
# The row itself is computed through the normal path and then zeroed rather than
# built by hand: a hand-built row missed `bonus["earned"]` and turned the 500
# this was fixing into a KeyError, because the real shape is deeper than its
# top-level keys suggest.
_PAYROLL_MONEY_KEYS = (
    "base_salary", "per_delivery_rate", "delivery_pay", "additions",
    "deductions", "gross_pay", "absence_deduction", "late_deduction",
    "advance_deduction", "other_deduction", "net_before_debt",
    "carried_debt_total", "carried_debt_applied", "debt_generated",
    "debt_balance", "net_pay",
)
_PAYROLL_COUNT_KEYS = ("eligible_orders", "driver_orders", "approved_orders")


def _zero_money(value):
    """Zero every number in a nested payroll structure, leaving its shape."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return type(value)(0)
    if isinstance(value, dict):
        return {k: _zero_money(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_zero_money(v) for v in value]
    return value


def outsourced_payroll_row(db: Session, courier: Courier, month: str) -> dict:
    """A complete, zeroed payroll row for a rider this tenant does not pay.

    Computed through the same path as everyone else and then zeroed, so its
    shape can never drift from a real row — every key a caller reads exists,
    at any depth.
    """
    rows = calculate_payroll_previews(db, [courier], month, _include_outsourced=True)
    row = rows[0] if rows else {"courier_id": courier.id}
    row = {
        key: (value if key in ("courier_id", "project_id", "contract_branch_id")
              else _zero_money(value))
        for key, value in row.items()
    }
    row["compensation_source"] = "OUTSOURCED_3PL"
    row["employment_model"] = "OUTSOURCED_3PL"
    row["operator_tenant_id"] = getattr(courier, "operator_tenant_id", None)
    row["is_overridden"] = False
    row["is_in_debt"] = False
    return row


def calculate_payroll_preview(db: Session, courier: Courier, month: str) -> dict:
    """Payroll for one rider, read through the same path as the payroll sheet.

    This delegates to :func:`payroll_rows` on purpose. A separate single-rider
    calculation used to exist here and silently disagreed with the sheet that
    actually pays: it ignored accountant order overrides, recomputed finalized
    months instead of reading their snapshot, and priced FLAT_PER_ORDER plans
    differently. One path removes that whole class of divergence.
    """
    if getattr(courier, "employment_model", None) == "OUTSOURCED_3PL":
        # An outsourced rider is paid by their own operator, not by this
        # tenant — but four callers read this function's result without
        # catching anything, two of them inside a loop over a whole fleet, so
        # raising took down the rider profile and both report endpoints with a
        # 500 for every account that had one. The answer is a complete row that
        # says "nothing is payable here", not an exception: the payroll sheet
        # excludes these riders in SQL, so a zeroed row can pay no one.
        return outsourced_payroll_row(db, courier, month)

    rows, _ = payroll_rows(db, courier.tenant_id, month, courier_ids=[courier.id])
    for row in rows:
        if row["courier_id"] == courier.id:
            return row
    # Rider has no snapshot in an already finalized month (hired afterwards).
    return calculate_payroll_previews(db, [courier], month)[0]


def calculate_payroll_previews(
    db: Session,
    couriers: list[Courier],
    month: str,
    orders_override: Optional[dict[int, int]] = None,
    _include_outsourced: bool = False,
) -> list[dict]:
    """Batch existing preview calculations with itemized breakdown and accountant override support.

    `_include_outsourced` exists only for :func:`outsourced_payroll_row`, which
    needs a real row's shape before zeroing it. No caller that pays anyone sets
    it. A missing `employment_model` reads as DIRECT_HIRE: a rider must never
    drop out of payroll because a flag was never set.
    """
    if not _include_outsourced:
        couriers = [
            c
            for c in couriers
            if (getattr(c, "employment_model", None) or "DIRECT_HIRE")
            != "OUTSOURCED_3PL"
        ]
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
    debts_by_courier = open_debts_for(db, tenant_id, ids, month)
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
        carried_debt = round(
            sum(
                float(debt.remaining or 0.0)
                for debt in debts_by_courier.get(courier.id, [])
            ),
            2,
        )
        settlement = apply_debt_settlement(gross_pay - deductions, carried_debt)
        net_pay = settlement["net_pay"]

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
            "net_before_debt": settlement["net_before_debt"],
            "carried_debt_total": settlement["carried_debt_total"],
            "carried_debt_applied": settlement["carried_debt_applied"],
            "debt_generated": settlement["debt_generated"],
            "debt_balance": settlement["debt_balance"],
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
                "net_before_debt": settlement["net_before_debt"],
                "carried_debt_total": settlement["carried_debt_total"],
                "carried_debt_applied": settlement["carried_debt_applied"],
                "debt_generated": settlement["debt_generated"],
                "debt_balance": settlement["debt_balance"],
                "is_in_debt": settlement["debt_balance"] > 0,
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
        else calculate_payroll_previews(db, couriers, month)
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


def payroll_rows(
    db: Session,
    tenant_id: int,
    month: str,
    courier_ids: Optional[list[int]] = None,
) -> tuple[list[dict], bool]:
    """Authoritative payroll rows for a month, plus whether the month is finalized.

    ``courier_ids`` narrows the computation to specific riders without changing
    any amount, so a single-rider view does not pay the cost of the whole tenant.
    """
    period = (
        db.query(PayrollPeriod)
        .filter(PayrollPeriod.tenant_id == tenant_id, PayrollPeriod.month == month)
        .first()
    )
    if period and period.status == "FINALIZED":
        snapshot_query = db.query(PayrollSnapshot).filter(
            PayrollSnapshot.payroll_period_id == period.id
        )
        if courier_ids is not None:
            snapshot_query = snapshot_query.filter(
                PayrollSnapshot.courier_id.in_(courier_ids)
            )
        snapshots = snapshot_query.all()
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
                    "net_before_debt": itemized.get(
                        "net_before_debt", round(float(item.net_pay or 0), 2)
                    ),
                    "carried_debt_total": itemized.get("carried_debt_total", 0.0),
                    "carried_debt_applied": itemized.get("carried_debt_applied", 0.0),
                    "debt_generated": itemized.get("debt_generated", 0.0),
                    "debt_balance": itemized.get("debt_balance", 0.0),
                    "is_in_debt": float(itemized.get("debt_balance", 0.0) or 0.0) > 0,
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

    # `employment_model != 'OUTSOURCED_3PL'` is NULL for a NULL column, and a
    # NULL predicate is not true, so every rider whose model was never set
    # vanished from the payroll sheet in silence. The migration created the
    # column nullable even though the model declares it NOT NULL, so production
    # can hold NULLs that no test can reproduce. A rider missing from payroll
    # must never be the result of an unset flag.
    courier_query = db.query(Courier).filter(
        Courier.tenant_id == tenant_id,
        or_(
            Courier.employment_model.is_(None),
            Courier.employment_model != "OUTSOURCED_3PL",
        ),
    )
    if courier_ids is not None:
        courier_query = courier_query.filter(Courier.id.in_(courier_ids))
    couriers = courier_query.order_by(Courier.name).all()
    return calculate_payroll_previews(
        db, couriers, month, orders_override=orders_override
    ), False


def _persist_debt_settlement(
    db: Session, tenant_id: int, month: str, rows: list[dict]
) -> None:
    """Write the debt movement a finalized month implies.

    Preview never touches these records — only finalization does — so reading a
    payroll sheet stays free of side effects. Older debts settle first so a
    rider clears the longest-standing balance before a newer one.
    """
    debts_by_courier = open_debts_for(
        db, tenant_id, [row["courier_id"] for row in rows], month
    )
    for row in rows:
        applied = round(float(row.get("carried_debt_applied") or 0.0), 2)
        for debt in debts_by_courier.get(row["courier_id"], []):
            if applied <= 0:
                break
            take = min(round(float(debt.remaining or 0.0), 2), applied)
            debt.remaining = round(float(debt.remaining or 0.0) - take, 2)
            applied = round(applied - take, 2)
            if debt.remaining <= 0:
                debt.remaining = 0.0
                debt.status = "SETTLED"
                debt.settled_month = month

        generated = round(float(row.get("debt_generated") or 0.0), 2)
        if generated <= 0:
            continue
        existing = (
            db.query(CourierDebt)
            .filter(
                CourierDebt.tenant_id == tenant_id,
                CourierDebt.courier_id == row["courier_id"],
                CourierDebt.origin_month == month,
            )
            .first()
        )
        if existing:
            existing.amount = generated
            existing.remaining = generated
            existing.status = "OPEN"
            existing.settled_month = None
        else:
            db.add(
                CourierDebt(
                    tenant_id=tenant_id,
                    courier_id=row["courier_id"],
                    origin_month=month,
                    amount=generated,
                    remaining=generated,
                    status="OPEN",
                    note="ترحيل تلقائي: السلف والخصومات تجاوزت مستحقات الشهر",
                )
            )


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
    _persist_debt_settlement(db, tenant_id, month, rows)
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

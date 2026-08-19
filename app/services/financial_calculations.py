"""Authoritative Phase 1 financial calculations.

The module deliberately separates client revenue from rider compensation.  It uses
DailyLog as the existing eligible-performance source for Phase 1 and never creates
attendance deductions because no company deduction policy exists yet.
"""
from __future__ import annotations

from datetime import date, datetime
import json
from typing import Optional

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
    Project,
)


def month_bounds(month: str) -> tuple[date, date]:
    try:
        year, number = (int(part) for part in month.split("-", 1))
        start = date(year, number, 1)
    except (AttributeError, TypeError, ValueError):
        raise ValueError("صيغة الشهر يجب أن تكون YYYY-MM")
    end = date(year + 1, 1, 1) if number == 12 else date(year, number + 1, 1)
    return start, end


def calculate_target_bonus(orders: int, target: int, target_bonus: float, over_target_rate: float) -> dict:
    orders = max(int(orders or 0), 0)
    target = max(int(target or 0), 0)
    target_bonus = max(float(target_bonus or 0), 0.0)
    over_target_rate = max(float(over_target_rate or 0), 0.0)
    achieved = target > 0 and orders >= target
    over_orders = max(orders - target, 0) if achieved else 0
    earned = target_bonus + over_orders * over_target_rate if achieved else 0.0
    return {
        "achieved": achieved,
        "remaining_orders": max(target - orders, 0),
        "over_orders": over_orders,
        "earned": round(earned, 2),
    }


def _plan_is_effective(plan: BonusPlan, as_of: date) -> bool:
    return bool(
        plan.is_active
        and (not plan.effective_from or plan.effective_from <= as_of)
        and (not plan.effective_to or plan.effective_to >= as_of)
    )


def bonus_plan_for_courier(db: Session, courier: Courier, as_of: date) -> Optional[BonusPlan]:
    """Explicit rider override wins; otherwise the branch/project plan is inherited."""
    if not courier.primary_project_id:
        return None
    base = db.query(BonusPlan).filter(
        BonusPlan.tenant_id == courier.tenant_id,
        BonusPlan.project_id == courier.primary_project_id,
        BonusPlan.is_active.is_(True),
    )
    if courier.contract_branch_id:
        base = base.filter(BonusPlan.contract_branch_id == courier.contract_branch_id)
    else:
        base = base.filter(BonusPlan.contract_branch_id.is_(None))
    plans = [plan for plan in base.all() if _plan_is_effective(plan, as_of)]
    overrides = [plan for plan in plans if plan.courier_id == courier.id]
    inherited = [plan for plan in plans if plan.courier_id is None]
    key = lambda plan: (plan.effective_from or date.min, plan.id)
    return max(overrides, key=key) if overrides else (max(inherited, key=key) if inherited else None)


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


def calculate_courier_bonus(db: Session, courier: Courier, month: str) -> dict:
    _, period_end = month_bounds(month)
    as_of = period_end.fromordinal(period_end.toordinal() - 1)
    plan = bonus_plan_for_courier(db, courier, as_of)
    orders = eligible_orders_for_courier(db, courier, month)
    if not plan:
        return {"plan_id": None, "source": None, "orders": orders, "target": 0, "earned": 0.0, "achieved": False, "remaining_orders": 0, "over_orders": 0, "over_target_rate": 0.0}
    result = calculate_target_bonus(orders, plan.target_orders, plan.bonus_amount, plan.over_target_rate)
    return {
        "plan_id": plan.id,
        "source": "override" if plan.courier_id else "inherited",
        "orders": orders,
        "target": plan.target_orders,
        "bonus_amount": round(float(plan.bonus_amount or 0), 2),
        "over_target_rate": round(float(plan.over_target_rate or 0), 2),
        **result,
    }


def _legacy_compensation_contract(db: Session, courier: Courier) -> Optional[Contract]:
    """Retain pre-existing explicit rider-contract compensation without using commercial terms."""
    candidates = db.query(Contract).filter(
        Contract.tenant_id == courier.tenant_id,
        Contract.status == "ACTIVE",
        Contract.scope_type.in_(("COURIER", "MANUAL", "PROJECT")),
    ).all()
    for contract in candidates:
        if contract.scope_type == "PROJECT" and contract.project_id == courier.primary_project_id:
            return contract
        if contract.scope_type in ("COURIER", "MANUAL"):
            try:
                if courier.id in {int(value) for value in json.loads(contract.courier_ids or "[]")}:
                    return contract
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
    return None


def calculate_payroll_preview(db: Session, courier: Courier, month: str) -> dict:
    month_bounds(month)
    compensation = _legacy_compensation_contract(db, courier)
    base_salary = float((compensation.base_salary if compensation else courier.base_salary) or 0)
    per_delivery_rate = float((compensation.per_delivery_rate if compensation else courier.per_delivery_rate) or 0)
    bonus = calculate_courier_bonus(db, courier, month)
    delivery_pay = round(bonus["orders"] * per_delivery_rate, 2)
    adjustments = db.query(PayrollAdjustment).filter(
        PayrollAdjustment.tenant_id == courier.tenant_id,
        PayrollAdjustment.courier_id == courier.id,
        PayrollAdjustment.month == month,
    ).all()
    additions = round(sum(float(item.amount or 0) for item in adjustments if item.kind == "OVERTIME"), 2)
    deductions = round(sum(float(item.amount or 0) for item in adjustments if item.kind != "OVERTIME"), 2)
    net_pay = round(base_salary + delivery_pay + float(bonus["earned"]) + additions - deductions, 2)
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
        "net_pay": net_pay,
        "compensation_source": "legacy_rider_contract" if compensation else "rider_profile",
    }


def branch_financial_preview(db: Session, tenant_id: int, branch: ContractBranch, month: str, payroll_rows: Optional[list[dict]] = None) -> dict:
    month_bounds(month)
    contract = db.get(Contract, branch.contract_id)
    couriers = db.query(Courier).filter(
        Courier.tenant_id == tenant_id,
        Courier.contract_branch_id == branch.id,
    ).all()
    rows = payroll_rows if payroll_rows is not None else [calculate_payroll_preview(db, courier, month) for courier in couriers]
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
        "rate_configured": bool(contract and contract.client_rate_per_order is not None),
    }


def payroll_rows(db: Session, tenant_id: int, month: str) -> tuple[list[dict], bool]:
    period = db.query(PayrollPeriod).filter(PayrollPeriod.tenant_id == tenant_id, PayrollPeriod.month == month).first()
    if period and period.status == "FINALIZED":
        snapshots = db.query(PayrollSnapshot).filter(PayrollSnapshot.payroll_period_id == period.id).all()
        return [{
            "courier_id": item.courier_id,
            "project_id": item.project_id,
            "contract_branch_id": item.contract_branch_id,
            "base_salary": round(float(item.base_salary or 0), 2),
            "delivery_pay": round(float(item.delivery_pay or 0), 2),
            "bonus": json.loads(item.calculation_data or "{}").get("bonus", {}),
            "eligible_orders": int(json.loads(item.calculation_data or "{}").get("eligible_orders", 0) or 0),
            "per_delivery_rate": round(float(json.loads(item.calculation_data or "{}").get("per_delivery_rate", 0) or 0), 2),
            "additions": round(float(item.additions or 0), 2),
            "deductions": round(float(item.deductions or 0), 2),
            "net_pay": round(float(item.net_pay or 0), 2),
            "finalized": True,
        } for item in snapshots], True
    couriers = db.query(Courier).filter(Courier.tenant_id == tenant_id).order_by(Courier.name).all()
    return [calculate_payroll_preview(db, courier, month) for courier in couriers], False


def finalize_payroll_period(db: Session, tenant_id: int, month: str, actor_id: int) -> dict:
    month_bounds(month)
    period = db.query(PayrollPeriod).filter(PayrollPeriod.tenant_id == tenant_id, PayrollPeriod.month == month).first()
    if period and period.status == "FINALIZED":
        return {"period_id": period.id, "month": month, "status": "FINALIZED", "already_finalized": True}
    if not period:
        period = PayrollPeriod(tenant_id=tenant_id, month=month, status="DRAFT")
        db.add(period)
        db.flush()
    couriers = db.query(Courier).filter(Courier.tenant_id == tenant_id).order_by(Courier.id).all()
    rows = [calculate_payroll_preview(db, courier, month) for courier in couriers]
    for row in rows:
        db.add(PayrollSnapshot(
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
            calculation_data=json.dumps({
                "bonus": row["bonus"], "eligible_orders": row["eligible_orders"],
                "per_delivery_rate": row["per_delivery_rate"], "compensation_source": row["compensation_source"],
            }),
        ))
    branches = db.query(ContractBranch).filter(ContractBranch.tenant_id == tenant_id, ContractBranch.is_active.is_(True)).all()
    for branch in branches:
        financial = branch_financial_preview(db, tenant_id, branch, month, rows)
        db.add(OperationalFinancialSnapshot(
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
            calculation_data=json.dumps({"rate_configured": financial["rate_configured"]}),
        ))
    period.status = "FINALIZED"
    period.finalized_by = actor_id
    period.finalized_at = datetime.utcnow()
    db.commit()
    return {"period_id": period.id, "month": month, "status": "FINALIZED", "snapshots": len(rows), "already_finalized": False}


def financial_rows(db: Session, tenant_id: int, month: str) -> tuple[list[dict], bool]:
    period = db.query(PayrollPeriod).filter(PayrollPeriod.tenant_id == tenant_id, PayrollPeriod.month == month).first()
    if period and period.status == "FINALIZED":
        rows = db.query(OperationalFinancialSnapshot).filter(OperationalFinancialSnapshot.payroll_period_id == period.id).all()
        return [{
            "contract_id": row.contract_id,
            "contract_branch_id": row.contract_branch_id,
            "project_id": row.project_id,
            "eligible_orders": row.eligible_orders,
            "client_rate_per_order": round(float(row.client_rate_per_order or 0), 2),
            "client_revenue": round(float(row.client_revenue or 0), 2),
            "direct_rider_cost": round(float(row.direct_rider_cost or 0), 2),
            "operational_margin": round(float(row.operational_margin or 0), 2),
            "rate_configured": bool(json.loads(row.calculation_data or "{}").get("rate_configured")),
            "finalized": True,
        } for row in rows], True
    branches = db.query(ContractBranch).filter(ContractBranch.tenant_id == tenant_id, ContractBranch.is_active.is_(True)).all()
    return [branch_financial_preview(db, tenant_id, branch, month) for branch in branches], False

"""Read-only Phase 1 analytics composition.

This module deliberately consumes DailyLog, Attendance, payroll_rows and
financial_rows.  It does not create a second bonus, payroll, revenue, or
margin calculation engine and it performs no mutations while serving reports.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import json
from typing import Callable, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..models.entities import (
    Attendance,
    AttendanceEvent,
    Contract,
    ContractBranch,
    Courier,
    DailyLog,
    GeoCity,
    Project,
    TenantOperatingCity,
    User,
    UserRole,
)
from .financial_calculations import calculate_courier_bonuses, courier_financial_rows


COMMERCIAL_ROLES = (UserRole.COMPANY, UserRole.COMPANY_ADMIN)


def _month_for(day: date) -> str:
    return day.strftime("%Y-%m")


def _permissions(user: User, role_permissions: dict) -> set[str]:
    if user.custom_permissions:
        try:
            return set(json.loads(user.custom_permissions))
        except (TypeError, ValueError, json.JSONDecodeError):
            return set()
    return set(role_permissions.get(user.role, []))


def _scoped_courier_query(
    db: Session,
    user: User,
    supervisor_scope: Callable[[Session, int], object],
):
    """Start with tenant/team scope before applying every requested filter."""
    query = db.query(Courier).filter(Courier.tenant_id == user.tenant_id)
    if user.role == UserRole.SUPERVISOR:
        query = query.filter(supervisor_scope(db, user.id))
    elif user.role == UserRole.PROJECT_MANAGER:
        try:
            managed = [int(value) for value in json.loads(user.managed_project_ids or "[]")]
        except (TypeError, ValueError, json.JSONDecodeError):
            managed = []
        query = query.filter(Courier.primary_project_id.in_(managed)) if managed else query.filter(False)
    return query


def _apply_filters(query, db: Session, tenant_id: int, filters: dict):
    """Apply normalized IDs only.  Base scope is intentionally already applied."""
    if filters.get("search"):
        needle = "%" + str(filters["search"]).strip() + "%"
        query = query.filter(or_(Courier.name.ilike(needle), Courier.phone.ilike(needle)))
    if filters.get("city_id"):
        query = query.filter(Courier.city_id == int(filters["city_id"]))
    if filters.get("branch_id"):
        query = query.filter(Courier.contract_branch_id == int(filters["branch_id"]))
    if filters.get("supervisor_id"):
        query = query.filter(Courier.supervisor_id == int(filters["supervisor_id"]))
    if filters.get("rider_id"):
        query = query.filter(Courier.id == int(filters["rider_id"]))
    if filters.get("project_id"):
        query = query.filter(Courier.primary_project_id == int(filters["project_id"]))
    if filters.get("contract_id"):
        branch_ids = db.query(ContractBranch.id).filter(
            ContractBranch.tenant_id == tenant_id,
            ContractBranch.contract_id == int(filters["contract_id"]),
        )
        query = query.filter(Courier.contract_branch_id.in_(branch_ids))
    if filters.get("employment_status"):
        query = query.filter(Courier.employment_status == str(filters["employment_status"]).upper())
    if filters.get("online") is not None:
        query = query.filter(Courier.is_online.is_(bool(filters["online"])))
    return query


def _names(db: Session, tenant_id: int, couriers: list[Courier]) -> dict:
    branch_ids = {row.contract_branch_id for row in couriers if row.contract_branch_id}
    project_ids = {row.primary_project_id for row in couriers if row.primary_project_id}
    supervisor_ids = {row.supervisor_id for row in couriers if row.supervisor_id}
    city_ids = {row.city_id for row in couriers if row.city_id}
    branches = {row.id: row for row in db.query(ContractBranch).filter(ContractBranch.tenant_id == tenant_id, ContractBranch.id.in_(branch_ids)).all()} if branch_ids else {}
    projects = {row.id: row.name for row in db.query(Project).filter(Project.tenant_id == tenant_id, Project.id.in_(project_ids)).all()} if project_ids else {}
    supervisors = {row.id: row.name for row in db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(supervisor_ids)).all()} if supervisor_ids else {}
    cities = {row.id: row.name for row in db.query(GeoCity).filter(GeoCity.id.in_(city_ids)).all()} if city_ids else {}
    contracts = {row.id: row for row in db.query(Contract).filter(Contract.tenant_id == tenant_id).all()}
    return {"branches": branches, "projects": projects, "supervisors": supervisors, "cities": cities, "contracts": contracts}


def _document_status(courier: Courier, today: date) -> str:
    dates = [courier.iqama_expiry, courier.license_expiry, courier.vehicle_license_expiry,
             courier.passport_expiry, courier.insurance_expiry, courier.inspection_expiry,
             courier.work_permit_expiry]
    if not courier.documents_valid or any(item and item < today for item in dates):
        return "CRITICAL"
    if any(item and (item - today).days <= 30 for item in dates):
        return "ATTENTION"
    return "OK"


def _activity_maps(db: Session, tenant_id: int, ids: list[int], start: date, end: date) -> dict:
    """Aggregate operational inputs once in the backend for all selected riders."""
    result = {
        "orders": defaultdict(int), "orders_by_day": defaultdict(int), "orders_by_project": defaultdict(int),
        "attendance_days": defaultdict(set), "worked_hours": defaultdict(float), "late": defaultdict(int),
        "early_leave": defaultdict(int), "absence": defaultdict(int),
    }
    if not ids:
        return result
    logs = db.query(DailyLog).filter(
        DailyLog.tenant_id == tenant_id, DailyLog.courier_id.in_(ids),
        DailyLog.log_date >= start, DailyLog.log_date <= end,
    ).all()
    for row in logs:
        amount = max(int(row.orders_count or 0), 0)
        result["orders"][row.courier_id] += amount
        result["orders_by_day"][row.log_date.isoformat()] += amount
        result["orders_by_project"][row.project_id] += amount
    attendance = db.query(Attendance).filter(
        Attendance.courier_id.in_(ids),
        Attendance.check_in >= datetime.combine(start, datetime.min.time()),
        Attendance.check_in < datetime.combine(end.fromordinal(end.toordinal() + 1), datetime.min.time()),
    ).all()
    for row in attendance:
        result["attendance_days"][row.courier_id].add(row.check_in.date())
        if row.check_out:
            result["worked_hours"][row.courier_id] += max((row.check_out - row.check_in).total_seconds() / 3600, 0)
        if row.is_late:
            result["late"][row.courier_id] += 1
    events = db.query(AttendanceEvent).filter(
        AttendanceEvent.tenant_id == tenant_id, AttendanceEvent.courier_id.in_(ids),
        AttendanceEvent.event_date >= start, AttendanceEvent.event_date <= end,
    ).all()
    for row in events:
        if row.event_type == "EARLY_LEAVE":
            result["early_leave"][row.courier_id] += 1
        elif row.event_type == "ABSENCE":
            result["absence"][row.courier_id] += 1
        elif row.event_type == "LATE" and not result["late"][row.courier_id]:
            result["late"][row.courier_id] += 1
    return result


def _financial_maps(db: Session, tenant_id: int, month: str, allowed_ids: set[int]) -> tuple[dict, bool]:
    """Use only the centralized rider-level financial reporting rows."""
    rows, finalized = courier_financial_rows(db, tenant_id, month)
    return {row["courier_id"]: row for row in rows if row.get("courier_id") in allowed_ids}, finalized


def _sum_financial(rows: list[dict]) -> dict:
    keys = ("eligible_orders", "base_salary", "delivery_pay", "bonus", "additions", "deductions", "payroll_cost", "client_revenue", "operational_margin")
    total = {key: 0.0 for key in keys}
    for row in rows:
        for key in keys:
            total[key] += float(row.get(key) or 0)
    total["eligible_orders"] = int(total["eligible_orders"])
    for key in keys:
        if key != "eligible_orders":
            total[key] = round(total[key], 2)
    total["cost_per_order"] = round(total["payroll_cost"] / total["eligible_orders"], 2) if total["eligible_orders"] else 0
    total["revenue_per_order"] = round(total["client_revenue"] / total["eligible_orders"], 2) if total["eligible_orders"] else 0
    total["operational_margin_pct"] = round(total["operational_margin"] / total["client_revenue"] * 100, 2) if total["client_revenue"] else 0
    return total


def report_filter_options(
    db: Session,
    user: User,
    filters: dict,
    supervisor_scope: Callable[[Session, int], object],
) -> dict:
    """Return cascading, scope-safe options.  Values are always normalized IDs."""
    base = _scoped_courier_query(db, user, supervisor_scope)
    selected = _apply_filters(base, db, user.tenant_id, filters).all()
    all_scoped = base.all()
    selected_ids = {row.id for row in selected}
    city_ids = {row.city_id for row in all_scoped if row.city_id}
    operating = db.query(TenantOperatingCity).filter(
        TenantOperatingCity.tenant_id == user.tenant_id,
        TenantOperatingCity.geo_city_id.in_(city_ids),
        TenantOperatingCity.is_active.is_(True),
    ).all() if city_ids else []
    geo = {row.id: row.name for row in db.query(GeoCity).filter(GeoCity.id.in_({item.geo_city_id for item in operating})).all()} if operating else {}
    names = _names(db, user.tenant_id, selected)
    branches = names["branches"]
    projects = names["projects"]
    supervisors = names["supervisors"]
    contracts = names["contracts"]
    branch_ids = set(branches)
    contract_ids = {row.contract_id for row in branches.values()}
    return {
        "cities": [{"id": item.geo_city_id, "name": item.display_name or geo.get(item.geo_city_id, "—")} for item in sorted(operating, key=lambda row: (row.display_name or geo.get(row.geo_city_id, ""), row.id))],
        "contracts": [{"id": row.id, "name": row.name} for row in sorted((row for row in contracts.values() if row.id in contract_ids), key=lambda row: row.name)],
        "branches": [{"id": row.id, "name": row.city, "city_id": row.city_id, "contract_id": row.contract_id, "project_id": row.project_id, "supervisor_id": row.supervisor_id} for row in sorted(branches.values(), key=lambda row: (row.city, row.id))],
        "projects": [{"id": key, "name": value} for key, value in sorted(projects.items(), key=lambda item: item[1])],
        "supervisors": [{"id": key, "name": value} for key, value in sorted(supervisors.items(), key=lambda item: item[1])],
        "riders": [{"id": row.id, "name": row.name, "city_id": row.city_id, "branch_id": row.contract_branch_id, "project_id": row.primary_project_id, "supervisor_id": row.supervisor_id} for row in sorted(selected, key=lambda row: (row.name, row.id))[:200]],
        "riders_total": len(selected_ids),
    }


def analytics_report(
    db: Session,
    user: User,
    report_type: str,
    filters: dict,
    start: date,
    end: date,
    page: int,
    page_size: int,
    supervisor_scope: Callable[[Session, int], object],
    role_permissions: dict,
) -> dict:
    """Build one read-only report payload with source labels and paged rider rows."""
    if start > end:
        raise ValueError("تاريخ البداية يجب أن يسبق تاريخ النهاية")
    permissions = _permissions(user, role_permissions)
    allow_commercial = user.role in COMMERCIAL_ROLES
    include_commercial = allow_commercial and report_type in {"executive", "financial"}
    allow_payroll = "*" in permissions or ("payroll" in permissions and user.role != UserRole.SUPERVISOR)
    if report_type == "financial" and not allow_commercial:
        raise PermissionError("Commercial financial reporting is restricted to company accounts")
    if report_type == "executive" and not allow_commercial:
        raise PermissionError("Executive commercial reporting is restricted to company accounts")

    query = _apply_filters(_scoped_courier_query(db, user, supervisor_scope), db, user.tenant_id, filters)
    couriers = query.order_by(Courier.name, Courier.id).all()
    ids = [row.id for row in couriers]
    names = _names(db, user.tenant_id, couriers)
    activity = _activity_maps(db, user.tenant_id, ids, start, end)
    month = _month_for(end)
    financial_by_courier, financial_finalized = _financial_maps(db, user.tenant_id, month, set(ids)) if (allow_payroll or allow_commercial) else ({}, False)

    # Bonus target is defined monthly.  We expose its MTD status as of the report end date.
    bonuses = calculate_courier_bonuses(db, couriers, month)
    today = date.today()
    day_count = (end - start).days + 1
    detail = []
    for courier in couriers:
        bonus = bonuses[courier.id]
        current_orders = int(activity["orders"].get(courier.id, 0))
        attendance_days = len(activity["attendance_days"].get(courier.id, set()))
        worked_hours = round(activity["worked_hours"].get(courier.id, 0.0), 2)
        target = int(bonus.get("target") or 0)
        mtd_orders = int(bonus.get("orders") or 0)
        branch = names["branches"].get(courier.contract_branch_id)
        fin = financial_by_courier.get(courier.id, {})
        row = {
            "rider_id": courier.id, "rider": courier.name,
            "city_id": courier.city_id, "city": names["cities"].get(courier.city_id) or (branch.city if branch else courier.work_city or "—"),
            "contract_id": branch.contract_id if branch else None,
            "contract": names["contracts"].get(branch.contract_id).name if branch and names["contracts"].get(branch.contract_id) else "—",
            "project_id": courier.primary_project_id, "project": names["projects"].get(courier.primary_project_id, courier.platform or "—"),
            "branch_id": courier.contract_branch_id, "branch": branch.city if branch else "—",
            "supervisor_id": courier.supervisor_id, "supervisor": names["supervisors"].get(courier.supervisor_id, "—"),
            "eligible_orders": current_orders, "mtd_orders": mtd_orders, "target": target,
            "achievement_pct": round(mtd_orders / target * 100, 2) if target else None,
            "worked_hours": worked_hours,
            "orders_per_worked_hour": round(current_orders / worked_hours, 2) if worked_hours else 0,
            "attendance_days": attendance_days,
            "attendance_pct": round(attendance_days / day_count * 100, 2),
            "late_count": int(activity["late"].get(courier.id, 0)),
            "absence_count": int(activity["absence"].get(courier.id, 0)),
            "early_leave_count": int(activity["early_leave"].get(courier.id, 0)),
            "employment_status": courier.employment_status or "ACTIVE",
            "online": bool(courier.is_online),
            "document_status": _document_status(courier, today),
            "segment": "SUSPENDED" if (courier.employment_status or "ACTIVE") != "ACTIVE" else ("ZERO_ORDERS" if current_orders == 0 else ("TARGET_ACHIEVED" if bonus.get("achieved") else "BELOW_TARGET")),
        }
        if allow_payroll:
            row.update({
                "bonus": round(float(fin.get("bonus") or 0), 2),
                "payroll_cost": round(float(fin.get("payroll_cost") or 0), 2),
                "cost_per_order": round(float(fin.get("payroll_cost") or 0) / int(fin.get("eligible_orders") or 0), 2) if int(fin.get("eligible_orders") or 0) else 0,
            })
        if include_commercial:
            row.update({
                "base_salary": round(float(fin.get("base_salary") or 0), 2),
                "delivery_pay": round(float(fin.get("delivery_pay") or 0), 2),
                "additions": round(float(fin.get("additions") or 0), 2),
                "deductions": round(float(fin.get("deductions") or 0), 2),
                "client_revenue": round(float(fin.get("client_revenue") or 0), 2),
                "operational_margin": round(float(fin.get("operational_margin") or 0), 2),
                "revenue_per_order": round(float(fin.get("client_revenue") or 0) / int(fin.get("eligible_orders") or 0), 2) if int(fin.get("eligible_orders") or 0) else 0,
            })
        detail.append(row)

    active = [row for row in detail if row["employment_status"] == "ACTIVE"]
    total_orders = sum(row["eligible_orders"] for row in detail)
    total_hours = sum(row["worked_hours"] for row in detail)
    target_rows = [row for row in detail if row["target"]]
    attendance_days = sum(row["attendance_days"] for row in active)
    base_kpis = {
        "total_riders": len(detail), "active_riders": len(active),
        "online_riders": sum(row["online"] for row in detail),
        "suspended_riders": sum(row["employment_status"] == "SUSPENDED" for row in detail),
        "eligible_orders": total_orders,
        "orders_per_active_rider": round(total_orders / len(active), 2) if active else 0,
        "worked_hours": round(total_hours, 2),
        "orders_per_worked_hour": round(total_orders / total_hours, 2) if total_hours else 0,
        "attendance_rate": round(attendance_days / (len(active) * day_count) * 100, 2) if active else 0,
        "absent_riders": sum(row["absence_count"] > 0 for row in detail),
        "late_riders": sum(row["late_count"] > 0 for row in detail),
        "target_achievement_pct": round(sum(row["mtd_orders"] for row in target_rows) / sum(row["target"] for row in target_rows) * 100, 2) if target_rows and sum(row["target"] for row in target_rows) else 0,
        "target_achievers": sum(row["segment"] == "TARGET_ACHIEVED" for row in detail),
        "zero_order_riders": sum(row["segment"] == "ZERO_ORDERS" for row in detail),
        "document_attention": sum(row["document_status"] != "OK" for row in detail),
    }
    if include_commercial:
        totals = _sum_financial([financial_by_courier[row["rider_id"]] for row in detail if row["rider_id"] in financial_by_courier])
        base_kpis.update({
            "total_bonus_cost": totals["bonus"], "estimated_or_final_payroll_cost": totals["payroll_cost"],
            "client_revenue": totals["client_revenue"], "operational_margin": totals["operational_margin"],
            "operational_margin_pct": totals["operational_margin_pct"], "financial_finalized": financial_finalized,
        })
    elif allow_payroll:
        base_kpis["estimated_or_final_payroll_cost"] = round(sum(row.get("payroll_cost") or 0 for row in detail), 2)

    city_orders, project_orders, supervisor_orders = defaultdict(int), defaultdict(int), defaultdict(int)
    city_financial, project_financial = defaultdict(lambda: {"revenue": 0.0, "cost": 0.0, "margin": 0.0}) , defaultdict(lambda: {"revenue": 0.0, "cost": 0.0, "margin": 0.0})
    for row in detail:
        city_orders[row["city"]] += row["eligible_orders"]
        project_orders[row["project"]] += row["eligible_orders"]
        supervisor_orders[row["supervisor"]] += row["eligible_orders"]
        fin = financial_by_courier.get(row["rider_id"])
        if fin and include_commercial:
            for bucket, key in ((city_financial, row["city"]), (project_financial, row["project"])):
                bucket[key]["revenue"] += fin["client_revenue"]
                bucket[key]["cost"] += fin["payroll_cost"]
                bucket[key]["margin"] += fin["operational_margin"]
    def ranked(mapping, key_name, limit=8):
        return [{key_name: key, "eligible_orders": value} for key, value in sorted(mapping.items(), key=lambda item: (-item[1], item[0]))[:limit]]
    charts = {
        "orders_trend": [{"date": key, "eligible_orders": value} for key, value in sorted(activity["orders_by_day"].items())],
        "orders_by_city": ranked(city_orders, "city"),
        "orders_by_project": ranked(project_orders, "project"),
        "top_supervisors": ranked(supervisor_orders, "supervisor", 5),
        "top_riders": [{"rider": row["rider"], "eligible_orders": row["eligible_orders"], "achievement_pct": row["achievement_pct"]} for row in sorted(detail, key=lambda row: (-row["eligible_orders"], row["rider"]))[:10]],
    }
    if include_commercial:
        charts["financial_by_project"] = [{"project": key, "client_revenue": round(value["revenue"], 2), "rider_cost": round(value["cost"], 2), "operational_margin": round(value["margin"], 2)} for key, value in sorted(project_financial.items(), key=lambda item: -item[1]["margin"])[:8]]
        charts["revenue_by_city"] = [{"city": key, "client_revenue": round(value["revenue"], 2)} for key, value in sorted(city_financial.items(), key=lambda item: -item[1]["revenue"])[:8]]

    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 50), 1), 5000)
    sort_key = (lambda row: (-row["eligible_orders"], row["rider"])) if report_type != "workforce" else (lambda row: (row["segment"] != "ZERO_ORDERS", -row["eligible_orders"], row["rider"]))
    ordered = sorted(detail, key=sort_key)
    paged = ordered[(page - 1) * page_size: page * page_size]
    return {
        "report_type": report_type, "period": {"from": start.isoformat(), "to": end.isoformat(), "financial_month": month},
        "financial_status": "CLOSED_FINAL" if financial_finalized else "OPEN_PREVIEW",
        "financial_finalized": financial_finalized,
        "kpis": base_kpis, "charts": charts, "rows": paged,
        "pagination": {"total": len(detail), "page": page, "page_size": page_size, "pages": (len(detail) + page_size - 1) // page_size},
        "definitions": {
            "eligible_orders": "DailyLog within the selected operational date range",
            "attendance_rate": "Recorded attendance rider-days divided by active riders multiplied by calendar days in the selected range",
            "target_achievement": "MTD monthly target position as of the report end month",
            "financial": "Monthly preview for an open payroll period or finalized snapshots for a closed period",
        },
    }


def flat_export_rows(report: dict, include_commercial: bool, include_payroll: bool) -> list[dict]:
    """Return already-scoped, presentation-safe detail rows for CSV generation."""
    base = ("rider", "city", "contract", "project", "branch", "supervisor", "eligible_orders", "mtd_orders", "target", "achievement_pct", "worked_hours", "orders_per_worked_hour", "attendance_pct", "late_count", "absence_count", "early_leave_count", "employment_status", "online", "document_status", "segment")
    keys = list(base)
    if include_payroll:
        keys.extend(("bonus", "payroll_cost", "cost_per_order"))
    if include_commercial:
        keys.extend(("client_revenue", "operational_margin"))
    return [{key: row.get(key) for key in keys} for row in report.get("rows", [])]

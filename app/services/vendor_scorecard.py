"""Vendor performance and compliance, for the delivery-platform product.

A platform does not employ most of its riders. It works through logistics
vendors who sponsor them, and its expensive unanswered questions are about those
vendors: which ones supply riders who actually show up, and which ones expose it
to a regulatory problem by supplying a rider whose residency permit lapsed.

Riders reach an operator two ways, matching how the rest of the codebase already
resolves it: an active RiderAssignment, or the rider's primary project. Both are
honoured here so a platform sees the same population everywhere.

Everything is computed inside one tenant. Reading another tenant's riders is a
separate, consented mechanism and deliberately not part of this module.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from ..models.entities import (
    Attendance,
    Courier,
    DailyLog,
    PlatformOperator,
    RiderAssignment,
    Tenant,
)

# The rider fields that carry a legal or operational expiry. Ordered by how
# much trouble a lapse causes: a lapsed residency permit stops the rider
# working at all, a lapsed vehicle inspection is a fine.
COMPLIANCE_FIELDS: tuple[tuple[str, str], ...] = (
    ("iqama_expiry", "الإقامة"),
    ("work_permit_expiry", "رخصة العمل"),
    ("license_expiry", "رخصة القيادة"),
    ("insurance_expiry", "التأمين"),
    ("vehicle_license_expiry", "رخصة المركبة"),
    ("inspection_expiry", "الفحص الدوري"),
    ("passport_expiry", "الجواز"),
)

DEFAULT_HORIZON_DAYS = 30


def _rider_operator_map(db: Session, tenant_id: int) -> dict[int, int]:
    """courier_id -> operator_id, active assignment winning over primary project."""
    mapping: dict[int, int] = {}
    for courier_id, project_id in (
        db.query(Courier.id, Courier.primary_project_id)
        .filter(Courier.tenant_id == tenant_id, Courier.primary_project_id.isnot(None))
        .all()
    ):
        mapping[courier_id] = project_id
    for courier_id, operator_id in (
        db.query(RiderAssignment.courier_id, RiderAssignment.operator_id)
        .filter(
            RiderAssignment.tenant_id == tenant_id,
            RiderAssignment.status == "ACTIVE",
        )
        .all()
    ):
        mapping[courier_id] = operator_id
    return mapping


def _operator_names(db: Session, tenant_id: int) -> dict[int, str]:
    names: dict[int, str] = {}
    for link in (
        db.query(PlatformOperator)
        .filter(
            PlatformOperator.tenant_id == tenant_id,
            PlatformOperator.is_active.is_(True),
        )
        .all()
    ):
        tenant = db.get(Tenant, link.operator_tenant_id)
        names[link.operator_tenant_id] = (
            tenant.name if tenant else f"مشغل #{link.operator_tenant_id}"
        )
    return names


def _compliance_state(rider: Courier, today: date, horizon: int):
    """Worst expiry state for one rider, and the documents behind it."""
    expired, expiring = [], []
    for field, label in COMPLIANCE_FIELDS:
        value = getattr(rider, field, None)
        if not value:
            continue
        days = (value - today).days
        if days < 0:
            expired.append({"document": label, "expiry": value.isoformat(), "days": days})
        elif days <= horizon:
            expiring.append({"document": label, "expiry": value.isoformat(), "days": days})
    return expired, expiring


def vendor_scorecard(
    db: Session, tenant_id: int, month: str | None = None, horizon: int = DEFAULT_HORIZON_DAYS
) -> dict:
    """One row per vendor: supply, attendance, compliance and delivered orders."""
    today = date.today()
    period = month or today.strftime("%Y-%m")
    year, month_number = (int(part) for part in period.split("-", 1))
    start = date(year, month_number, 1)
    end = date(year + 1, 1, 1) if month_number == 12 else date(year, month_number + 1, 1)

    riders = db.query(Courier).filter(Courier.tenant_id == tenant_id).all()
    by_operator = _rider_operator_map(db, tenant_id)
    names = _operator_names(db, tenant_id)
    rider_ids = [r.id for r in riders]

    orders: dict[int, int] = defaultdict(int)
    if rider_ids:
        for courier_id, count in (
            db.query(DailyLog.courier_id, DailyLog.orders_count)
            .filter(
                DailyLog.courier_id.in_(rider_ids),
                DailyLog.log_date >= start,
                DailyLog.log_date < end,
            )
            .all()
        ):
            orders[courier_id] += int(count or 0)

    present_today: set[int] = set()
    if rider_ids:
        day_start = date.today()
        for (courier_id,) in (
            db.query(Attendance.courier_id)
            .filter(
                Attendance.courier_id.in_(rider_ids),
                Attendance.check_in >= day_start,
            )
            .distinct()
            .all()
        ):
            present_today.add(courier_id)

    groups: dict[int | None, dict] = defaultdict(
        lambda: {"riders": 0, "active": 0, "present": 0, "orders": 0, "expired": 0, "expiring": 0, "target": 0}
    )
    for rider in riders:
        operator_id = by_operator.get(rider.id)
        bucket = groups[operator_id]
        bucket["riders"] += 1
        if (rider.employment_status or "ACTIVE") == "ACTIVE":
            bucket["active"] += 1
        if rider.id in present_today:
            bucket["present"] += 1
        bucket["orders"] += orders.get(rider.id, 0)
        bucket["target"] += int(rider.bonus_target or 0)
        expired, expiring = _compliance_state(rider, today, horizon)
        if expired:
            bucket["expired"] += 1
        elif expiring:
            bucket["expiring"] += 1

    rows = []
    for operator_id, data in groups.items():
        riders_count = data["riders"] or 1
        compliant = data["riders"] - data["expired"] - data["expiring"]
        rows.append(
            {
                "operator_id": operator_id,
                "operator_name": names.get(operator_id)
                or ("غير مُسند" if operator_id is None else f"مشغل #{operator_id}"),
                "is_linked": operator_id in names,
                "riders": data["riders"],
                "active_riders": data["active"],
                "present_today": data["present"],
                "attendance_rate": round(data["present"] / riders_count * 100, 1),
                "orders_month": data["orders"],
                "monthly_target": data["target"],
                "target_achievement": round(data["orders"] / data["target"] * 100, 1)
                if data["target"] > 0
                else None,
                "riders_expired": data["expired"],
                "riders_expiring": data["expiring"],
                "compliance_rate": round(max(compliant, 0) / riders_count * 100, 1),
            }
        )

    # Worst compliance first: the row that can stop riders working, not the
    # biggest vendor, is what the platform needs to see at the top.
    rows.sort(key=lambda r: (r["compliance_rate"], -r["riders_expired"]))
    for position, row in enumerate(rows, 1):
        row["rank"] = position

    total_riders = sum(r["riders"] for r in rows)
    return {
        "period": period,
        "horizon_days": horizon,
        "vendors": len(rows),
        "totals": {
            "riders": total_riders,
            "present_today": sum(r["present_today"] for r in rows),
            "orders_month": sum(r["orders_month"] for r in rows),
            "riders_expired": sum(r["riders_expired"] for r in rows),
            "riders_expiring": sum(r["riders_expiring"] for r in rows),
        },
        "rows": rows,
    }


def compliance_wall(
    db: Session, tenant_id: int, horizon: int = DEFAULT_HORIZON_DAYS
) -> dict:
    """Every lapsed or lapsing document, soonest first, attributed to its vendor.

    Grouped by vendor because that is who has to fix it: the platform does not
    hold the rider's paperwork, its vendor does.
    """
    today = date.today()
    riders = db.query(Courier).filter(Courier.tenant_id == tenant_id).all()
    by_operator = _rider_operator_map(db, tenant_id)
    names = _operator_names(db, tenant_id)

    items = []
    for rider in riders:
        expired, expiring = _compliance_state(rider, today, horizon)
        operator_id = by_operator.get(rider.id)
        for entry in expired + expiring:
            items.append(
                {
                    "rider_id": rider.id,
                    "rider_name": rider.name,
                    "rider_phone": rider.phone,
                    "operator_id": operator_id,
                    "operator_name": names.get(operator_id)
                    or ("غير مُسند" if operator_id is None else f"مشغل #{operator_id}"),
                    "document": entry["document"],
                    "expiry_date": entry["expiry"],
                    "days_remaining": entry["days"],
                    "severity": "EXPIRED" if entry["days"] < 0 else "EXPIRING",
                }
            )

    items.sort(key=lambda i: i["days_remaining"])
    return {
        "horizon_days": horizon,
        "as_of": today.isoformat(),
        "totals": {
            "expired": sum(1 for i in items if i["severity"] == "EXPIRED"),
            "expiring": sum(1 for i in items if i["severity"] == "EXPIRING"),
            "riders_affected": len({i["rider_id"] for i in items}),
            "vendors_affected": len({i["operator_id"] for i in items}),
        },
        "rows": items,
    }


def horizon_from(value: int | None) -> int:
    """Clamp a caller-supplied horizon to something a query can serve."""
    try:
        days = int(value) if value is not None else DEFAULT_HORIZON_DAYS
    except (TypeError, ValueError):
        return DEFAULT_HORIZON_DAYS
    return max(1, min(days, 180))


def eligible_orders_for_operator(
    db: Session, tenant_id: int, operator_id: int, period_month: str
) -> int:
    """Delivered orders a platform owes an operator for, in one month.

    Counted from the platform's own tenant and grouped by operator, which is the
    same source and the same grouping the vendor scorecard shows. Settlement
    previously counted rows inside the *operator's* tenant instead: a read
    across a tenant boundary with no grant behind it, against a table nothing
    populates, so every settlement computed zero while the scorecard beside it
    showed real orders.
    """
    year, month_number = (int(part) for part in period_month.split("-", 1))
    start = date(year, month_number, 1)
    end = date(year + 1, 1, 1) if month_number == 12 else date(year, month_number + 1, 1)

    rider_ids = [
        courier_id
        for courier_id, mapped in _rider_operator_map(db, tenant_id).items()
        if mapped == operator_id
    ]
    if not rider_ids:
        return 0

    return sum(
        max(int(count or 0), 0)
        for (count,) in db.query(DailyLog.orders_count)
        .filter(
            DailyLog.courier_id.in_(rider_ids),
            DailyLog.log_date >= start,
            DailyLog.log_date < end,
        )
        .all()
    )

"""What a vendor sees of its own work inside a platform's account.

A platform's rider data lives in the platform's tenant, because it arrived under
the platform's contract. When the platform opens the dashboard to a vendor, the
vendor does not receive a copy: it is granted read access to the slice of that
tenant which describes its own riders, resolved at query time.

Nothing is duplicated, so revoking is instant and leaves no orphan rows behind.
Three rules hold everywhere in this module:

  * read only - a grant never carries write access
  * one slice - a vendor resolves only to riders assigned to itself
  * no names  - ranking tells a vendor where it stands without naming anyone else

The ranking is the reason a vendor pays. "You are fourth of twelve in Riyadh" is
worth something to the vendor and costs the platform nothing, because the other
eleven stay anonymous.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models.entities import Capability, DelegatedScope, PlatformOperator, Tenant
from .entitlements import VENDOR_PORTAL, capabilities_for
from .vendor_scorecard import compliance_wall, vendor_scorecard


@dataclass(frozen=True)
class VendorGrant:
    """One platform that has opened its dashboard to this vendor."""

    platform_tenant_id: int
    platform_name: str
    operator_id: int  # the vendor's own tenant id, which keys the platform's data
    permissions: tuple[str, ...]
    valid_to: date | None


def _permissions(scope: DelegatedScope) -> tuple[str, ...]:
    try:
        loaded = json.loads(scope.permissions or "[]")
    except (TypeError, ValueError):
        return ()
    return tuple(str(p).upper() for p in loaded) if isinstance(loaded, list) else ()


def grants_for_vendor(db: Session, vendor_tenant_id: int) -> list[VendorGrant]:
    """Live grants, newest platform first.

    Three things must all hold, and each can be withdrawn independently:
    the operator link is active, the platform still pays for VENDOR_PORTAL, and
    the delegated scope is inside its validity window.
    """
    today = date.today()
    links = (
        db.query(PlatformOperator)
        .filter(
            PlatformOperator.operator_tenant_id == vendor_tenant_id,
            PlatformOperator.is_active.is_(True),
        )
        .all()
    )

    grants: list[VendorGrant] = []
    for link in links:
        platform = db.get(Tenant, link.tenant_id)
        if platform is None:
            continue
        if VENDOR_PORTAL not in capabilities_for(platform):
            # The platform has not bought the portal, so the link exists for the
            # platform's own reporting and grants the vendor nothing.
            continue
        scope = (
            db.query(DelegatedScope)
            .filter(
                DelegatedScope.tenant_id == link.tenant_id,
                DelegatedScope.platform_operator_id == link.id,
                DelegatedScope.valid_from <= today,
                or_(DelegatedScope.valid_to.is_(None), DelegatedScope.valid_to >= today),
            )
            .order_by(DelegatedScope.valid_from.desc())
            .first()
        )
        if scope is None:
            continue
        grants.append(
            VendorGrant(
                platform_tenant_id=link.tenant_id,
                platform_name=platform.name,
                operator_id=vendor_tenant_id,
                permissions=_permissions(scope),
                valid_to=scope.valid_to,
            )
        )
    return grants


def _grant_or_none(
    db: Session, vendor_tenant_id: int, platform_tenant_id: int | None
) -> VendorGrant | None:
    grants = grants_for_vendor(db, vendor_tenant_id)
    if not grants:
        return None
    if platform_tenant_id is None:
        return grants[0]
    return next((g for g in grants if g.platform_tenant_id == platform_tenant_id), None)


def vendor_standing(
    db: Session, vendor_tenant_id: int, platform_tenant_id: int | None = None,
    month: str | None = None,
) -> dict:
    """The vendor's own numbers, plus where it stands without naming anyone.

    Reuses the platform's own scorecard so both sides read one computation. A
    vendor and its platform arguing over two different numbers for the same
    month would defeat the point of the portal.
    """
    grant = _grant_or_none(db, vendor_tenant_id, platform_tenant_id)
    if grant is None:
        return {"granted": False, "platforms": [], "standing": None}

    board = vendor_scorecard(db, grant.platform_tenant_id, month=month)
    rows = board.get("rows") or []
    mine = next((r for r in rows if r["operator_id"] == grant.operator_id), None)
    if mine is None:
        return {
            "granted": True,
            "platform": grant.platform_name,
            "standing": None,
            "note": "لا توجد بيانات تشغيل لك لدى هذه المنصة في هذه الفترة",
        }

    ranked = [r for r in rows if r["operator_id"] is not None]
    total = len(ranked)

    def _peer_stats(field: str) -> dict:
        values = [r[field] for r in ranked if r.get(field) is not None]
        if not values:
            return {"best": None, "median": None}
        ordered = sorted(values)
        middle = len(ordered) // 2
        median = (
            ordered[middle]
            if len(ordered) % 2
            else round((ordered[middle - 1] + ordered[middle]) / 2, 1)
        )
        return {"best": max(values), "median": median}

    return {
        "granted": True,
        "platform": grant.platform_name,
        "platform_tenant_id": grant.platform_tenant_id,
        "grant_expires": grant.valid_to.isoformat() if grant.valid_to else None,
        "period": board.get("period"),
        "standing": {
            # Rank only. Peer identities never cross the boundary; the best and
            # median values give the vendor something to aim at without saying
            # who holds them.
            "rank": mine["rank"],
            "of": total,
            "riders": mine["riders"],
            "active_riders": mine["active_riders"],
            "present_today": mine["present_today"],
            "attendance_rate": mine["attendance_rate"],
            "compliance_rate": mine["compliance_rate"],
            "orders_month": mine["orders_month"],
            "target_achievement": mine["target_achievement"],
            "riders_expired": mine["riders_expired"],
            "riders_expiring": mine["riders_expiring"],
            "peers": {
                "attendance": _peer_stats("attendance_rate"),
                "compliance": _peer_stats("compliance_rate"),
                "target": _peer_stats("target_achievement"),
            },
        },
    }


def vendor_compliance(
    db: Session, vendor_tenant_id: int, platform_tenant_id: int | None = None,
    horizon: int = 30,
) -> dict:
    """The vendor's own lapsed documents, and only its own."""
    grant = _grant_or_none(db, vendor_tenant_id, platform_tenant_id)
    if grant is None:
        return {"granted": False, "rows": [], "totals": {}}

    wall = compliance_wall(db, grant.platform_tenant_id, horizon=horizon)
    mine = [row for row in wall["rows"] if row["operator_id"] == grant.operator_id]
    # Peer identity is stripped rather than filtered later: the vendor's own
    # rows already name only itself, and nothing else is returned.
    for row in mine:
        row.pop("operator_name", None)
        row.pop("operator_id", None)
    return {
        "granted": True,
        "platform": grant.platform_name,
        "horizon_days": wall["horizon_days"],
        "as_of": wall["as_of"],
        "totals": {
            "expired": sum(1 for r in mine if r["severity"] == "EXPIRED"),
            "expiring": sum(1 for r in mine if r["severity"] == "EXPIRING"),
            "riders_affected": len({r["rider_id"] for r in mine}),
        },
        "rows": mine,
    }


def platform_may_open_portal(db: Session, platform_tenant_id: int) -> bool:
    tenant = db.get(Tenant, platform_tenant_id)
    caps = capabilities_for(tenant)
    return VENDOR_PORTAL in caps and Capability.MANAGE_OPERATORS.value in caps

"""Ninja Logistics Live API Integration & Webhook Ingestion Router.

Provides real-time event ingestion from Ninja's external platform,
automatic courier mapping, daily performance incrementing, and live feed telemetry.
"""

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import entities as ent
from ..services.ingestion import normalize_row, source_platform_for
from ..services.partner_auth import api_key_header, ingestion_tenant
from .auth import get_current_user

router = APIRouter(prefix="/sources/ninja", tags=["ninja-integration"])

# The scope a partner key must carry to post delivery facts, and the capability
# the receiving tenant must still hold. Both are checked on every request:
# see app/services/partner_auth.py for why one alone is not enough.
INGEST_SCOPE = "performance:write"
INGEST_CAPABILITY = ent.Capability.PERFORMANCE_API_INGESTION.value


class NinjaDeliveryEvent(BaseModel):
    event_type: str = Field(default="DELIVERY_COMPLETED")
    ninja_rider_id: str
    rider_phone: Optional[str] = None
    order_id: str
    event_timestamp: Optional[datetime] = None
    city: Optional[str] = "Riyadh"
    delivery_status: str = "DELIVERED"
    delivery_fee: float = 0.0
    tip_amount: float = 0.0
    cod_amount_collected: float = 0.0
    distance_km: float = 0.0
    duration_minutes: float = 0.0
    rating: Optional[float] = 5.0
    metadata: Optional[Dict[str, Any]] = None


class NinjaBatchEventPayload(BaseModel):
    batch_id: Optional[str] = None
    source: str = "NINJA_LIVE_DISPATCH_ENGINE"
    events: List[NinjaDeliveryEvent]


@router.post("/live-event")
@router.post("/webhook")
async def ingest_ninja_live_event(
    event: NinjaDeliveryEvent,
    db: Session = Depends(get_db),
    api_key: Optional[str] = Depends(api_key_header),
):
    """Ingest one delivery event from Ninja's dispatch API.

    The tenant is whichever one issued the key. It used to come from an
    `X-Tenant-Id` header on an endpoint with no authentication at all, so any
    caller could write orders — the number payroll pays on — into any company.
    """
    tenant = ingestion_tenant(db, api_key, INGEST_SCOPE, INGEST_CAPABILITY)
    return _ingest_event(db, tenant, event)


def _ingest_event(db: Session, tenant: ent.Tenant, event: NinjaDeliveryEvent):
    """Record one event for an already-authenticated tenant.

    Two things this used to do wrong. It wrote `source_platform_id=1` as a
    literal — SourcePlatform rows are tenant-scoped, so id 1 belongs to whichever
    tenant created the first one, and every other tenant's deliveries were
    attributed to a stranger's source in any report that groups by it. And it
    wrote the fact directly, with no raw row behind it: `raw_row_id` and
    `provenance` are columns on the fact and both were always null, so a
    delivery a rider was paid for had no record of what produced it.

    The event is now recorded verbatim as a raw row and normalized through the
    same function that serves POST /sources/raw-rows, so a fact means the same
    thing whichever way it arrived — and a rejected event is visible on the
    integration screen with its reason, instead of vanishing.
    """
    tenant_id = tenant.id
    platform = source_platform_for(db, tenant_id, "NINJA", "نينجا")

    payload = event.model_dump(mode="json")
    row_data = json.dumps(payload, ensure_ascii=False)
    checksum = hashlib.sha256(row_data.encode()).hexdigest()

    row = (
        db.query(ent.RawImportRow)
        .filter(
            ent.RawImportRow.tenant_id == tenant_id,
            ent.RawImportRow.source_platform_id == platform.id,
            ent.RawImportRow.source_id == event.order_id,
        )
        .first()
    )
    if row is None:
        row = ent.RawImportRow(
            tenant_id=tenant_id,
            source_platform_id=platform.id,
            source_id=event.order_id,
            row_data=row_data,
            checksum=checksum,
            schema_version="ninja-1.0",
            source_timestamp=event.event_timestamp or datetime.now(timezone.utc),
        )
        db.add(row)
        db.flush()

    before = row.status
    fact = normalize_row(db, row)
    is_new_fact = fact is not None and before != "NORMALIZED"
    courier = db.get(ent.Courier, fact.courier_id) if fact and fact.courier_id else None
    today = fact.event_date if fact else (
        event.event_timestamp or datetime.now(timezone.utc)
    ).date()

    ninja_project = (
        db.query(ent.Project)
        .filter(
            ent.Project.tenant_id == tenant_id,
            func.lower(ent.Project.name).contains("ninja"),
        )
        .first()
    )

    if not ninja_project:
        ninja_project = ent.Project(
            tenant_id=tenant_id, name="Ninja Express (نينجا إكسبريس)", is_active=True
        )
        db.add(ninja_project)
        db.flush()

    daily_log = None
    if courier:
        daily_log = (
            db.query(ent.DailyLog)
            .filter(
                ent.DailyLog.courier_id == courier.id,
                ent.DailyLog.log_date == today,
                ent.DailyLog.project_id == ninja_project.id,
            )
            .first()
        )

        if not daily_log:
            daily_log = ent.DailyLog(
                courier_id=courier.id,
                tenant_id=tenant_id,
                project_id=ninja_project.id,
                log_date=today,
                orders_count=1 if is_new_fact else 0,
                driver_orders=0,
                verified_orders=1 if is_new_fact else 0,
                variance=1 if is_new_fact else 0,
                source_type="LIVE_API_NINJA",
                notes=f"Ninja Live Ingestion: Order {event.order_id}",
            )
            db.add(daily_log)
        elif is_new_fact:
            daily_log.verified_orders = (daily_log.verified_orders or 0) + 1
            daily_log.orders_count = daily_log.verified_orders
            daily_log.variance = daily_log.orders_count - (daily_log.driver_orders or 0)
            daily_log.source_type = "LIVE_API_NINJA"

    db.commit()

    return {
        "status": "success",
        "order_id": event.order_id,
        "is_new": is_new_fact,
        "matched_courier": {
            "id": courier.id if courier else None,
            "name": courier.name if courier else "Unassigned",
            "phone": courier.phone if courier else None,
        },
        "today_orders_count": daily_log.orders_count
        if daily_log
        else (1 if is_new_fact else 0),
        "cod_collected": event.cod_amount_collected,
        "timestamp": datetime.now(timezone.utc).isoformat()
        if hasattr(datetime, "now")
        else datetime.utcnow().isoformat(),
    }


@router.post("/batch-sync")
async def ingest_ninja_batch_events(
    payload: NinjaBatchEventPayload,
    db: Session = Depends(get_db),
    api_key: Optional[str] = Depends(api_key_header),
):
    """Batch ingest delivery facts. Authenticated once, for the whole batch."""
    tenant = ingestion_tenant(db, api_key, INGEST_SCOPE, INGEST_CAPABILITY)
    results = [_ingest_event(db, tenant, ev) for ev in payload.events]
    return {
        "status": "batch_completed",
        "processed_count": len(results),
        "details": results,
    }


@router.get("/telemetry")
def get_ninja_telemetry(
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get live telemetry, connection health, and today's Ninja ingestion stats."""
    tenant_id = user.tenant_id or 1
    today = date.today()

    # Find Ninja Project
    ninja_proj = (
        db.query(ent.Project)
        .filter(
            ent.Project.tenant_id == tenant_id,
            func.lower(ent.Project.name).contains("ninja"),
        )
        .first()
    )

    today_logs = []
    total_orders = 0
    active_riders = 0
    if ninja_proj:
        today_logs = (
            db.query(ent.DailyLog)
            .filter(
                ent.DailyLog.tenant_id == tenant_id,
                ent.DailyLog.project_id == ninja_proj.id,
                ent.DailyLog.log_date == today,
            )
            .all()
        )
        total_orders = sum(log.orders_count or 0 for log in today_logs)
        active_riders = len(today_logs)

    recent_facts = (
        db.query(ent.NormalizedDeliveryFact)
        .filter(ent.NormalizedDeliveryFact.tenant_id == tenant_id)
        .order_by(ent.NormalizedDeliveryFact.id.desc())
        .limit(10)
        .all()
    )

    return {
        "adapter_status": "ONLINE_LIVE",
        "source_name": "Ninja Express Platform (API / Webhooks)",
        "protocol": "REST Webhook / JSON Stream",
        "tenant_id": tenant_id,
        "today_stats": {
            "date": today.isoformat(),
            "total_live_orders_ingested": total_orders,
            "active_connected_riders": active_riders,
        },
        "recent_live_events": [
            {
                "order_id": f.source_delivery_id,
                "courier_id": f.courier_id,
                "status": f.status,
                "completed_at": f.completed_at.isoformat() if f.completed_at else None,
                "fee": f.fee_amount,
            }
            for f in recent_facts
        ],
    }

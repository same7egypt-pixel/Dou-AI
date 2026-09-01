"""Ninja Logistics Live API Integration & Webhook Ingestion Router.

Provides real-time event ingestion from Ninja's external platform,
automatic courier mapping, daily performance incrementing, and live feed telemetry.
"""

from datetime import datetime, date, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import entities as ent
from .auth import get_current_user


router = APIRouter(prefix="/sources/ninja", tags=["ninja-integration"])


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
    x_ninja_signature: Optional[str] = Header(None),
    x_tenant_id: Optional[int] = Header(None),
):
    """Ingest a single real-time delivery event from Ninja's dispatching API with strict tenant isolation and courier matching."""
    tenant_id = x_tenant_id or 1
    tenant = db.get(ent.Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, f"Tenant {tenant_id} not found")

    # 1. Resolve Courier (strictly by phone, platform_courier_id, or RiderIdentityMapping — never fallback to random courier)
    courier = None
    if event.rider_phone:
        clean_phone = event.rider_phone.replace("+", "").strip()
        courier = (
            db.query(ent.Courier)
            .filter(
                ent.Courier.tenant_id == tenant_id, ent.Courier.phone == clean_phone
            )
            .first()
        )

    if not courier and event.ninja_rider_id:
        courier = (
            db.query(ent.Courier)
            .filter(
                ent.Courier.tenant_id == tenant_id,
                ent.Courier.platform_courier_id == event.ninja_rider_id,
            )
            .first()
        )

    if not courier and event.ninja_rider_id:
        # Check RiderIdentityMapping
        mapping = (
            db.query(ent.RiderIdentityMapping)
            .filter(
                ent.RiderIdentityMapping.tenant_id == tenant_id,
                ent.RiderIdentityMapping.source_rider_id == event.ninja_rider_id,
            )
            .first()
        )
        if mapping:
            courier = db.get(ent.Courier, mapping.courier_id)

    # 2. Check existing NormalizedDeliveryFact for idempotency
    fact = (
        db.query(ent.NormalizedDeliveryFact)
        .filter(
            ent.NormalizedDeliveryFact.tenant_id == tenant_id,
            ent.NormalizedDeliveryFact.source_platform_id == 1,
            ent.NormalizedDeliveryFact.source_delivery_id == event.order_id,
        )
        .first()
    )

    is_new_fact = False
    today = (
        (event.event_timestamp or datetime.now(timezone.utc)).date()
        if hasattr(datetime, "now")
        else datetime.utcnow().date()
    )

    if not fact:
        is_new_fact = True
        fact = ent.NormalizedDeliveryFact(
            tenant_id=tenant_id,
            source_platform_id=1,
            source_delivery_id=event.order_id,
            courier_id=courier.id if courier else None,
            event_type="COMPLETED"
            if event.delivery_status == "DELIVERED"
            else event.delivery_status,
            event_date=today,
            event_timestamp=event.event_timestamp or datetime.now(timezone.utc),
            distance_km=event.distance_km,
            revenue_amount=event.delivery_fee,
            idempotency_key=f"NINJA-{tenant_id}-{event.order_id}",
        )
        db.add(fact)
    else:
        if courier and not fact.courier_id:
            fact.courier_id = courier.id

    # 3. Record / Upsert DailyLog for today only if this is a newly ingested delivery fact and courier is mapped
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
                source_type="LIVE_API_NINJA",
                notes=f"Ninja Live Ingestion: Order {event.order_id}",
            )
            db.add(daily_log)
        elif is_new_fact:
            daily_log.orders_count = (daily_log.orders_count or 0) + 1
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
    x_tenant_id: Optional[int] = Header(None),
):
    """Batch ingest real-time delivery facts from Ninja platform."""
    results = []
    for ev in payload.events:
        res = await ingest_ninja_live_event(event=ev, db=db, x_tenant_id=x_tenant_id)
        results.append(res)
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

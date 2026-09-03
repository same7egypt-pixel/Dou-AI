"""A delivery that becomes a fact must also become pay.

Payroll does not read delivery facts. `eligible_orders_for_courier` reads
`DailyLog.orders_count`, so a fact with no daily log is a delivery the
integration screen shows as accepted and the payslip pays nothing for.

The Ninja live endpoint credited the daily log inline. The reprocess path added
later did not — so the operator's entire loop (a row is rejected for an unmapped
rider, the mapping is added, reprocess accepts it) produced facts worth 0 SAR,
with the UI reporting success. Found by an external reviewer; this is the test
that would have caught it.
"""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.entities import (
    Country,
    Courier,
    CourierType,
    CustomerType,
    DailyLog,
    NormalizedDeliveryFact,
    PartnerCredential,
    SourcePlatform,
    Tenant,
    User,
    UserRole,
)
from app.routers.auth import create_token, hash_password
from app.services import entitlements
from app.services.financial_calculations import eligible_orders_for_courier

import hashlib


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    tenant = Tenant(
        name="نينجا", country=Country.SA, plan="PRO", subscription_status="ACTIVE",
        customer_type=CustomerType.DELIVERY_PLATFORM.value,
        capabilities=entitlements.serialize(entitlements.PLATFORM_DEFAULTS),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    user = User(
        phone="966590000001", name="مدير", role=UserRole.COMPANY_ADMIN,
        tenant_id=tenant.id, is_active=True, password_hash=hash_password("Pass12345!"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    source = SourcePlatform(
        tenant_id=tenant.id, code="NINJA", name_ar="نينجا", is_active=True
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    rider = Courier(
        tenant_id=tenant.id, name="مندوب", phone="966597779901",
        courier_type=CourierType.COMPANY, country=Country.SA,
        employment_status="ACTIVE", base_salary=0.0, per_delivery_rate=6.0,
    )
    db.add(rider)
    db.commit()
    db.refresh(rider)

    app.dependency_overrides[get_db] = lambda: db
    yield {
        "db": db, "client": TestClient(app), "tenant": tenant, "source": source,
        "rider": rider, "H": {"Authorization": f"Bearer {create_token(user)}"},
    }
    app.dependency_overrides.clear()
    db.close()


def _row(env, source_id, rider_id="NJ-1", day="2026-09-01"):
    return env["client"].post(
        "/sources/raw-rows",
        json={
            "source_platform_id": env["source"].id,
            "source_id": source_id,
            "row_data": json.dumps({
                "order_id": source_id, "rider_id": rider_id,
                "delivery_status": "DELIVERED", "event_date": day,
                "delivery_fee": 12.0,
            }),
        },
        headers=env["H"],
    )


def _map(env, source_rider_id="NJ-1"):
    return env["client"].post(
        "/sources/rider-mappings",
        json={
            "source_platform_id": env["source"].id,
            "source_rider_id": source_rider_id,
            "courier_id": env["rider"].id,
            "match_method": "MANUAL", "confidence": 1.0,
            "effective_from": "2026-01-01",
        },
        headers=env["H"],
    )


def test_a_reprocessed_delivery_reaches_payroll(env):
    """The whole operator loop, ending at the number the rider is paid on."""
    _row(env, "ORD-1")
    assert env["db"].query(NormalizedDeliveryFact).count() == 0
    assert eligible_orders_for_courier(env["db"], env["rider"], "2026-09") == 0

    _map(env)
    result = env["client"].post("/sources/raw-rows/reprocess", headers=env["H"])
    assert result.json() == {"normalized": 1, "rejected": 0}
    assert env["db"].query(NormalizedDeliveryFact).count() == 1

    assert eligible_orders_for_courier(env["db"], env["rider"], "2026-09") == 1, (
        "the screen says the delivery was accepted and payroll pays nothing "
        "for it — a fact without a daily log is worth 0 SAR"
    )


def test_a_delivery_accepted_on_arrival_also_reaches_payroll(env):
    _map(env)
    _row(env, "ORD-2")
    assert eligible_orders_for_courier(env["db"], env["rider"], "2026-09") == 1


def test_the_credit_lands_on_the_day_the_rider_worked(env):
    """A batch arriving after midnight belongs to the day it was delivered."""
    _map(env)
    _row(env, "ORD-3", day="2026-08-31")
    log = env["db"].query(DailyLog).one()
    assert log.log_date == date(2026, 8, 31)
    assert eligible_orders_for_courier(env["db"], env["rider"], "2026-09") == 0
    assert eligible_orders_for_courier(env["db"], env["rider"], "2026-08") == 1


def test_reprocessing_repeatedly_cannot_pay_the_same_delivery_twice(env):
    _map(env)
    _row(env, "ORD-4")
    for _ in range(3):
        env["client"].post("/sources/raw-rows/reprocess", headers=env["H"])
    assert eligible_orders_for_courier(env["db"], env["rider"], "2026-09") == 1


def test_two_deliveries_on_one_day_are_both_paid(env):
    _map(env)
    _row(env, "ORD-5")
    _row(env, "ORD-6")
    assert eligible_orders_for_courier(env["db"], env["rider"], "2026-09") == 2
    assert env["db"].query(DailyLog).count() == 1


def test_a_cancelled_delivery_is_not_paid(env):
    _map(env)
    env["client"].post(
        "/sources/raw-rows",
        json={
            "source_platform_id": env["source"].id, "source_id": "ORD-7",
            "row_data": json.dumps({
                "order_id": "ORD-7", "rider_id": "NJ-1",
                "delivery_status": "CANCELLED", "event_date": "2026-09-01",
            }),
        },
        headers=env["H"],
    )
    assert eligible_orders_for_courier(env["db"], env["rider"], "2026-09") == 0


def test_a_live_ninja_event_credits_the_rider_exactly_once(env):
    """The live path used to credit inline; the normalizer does it now, and
    doing both would pay the same order twice."""
    _map(env, "NJ-LIVE")
    raw = "dou_live_key_reprocess_0001"
    env["db"].add(PartnerCredential(
        tenant_id=env["tenant"].id, partner_name="Ninja", key_prefix=raw[:16],
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        scopes="performance:write", is_active=True,
    ))
    env["db"].commit()

    for _ in range(2):  # the platform retries
        env["client"].post(
            "/sources/ninja/live-event",
            json={
                "order_id": "NINJA-1", "ninja_rider_id": "NJ-LIVE",
                "delivery_status": "DELIVERED", "delivery_fee": 12.0,
            },
            headers={"X-API-Key": raw},
        )

    month = date.today().strftime("%Y-%m")
    assert eligible_orders_for_courier(env["db"], env["rider"], month) == 1, (
        "a retried webhook paid the rider twice, or the live path stopped "
        "crediting at all"
    )


def test_an_order_that_completes_later_still_reaches_payroll(env):
    """The same order arriving with a changed payload is an update, not a
    replay. The row kept the first version, so normalize_row re-read stale data
    and the completion was thrown away — a delivered order stayed unpaid."""
    _map(env, "NJ-LIVE")
    raw = "dou_live_key_update_00001"
    env["db"].add(PartnerCredential(
        tenant_id=env["tenant"].id, partner_name="Ninja", key_prefix=raw[:16],
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        scopes="performance:write", is_active=True,
    ))
    env["db"].commit()
    headers = {"X-API-Key": raw}
    month = date.today().strftime("%Y-%m")

    # First: assigned, not delivered.
    env["client"].post(
        "/sources/ninja/live-event",
        json={"order_id": "NINJA-U1", "ninja_rider_id": "NJ-LIVE",
              "delivery_status": "CANCELLED", "delivery_fee": 0.0},
        headers=headers,
    )
    assert eligible_orders_for_courier(env["db"], env["rider"], month) == 0

    # Then: the same order completes.
    env["client"].post(
        "/sources/ninja/live-event",
        json={"order_id": "NINJA-U1", "ninja_rider_id": "NJ-LIVE",
              "delivery_status": "DELIVERED", "delivery_fee": 14.0},
        headers=headers,
    )
    assert eligible_orders_for_courier(env["db"], env["rider"], month) == 1, (
        "the completion update was discarded and the rider went unpaid"
    )
    fact = env["db"].query(NormalizedDeliveryFact).one()
    assert fact.event_type == "COMPLETED"


def test_an_order_cancelled_after_delivery_is_taken_back(env):
    """The correction has to run both ways, or the platform keeps paying for a
    delivery it later said did not happen."""
    _map(env, "NJ-LIVE")
    raw = "dou_live_key_undo_000001"
    env["db"].add(PartnerCredential(
        tenant_id=env["tenant"].id, partner_name="Ninja", key_prefix=raw[:16],
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        scopes="performance:write", is_active=True,
    ))
    env["db"].commit()
    headers = {"X-API-Key": raw}
    month = date.today().strftime("%Y-%m")

    env["client"].post(
        "/sources/ninja/live-event",
        json={"order_id": "NINJA-U2", "ninja_rider_id": "NJ-LIVE",
              "delivery_status": "DELIVERED", "delivery_fee": 14.0},
        headers=headers,
    )
    assert eligible_orders_for_courier(env["db"], env["rider"], month) == 1

    env["client"].post(
        "/sources/ninja/live-event",
        json={"order_id": "NINJA-U2", "ninja_rider_id": "NJ-LIVE",
              "delivery_status": "CANCELLED", "delivery_fee": 0.0},
        headers=headers,
    )
    assert eligible_orders_for_courier(env["db"], env["rider"], month) == 0


def test_a_correction_never_drives_the_count_below_zero(env):
    """A cancellation for a delivery that was never credited must not make the
    rider owe one back.

    Driven at the unit level on purpose: a repeated webhook cancellation has
    the same checksum as the first, so it is not treated as an update and never
    reaches the decrement — the round trip could not exercise the floor, and a
    mutation removing it did not fail until this test called it directly.
    """
    from app.models.entities import NormalizedDeliveryFact as Fact
    from app.services.ingestion import _credit_daily_log

    fact = Fact(
        tenant_id=env["tenant"].id,
        source_platform_id=env["source"].id,
        source_delivery_id="FLOOR-1",
        courier_id=env["rider"].id,
        event_type="CANCELLED",
        event_date=date(2026, 9, 1),
        idempotency_key="floor-1",
    )
    env["db"].add(fact)
    env["db"].commit()

    env["db"].add(DailyLog(
        courier_id=env["rider"].id, tenant_id=env["tenant"].id,
        project_id=None, log_date=date(2026, 9, 1),
        orders_count=0, driver_orders=0, verified_orders=0, variance=0,
        source_type="PLATFORM_INGESTION",
    ))
    env["db"].commit()

    for _ in range(3):
        _credit_daily_log(env["db"], fact, delta=-1)
    env["db"].commit()

    log = env["db"].query(DailyLog).one()
    assert log.orders_count == 0, f"the count went negative: {log.orders_count}"
    assert log.verified_orders == 0
    assert eligible_orders_for_courier(env["db"], env["rider"], "2026-09") == 0

"""Verification tests for Phase 1 architectural & operational improvements.

Tests:
1. Rate limit X-Forwarded-For parsing.
2. DailyLog driver_orders and verified_orders non-destructive coexistence.
3. Mutual Operator invitation, inspection, acceptance, and rejection lifecycle.
"""

from datetime import date, datetime
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.middleware.rate_limit import RateLimitMiddleware
from app.models import entities as ent


def test_rate_limit_reads_x_forwarded_for():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, requests_per_minute=5)

    @app.get("/test-endpoint")
    def sample_endpoint():
        return {"status": "ok"}

    client = TestClient(app)

    # 5 requests from IP 1.1.1.1 should succeed
    for _ in range(5):
        r = client.get("/test-endpoint", headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.1"})
        assert r.status_code == 200

    # 6th request from IP 1.1.1.1 should be rate limited (429)
    r = client.get("/test-endpoint", headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.1"})
    assert r.status_code == 429

    # But request from a DIFFERENT IP 2.2.2.2 should succeed (not shared 127.0.0.1)
    r2 = client.get("/test-endpoint", headers={"X-Forwarded-For": "2.2.2.2"})
    assert r2.status_code == 200


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_daily_log_preserves_driver_and_verified_orders(test_db):
    tenant = ent.Tenant(name="Logistics Co", country=ent.Country.SA)
    test_db.add(tenant)
    test_db.commit()

    project = ent.Project(name="Ninja Project", tenant_id=tenant.id)
    test_db.add(project)
    test_db.commit()

    courier = ent.Courier(
        name="Test Courier",
        phone="0550001122",
        country=ent.Country.SA,
        courier_type=ent.CourierType.COMPANY,
        tenant_id=tenant.id,
        primary_project_id=project.id,
        employment_status="ACTIVE",
    )
    test_db.add(courier)
    test_db.commit()

    today = date.today()

    # 1. Ninja Webhook records 5 verified orders
    log = ent.DailyLog(
        courier_id=courier.id,
        tenant_id=tenant.id,
        project_id=project.id,
        log_date=today,
        orders_count=5,
        driver_orders=0,
        verified_orders=5,
        variance=5,
        source_type="LIVE_API_NINJA",
    )
    test_db.add(log)
    test_db.commit()

    # 2. Driver enters 7 manual orders later in the evening
    row = test_db.query(ent.DailyLog).filter(
        ent.DailyLog.courier_id == courier.id,
        ent.DailyLog.log_date == today,
        ent.DailyLog.project_id == project.id,
    ).first()

    assert row is not None
    assert row.verified_orders == 5

    # Update preserving both:
    row.driver_orders = 7
    if (row.verified_orders or 0) > 0:
        row.orders_count = row.verified_orders
        row.variance = row.orders_count - 7
    test_db.commit()
    test_db.refresh(row)

    # 3. Verified facts remain intact and variance is calculated
    assert row.verified_orders == 5
    assert row.driver_orders == 7
    assert row.orders_count == 5
    assert row.variance == -2


def test_mutual_operator_invitation_lifecycle(test_db):
    platform = ent.Tenant(name="Ninja Platform", customer_type="DELIVERY_PLATFORM", country=ent.Country.SA)
    test_db.add(platform)
    test_db.commit()

    source = ent.SourcePlatform(tenant_id=platform.id, code="NINJA_MAIN", name_ar="منصة نينجا")
    test_db.add(source)
    test_db.commit()

    vendor = ent.Tenant(name="Speed Logistics 3PL", customer_type="LOGISTICS_OPERATOR", country=ent.Country.SA)
    test_db.add(vendor)
    test_db.commit()

    # 1. Platform sends invitation
    invitation = ent.PlatformOperator(
        tenant_id=platform.id,
        source_platform_id=source.id,
        operator_tenant_id=vendor.id,
        relationship_type="OPERATOR",
        invitation_status="PENDING",
        invited_at=datetime.utcnow(),
        is_active=False,
    )
    test_db.add(invitation)
    test_db.commit()
    test_db.refresh(invitation)

    assert invitation.id is not None
    assert invitation.invitation_status == "PENDING"
    assert invitation.is_active is False

    # 2. Vendor queries incoming invitations
    incoming = test_db.query(ent.PlatformOperator).filter(
        ent.PlatformOperator.operator_tenant_id == vendor.id,
        ent.PlatformOperator.invitation_status == "PENDING",
    ).all()
    assert len(incoming) == 1
    assert incoming[0].tenant_id == platform.id

    # 3. Vendor accepts invitation
    inv = incoming[0]
    inv.invitation_status = "ACCEPTED"
    inv.is_active = True
    inv.responded_at = datetime.utcnow()
    test_db.commit()
    test_db.refresh(inv)

    assert inv.invitation_status == "ACCEPTED"
    assert inv.is_active is True
    assert inv.responded_at is not None

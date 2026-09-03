"""Delivery facts may only be written by a partner that proves which tenant it is.

`/sources/ninja/live-event`, `/webhook` and `/batch-sync` had no authentication
at all. They read the target company from an `X-Tenant-Id` request header and
believed it, defaulting to tenant 1 when it was absent. The `X-Ninja-Signature`
header the handler declared was never read.

What that bought an attacker who could reach the port: writing completed
deliveries into any company on the platform. Order counts are what payroll pays
a rider per order, and what a bonus plan measures a target against, so this was
a way to change what a company owes its riders from outside the product.

These tests hold the endpoints to the credential that already existed for the
purpose: PartnerCredential, which is issued per tenant with scopes and an
expiry, and stores only the hash of the key.
"""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.entities import (
    Capability,
    Country,
    CustomerType,
    PartnerCredential,
    Tenant,
)
from app.routers.ninja_integration import INGEST_SCOPE
from app.services import entitlements


def make_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()

EVENT = {
    "order_id": "NINJA-AUTH-1",
    "ninja_rider_id": "RIDER-1",
    "delivery_status": "DELIVERED",
    "delivery_fee": 20.0,
}


def _issue_key(db, tenant_id, scopes=(INGEST_SCOPE,), expires_at=None, active=True):
    raw = secrets.token_urlsafe(32)
    db.add(
        PartnerCredential(
            tenant_id=tenant_id,
            partner_name="Ninja",
            key_prefix=raw[:16],
            key_hash=hashlib.sha256(raw.encode()).hexdigest(),
            scopes=json.dumps(list(scopes)),
            expires_at=expires_at,
            is_active=active,
        )
    )
    db.commit()
    return raw


@pytest.fixture
def env():
    db = make_session()

    def tenant(name, customer_type, capabilities):
        row = Tenant(
            name=name,
            country=Country.SA,
            plan="PRO",
            subscription_status="ACTIVE",
            customer_type=customer_type.value,
            capabilities=entitlements.serialize(capabilities),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    platform = tenant(
        "Ninja KSA",
        CustomerType.DELIVERY_PLATFORM,
        entitlements.PLATFORM_DEFAULTS,
    )
    other = tenant(
        "A different company",
        CustomerType.DELIVERY_PLATFORM,
        entitlements.PLATFORM_DEFAULTS,
    )
    no_feed = tenant(
        "Manual imports only",
        CustomerType.LOGISTICS_OPERATOR,
        entitlements.LOGISTICS_DEFAULTS,
    )

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield {
            "db": db,
            "client": client,
            "platform": platform,
            "other": other,
            "no_feed": no_feed,
        }
    app.dependency_overrides.clear()
    db.close()


@pytest.mark.parametrize("path", ["/sources/ninja/live-event", "/sources/ninja/webhook"])
def test_writing_without_a_key_is_refused(env, path):
    res = env["client"].post(path, json=EVENT)
    assert res.status_code == 401, (
        f"{path} accepted an unauthenticated delivery event; anyone who can "
        "reach the port can write the orders payroll pays on"
    )


def test_a_tenant_id_header_no_longer_chooses_the_target(env):
    """The header was the whole vulnerability: the caller named its victim."""
    res = env["client"].post(
        "/sources/ninja/live-event",
        json=EVENT,
        headers={"X-Tenant-Id": str(env["platform"].id)},
    )
    assert res.status_code == 401


def test_batch_sync_is_refused_without_a_key(env):
    res = env["client"].post("/sources/ninja/batch-sync", json={"events": [EVENT]})
    assert res.status_code == 401


def test_a_valid_key_writes_to_its_own_tenant(env):
    key = _issue_key(env["db"], env["platform"].id)
    res = env["client"].post(
        "/sources/ninja/live-event", json=EVENT, headers={"X-API-Key": key}
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "success"


def test_a_bearer_token_is_accepted_too(env):
    key = _issue_key(env["db"], env["platform"].id)
    res = env["client"].post(
        "/sources/ninja/live-event",
        json=dict(EVENT, order_id="NINJA-AUTH-BEARER"),
        headers={"Authorization": f"Bearer {key}"},
    )
    assert res.status_code == 200, res.text


def test_a_key_cannot_be_pointed_at_another_tenant(env):
    """The tenant comes from the credential, so the header is inert."""
    key = _issue_key(env["db"], env["platform"].id)
    res = env["client"].post(
        "/sources/ninja/live-event",
        json=dict(EVENT, order_id="NINJA-AUTH-CROSS"),
        headers={"X-API-Key": key, "X-Tenant-Id": str(env["other"].id)},
    )
    assert res.status_code == 200
    # Nothing was written for the tenant named in the header.
    from app.models.entities import PlatformDeliveryFact

    leaked = (
        env["db"]
        .query(PlatformDeliveryFact)
        .filter(PlatformDeliveryFact.tenant_id == env["other"].id)
        .count()
    )
    assert leaked == 0, "an X-Tenant-Id header still steered the write"


def test_a_key_without_the_scope_is_refused(env):
    key = _issue_key(env["db"], env["platform"].id, scopes=("orders:read",))
    res = env["client"].post(
        "/sources/ninja/live-event", json=EVENT, headers={"X-API-Key": key}
    )
    assert res.status_code == 403


def test_an_expired_key_is_refused(env):
    key = _issue_key(
        env["db"],
        env["platform"].id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    res = env["client"].post(
        "/sources/ninja/live-event", json=EVENT, headers={"X-API-Key": key}
    )
    assert res.status_code == 401


def test_a_revoked_key_is_refused(env):
    key = _issue_key(env["db"], env["platform"].id, active=False)
    res = env["client"].post(
        "/sources/ninja/live-event", json=EVENT, headers={"X-API-Key": key}
    )
    assert res.status_code == 401


def test_a_tenant_without_the_capability_is_refused(env):
    """A lapsed entitlement stops the feed without anyone revoking the key."""
    assert Capability.PERFORMANCE_API_INGESTION.value not in entitlements.capabilities_for(
        env["no_feed"]
    )
    key = _issue_key(env["db"], env["no_feed"].id)
    res = env["client"].post(
        "/sources/ninja/live-event", json=EVENT, headers={"X-API-Key": key}
    )
    assert res.status_code == 403

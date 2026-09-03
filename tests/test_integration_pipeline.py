"""The ingestion pipeline moves, is gated, and is reachable from a screen.

CLAUDE.md describes RawImportRow → RiderIdentityMapping / ProjectContractMapping
→ NormalizedDeliveryFact. The middle arrow did not exist. `RawImportRow.status`
documents PENDING / ACCEPTED / REJECTED / NORMALIZED and nothing in the codebase
had ever written anything but the default: rows landed and stayed PENDING
forever, because no code anywhere read a raw row and produced a fact.

Meanwhile the Ninja live endpoint wrote facts directly with no raw row behind
them — `raw_row_id` and `provenance` are columns on the fact and both were
always null, so a delivery a rider was paid for had no record of what produced
it — and stamped `source_platform_id=1` as a literal. SourcePlatform rows are
tenant-scoped, so id 1 belongs to whichever tenant created the first one: every
other tenant's deliveries pointed at a stranger's row.

All seventeen /sources endpoints checked role and nothing else, so an account
that buys no API feed could create source platforms, identity mappings, raw rows
and delivery facts — and a delivery fact is what payroll pays on. Same defect as
payroll and vendor settlements: the capability existed and nothing read it.

And none of it was reachable from any screen. Zero lines of frontend code
touched /sources.
"""

import hashlib
import json
import re
from datetime import date
from pathlib import Path

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
    Courier,
    CourierType,
    CustomerType,
    NormalizedDeliveryFact,
    PartnerCredential,
    Project,
    ProjectContractMapping,
    RawImportRow,
    RiderIdentityMapping,
    SourcePlatform,
    Tenant,
    User,
    UserRole,
)
from app.routers.auth import create_token, hash_password
from app.services import entitlements

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend-v2"
INTEGRATION = FRONTEND / "fleet" / "views" / "integration.js"


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    def account(name, capabilities, phone):
        tenant = Tenant(
            name=name,
            country=Country.SA,
            plan="PRO",
            subscription_status="ACTIVE",
            customer_type=CustomerType.DELIVERY_PLATFORM.value,
            capabilities=entitlements.serialize(capabilities),
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        user = User(
            phone=phone,
            name=name,
            role=UserRole.COMPANY_ADMIN,
            tenant_id=tenant.id,
            is_active=True,
            password_hash=hash_password("Pass12345!"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"tenant": tenant, "token": create_token(user)}

    platform = account("Ninja", entitlements.PLATFORM_DEFAULTS, "966590000001")

    source = SourcePlatform(
        tenant_id=platform["tenant"].id, code="NINJA", name_ar="نينجا", is_active=True
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    rider = Courier(
        tenant_id=platform["tenant"].id,
        name="مندوب نينجا",
        phone="966597779901",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        employment_status="ACTIVE",
    )
    db.add(rider)
    db.commit()
    db.refresh(rider)

    app.dependency_overrides[get_db] = lambda: db
    yield {
        "db": db,
        "client": TestClient(app),
        "platform": platform,
        "source": source,
        "rider": rider,
        "account": account,
        "H": {"Authorization": f"Bearer {platform['token']}"},
    }
    app.dependency_overrides.clear()
    db.close()


def _row(env, source_id, **overrides):
    body = {
        "order_id": source_id,
        "rider_id": "NJ-77",
        "delivery_status": "DELIVERED",
        "event_date": "2026-09-01",
        "delivery_fee": 18.5,
        "distance_km": 4.2,
    }
    body.update(overrides)
    return env["client"].post(
        "/sources/raw-rows",
        json={
            "source_platform_id": env["source"].id,
            "source_id": source_id,
            "row_data": json.dumps(body, ensure_ascii=False),
        },
        headers=env["H"],
    )


def _map_rider(env, source_rider_id="NJ-77"):
    return env["client"].post(
        "/sources/rider-mappings",
        json={
            "source_platform_id": env["source"].id,
            "source_rider_id": source_rider_id,
            "courier_id": env["rider"].id,
            "match_method": "MANUAL",
            "confidence": 1.0,
            "effective_from": "2026-01-01",
        },
        headers=env["H"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# The middle arrow exists
# ─────────────────────────────────────────────────────────────────────────────


def test_a_row_with_a_mapped_rider_becomes_a_fact_on_arrival(env):
    """Rows used to land at PENDING and stay there forever."""
    _map_rider(env)
    created = _row(env, "ORD-1")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "NORMALIZED"
    assert body["fact_id"] is not None

    fact = env["db"].get(NormalizedDeliveryFact, body["fact_id"])
    assert fact.courier_id == env["rider"].id
    assert fact.event_type == "COMPLETED"
    assert fact.event_date == date(2026, 9, 1)
    assert fact.revenue_amount == 18.5
    assert fact.distance_km == 4.2


def test_an_unmapped_rider_rejects_the_row_and_names_the_id(env):
    """The reason is the entire value: it says what to add, then reprocess."""
    created = _row(env, "ORD-2")
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "REJECTED"
    assert body["fact_id"] is None
    issue = body["validation_issues"][0]
    assert issue["field"] == "source_rider_id"
    assert "NJ-77" in issue["reason"], (
        "a generic failure leaves the operator with nothing to act on"
    )
    assert env["db"].query(NormalizedDeliveryFact).count() == 0


def test_adding_the_mapping_then_reprocessing_accepts_the_row(env):
    """The operator's whole loop, end to end."""
    _row(env, "ORD-3")
    assert env["db"].query(NormalizedDeliveryFact).count() == 0

    _map_rider(env)
    result = env["client"].post("/sources/raw-rows/reprocess", headers=env["H"])
    assert result.status_code == 200, result.text
    assert result.json() == {"normalized": 1, "rejected": 0}

    row = env["db"].query(RawImportRow).one()
    assert row.status == "NORMALIZED"
    assert row.validation_issues is None
    assert env["db"].query(NormalizedDeliveryFact).count() == 1


def test_reprocessing_cannot_count_a_delivery_twice(env):
    _map_rider(env)
    _row(env, "ORD-4")
    for _ in range(3):
        env["client"].post("/sources/raw-rows/reprocess", headers=env["H"])
    assert env["db"].query(NormalizedDeliveryFact).count() == 1


def test_reprocessing_leaves_accepted_rows_alone(env):
    """Asserting the outcome alone was too weak: normalize_row is itself
    idempotent, so a reprocess that swept up NORMALIZED rows still produced one
    fact and the test passed — verified, that mutation did not fail. What the
    code claims is that those rows are not touched at all, and that is what the
    count has to say."""
    _map_rider(env)
    _row(env, "ORD-4B")
    first = env["client"].post("/sources/raw-rows/reprocess", headers=env["H"]).json()
    assert first == {"normalized": 0, "rejected": 0}, (
        "a row already accepted on arrival is not work for a reprocess"
    )


def test_every_fact_carries_the_row_that_produced_it(env):
    """A number in payroll has to be answerable for months later."""
    _map_rider(env)
    fact_id = _row(env, "ORD-5").json()["fact_id"]
    fact = env["db"].get(NormalizedDeliveryFact, fact_id)

    assert fact.raw_row_id is not None
    assert fact.provenance, "provenance was always null"
    lineage = json.loads(fact.provenance)
    assert lineage["source_id"] == "ORD-5"
    assert lineage["source_rider_id"] == "NJ-77"
    assert lineage["resolved_courier_id"] == env["rider"].id
    assert len(lineage["checksum"]) == 64

    listed = env["client"].get("/sources/delivery-facts", headers=env["H"]).json()[0]
    assert listed["raw_row_id"] == fact.raw_row_id, (
        "the reader returned neither the row link nor the lineage, so nothing "
        "could actually be traced"
    )
    assert listed["provenance"]["checksum"] == lineage["checksum"]
    assert listed["distance_km"] == 4.2


def test_a_mapped_project_is_carried_onto_the_fact(env):
    db = env["db"]
    project = Project(
        tenant_id=env["platform"]["tenant"].id, name="نينجا الرياض", is_active=True
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    db.add(ProjectContractMapping(
        tenant_id=env["platform"]["tenant"].id,
        source_platform_id=env["source"].id,
        project_id=project.id,
        is_active=True,
    ))
    db.commit()

    _map_rider(env)
    fact_id = _row(env, "ORD-6").json()["fact_id"]
    assert db.get(NormalizedDeliveryFact, fact_id).project_id == project.id


def test_a_missing_project_mapping_does_not_reject_the_delivery(env):
    """A rider made the delivery; a reporting gap must not unmake it."""
    _map_rider(env)
    body = _row(env, "ORD-7").json()
    assert body["status"] == "NORMALIZED"
    assert env["db"].get(NormalizedDeliveryFact, body["fact_id"]).project_id is None


def test_an_unreadable_row_is_rejected_with_the_field_named(env):
    _map_rider(env)
    assert _row(env, "ORD-8", event_date="not-a-date").json()["status"] == "REJECTED"
    no_id = env["client"].post(
        "/sources/raw-rows",
        json={
            "source_platform_id": env["source"].id,
            "source_id": "ORD-9",
            "row_data": json.dumps({"rider_id": "NJ-77", "event_date": "2026-09-01"}),
        },
        headers=env["H"],
    ).json()
    assert no_id["validation_issues"][0]["field"] == "source_delivery_id"


# ─────────────────────────────────────────────────────────────────────────────
# The live path joins the same pipeline
# ─────────────────────────────────────────────────────────────────────────────


def _ninja_key(env):
    raw = "dou_live_test_key_m5_0001"
    env["db"].add(PartnerCredential(
        tenant_id=env["platform"]["tenant"].id,
        partner_name="Ninja",
        key_prefix=raw[:16],
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        scopes="performance:write",
        is_active=True,
    ))
    env["db"].commit()
    return {"X-API-Key": raw}


def test_a_live_event_is_recorded_as_a_row_and_normalized(env):
    """The live path wrote facts with nothing behind them."""
    _map_rider(env, "NINJA-C9")
    sent = env["client"].post(
        "/sources/ninja/live-event",
        json={
            "order_id": "NINJA-LIVE-1",
            "ninja_rider_id": "NINJA-C9",
            "delivery_status": "DELIVERED",
            "delivery_fee": 12.0,
        },
        headers=_ninja_key(env),
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["is_new"] is True

    row = env["db"].query(RawImportRow).filter(
        RawImportRow.source_id == "NINJA-LIVE-1"
    ).one()
    assert row.status == "NORMALIZED"

    fact = env["db"].query(NormalizedDeliveryFact).one()
    assert fact.raw_row_id == row.id
    assert fact.provenance, "a delivery a rider is paid for had no record of its origin"


def test_a_live_event_is_stamped_with_this_tenants_own_source(env):
    """`source_platform_id=1` is a literal that belongs to another tenant."""
    other = env["account"]("HungerStation", entitlements.PLATFORM_DEFAULTS, "966590000009")
    db = env["db"]
    # This tenant's own NINJA source is deliberately not id 1.
    assert env["source"].id == 1
    raw = "dou_live_test_key_m5_0002"
    db.add(PartnerCredential(
        tenant_id=other["tenant"].id, partner_name="Ninja",
        key_prefix=raw[:16], key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        scopes="performance:write", is_active=True,
    ))
    db.commit()

    env["client"].post(
        "/sources/ninja/live-event",
        json={"order_id": "HS-1", "ninja_rider_id": "X", "delivery_status": "DELIVERED"},
        headers={"X-API-Key": raw},
    )
    created = db.query(SourcePlatform).filter(
        SourcePlatform.tenant_id == other["tenant"].id
    ).one()
    assert created.id != env["source"].id
    row = db.query(RawImportRow).filter(RawImportRow.source_id == "HS-1").one()
    assert row.source_platform_id == created.id, (
        "the event was attributed to another tenant's source platform"
    )


def test_a_live_event_whose_rider_is_unknown_is_visible_rather_than_lost(env):
    env["client"].post(
        "/sources/ninja/live-event",
        json={"order_id": "NINJA-LIVE-2", "ninja_rider_id": "NOBODY",
              "delivery_status": "DELIVERED"},
        headers=_ninja_key(env),
    )
    row = env["db"].query(RawImportRow).one()
    assert row.status == "REJECTED"
    assert "NOBODY" in row.validation_issues


def test_a_live_event_still_matches_a_rider_by_phone(env):
    """Routing the live path through the shared normalizer must not narrow it."""
    sent = env["client"].post(
        "/sources/ninja/live-event",
        json={
            "order_id": "NINJA-LIVE-3",
            "ninja_rider_id": "UNMAPPED",
            "rider_phone": "966597779901",
            "delivery_status": "DELIVERED",
        },
        headers=_ninja_key(env),
    )
    assert sent.status_code == 200
    assert env["db"].query(NormalizedDeliveryFact).one().courier_id == env["rider"].id


# ─────────────────────────────────────────────────────────────────────────────
# The pipeline is gated on the capability that sells it
# ─────────────────────────────────────────────────────────────────────────────


def test_an_account_without_the_api_feed_cannot_touch_the_pipeline(env):
    caps = [
        c for c in entitlements.PLATFORM_DEFAULTS
        if c != Capability.PERFORMANCE_API_INGESTION.value
    ]
    lean = env["account"]("Marsool", caps, "966590000011")
    headers = {"Authorization": f"Bearer {lean['token']}"}

    for method, path, body in (
        ("get", "/sources/platforms", None),
        ("get", "/sources/raw-rows", None),
        ("get", "/sources/delivery-facts", None),
        ("post", "/sources/platforms", {"code": "X", "name_ar": "س"}),
        ("post", "/sources/raw-rows/reprocess", None),
    ):
        res = getattr(env["client"], method)(
            path, headers=headers, **({"json": body} if body else {})
        )
        assert res.status_code == 403, f"{method.upper()} {path} answered {res.status_code}"
        assert "PERFORMANCE_API_INGESTION" in res.json()["detail"]


def test_a_delivery_fact_cannot_be_written_without_the_capability(env):
    """A delivery fact is what payroll pays on."""
    caps = [
        c for c in entitlements.PLATFORM_DEFAULTS
        if c != Capability.PERFORMANCE_API_INGESTION.value
    ]
    lean = env["account"]("Marsool", caps, "966590000012")
    refused = env["client"].post(
        "/sources/delivery-facts",
        json={
            "source_platform_id": env["source"].id,
            "source_delivery_id": "X-1",
            "event_type": "COMPLETED",
            "event_date": "2026-09-01",
        },
        headers={"Authorization": f"Bearer {lean['token']}"},
    )
    assert refused.status_code == 403


def test_rows_and_facts_never_cross_a_tenant_boundary(env):
    _map_rider(env)
    _row(env, "ORD-ISOLATED")
    other = env["account"]("HungerStation", entitlements.PLATFORM_DEFAULTS, "966590000013")
    headers = {"Authorization": f"Bearer {other['token']}"}
    assert env["client"].get("/sources/raw-rows", headers=headers).json() == []
    assert env["client"].get("/sources/delivery-facts", headers=headers).json() == []


# ─────────────────────────────────────────────────────────────────────────────
# It is reachable from a screen
# ─────────────────────────────────────────────────────────────────────────────


def test_the_pipeline_is_reachable_from_the_product():
    """Seventeen endpoints existed and no frontend line touched any of them."""
    assert INTEGRATION.exists(), "there is no integration screen"
    code = re.sub(r"//[^\n]*", "", INTEGRATION.read_text(encoding="utf-8"))
    for endpoint in (
        "/sources/platforms",
        "/sources/connections",
        "/sources/rider-mappings",
        "/sources/raw-rows",
        "/sources/raw-rows/reprocess",
        "/sources/delivery-facts",
        "/enterprise/credentials",
    ):
        assert endpoint in code, f"{endpoint} is still unreachable from a browser"


def test_the_screen_is_registered_and_gated():
    shell = (FRONTEND / "fleet" / "shell.js").read_text(encoding="utf-8")
    main = (FRONTEND / "fleet" / "main.js").read_text(encoding="utf-8")
    assert "integration: loadIntegration" in main, "the view has no loader"
    assert "integration: 'PERFORMANCE_API_INGESTION'" in shell, (
        "a screen the account cannot use must be absent, not merely empty"
    )
    assert "views: ['integration']" in shell, "the screen is in no nav group"


def test_the_screen_uses_the_shared_table_contract():
    """Passing arrays where the helper wants {key,label} renders empty cells —
    which is exactly what shipped until the screen was actually clicked.

    Looking for "key:" anywhere in the next 80 characters was too loose: it
    still matched the *following* column when only the first was broken —
    verified, that mutation did not fail. The first element after `table([` is
    what decides the shape, so that is what gets checked."""
    code = INTEGRATION.read_text(encoding="utf-8")
    calls = re.findall(r"table\(\s*\[\s*(.)", code, re.S)
    assert calls, "no table is rendered on the integration screen"
    for first_char in calls:
        assert first_char == "{", (
            "a table is built from bare values rather than {key,label} columns; "
            "every cell renders empty"
        )


def test_the_key_screen_says_the_secret_is_shown_once():
    code = INTEGRATION.read_text(encoding="utf-8")
    assert "لن يُعرض مرة أخرى" in code, (
        "the server stores only a hash; an operator who does not copy the key "
        "has to rotate it, and should be told so before that happens"
    )

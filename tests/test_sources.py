"""Wave 2 tests — source platforms, raw ingestion, rider mapping, delivery facts, reconciliation."""
import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Capability,
    Courier, CourierType, Country, DocumentType, NormalizedDeliveryFact,
    ProjectContractMapping, RawImportRow, ReconciliationResult,
    RiderIdentityMapping, SourcePlatform, TenantConnection, Tenant, User, UserRole,
)
from app.routers.sources import (
    NormalizedDeliveryFactCreate, ProjectContractMappingCreate,
    RawImportRowCreate, ReconciliationCreate, RiderIdentityMappingCreate,
    RiderIdentityMappingUpdate, SourcePlatformCreate, SourcePlatformUpdate,
    TenantConnectionCreate, TenantConnectionUpdate,
    create_source_platform, update_source_platform, list_source_platforms,
    create_connection, list_connections, update_connection,
    create_project_mapping, list_project_mappings,
    create_rider_mapping, list_rider_mappings, update_rider_mapping,
    create_raw_row, list_raw_rows,
    create_delivery_fact, list_delivery_facts,
    create_reconciliation, list_reconciliations,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def make_tenant(db, name):
    # /sources is the API-ingestion pipeline and is gated on the capability that
    # sells it. These tests exercise the endpoints, not the entitlement — that
    # is tests/test_integration_pipeline.py — so the fixture grants it.
    tenant = Tenant(
        name=name,
        country=Country.SA,
        capabilities=json.dumps([Capability.PERFORMANCE_API_INGESTION.value]),
    )
    db.add(tenant); db.commit(); db.refresh(tenant)
    return tenant


def make_user(db, tenant_id, phone, role=UserRole.COMPANY):
    user = User(phone=phone, password_hash="x", role=role, tenant_id=tenant_id)
    db.add(user); db.commit(); db.refresh(user)
    return user


def make_rider(db, tenant_id, suffix):
    rider = Courier(
        tenant_id=tenant_id, name=f"Rider {suffix}", phone=f"700{suffix}",
        courier_type=CourierType.COMPANY, country=Country.SA,
    )
    db.add(rider); db.commit(); db.refresh(rider)
    return rider


# ---------- source platforms ----------

def test_create_source_platform(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000001")
    result = create_source_platform(
        SourcePlatformCreate(code="HS", name_ar="هنقرستيشن", name_en="HungerStation"),
        user, db,
    )
    assert result["code"] == "HS"


def test_source_platform_code_unique_within_tenant(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000002")
    create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    with pytest.raises(HTTPException) as error:
        create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن 2"), user, db)
    assert error.value.status_code == 409


def test_source_platform_rejects_cross_tenant_code(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000003")
    user2 = make_user(db, tenant2.id, "966500000004")
    create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user1, db)
    result = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user2, db)
    assert result["code"] == "HS"


def test_update_source_platform(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000005")
    created = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    updated = update_source_platform(created["id"], SourcePlatformUpdate(name_ar="هنقرستيشن المحدث"), user, db)
    assert updated["name_ar"] == "هنقرستيشن المحدث"


# ---------- tenant connections ----------

def test_create_connection(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000006")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    result = create_connection(
        TenantConnectionCreate(source_platform_id=sp["id"], connection_name="HS Riyadh"),
        user, db,
    )
    assert result["connection_name"] == "HS Riyadh"


def test_connection_unique_per_platform(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000007")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    create_connection(TenantConnectionCreate(source_platform_id=sp["id"], connection_name="HS Riyadh"), user, db)
    with pytest.raises(HTTPException) as error:
        create_connection(TenantConnectionCreate(source_platform_id=sp["id"], connection_name="HS Jeddah"), user, db)
    assert error.value.status_code == 409


# ---------- rider identity mappings ----------

def test_create_rider_mapping(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000008")
    rider = make_rider(db, tenant.id, "1")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    result = create_rider_mapping(
        RiderIdentityMappingCreate(
            source_platform_id=sp["id"],
            source_rider_id="HS_12345",
            courier_id=rider.id,
            effective_from=date(2026, 1, 1),
        ),
        user, db,
    )
    assert result["source_rider_id"] == "HS_12345"
    assert result["courier_id"] == rider.id


def test_rider_mapping_unique_per_source(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000009")
    rider = make_rider(db, tenant.id, "2")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    create_rider_mapping(
        RiderIdentityMappingCreate(
            source_platform_id=sp["id"], source_rider_id="HS_12345",
            courier_id=rider.id, effective_from=date(2026, 1, 1),
        ),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        create_rider_mapping(
            RiderIdentityMappingCreate(
                source_platform_id=sp["id"], source_rider_id="HS_12345",
                courier_id=rider.id, effective_from=date(2026, 1, 1),
            ),
            user, db,
        )
    assert error.value.status_code == 409


def test_update_rider_mapping(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000010")
    rider = make_rider(db, tenant.id, "3")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    created = create_rider_mapping(
        RiderIdentityMappingCreate(
            source_platform_id=sp["id"], source_rider_id="HS_12345",
            courier_id=rider.id, effective_from=date(2026, 1, 1),
        ),
        user, db,
    )
    updated = update_rider_mapping(
        created["id"],
        RiderIdentityMappingUpdate(status="INACTIVE"),
        user, db,
    )
    assert updated["source_rider_id"] == "HS_12345"


# ---------- raw import rows ----------

def test_create_raw_row(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000011")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    result = create_raw_row(
        RawImportRowCreate(
            source_platform_id=sp["id"],
            source_id="DEL_001",
            row_data=json.dumps({"order_id": "123", "status": "completed"}),
        ),
        user, db,
    )
    assert result["source_id"] == "DEL_001"
    assert "checksum" in result


def test_raw_row_rejects_invalid_json(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000012")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    with pytest.raises(HTTPException) as error:
        create_raw_row(
            RawImportRowCreate(
                source_platform_id=sp["id"],
                source_id="DEL_001",
                row_data="not valid json",
            ),
            user, db,
        )
    assert error.value.status_code == 400


def test_raw_row_unique_per_source(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000013")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    create_raw_row(
        RawImportRowCreate(
            source_platform_id=sp["id"], source_id="DEL_001",
            row_data=json.dumps({"order_id": "123"}),
        ),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        create_raw_row(
            RawImportRowCreate(
                source_platform_id=sp["id"], source_id="DEL_001",
                row_data=json.dumps({"order_id": "123"}),
            ),
            user, db,
        )
    assert error.value.status_code == 409


# ---------- normalized delivery facts ----------

def test_create_delivery_fact(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000014")
    rider = make_rider(db, tenant.id, "4")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    result = create_delivery_fact(
        NormalizedDeliveryFactCreate(
            source_platform_id=sp["id"],
            source_delivery_id="DEL_001",
            courier_id=rider.id,
            event_type="COMPLETED",
            event_date=date(2026, 9, 1),
            revenue_amount=25.0,
            cost_amount=5.0,
        ),
        user, db,
    )
    assert result["source_delivery_id"] == "DEL_001"
    assert result["event_type"] == "COMPLETED"


def test_delivery_fact_idempotent(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000015")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    create_delivery_fact(
        NormalizedDeliveryFactCreate(
            source_platform_id=sp["id"], source_delivery_id="DEL_001",
            event_type="COMPLETED", event_date=date(2026, 9, 1),
        ),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        create_delivery_fact(
            NormalizedDeliveryFactCreate(
                source_platform_id=sp["id"], source_delivery_id="DEL_001",
                event_type="COMPLETED", event_date=date(2026, 9, 1),
            ),
            user, db,
        )
    assert error.value.status_code == 409


def test_delivery_fact_rejects_invalid_event_type(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000016")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    with pytest.raises(HTTPException) as error:
        create_delivery_fact(
            NormalizedDeliveryFactCreate(
                source_platform_id=sp["id"], source_delivery_id="DEL_001",
                event_type="INVALID", event_date=date(2026, 9, 1),
            ),
            user, db,
        )
    assert error.value.status_code == 400


# ---------- reconciliation ----------

def test_create_reconciliation(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000017")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user, db)
    result = create_reconciliation(
        ReconciliationCreate(source_platform_id=sp["id"], reconciliation_date=date(2026, 9, 1)),
        user, db,
    )
    assert result["status"] == "COMPLETED"


# ---------- tenant isolation ----------

def test_cross_tenant_source_platform_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000018")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user1, db)
    user2 = make_user(db, tenant2.id, "966500000019")
    with pytest.raises(HTTPException) as error:
        update_source_platform(sp["id"], SourcePlatformUpdate(name_ar="Hacked"), user2, db)
    assert error.value.status_code == 404


def test_cross_tenant_rider_mapping_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000020")
    rider2 = make_rider(db, tenant2.id, "5")
    sp = create_source_platform(SourcePlatformCreate(code="HS", name_ar="هنقرستيشن"), user1, db)
    user2 = make_user(db, tenant2.id, "966500000021")
    with pytest.raises(HTTPException) as error:
        create_rider_mapping(
            RiderIdentityMappingCreate(
                source_platform_id=sp["id"], source_rider_id="HS_12345",
                courier_id=rider2.id, effective_from=date(2026, 1, 1),
            ),
            user2, db,
        )
    assert error.value.status_code in (403, 404)

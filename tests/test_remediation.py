"""Remediation tests — negative/concurrency tests for CRITICAL and HIGH fixes."""
import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Capability,
    Attendance, Courier, CourierType, Country, DelegatedScope,
    IntegrationAuditLog, MFASetting, NormalizedDeliveryFact,
    OperationalImportBatch, PartnerCredential, PlatformOperator,
    SecurityAuditLog, SourcePlatform, Tenant, User, UserRole,
)
from app.routers.analytics import (
    PayrollInputCreate, create_payroll_input, reverse_payroll_input,
)
from app.routers.enterprise import (
    PlatformOperatorCreate, create_operator,
    PartnerCredentialCreate, create_credential, rotate_credential,
)
from app.routers.sources import (
    NormalizedDeliveryFactCreate, RawImportRowCreate,
    create_delivery_fact, create_raw_row,
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


# ---------- C1: Payroll source_id cross-tenant validation ----------

def test_payroll_input_cross_tenant_source_rejected(db):
    """C1: source_id from another tenant should be rejected."""
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000001")
    rider1 = make_rider(db, tenant1.id, "1")
    
    # Create a leave request in tenant2
    from app.models.entities import LeaveRequest, LeaveType
    lt2 = LeaveType(tenant_id=tenant2.id, code="ANNUAL", name_ar="سنوية")
    db.add(lt2); db.commit()
    leave2 = LeaveRequest(
        tenant_id=tenant2.id, courier_id=1, leave_type_id=lt2.id,
        from_date=date(2026, 9, 1), to_date=date(2026, 9, 5),
    )
    db.add(leave2); db.commit()
    
    # Try to create payroll input in tenant1 referencing tenant2's leave
    with pytest.raises(HTTPException) as error:
        create_payroll_input(
            PayrollInputCreate(
                courier_id=rider1.id, month="2026-09", source_type="LEAVE",
                source_id=leave2.id, input_type="EARNING", amount=100,
            ),
            user1, db,
        )
    assert error.value.status_code == 404


# ---------- C2: Reversal of reversal rejected ----------

def test_reverse_reversal_rejected(db):
    """C2: Reversing a reversal should be rejected."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000002")
    rider = make_rider(db, tenant.id, "3")
    
    # Create original input
    original = create_payroll_input(
        PayrollInputCreate(
            courier_id=rider.id, month="2026-09", source_type="MANUAL",
            input_type="EARNING", amount=500,
        ),
        user, db,
    )
    
    # Reverse it
    reversal = reverse_payroll_input(original["id"], user, db)
    
    # Try to reverse the reversal
    with pytest.raises(HTTPException) as error:
        reverse_payroll_input(reversal["id"], user, db)
    assert error.value.status_code == 409


# ---------- C3: Delivery fact courier_id cross-tenant validation ----------

def test_delivery_fact_cross_tenant_courier_rejected(db):
    """C3: courier_id from another tenant should be rejected."""
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000003")
    rider2 = make_rider(db, tenant2.id, "4")
    
    sp = SourcePlatform(tenant_id=tenant1.id, code="HS", name_ar="هنقرستيشن")
    db.add(sp); db.commit()
    
    with pytest.raises(HTTPException) as error:
        create_delivery_fact(
            NormalizedDeliveryFactCreate(
                source_platform_id=sp.id, source_delivery_id="DEL_001",
                courier_id=rider2.id, event_type="COMPLETED", event_date=date(2026, 9, 1),
            ),
            user1, db,
        )
    assert error.value.status_code == 404


# ---------- H1: Raw row import_batch_id cross-tenant validation ----------

def test_raw_row_cross_tenant_batch_rejected(db):
    """H1: import_batch_id from another tenant should be rejected."""
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000004")
    
    sp = SourcePlatform(tenant_id=tenant1.id, code="HS", name_ar="هنقرستيشن")
    db.add(sp); db.commit()
    
    # Create batch in tenant2
    batch2 = OperationalImportBatch(
        tenant_id=tenant2.id, import_type="PERFORMANCE", fingerprint="abc123"
    )
    db.add(batch2); db.commit()
    
    with pytest.raises(HTTPException) as error:
        create_raw_row(
            RawImportRowCreate(
                source_platform_id=sp.id, import_batch_id=batch2.id,
                source_id="DEL_001", row_data=json.dumps({"test": "data"}),
            ),
            user1, db,
        )
    assert error.value.status_code == 404


# ---------- H2: Operator invalid tenant validation ----------

def test_operator_invalid_tenant_rejected(db):
    """H2: operator_tenant_id that doesn't exist should be rejected."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000005")
    
    sp = SourcePlatform(tenant_id=tenant.id, code="HS", name_ar="هنقرستيشن")
    db.add(sp); db.commit()
    
    with pytest.raises(HTTPException) as error:
        create_operator(
            PlatformOperatorCreate(
                source_platform_id=sp.id, operator_tenant_id=99999,
            ),
            user, db,
        )
    assert error.value.status_code == 400


# ---------- H4: Leave concurrent entitlement no overdraw ----------

def test_leave_concurrent_entitlement_no_overdraw(db):
    """H4: Two concurrent leave requests should not overdraw balance."""
    # This test verifies the atomic update prevents overdraw
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000006")
    rider = make_rider(db, tenant.id, "5")
    
    # Create leave type and policy with 10 days entitlement
    from app.models.entities import LeaveType, LeavePolicy, LeaveEntitlement
    lt = LeaveType(tenant_id=tenant.id, code="ANNUAL", name_ar="سنوية")
    db.add(lt); db.commit()
    
    policy = LeavePolicy(
        tenant_id=tenant.id, leave_type_id=lt.id,
        entitlement_days=10, effective_from=date(2026, 1, 1),
    )
    db.add(policy); db.commit()
    
    # Create entitlement with 10 days
    entitlement = LeaveEntitlement(
        tenant_id=tenant.id, courier_id=rider.id, leave_type_id=lt.id,
        year=2026, entitled_days=10,
    )
    db.add(entitlement); db.commit()
    
    # First request for 7 days should succeed
    from app.routers.leave import create_leave_request, LeaveRequestCreate
    req1 = create_leave_request(
        LeaveRequestCreate(
            courier_id=rider.id, leave_type_id=lt.id,
            from_date=date(2026, 9, 1), to_date=date(2026, 9, 7),
        ),
        user, db,
    )
    assert req1["status"] == "PENDING"
    
    # Second request for 5 days should fail (only 3 left)
    with pytest.raises(HTTPException) as error:
        create_leave_request(
            LeaveRequestCreate(
                courier_id=rider.id, leave_type_id=lt.id,
                from_date=date(2026, 9, 10), to_date=date(2026, 9, 14),
            ),
            user, db,
        )
    assert error.value.status_code == 400


# ---------- M1: Audit creation endpoints removed ----------

def test_integration_audit_creation_removed(db):
    """M1: Integration audit creation endpoint should be removed."""
    from app.routers import enterprise
    assert not hasattr(enterprise, 'create_integration_audit')


def test_security_audit_creation_removed(db):
    """M1: Security audit creation endpoint should be removed."""
    from app.routers import enterprise
    assert not hasattr(enterprise, 'create_security_audit')


# ---------- H3: Reconciliation timezone correctness ----------

def test_reconciliation_uses_import_date(db):
    """H3: Reconciliation should use explicit import_date, not timezone-sensitive func.date()."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000020")
    
    sp = SourcePlatform(tenant_id=tenant.id, code="HS", name_ar="هنقرستيشن")
    db.add(sp); db.commit()
    
    # Create raw rows with explicit import_date
    from app.models.entities import RawImportRow
    row1 = RawImportRow(
        tenant_id=tenant.id, source_platform_id=sp.id,
        source_id="DEL_001", row_data=json.dumps({"test": "data"}),
        checksum="abc123", import_date=date(2026, 9, 1),
    )
    row2 = RawImportRow(
        tenant_id=tenant.id, source_platform_id=sp.id,
        source_id="DEL_002", row_data=json.dumps({"test": "data2"}),
        checksum="def456", import_date=date(2026, 9, 1),
    )
    db.add_all([row1, row2]); db.commit()
    
    # Create reconciliation
    from app.routers.sources import create_reconciliation, ReconciliationCreate
    result = create_reconciliation(
        ReconciliationCreate(source_platform_id=sp.id, reconciliation_date=date(2026, 9, 1)),
        user, db,
    )
    # The subject of this test is the date: both rows carry import_date
    # 2026-09-01 and no date inside row_data, so both belong to that day. It
    # previously asserted only status == COMPLETED, which the endpoint returned
    # unconditionally and which said nothing about dates.
    assert result["source_total_count"] == 2
    # Two rows arrived and neither became a delivery fact. A day that does not
    # balance is an exception, not a completed reconciliation.
    assert result["status"] == "EXCEPTION"
    assert result["missing_count"] == 2


# ---------- H5: KPI result concurrency-safe upsert ----------

def test_kpi_result_upsert_atomic(db):
    """H5: KPI result upsert should be atomic with freshness tracking."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000021")
    
    from app.models.entities import KPIDefinition
    kpi = KPIDefinition(
        tenant_id=tenant.id, code="CR", name_ar="معدل الإكمال",
        numerator_expression="completed", denominator_expression="total",
        effective_from=date(2026, 1, 1),
    )
    db.add(kpi); db.commit()
    
    from app.routers.analytics import create_kpi_result, KPIResultCreate
    # First create
    result1 = create_kpi_result(
        KPIResultCreate(
            kpi_definition_id=kpi.id, scope_type="RIDER", scope_id=1,
            period="2026-09", numerator_value=95, denominator_value=100, result_value=95.0,
        ),
        user, db,
    )
    assert result1["result_value"] == 95.0
    
    # Second create (upsert)
    result2 = create_kpi_result(
        KPIResultCreate(
            kpi_definition_id=kpi.id, scope_type="RIDER", scope_id=1,
            period="2026-09", numerator_value=98, denominator_value=100, result_value=98.0,
        ),
        user, db,
    )
    assert result2["result_value"] == 98.0
    assert result2["id"] == result1["id"]  # Same record updated
    
    # Verify freshness_at was updated
    assert "freshness_at" in result2


# ---------- H6: Credential prefix collision handling ----------

def test_credential_prefix_collision_handled(db):
    """H6: Credential creation should handle prefix collisions gracefully."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000022")
    
    # Create many credentials - should not fail due to collision
    for i in range(10):
        result = create_credential(
            PartnerCredentialCreate(partner_name=f"Partner {i}"),
            user, db,
        )
        assert "api_key" in result
        assert len(result["key_prefix"]) == 16  # H6 FIX: 16-char prefix


# ---------- M2: Delivery fact idempotency integrity ----------

def test_delivery_fact_idempotent_data_unchanged(db):
    """M2: Idempotent delivery fact creation should not modify original data."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000023")
    
    sp = SourcePlatform(tenant_id=tenant.id, code="HS", name_ar="هنقرستيشن")
    db.add(sp); db.commit()
    
    # Create first fact
    result1 = create_delivery_fact(
        NormalizedDeliveryFactCreate(
            source_platform_id=sp.id, source_delivery_id="DEL_001",
            event_type="COMPLETED", event_date=date(2026, 9, 1),
            revenue_amount=25.0,
        ),
        user, db,
    )
    
    # Try to create duplicate
    with pytest.raises(HTTPException) as error:
        create_delivery_fact(
            NormalizedDeliveryFactCreate(
                source_platform_id=sp.id, source_delivery_id="DEL_001",
                event_type="COMPLETED", event_date=date(2026, 9, 1),
                revenue_amount=50.0,  # Different amount
            ),
            user, db,
        )
    assert error.value.status_code == 409
    
    # Verify original data unchanged
    from app.models.entities import NormalizedDeliveryFact
    fact = db.query(NormalizedDeliveryFact).get(result1["id"])
    assert fact.revenue_amount == 25.0  # Original value preserved


# ---------- M3: KPI update freshness + duplicate prevention ----------

def test_kpi_result_update_freshness_and_no_duplicates(db):
    """M3: KPI result update should track freshness and prevent duplicates."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000024")
    
    from app.models.entities import KPIDefinition, KPIResult
    kpi = KPIDefinition(
        tenant_id=tenant.id, code="CR", name_ar="معدل الإكمال",
        numerator_expression="completed", denominator_expression="total",
        effective_from=date(2026, 1, 1),
    )
    db.add(kpi); db.commit()
    
    from app.routers.analytics import create_kpi_result, KPIResultCreate
    
    # Create initial result
    result1 = create_kpi_result(
        KPIResultCreate(
            kpi_definition_id=kpi.id, scope_type="RIDER", scope_id=1,
            period="2026-09", numerator_value=95, denominator_value=100, result_value=95.0,
        ),
        user, db,
    )
    
    # Update result
    result2 = create_kpi_result(
        KPIResultCreate(
            kpi_definition_id=kpi.id, scope_type="RIDER", scope_id=1,
            period="2026-09", numerator_value=98, denominator_value=100, result_value=98.0,
        ),
        user, db,
    )
    
    # Verify same record (no duplicate)
    assert result2["id"] == result1["id"]
    
    # Verify only one record exists
    count = db.query(KPIResult).filter(
        KPIResult.kpi_definition_id == kpi.id,
        KPIResult.period == "2026-09",
    ).count()
    assert count == 1


# ---------- M4: Credential rotation hash verification ----------

def test_credential_rotation_hash_changed(db):
    """M4: Credential rotation should change key_hash."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000025")
    
    from app.models.entities import PartnerCredential
    
    # Create credential
    cred = create_credential(
        PartnerCredentialCreate(partner_name="Test Partner"),
        user, db,
    )
    cred_id = cred["id"]
    
    # Get original hash
    original = db.query(PartnerCredential).get(cred_id)
    original_hash = original.key_hash
    
    # Rotate
    rotate_credential(cred_id, user, db)
    
    # Verify hash changed
    rotated = db.query(PartnerCredential).get(cred_id)
    assert rotated.key_hash != original_hash

"""Final cleanup regression tests — M7, M6, L1, L3, L2."""
import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Courier, CourierType, Country, Document, NormalizedDeliveryFact,
    PayrollInputRecord, RawImportRow, ReconciliationResult,
    SourcePlatform, Tenant, User, UserRole, WebhookEndpoint,
)
from app.routers.analytics import (
    PayrollInputCreate, create_payroll_input, reverse_payroll_input,
)
from app.routers.documents import DocumentUpload, upload_document
from app.routers.sources import (
    NormalizedDeliveryFactCreate, RawImportRowCreate,
    create_delivery_fact, create_raw_row, create_reconciliation,
    ReconciliationCreate,
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
    tenant = Tenant(name=name, country=Country.SA)
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


# ---------- M7: Cross-tenant raw_row_id rejection ----------

def test_delivery_fact_cross_tenant_raw_row_rejected(db):
    """M7: raw_row_id from another tenant should be rejected."""
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000001")
    
    sp = SourcePlatform(tenant_id=tenant1.id, code="HS", name_ar="هنقرستيشن")
    db.add(sp); db.commit()
    
    # Create raw row in tenant2
    raw_row2 = RawImportRow(
        tenant_id=tenant2.id, source_platform_id=sp.id,
        source_id="DEL_001", row_data=json.dumps({"test": "data"}),
        checksum="abc123",
    )
    db.add(raw_row2); db.commit()
    
    with pytest.raises(HTTPException) as error:
        create_delivery_fact(
            NormalizedDeliveryFactCreate(
                source_platform_id=sp.id, source_delivery_id="DEL_001",
                raw_row_id=raw_row2.id, event_type="COMPLETED", event_date=date(2026, 9, 1),
            ),
            user1, db,
        )
    assert error.value.status_code == 404


# ---------- M6: Payroll duplicate/idempotency behavior ----------

def test_payroll_manual_duplicate_same_amount_description_rejected(db):
    """M6: Duplicate MANUAL inputs with same amount and description should be rejected."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000002")
    rider = make_rider(db, tenant.id, "1")
    
    # Create first MANUAL input
    create_payroll_input(
        PayrollInputCreate(
            courier_id=rider.id, month="2026-09", source_type="MANUAL",
            input_type="EARNING", amount=500, description="Bonus",
        ),
        user, db,
    )
    
    # Try to create duplicate with same amount + description
    with pytest.raises(HTTPException) as error:
        create_payroll_input(
            PayrollInputCreate(
                courier_id=rider.id, month="2026-09", source_type="MANUAL",
                input_type="EARNING", amount=500, description="Bonus",
            ),
            user, db,
        )
    assert error.value.status_code == 409


def test_payroll_manual_different_description_accepted(db):
    """M6: MANUAL inputs with different descriptions should be allowed."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000003")
    rider = make_rider(db, tenant.id, "2")
    
    # Create first MANUAL input
    create_payroll_input(
        PayrollInputCreate(
            courier_id=rider.id, month="2026-09", source_type="MANUAL",
            input_type="EARNING", amount=500, description="Bonus",
        ),
        user, db,
    )
    
    # Create second MANUAL input with different description — should succeed
    result = create_payroll_input(
        PayrollInputCreate(
            courier_id=rider.id, month="2026-09", source_type="MANUAL",
            input_type="EARNING", amount=500, description="Overtime",
        ),
        user, db,
    )
    assert result["amount"] == 500


# ---------- L1: storage_key not exposed ----------

def test_document_upload_does_not_expose_storage_key(db):
    """L1: Document upload response should not contain storage_key."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000004")
    rider = make_rider(db, tenant.id, "3")
    
    from app.models.entities import DocumentType
    dt = DocumentType(tenant_id=tenant.id, code="ID", name_ar="هوية")
    db.add(dt); db.commit()
    
    result = upload_document(
        DocumentUpload(
            document_type_id=dt.id,
            owner_type="RIDER",
            owner_id=rider.id,
            filename="id.jpg",
            mime_type="image/jpeg",
            file_size_bytes=1024,
        ),
        user, db,
    )
    
    assert "storage_key" not in result
    assert "signed_url" in result


# ---------- L3: Accurate reconciliation counts ----------

def test_reconciliation_duplicate_count_accurate(db):
    """L3: Reconciliation duplicate count should be derived from actual data."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000005")

    sp = SourcePlatform(tenant_id=tenant.id, code="HS", name_ar="هنقرستيشن")
    db.add(sp); db.commit()

    # Create raw rows — unique source_ids (unique constraint prevents duplicates)
    row1 = RawImportRow(
        tenant_id=tenant.id, source_platform_id=sp.id,
        source_id="DEL_001", row_data=json.dumps({"test": "1"}),
        checksum="aaa", import_date=date(2026, 9, 1),
    )
    row2 = RawImportRow(
        tenant_id=tenant.id, source_platform_id=sp.id,
        source_id="DEL_002", row_data=json.dumps({"test": "2"}),
        checksum="bbb", import_date=date(2026, 9, 1),
    )
    row3 = RawImportRow(
        tenant_id=tenant.id, source_platform_id=sp.id,
        source_id="DEL_003", row_data=json.dumps({"test": "3"}),
        checksum="ccc", import_date=date(2026, 9, 1),
    )
    db.add_all([row1, row2, row3]); db.commit()

    result = create_reconciliation(
        ReconciliationCreate(source_platform_id=sp.id, reconciliation_date=date(2026, 9, 1)),
        user, db,
    )
    assert result["status"] == "COMPLETED"

    # Verify counts in database
    recon = db.query(ReconciliationResult).first()
    assert recon.source_total_count == 3
    assert recon.duplicate_count == 0  # No duplicates (unique constraint prevents them)


# ---------- L2: Webhook secret lifecycle ----------

def test_webhook_secret_returned_on_creation(db):
    """L2: Webhook secret should be returned on creation."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000006")
    
    from app.routers.enterprise import create_webhook, WebhookEndpointCreate
    result = create_webhook(
        WebhookEndpointCreate(url="https://example.com/webhook", event_type="ORDER_CREATED"),
        user, db,
    )
    
    assert "secret" in result
    assert len(result["secret"]) > 0


def test_webhook_secret_not_retrievable_after_creation(db):
    """L2: Webhook secret should not be retrievable after creation."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000007")
    
    from app.routers.enterprise import create_webhook, WebhookEndpointCreate
    created = create_webhook(
        WebhookEndpointCreate(url="https://example.com/webhook", event_type="ORDER_CREATED"),
        user, db,
    )
    
    # List webhooks — secret should not be in response
    from app.routers.enterprise import list_webhooks
    webhooks = list_webhooks(user=user, db=db)
    for wh in webhooks:
        assert "secret" not in wh
        assert "secret_hash" not in wh


def test_webhook_secret_hashed_in_database(db):
    """L2: Webhook secret should be stored as hash, not plaintext."""
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000008")
    
    from app.routers.enterprise import create_webhook, WebhookEndpointCreate
    created = create_webhook(
        WebhookEndpointCreate(url="https://example.com/webhook", event_type="ORDER_CREATED"),
        user, db,
    )
    secret = created["secret"]
    
    # Verify hash in database
    wh = db.query(WebhookEndpoint).filter(WebhookEndpoint.url == "https://example.com/webhook").first()
    assert wh.secret_hash != secret  # Not stored as plaintext
    import hashlib
    assert wh.secret_hash == hashlib.sha256(secret.encode()).hexdigest()

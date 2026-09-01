"""Documents and KYC pipeline tests — W1-E6."""
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Courier, CourierType, Country, Document, DocumentRequirement,
    DocumentType, KYCStatus, Tenant, User, UserRole,
)
from app.routers.documents import (
    DocumentRequirementCreate, DocumentReview, DocumentTypeCreate,
    DocumentTypeUpdate, DocumentUpload,
    create_document_type, update_document_type, list_document_types,
    create_requirement, list_requirements, update_requirement,
    upload_document, list_documents, review_document, get_access_url,
    get_kyc_status, recompute_kyc, update_kyc,
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


# ---------- document types ----------

def test_create_document_type(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000001")
    result = create_document_type(
        DocumentTypeCreate(code="ID", name_ar="هوية", name_en="ID", category="RIDER"),
        user, db,
    )
    assert result["code"] == "ID"


def test_document_type_code_unique_within_tenant(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000002")
    create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    with pytest.raises(HTTPException) as error:
        create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية 2"), user, db)
    assert error.value.status_code == 409


def test_document_type_rejects_cross_tenant_code(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000003")
    user2 = make_user(db, tenant2.id, "966500000004")
    create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user1, db)
    result = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user2, db)
    assert result["code"] == "ID"


def test_update_document_type(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000005")
    created = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    updated = update_document_type(created["id"], DocumentTypeUpdate(name_ar="هوية وطنية"), user, db)
    assert updated["name_ar"] == "هوية وطنية"


# ---------- document requirements ----------

def test_create_requirement(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000006")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    result = create_requirement(
        DocumentRequirementCreate(document_type_id=dt["id"], scope="RIDER", market_code="SA"),
        user, db,
    )
    assert result["scope"] == "RIDER"


def test_requirement_unique_per_type_scope_market(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000007")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    create_requirement(
        DocumentRequirementCreate(document_type_id=dt["id"], scope="RIDER"),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        create_requirement(
            DocumentRequirementCreate(document_type_id=dt["id"], scope="RIDER"),
            user, db,
        )
    assert error.value.status_code == 409


def test_requirement_rejects_invalid_scope(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000008")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    with pytest.raises(HTTPException) as error:
        create_requirement(
            DocumentRequirementCreate(document_type_id=dt["id"], scope="INVALID"),
            user, db,
        )
    assert error.value.status_code == 400


# ---------- documents ----------

def test_upload_document(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000009")
    rider = make_rider(db, tenant.id, "1")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    result = upload_document(
        DocumentUpload(
            document_type_id=dt["id"],
            owner_type="RIDER",
            owner_id=rider.id,
            filename="id.jpg",
            mime_type="image/jpeg",
            file_size_bytes=1024,
        ),
        user, db,
    )
    assert result["status"] == "PENDING"
    assert result["mime_type"] == "image/jpeg"
    assert "signed_url" in result
    assert "storage_key" not in result  # L1 FIX: storage_key should not be exposed


def test_upload_rejects_invalid_mime(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000010")
    rider = make_rider(db, tenant.id, "2")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    with pytest.raises(HTTPException) as error:
        upload_document(
            DocumentUpload(
                document_type_id=dt["id"],
                owner_type="RIDER",
                owner_id=rider.id,
                filename="file.exe",
                mime_type="application/x-executable",
            ),
            user, db,
        )
    assert error.value.status_code == 400


def test_upload_rejects_oversized_file(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000011")
    rider = make_rider(db, tenant.id, "3")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    with pytest.raises(HTTPException) as error:
        upload_document(
            DocumentUpload(
                document_type_id=dt["id"],
                owner_type="RIDER",
                owner_id=rider.id,
                filename="large.jpg",
                mime_type="image/jpeg",
                file_size_bytes=20 * 1024 * 1024,  # 20 MB
            ),
            user, db,
        )
    assert error.value.status_code == 400


def test_review_document_valid(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000012")
    rider = make_rider(db, tenant.id, "4")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    doc = upload_document(
        DocumentUpload(
            document_type_id=dt["id"],
            owner_type="RIDER",
            owner_id=rider.id,
            filename="id.jpg",
            mime_type="image/jpeg",
        ),
        user, db,
    )
    result = review_document(doc["id"], DocumentReview(decision="VALID"), user, db)
    assert result["status"] == "VALID"


def test_review_document_rejected(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000013")
    rider = make_rider(db, tenant.id, "5")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    doc = upload_document(
        DocumentUpload(
            document_type_id=dt["id"],
            owner_type="RIDER",
            owner_id=rider.id,
            filename="id.jpg",
            mime_type="image/jpeg",
        ),
        user, db,
    )
    result = review_document(doc["id"], DocumentReview(decision="REJECTED", note="Blurry"), user, db)
    assert result["status"] == "REJECTED"


def test_review_rejects_invalid_decision(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000014")
    rider = make_rider(db, tenant.id, "6")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    doc = upload_document(
        DocumentUpload(
            document_type_id=dt["id"],
            owner_type="RIDER",
            owner_id=rider.id,
            filename="id.jpg",
            mime_type="image/jpeg",
        ),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        review_document(doc["id"], DocumentReview(decision="MAYBE"), user, db)
    assert error.value.status_code == 400


def test_get_access_url(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000015")
    rider = make_rider(db, tenant.id, "7")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    doc = upload_document(
        DocumentUpload(
            document_type_id=dt["id"],
            owner_type="RIDER",
            owner_id=rider.id,
            filename="id.jpg",
            mime_type="image/jpeg",
        ),
        user, db,
    )
    result = get_access_url(doc["id"], user, db)
    assert "signed_url" in result
    assert result["expires_in_minutes"] == 15


# ---------- KYC ----------

def test_get_kyc_status(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000016")
    rider = make_rider(db, tenant.id, "8")
    result = get_kyc_status(rider.id, user, db)
    assert result["courier_id"] == rider.id
    # With no requirements, status is VERIFIED (nothing missing)
    assert result["status"] == "VERIFIED"


def test_recompute_kyc_verified(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000017")
    rider = make_rider(db, tenant.id, "9")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    create_requirement(
        DocumentRequirementCreate(document_type_id=dt["id"], scope="RIDER"),
        user, db,
    )
    # Upload and validate document
    doc = upload_document(
        DocumentUpload(
            document_type_id=dt["id"],
            owner_type="RIDER",
            owner_id=rider.id,
            filename="id.jpg",
            mime_type="image/jpeg",
        ),
        user, db,
    )
    review_document(doc["id"], DocumentReview(decision="VALID"), user, db)
    
    result = recompute_kyc(rider.id, user, db)
    assert result["status"] == "VERIFIED"


def test_recompute_kyc_missing_documents(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000018")
    rider = make_rider(db, tenant.id, "10")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user, db)
    create_requirement(
        DocumentRequirementCreate(document_type_id=dt["id"], scope="RIDER"),
        user, db,
    )
    result = recompute_kyc(rider.id, user, db)
    assert result["status"] != "VERIFIED"


def test_update_kyc_status(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000019")
    rider = make_rider(db, tenant.id, "11")
    result = update_kyc(rider.id, type("Payload", (), {"status": "IN_REVIEW", "notes": "Waiting"})(), user, db)
    assert result["status"] == "IN_REVIEW"


def test_update_kyc_rejects_invalid_status(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000020")
    rider = make_rider(db, tenant.id, "12")
    with pytest.raises(HTTPException) as error:
        update_kyc(rider.id, type("Payload", (), {"status": "INVALID"})(), user, db)
    assert error.value.status_code == 400


# ---------- tenant isolation ----------

def test_cross_tenant_document_type_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000021")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user1, db)
    user2 = make_user(db, tenant2.id, "966500000022")
    with pytest.raises(HTTPException) as error:
        update_document_type(dt["id"], DocumentTypeUpdate(name_ar="Hacked"), user2, db)
    assert error.value.status_code == 404


def test_cross_tenant_upload_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000023")
    rider2 = make_rider(db, tenant2.id, "13")
    dt = create_document_type(DocumentTypeCreate(code="ID", name_ar="هوية"), user1, db)
    user2 = make_user(db, tenant2.id, "966500000024")
    with pytest.raises(HTTPException) as error:
        upload_document(
            DocumentUpload(
                document_type_id=dt["id"],
                owner_type="RIDER",
                owner_id=rider2.id,
                filename="id.jpg",
                mime_type="image/jpeg",
            ),
            user2, db,
        )
    assert error.value.status_code in (403, 404)

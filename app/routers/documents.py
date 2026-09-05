"""Documents and KYC pipeline — W1-E6."""

import json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from ..database import get_db
from ..models import entities as ent
from .auth import get_current_user

router = APIRouter(prefix="/documents", tags=["documents"])

MANAGE_ROLES = {
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.OPERATIONS,
    ent.UserRole.HR,
}
STAFF_ROLES = MANAGE_ROLES | {ent.UserRole.SUPERVISOR}
READ_ROLES = STAFF_ROLES | {
    ent.UserRole.ACCOUNTANT,
    ent.UserRole.VIEWER,
    ent.UserRole.PROJECT_MANAGER,
}

# Allowed MIME types for upload validation
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "application/pdf",
    "text/plain",
}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


# ---------- helpers ----------


def _tenant_id(user: ent.User, manage: bool = False) -> int:
    allowed = MANAGE_ROLES if manage else READ_ROLES
    if user.role not in allowed or not user.tenant_id:
        raise HTTPException(403, "Document access required")
    return user.tenant_id


def _same_tenant(db, model, record_id: int, tenant_id: int):
    row = (
        db.query(model)
        .filter(model.id == record_id, model.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(404, f"{model.__name__} not found")
    return row


def _validate_mime_type(mime_type: str) -> None:
    """Validate MIME type is allowed."""
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            400,
            f"MIME type not allowed: {mime_type}. Allowed: {', '.join(sorted(ALLOWED_MIME_TYPES))}",
        )


def _validate_file_size(size_bytes: int) -> None:
    """Validate file size is within limits."""
    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            400, f"File too large: {size_bytes} bytes. Max: {MAX_FILE_SIZE_BYTES} bytes"
        )


def _generate_storage_key(
    tenant_id: int, owner_type: str, owner_id: int, filename: str
) -> str:
    """Generate a unique storage key for external storage."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    return f"tenants/{tenant_id}/{owner_type.lower()}s/{owner_id}/{timestamp}_{safe_filename}"


def _generate_signed_url(storage_key: str, expires_minutes: int = 15) -> str:
    """Generate a signed access URL (placeholder for actual signed URL logic)."""
    # In production, this would generate a signed URL for S3/GCS
    expiry = datetime.utcnow() + timedelta(minutes=expires_minutes)
    return f"https://storage.dou.app/{storage_key}?expires={expiry.timestamp()}"


def _recompute_kyc_status(db, tenant_id: int, courier_id: int) -> ent.KYCStatus:
    """Recompute KYC status based on document requirements and submissions."""
    # Get all mandatory requirements for riders in this tenant
    requirements = (
        db.query(ent.DocumentRequirement)
        .filter(
            ent.DocumentRequirement.tenant_id == tenant_id,
            ent.DocumentRequirement.scope == "RIDER",
            ent.DocumentRequirement.is_active.is_(True),
            ent.DocumentRequirement.is_mandatory.is_(True),
        )
        .all()
    )

    missing = []
    for req in requirements:
        # Check if there's a valid document for this requirement
        doc = (
            db.query(ent.Document)
            .filter(
                ent.Document.tenant_id == tenant_id,
                ent.Document.document_type_id == req.document_type_id,
                ent.Document.owner_type == "RIDER",
                ent.Document.owner_id == courier_id,
                ent.Document.status == "VALID",
            )
            .first()
        )
        if not doc:
            doc_type = db.query(ent.DocumentType).get(req.document_type_id)
            if doc_type:
                missing.append(doc_type.code)

    # Get or create KYC status
    kyc = (
        db.query(ent.KYCStatus)
        .filter(
            ent.KYCStatus.tenant_id == tenant_id,
            ent.KYCStatus.courier_id == courier_id,
        )
        .first()
    )

    if not kyc:
        kyc = ent.KYCStatus(tenant_id=tenant_id, courier_id=courier_id)
        db.add(kyc)

    kyc.missing_documents = json.dumps(missing) if missing else None

    if not missing:
        kyc.status = "VERIFIED"
        kyc.verified_at = datetime.utcnow()
    elif kyc.status == "VERIFIED":
        # Was verified but now missing something
        kyc.status = "IN_REVIEW"
        kyc.verified_at = None
        kyc.verified_by = None

    db.flush()
    return kyc


# ---------- schemas ----------


class DocumentTypeCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name_ar: str
    name_en: Optional[str] = None
    description_ar: Optional[str] = None
    description_en: Optional[str] = None
    category: str = "RIDER"
    requires_expiry: bool = True


class DocumentTypeUpdate(BaseModel):
    name_ar: Optional[str] = None
    name_en: Optional[str] = None
    description_ar: Optional[str] = None
    description_en: Optional[str] = None
    category: Optional[str] = None
    requires_expiry: Optional[bool] = None
    is_active: Optional[bool] = None


class DocumentRequirementCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    document_type_id: int
    scope: str  # RIDER / VEHICLE
    market_code: str = "SA"
    is_mandatory: bool = True


class DocumentRequirementUpdate(BaseModel):
    is_mandatory: Optional[bool] = None
    is_active: Optional[bool] = None


class DocumentUpload(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    document_type_id: int
    owner_type: str  # RIDER / VEHICLE
    owner_id: int
    filename: str
    mime_type: str
    file_size_bytes: int = 0
    checksum_sha256: Optional[str] = None
    expiry_date: Optional[date] = None


class DocumentReview(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    decision: str  # VALID / REJECTED
    review_note: Optional[str] = None


class KYCUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status: Optional[str] = None
    notes: Optional[str] = None


# ---------- document types ----------


@router.post("/types", status_code=201)
def create_document_type(
    payload: DocumentTypeCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    existing = (
        db.query(ent.DocumentType)
        .filter(
            ent.DocumentType.tenant_id == tenant_id,
            ent.DocumentType.code == payload.code,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Document type code already exists")
    row = ent.DocumentType(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


@router.get("/types")
def list_document_types(
    active_only: bool = Query(True),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.DocumentType).filter(ent.DocumentType.tenant_id == tenant_id)
    if active_only:
        q = q.filter(ent.DocumentType.is_active.is_(True))
    return [
        {
            "id": r.id,
            "code": r.code,
            "name_ar": r.name_ar,
            "name_en": r.name_en,
            "category": r.category,
            "requires_expiry": r.requires_expiry,
        }
        for r in q.order_by(ent.DocumentType.code).all()
    ]


@router.patch("/types/{type_id}")
def update_document_type(
    type_id: int,
    payload: DocumentTypeUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.DocumentType, type_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


# ---------- document requirements ----------


@router.post("/requirements", status_code=201)
def create_requirement(
    payload: DocumentRequirementCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.DocumentType, payload.document_type_id, tenant_id)
    if payload.scope not in ("RIDER", "VEHICLE"):
        raise HTTPException(400, "scope must be RIDER or VEHICLE")
    existing = (
        db.query(ent.DocumentRequirement)
        .filter(
            ent.DocumentRequirement.tenant_id == tenant_id,
            ent.DocumentRequirement.document_type_id == payload.document_type_id,
            ent.DocumentRequirement.scope == payload.scope,
            ent.DocumentRequirement.market_code == payload.market_code,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Document requirement already exists")
    row = ent.DocumentRequirement(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "document_type_id": row.document_type_id, "scope": row.scope}


@router.get("/requirements")
def list_requirements(
    scope: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.DocumentRequirement).filter(
        ent.DocumentRequirement.tenant_id == tenant_id
    )
    if scope:
        q = q.filter(ent.DocumentRequirement.scope == scope)
    return [
        {
            "id": r.id,
            "document_type_id": r.document_type_id,
            "scope": r.scope,
            "market_code": r.market_code,
            "is_mandatory": r.is_mandatory,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.DocumentRequirement.id).all()
    ]


@router.patch("/requirements/{req_id}")
def update_requirement(
    req_id: int,
    payload: DocumentRequirementUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.DocumentRequirement, req_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "document_type_id": row.document_type_id, "scope": row.scope}


# ---------- documents ----------


@router.post("/upload", status_code=201)
def upload_document(
    payload: DocumentUpload,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Upload a document — metadata only, binary stored externally."""
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.DocumentType, payload.document_type_id, tenant_id)

    # Validate owner exists
    if payload.owner_type == "RIDER":
        _same_tenant(db, ent.Courier, payload.owner_id, tenant_id)
    elif payload.owner_type == "VEHICLE":
        _same_tenant(db, ent.Vehicle, payload.owner_id, tenant_id)
    else:
        raise HTTPException(400, "owner_type must be RIDER or VEHICLE")

    # Validate MIME type and file size
    _validate_mime_type(payload.mime_type)
    _validate_file_size(payload.file_size_bytes)

    # Generate storage key (external storage reference)
    storage_key = _generate_storage_key(
        tenant_id, payload.owner_type, payload.owner_id, payload.filename
    )

    row = ent.Document(
        tenant_id=tenant_id,
        document_type_id=payload.document_type_id,
        owner_type=payload.owner_type,
        owner_id=payload.owner_id,
        filename=payload.filename,
        mime_type=payload.mime_type,
        file_size_bytes=payload.file_size_bytes,
        storage_key=storage_key,
        checksum_sha256=payload.checksum_sha256,
        expiry_date=payload.expiry_date,
        uploaded_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # Generate signed URL for access
    signed_url = _generate_signed_url(storage_key)

    return {
        "id": row.id,
        "document_type_id": row.document_type_id,
        "owner_type": row.owner_type,
        "owner_id": row.owner_id,
        "filename": row.filename,
        "mime_type": row.mime_type,
        "status": row.status,
        "signed_url": signed_url,
    }


@router.get("/{owner_type}/{owner_id}")
def list_documents(
    owner_type: str,
    owner_id: int,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    owner_types = (
        ["RIDER", "COURIER"]
        if owner_type.upper() in ("RIDER", "COURIER")
        else [owner_type.upper()]
    )
    q = db.query(ent.Document).filter(
        ent.Document.tenant_id == tenant_id,
        ent.Document.owner_type.in_(owner_types),
        ent.Document.owner_id == owner_id,
    )
    return [
        {
            "id": r.id,
            "document_type_id": r.document_type_id,
            "filename": r.filename,
            "mime_type": r.mime_type,
            "file_size_bytes": r.file_size_bytes,
            "expiry_date": r.expiry_date.isoformat() if r.expiry_date else None,
            "status": r.status,
            "scan_status": r.scan_status,
            "created_at": r.created_at.isoformat(),
        }
        for r in q.order_by(ent.Document.created_at.desc()).all()
    ]


@router.post("/{document_id}/review", status_code=200)
def review_document(
    document_id: int,
    payload: DocumentReview,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.Document, document_id, tenant_id)
    if payload.decision not in ("VALID", "REJECTED"):
        raise HTTPException(400, "decision must be VALID or REJECTED")

    row.status = payload.decision
    row.reviewed_by = user.id
    row.reviewed_at = datetime.utcnow()
    row.review_note = payload.review_note

    # If rejected, set scan status
    if payload.decision == "REJECTED":
        row.scan_status = "REJECTED"

    db.commit()

    # Recompute KYC status if this is a rider document
    if row.owner_type in ("RIDER", "COURIER"):
        _recompute_kyc_status(db, tenant_id, row.owner_id)

    db.commit()
    db.refresh(row)
    return {"id": row.id, "status": row.status, "reviewed_by": row.reviewed_by}


@router.get("/{document_id}/access-url", status_code=200)
def get_access_url(
    document_id: int, user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    """Get a signed access URL for a document."""
    tenant_id = _tenant_id(user)
    row = _same_tenant(db, ent.Document, document_id, tenant_id)

    # Only allow access to valid documents
    if row.status not in ("VALID", "PENDING"):
        raise HTTPException(404, "Document not available")

    signed_url = _generate_signed_url(row.storage_key)
    return {"document_id": row.id, "signed_url": signed_url, "expires_in_minutes": 15}


# ---------- KYC ----------


@router.get("/kyc/{courier_id}")
def get_kyc_status(
    courier_id: int, user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    tenant_id = _tenant_id(user)
    _same_tenant(db, ent.Courier, courier_id, tenant_id)

    kyc = (
        db.query(ent.KYCStatus)
        .filter(
            ent.KYCStatus.tenant_id == tenant_id,
            ent.KYCStatus.courier_id == courier_id,
        )
        .first()
    )

    if not kyc:
        # Compute on the fly without persisting to DB on GET
        kyc = _recompute_kyc_status(db, tenant_id, courier_id)

    missing = json.loads(kyc.missing_documents) if kyc.missing_documents else []

    return {
        "courier_id": kyc.courier_id,
        "status": kyc.status,
        "missing_documents": missing,
        "notes": kyc.notes,
        "verified_by": kyc.verified_by,
        "verified_at": kyc.verified_at.isoformat() if kyc.verified_at else None,
    }


@router.post("/kyc/{courier_id}/recompute", status_code=200)
def recompute_kyc(
    courier_id: int, user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    """Recompute KYC status for a courier."""
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.Courier, courier_id, tenant_id)
    kyc = _recompute_kyc_status(db, tenant_id, courier_id)
    db.commit()
    return {"courier_id": kyc.courier_id, "status": kyc.status}


@router.patch("/kyc/{courier_id}")
def update_kyc(
    courier_id: int,
    payload: KYCUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Update KYC status (manual override)."""
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.Courier, courier_id, tenant_id)

    kyc = (
        db.query(ent.KYCStatus)
        .filter(
            ent.KYCStatus.tenant_id == tenant_id,
            ent.KYCStatus.courier_id == courier_id,
        )
        .first()
    )

    if not kyc:
        kyc = ent.KYCStatus(tenant_id=tenant_id, courier_id=courier_id)
        db.add(kyc)

    if payload.status:
        if payload.status not in ("PENDING", "IN_REVIEW", "VERIFIED", "REJECTED"):
            raise HTTPException(400, "Invalid status")
        kyc.status = payload.status
        if payload.status == "VERIFIED":
            kyc.verified_by = user.id
            kyc.verified_at = datetime.utcnow()

    if payload.notes is not None:
        kyc.notes = payload.notes

    db.commit()
    db.refresh(kyc)
    return {"courier_id": kyc.courier_id, "status": kyc.status}

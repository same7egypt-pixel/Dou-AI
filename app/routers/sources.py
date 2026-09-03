"""Wave 2 router — source platforms, raw ingestion, rider mapping, delivery facts, reconciliation."""

import hashlib
import json
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func

from ..database import get_db
from ..models import entities as ent
from ..services.entitlements import require_capability
from ..services.ingestion import normalize_row, reprocess_rows
from .auth import get_current_user

router = APIRouter(prefix="/sources", tags=["sources"])

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


def _tenant_id(user: ent.User, db=None, manage: bool = False) -> int:
    """The tenant whose ingestion pipeline this user may reach.

    Role was the only check on all seventeen endpoints here, so an account that
    buys no API feed at all could still create source platforms, connections,
    identity mappings, raw rows and delivery facts — and a delivery fact is what
    payroll pays on. The same defect as payroll and vendor settlements: the
    capability existed and nothing read it. `db` is optional so a caller that
    only needs the role check does not have to change shape.
    """
    allowed = MANAGE_ROLES if manage else READ_ROLES
    if user.role not in allowed or not user.tenant_id:
        raise HTTPException(403, "Source access required")
    if db is not None:
        require_capability(
            db, user, ent.Capability.PERFORMANCE_API_INGESTION.value
        )
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


# ---------- schemas ----------


class SourcePlatformCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name_ar: str
    name_en: Optional[str] = None
    description: Optional[str] = None


class SourcePlatformUpdate(BaseModel):
    name_ar: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class TenantConnectionCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source_platform_id: int
    connection_name: str
    import_frequency: str = "DAILY"
    credential_reference: Optional[str] = None


class TenantConnectionUpdate(BaseModel):
    connection_name: Optional[str] = None
    import_frequency: Optional[str] = None
    credential_reference: Optional[str] = None
    is_active: Optional[bool] = None


class ProjectContractMappingCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source_platform_id: int
    project_id: int
    contract_id: Optional[int] = None


class RiderIdentityMappingCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source_platform_id: int
    source_rider_id: str
    courier_id: int
    match_method: str = "MANUAL"
    confidence: float = 1.0
    effective_from: date


class RiderIdentityMappingUpdate(BaseModel):
    match_method: Optional[str] = None
    confidence: Optional[float] = None
    status: Optional[str] = None
    effective_to: Optional[date] = None


class RawImportRowCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source_platform_id: int
    import_batch_id: Optional[int] = None
    source_id: str
    row_data: str  # JSON string
    schema_version: str = "1.0"
    source_timestamp: Optional[datetime] = None


class NormalizedDeliveryFactCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source_platform_id: int
    source_delivery_id: str
    raw_row_id: Optional[int] = None
    courier_id: Optional[int] = None
    project_id: Optional[int] = None
    contract_branch_id: Optional[int] = None
    team_id: Optional[int] = None
    event_type: str
    event_date: date
    event_timestamp: Optional[datetime] = None
    distance_km: Optional[float] = None
    revenue_amount: Optional[float] = None
    cost_amount: Optional[float] = None
    currency: str = "SAR"


class ReconciliationCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source_platform_id: int
    reconciliation_date: date


# ---------- source platforms ----------


@router.post("/platforms", status_code=201)
def create_source_platform(
    payload: SourcePlatformCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db, manage=True)
    existing = (
        db.query(ent.SourcePlatform)
        .filter(
            ent.SourcePlatform.tenant_id == tenant_id,
            ent.SourcePlatform.code == payload.code,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Source platform code already exists")
    row = ent.SourcePlatform(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


@router.get("/platforms")
def list_source_platforms(
    active_only: bool = Query(True),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db)
    q = db.query(ent.SourcePlatform).filter(ent.SourcePlatform.tenant_id == tenant_id)
    if active_only:
        q = q.filter(ent.SourcePlatform.is_active.is_(True))
    return [
        {
            "id": r.id,
            "code": r.code,
            "name_ar": r.name_ar,
            "name_en": r.name_en,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.SourcePlatform.code).all()
    ]


@router.patch("/platforms/{platform_id}")
def update_source_platform(
    platform_id: int,
    payload: SourcePlatformUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db, manage=True)
    row = _same_tenant(db, ent.SourcePlatform, platform_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


# ---------- tenant connections ----------


@router.post("/connections", status_code=201)
def create_connection(
    payload: TenantConnectionCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db, manage=True)
    _same_tenant(db, ent.SourcePlatform, payload.source_platform_id, tenant_id)
    existing = (
        db.query(ent.TenantConnection)
        .filter(
            ent.TenantConnection.tenant_id == tenant_id,
            ent.TenantConnection.source_platform_id == payload.source_platform_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Connection already exists for this platform")
    row = ent.TenantConnection(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "connection_name": row.connection_name}


@router.get("/connections")
def list_connections(
    active_only: bool = Query(True),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db)
    q = db.query(ent.TenantConnection).filter(
        ent.TenantConnection.tenant_id == tenant_id
    )
    if active_only:
        q = q.filter(ent.TenantConnection.is_active.is_(True))
    return [
        {
            "id": r.id,
            "source_platform_id": r.source_platform_id,
            "connection_name": r.connection_name,
            "import_frequency": r.import_frequency,
            "is_active": r.is_active,
            "last_import_at": r.last_import_at.isoformat()
            if r.last_import_at
            else None,
        }
        for r in q.order_by(ent.TenantConnection.connection_name).all()
    ]


@router.patch("/connections/{connection_id}")
def update_connection(
    connection_id: int,
    payload: TenantConnectionUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db, manage=True)
    row = _same_tenant(db, ent.TenantConnection, connection_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "connection_name": row.connection_name}


# ---------- project contract mappings ----------


@router.post("/project-mappings", status_code=201)
def create_project_mapping(
    payload: ProjectContractMappingCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db, manage=True)
    _same_tenant(db, ent.SourcePlatform, payload.source_platform_id, tenant_id)
    existing = (
        db.query(ent.ProjectContractMapping)
        .filter(
            ent.ProjectContractMapping.tenant_id == tenant_id,
            ent.ProjectContractMapping.source_platform_id == payload.source_platform_id,
            ent.ProjectContractMapping.project_id == payload.project_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Project mapping already exists")
    row = ent.ProjectContractMapping(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "project_id": row.project_id}


@router.get("/project-mappings")
def list_project_mappings(
    user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    tenant_id = _tenant_id(user, db)
    q = db.query(ent.ProjectContractMapping).filter(
        ent.ProjectContractMapping.tenant_id == tenant_id
    )
    return [
        {
            "id": r.id,
            "source_platform_id": r.source_platform_id,
            "project_id": r.project_id,
            "contract_id": r.contract_id,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.ProjectContractMapping.id).all()
    ]


# ---------- rider identity mappings ----------


@router.post("/rider-mappings", status_code=201)
def create_rider_mapping(
    payload: RiderIdentityMappingCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db, manage=True)
    _same_tenant(db, ent.SourcePlatform, payload.source_platform_id, tenant_id)
    _same_tenant(db, ent.Courier, payload.courier_id, tenant_id)
    existing = (
        db.query(ent.RiderIdentityMapping)
        .filter(
            ent.RiderIdentityMapping.tenant_id == tenant_id,
            ent.RiderIdentityMapping.source_platform_id == payload.source_platform_id,
            ent.RiderIdentityMapping.source_rider_id == payload.source_rider_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Rider identity mapping already exists")
    row = ent.RiderIdentityMapping(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "source_rider_id": row.source_rider_id,
        "courier_id": row.courier_id,
    }


@router.get("/rider-mappings")
def list_rider_mappings(
    source_platform_id: Optional[int] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db)
    q = db.query(ent.RiderIdentityMapping).filter(
        ent.RiderIdentityMapping.tenant_id == tenant_id
    )
    if source_platform_id:
        q = q.filter(ent.RiderIdentityMapping.source_platform_id == source_platform_id)
    return [
        {
            "id": r.id,
            "source_platform_id": r.source_platform_id,
            "source_rider_id": r.source_rider_id,
            "courier_id": r.courier_id,
            "match_method": r.match_method,
            "confidence": r.confidence,
            "status": r.status,
        }
        for r in q.order_by(ent.RiderIdentityMapping.id).all()
    ]


@router.patch("/rider-mappings/{mapping_id}")
def update_rider_mapping(
    mapping_id: int,
    payload: RiderIdentityMappingUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db, manage=True)
    row = _same_tenant(db, ent.RiderIdentityMapping, mapping_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "source_rider_id": row.source_rider_id,
        "courier_id": row.courier_id,
    }


# ---------- raw import rows ----------


@router.post("/raw-rows", status_code=201)
def create_raw_row(
    payload: RawImportRowCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db, manage=True)
    _same_tenant(db, ent.SourcePlatform, payload.source_platform_id, tenant_id)
    # H1 FIX: Validate import_batch_id belongs to tenant
    if payload.import_batch_id is not None:
        _same_tenant(db, ent.OperationalImportBatch, payload.import_batch_id, tenant_id)
    # Validate JSON
    try:
        json.loads(payload.row_data)
    except json.JSONDecodeError:
        raise HTTPException(400, "row_data must be valid JSON")
    # Compute checksum
    checksum = hashlib.sha256(payload.row_data.encode()).hexdigest()
    existing = (
        db.query(ent.RawImportRow)
        .filter(
            ent.RawImportRow.tenant_id == tenant_id,
            ent.RawImportRow.source_platform_id == payload.source_platform_id,
            ent.RawImportRow.source_id == payload.source_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Raw row with this source_id already exists")
    row = ent.RawImportRow(
        tenant_id=tenant_id,
        source_platform_id=payload.source_platform_id,
        import_batch_id=payload.import_batch_id,
        source_id=payload.source_id,
        row_data=payload.row_data,
        checksum=checksum,
        schema_version=payload.schema_version,
        source_timestamp=payload.source_timestamp,
    )
    db.add(row)
    db.flush()
    # A row used to land at PENDING and stay there: nothing in the codebase ever
    # advanced the status, so the pipeline's middle arrow did not exist. It is
    # normalized on arrival now; if it cannot be, the reason is on the row.
    fact = normalize_row(db, row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "source_id": row.source_id,
        "checksum": row.checksum,
        "status": row.status,
        "fact_id": fact.id if fact else None,
        "validation_issues": json.loads(row.validation_issues)
        if row.validation_issues
        else None,
    }


@router.get("/raw-rows")
def list_raw_rows(
    source_platform_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db)
    q = db.query(ent.RawImportRow).filter(ent.RawImportRow.tenant_id == tenant_id)
    if source_platform_id:
        q = q.filter(ent.RawImportRow.source_platform_id == source_platform_id)
    if status_filter is not None and status_filter != "":
        q = q.filter(ent.RawImportRow.status == status_filter)
    return [
        {
            "id": r.id,
            "source_platform_id": r.source_platform_id,
            "source_id": r.source_id,
            "status": r.status,
            "checksum": r.checksum,
            "validation_issues": json.loads(r.validation_issues)
            if r.validation_issues
            else None,
            "row_data": r.row_data,
            "created_at": r.created_at.isoformat(),
        }
        for r in q.order_by(ent.RawImportRow.created_at.desc()).all()
    ]


@router.post("/raw-rows/reprocess")
def reprocess_raw_rows(
    source_platform_id: Optional[int] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Retry every row that is not yet a fact.

    The operator's loop is: read why the row was rejected, add the mapping it
    named, press this. Rows already NORMALIZED are skipped — reprocessing must
    never be a way to count a delivery twice.
    """
    tenant_id = _tenant_id(user, db, manage=True)
    if source_platform_id:
        _same_tenant(db, ent.SourcePlatform, source_platform_id, tenant_id)
    return reprocess_rows(db, tenant_id, source_platform_id)


# ---------- normalized delivery facts ----------


@router.post("/delivery-facts", status_code=201)
def create_delivery_fact(
    payload: NormalizedDeliveryFactCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db, manage=True)
    _same_tenant(db, ent.SourcePlatform, payload.source_platform_id, tenant_id)
    if payload.event_type not in ("COMPLETED", "CANCELLED", "FAILED"):
        raise HTTPException(400, "event_type must be COMPLETED, CANCELLED, or FAILED")
    # Idempotency key
    idempotency_key = (
        f"{tenant_id}:{payload.source_platform_id}:{payload.source_delivery_id}"
    )
    existing = (
        db.query(ent.NormalizedDeliveryFact)
        .filter(
            ent.NormalizedDeliveryFact.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            409, "Delivery fact already exists for this source delivery"
        )
    provenance = {
        "source_platform_id": payload.source_platform_id,
        "source_delivery_id": payload.source_delivery_id,
    }
    if payload.raw_row_id:
        provenance["raw_row_id"] = payload.raw_row_id
    # M7 FIX: Validate raw_row_id belongs to tenant
    if payload.raw_row_id is not None:
        _same_tenant(db, ent.RawImportRow, payload.raw_row_id, tenant_id)
    # C3 FIX: Validate courier_id belongs to tenant
    if payload.courier_id is not None:
        _same_tenant(db, ent.Courier, payload.courier_id, tenant_id)
    row = ent.NormalizedDeliveryFact(
        tenant_id=tenant_id,
        source_platform_id=payload.source_platform_id,
        source_delivery_id=payload.source_delivery_id,
        raw_row_id=payload.raw_row_id,
        courier_id=payload.courier_id,
        project_id=payload.project_id,
        contract_branch_id=payload.contract_branch_id,
        team_id=payload.team_id,
        event_type=payload.event_type,
        event_date=payload.event_date,
        event_timestamp=payload.event_timestamp,
        distance_km=payload.distance_km,
        revenue_amount=payload.revenue_amount,
        cost_amount=payload.cost_amount,
        currency=payload.currency,
        provenance=json.dumps(provenance),
        idempotency_key=idempotency_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "source_delivery_id": row.source_delivery_id,
        "event_type": row.event_type,
    }


@router.get("/delivery-facts")
def list_delivery_facts(
    source_platform_id: Optional[int] = Query(None),
    event_date: Optional[date] = Query(None),
    courier_id: Optional[int] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db)
    q = db.query(ent.NormalizedDeliveryFact).filter(
        ent.NormalizedDeliveryFact.tenant_id == tenant_id
    )
    if source_platform_id:
        q = q.filter(
            ent.NormalizedDeliveryFact.source_platform_id == source_platform_id
        )
    if event_date:
        q = q.filter(ent.NormalizedDeliveryFact.event_date == event_date)
    if courier_id:
        q = q.filter(ent.NormalizedDeliveryFact.courier_id == courier_id)
    return [
        {
            "id": r.id,
            "source_platform_id": r.source_platform_id,
            "source_delivery_id": r.source_delivery_id,
            "raw_row_id": r.raw_row_id,
            "courier_id": r.courier_id,
            "project_id": r.project_id,
            "event_type": r.event_type,
            "event_date": r.event_date.isoformat(),
            "distance_km": r.distance_km,
            "revenue_amount": r.revenue_amount,
            "cost_amount": r.cost_amount,
            "currency": r.currency,
            # Lineage is the point: a number in payroll has to be traceable to
            # the row it came from and the mappings that resolved it. The fact
            # carried both and this reader returned neither.
            "provenance": json.loads(r.provenance) if r.provenance else None,
        }
        for r in q.order_by(ent.NormalizedDeliveryFact.event_date.desc()).all()
    ]


# ---------- reconciliation ----------


@router.post("/reconcile", status_code=201)
def create_reconciliation(
    payload: ReconciliationCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db, manage=True)
    _same_tenant(db, ent.SourcePlatform, payload.source_platform_id, tenant_id)
    # H3 FIX: Use explicit import_date instead of timezone-sensitive func.date()
    raw_rows = db.query(ent.RawImportRow).filter(
        ent.RawImportRow.tenant_id == tenant_id,
        ent.RawImportRow.source_platform_id == payload.source_platform_id,
        ent.RawImportRow.import_date == payload.reconciliation_date,
    )
    source_total = raw_rows.count()
    raw_rows.filter(ent.RawImportRow.status == "ACCEPTED").count()
    rejected = raw_rows.filter(ent.RawImportRow.status == "REJECTED").count()
    raw_rows.filter(ent.RawImportRow.status == "NORMALIZED").count()
    raw_rows.filter(ent.RawImportRow.status == "PENDING").count()
    # L3 FIX: Count actual duplicate raw rows (same source_id appearing multiple times)
    duplicate_subquery = (
        db.query(
            ent.RawImportRow.source_id, func.count(ent.RawImportRow.id).label("cnt")
        )
        .filter(
            ent.RawImportRow.tenant_id == tenant_id,
            ent.RawImportRow.source_platform_id == payload.source_platform_id,
            ent.RawImportRow.import_date == payload.reconciliation_date,
        )
        .group_by(ent.RawImportRow.source_id)
        .having(func.count(ent.RawImportRow.id) > 1)
        .subquery()
    )
    duplicate_count = db.query(func.sum(duplicate_subquery.c.cnt - 1)).scalar() or 0
    # Delivery facts for this date
    facts = db.query(ent.NormalizedDeliveryFact).filter(
        ent.NormalizedDeliveryFact.tenant_id == tenant_id,
        ent.NormalizedDeliveryFact.source_platform_id == payload.source_platform_id,
        ent.NormalizedDeliveryFact.event_date == payload.reconciliation_date,
    )
    accepted_facts = facts.count()
    revenue_accepted = sum(float(f.revenue_amount or 0) for f in facts.all())
    row = ent.ReconciliationResult(
        tenant_id=tenant_id,
        source_platform_id=payload.source_platform_id,
        reconciliation_date=payload.reconciliation_date,
        source_total_count=source_total,
        accepted_count=accepted_facts,
        rejected_count=rejected,
        duplicate_count=duplicate_count,
        unmapped_count=0,
        missing_count=source_total - accepted_facts
        if source_total > accepted_facts
        else 0,
        total_revenue_source=0,
        total_revenue_accepted=revenue_accepted,
        status="COMPLETED",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "reconciliation_date": row.reconciliation_date.isoformat(),
        "status": row.status,
    }


@router.get("/reconcile")
def list_reconciliations(
    source_platform_id: Optional[int] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, db)
    q = db.query(ent.ReconciliationResult).filter(
        ent.ReconciliationResult.tenant_id == tenant_id
    )
    if source_platform_id:
        q = q.filter(ent.ReconciliationResult.source_platform_id == source_platform_id)
    return [
        {
            "id": r.id,
            "source_platform_id": r.source_platform_id,
            "reconciliation_date": r.reconciliation_date.isoformat(),
            "source_total_count": r.source_total_count,
            "accepted_count": r.accepted_count,
            "rejected_count": r.rejected_count,
            "status": r.status,
        }
        for r in q.order_by(ent.ReconciliationResult.reconciliation_date.desc()).all()
    ]

"""Fleet vehicle registry, documents, assignment, and readiness."""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import (
    AuditLog,
    Courier,
    RiderVehicleAssignment,
    User,
    UserRole,
    Vehicle,
    VehicleDocument,
)
from .auth import get_current_user

router = APIRouter(prefix="/vehicles", tags=["vehicles"])
MANAGE_ROLES = {
    UserRole.COMPANY,
    UserRole.COMPANY_ADMIN,
    UserRole.OPERATIONS,
    UserRole.HR,
}
READ_ROLES = MANAGE_ROLES | {
    UserRole.ACCOUNTANT,
    UserRole.VIEWER,
    UserRole.PROJECT_MANAGER,
    UserRole.SUPERVISOR,
}


class VehicleCreate(BaseModel):
    plate_number: str = Field(min_length=1, max_length=40)
    vehicle_type: str = Field(min_length=1, max_length=30)
    make: Optional[str] = None
    model: Optional[str] = None
    model_year: Optional[int] = None
    market_code: str = Field(default="SA", min_length=2, max_length=2)
    is_exclusive: bool = True


class VehicleDocumentCreate(BaseModel):
    document_type: str = Field(min_length=1, max_length=40)
    document_number: Optional[str] = None
    expiry_date: Optional[date] = None
    status: str = "VALID"


class VehicleAssignmentCreate(BaseModel):
    courier_id: int
    effective_from: date = Field(default_factory=date.today)
    effective_to: Optional[date] = None
    is_primary: bool = True


class VehicleTransfer(BaseModel):
    vehicle_id: int
    effective_on: date = Field(default_factory=date.today)


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plate_number: str
    plate_normalized: str
    vehicle_type: str
    make: Optional[str]
    model: Optional[str]
    model_year: Optional[int]
    market_code: str
    operational_status: str
    compliance_status: str
    is_exclusive: bool
    created_at: Optional[str]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vehicle_id: int
    document_type: str
    document_number: Optional[str]
    expiry_date: Optional[str]
    status: str


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vehicle_id: int
    courier_id: int
    effective_from: str
    effective_to: Optional[str]
    is_primary: bool


def _tenant_id(user: User, manage: bool = False) -> int:
    allowed = MANAGE_ROLES if manage else READ_ROLES
    if user.role not in allowed or not user.tenant_id:
        raise HTTPException(403, "Fleet vehicle access required")
    return user.tenant_id


def _same_tenant(db: Session, model, record_id: int, tenant_id: int):
    row = (
        db.query(model)
        .filter(model.id == record_id, model.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(404, f"{model.__name__} not found")
    return row


def _audit(db: Session, user: User, action: str, entity: str, entity_id: int):
    db.add(
        AuditLog(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            actor_name=user.name or "—",
            actor_role=user.role.value,
            action=action,
            entity=entity,
            entity_id=entity_id,
        )
    )


def _commit(db: Session, conflict_message: str):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, conflict_message) from exc


def _normalize_plate(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum()).upper()


def _vehicle_out(row: Vehicle):
    return {
        "id": row.id,
        "plate_number": row.plate_number,
        "plate_normalized": row.plate_normalized,
        "vehicle_type": row.vehicle_type,
        "make": row.make,
        "model": row.model,
        "model_year": row.model_year,
        "market_code": row.market_code,
        "operational_status": row.operational_status,
        "compliance_status": row.compliance_status,
        "is_exclusive": row.is_exclusive,
    }


def _document_out(row: VehicleDocument):
    return {
        "id": row.id,
        "vehicle_id": row.vehicle_id,
        "document_type": row.document_type,
        "document_number": row.document_number,
        "expiry_date": row.expiry_date.isoformat() if row.expiry_date else None,
        "status": row.status,
    }


def _assignment_out(row: RiderVehicleAssignment):
    return {
        "id": row.id,
        "vehicle_id": row.vehicle_id,
        "courier_id": row.courier_id,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "is_primary": row.is_primary,
    }


@router.post("/", status_code=201)
def create_vehicle(
    payload: VehicleCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    normalized = _normalize_plate(payload.plate_number)
    existing = (
        db.query(Vehicle)
        .filter(
            Vehicle.tenant_id == tenant_id,
            Vehicle.market_code == payload.market_code.strip(),
            Vehicle.plate_normalized == normalized,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Vehicle plate already exists in this market")
    row = Vehicle(
        tenant_id=tenant_id,
        market_code=payload.market_code.strip().upper(),
        plate_number=payload.plate_number.strip(),
        plate_normalized=normalized,
        vehicle_type=payload.vehicle_type.strip(),
        make=payload.make.strip() if payload.make else None,
        model=payload.model.strip() if payload.model else None,
        model_year=payload.model_year,
        is_exclusive=payload.is_exclusive,
    )
    db.add(row)
    db.flush()
    _audit(db, user, "create vehicle", "vehicle", row.id)
    _commit(db, "Vehicle creation conflict")
    db.refresh(row)
    return _vehicle_out(row)


@router.get("/")
def list_vehicles(
    active_only: bool = Query(True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user)
    query = db.query(Vehicle).filter(Vehicle.tenant_id == tenant_id)
    if active_only:
        query = query.filter(Vehicle.operational_status == "ACTIVE")
    return [_vehicle_out(row) for row in query.order_by(Vehicle.plate_normalized).all()]


@router.patch("/{vehicle_id}")
def update_vehicle(
    vehicle_id: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, Vehicle, vehicle_id, tenant_id)
    if "plate_number" in payload and payload["plate_number"]:
        row.plate_number = str(payload["plate_number"]).strip()
        row.plate_normalized = _normalize_plate(row.plate_number)
    if "vehicle_type" in payload and payload["vehicle_type"]:
        row.vehicle_type = str(payload["vehicle_type"]).strip()
    if "make" in payload:
        row.make = str(payload["make"]).strip() if payload["make"] else None
    if "model" in payload:
        row.model = str(payload["model"]).strip() if payload["model"] else None
    if "model_year" in payload:
        row.model_year = int(payload["model_year"]) if payload["model_year"] else None
    if "operational_status" in payload and payload["operational_status"]:
        row.operational_status = str(payload["operational_status"]).upper()
    db.commit()
    _audit(db, user, "update vehicle", "vehicle", row.id)
    return _vehicle_out(row)


@router.delete("/{vehicle_id}")
def delete_vehicle(
    vehicle_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, Vehicle, vehicle_id, tenant_id)
    row.operational_status = "INACTIVE"
    db.commit()
    _audit(db, user, "deactivate vehicle", "vehicle", row.id)
    return {"ok": True}


@router.get("/{vehicle_id}")
def get_vehicle(
    vehicle_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user)
    vehicle = _same_tenant(db, Vehicle, vehicle_id, tenant_id)
    documents = [
        _document_out(row)
        for row in db.query(VehicleDocument)
        .filter(
            VehicleDocument.tenant_id == tenant_id,
            VehicleDocument.vehicle_id == vehicle.id,
        )
        .order_by(VehicleDocument.document_type)
        .all()
    ]
    return {
        "vehicle": _vehicle_out(vehicle),
        "documents": documents,
        "market_code": vehicle.market_code,
    }


@router.post("/{vehicle_id}/documents", status_code=201)
def add_vehicle_document(
    vehicle_id: int,
    payload: VehicleDocumentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    vehicle = _same_tenant(db, Vehicle, vehicle_id, tenant_id)
    row = VehicleDocument(
        tenant_id=tenant_id,
        vehicle_id=vehicle.id,
        document_type=payload.document_type.strip(),
        document_number=payload.document_number.strip()
        if payload.document_number
        else None,
        expiry_date=payload.expiry_date,
        status=payload.status,
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    _audit(db, user, "add vehicle document", "vehicle_document", row.id)
    _commit(db, "Vehicle document creation conflict")
    db.refresh(row)
    return _document_out(row)


def _validate_dates(start: date, end: Optional[date]):
    if end is not None and end < start:
        raise HTTPException(422, "effective_to must be on or after effective_from")


def _primary_overlap(
    db: Session,
    tenant_id: int,
    vehicle_id: int,
    effective_from: date,
    effective_to: Optional[date],
):
    requested_end = effective_to or date.max
    rows = (
        db.query(RiderVehicleAssignment)
        .filter(
            RiderVehicleAssignment.tenant_id == tenant_id,
            RiderVehicleAssignment.vehicle_id == vehicle_id,
            RiderVehicleAssignment.is_primary.is_(True),
        )
        .all()
    )
    return next(
        (
            row
            for row in rows
            if row.effective_from <= requested_end
            and effective_from <= (row.effective_to or date.max)
        ),
        None,
    )


@router.post("/assignments", status_code=201)
def assign_vehicle(
    vehicle_id: int,
    payload: VehicleAssignmentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    vehicle = _same_tenant(db, Vehicle, vehicle_id, tenant_id)
    _same_tenant(db, Courier, payload.courier_id, tenant_id)
    courier = (
        db.query(Courier)
        .filter(
            Courier.tenant_id == tenant_id,
            Courier.id == payload.courier_id,
        )
        .first()
    )
    if not courier or vehicle.market_code != courier.country.value:
        raise HTTPException(409, "Vehicle market does not match rider market")
    _validate_dates(payload.effective_from, payload.effective_to)
    if payload.is_primary and _primary_overlap(
        db, tenant_id, vehicle_id, payload.effective_from, payload.effective_to
    ):
        raise HTTPException(
            409, "Primary vehicle assignment overlaps an existing assignment"
        )
    row = RiderVehicleAssignment(
        tenant_id=tenant_id,
        vehicle_id=vehicle_id,
        courier_id=payload.courier_id,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        is_primary=payload.is_primary,
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    _audit(db, user, "assign vehicle to rider", "rider_vehicle_assignment", row.id)
    _commit(db, "Vehicle assignment conflict")
    db.refresh(row)
    return _assignment_out(row)


@router.post("/riders/{courier_id}/transfer", status_code=201)
def transfer_rider_vehicle(
    courier_id: int,
    payload: VehicleTransfer,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, Courier, courier_id, tenant_id)
    target = _same_tenant(db, Vehicle, payload.vehicle_id, tenant_id)
    target_overlap = _primary_overlap(
        db, tenant_id, target.id, payload.effective_on, None
    )
    if target_overlap and target_overlap.courier_id != courier_id:
        raise HTTPException(
            409, "Target vehicle has an overlapping primary assignment to another rider"
        )
    existing = (
        db.query(RiderVehicleAssignment)
        .filter(
            RiderVehicleAssignment.tenant_id == tenant_id,
            RiderVehicleAssignment.courier_id == courier_id,
            RiderVehicleAssignment.is_primary.is_(True),
            RiderVehicleAssignment.effective_from <= payload.effective_on,
            or_(
                RiderVehicleAssignment.effective_to.is_(None),
                RiderVehicleAssignment.effective_to >= payload.effective_on,
            ),
        )
        .first()
    )
    if existing:
        if existing.vehicle_id == target.id:
            raise HTTPException(409, "Already assigned to target vehicle")
        if existing.effective_from >= payload.effective_on:
            raise HTTPException(409, "Transfer date conflicts with current assignment")
        existing.effective_to = payload.effective_on - timedelta(days=1)
    future = (
        db.query(RiderVehicleAssignment)
        .filter(
            RiderVehicleAssignment.tenant_id == tenant_id,
            RiderVehicleAssignment.courier_id == courier_id,
            RiderVehicleAssignment.is_primary.is_(True),
            RiderVehicleAssignment.effective_from > payload.effective_on,
        )
        .first()
    )
    if future:
        raise HTTPException(409, "A future primary assignment already exists")
    row = RiderVehicleAssignment(
        tenant_id=tenant_id,
        vehicle_id=target.id,
        courier_id=courier_id,
        effective_from=payload.effective_on,
        is_primary=True,
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    _audit(db, user, "transfer rider vehicle", "rider_vehicle_assignment", row.id)
    _commit(db, "Vehicle transfer conflict")
    db.refresh(row)
    return _assignment_out(row)


@router.get("/riders/{courier_id}/readiness")
def rider_vehicle_readiness(
    courier_id: int,
    as_of: date = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user)
    _same_tenant(db, Courier, courier_id, tenant_id)
    today = as_of
    assignment = (
        db.query(RiderVehicleAssignment)
        .filter(
            RiderVehicleAssignment.tenant_id == tenant_id,
            RiderVehicleAssignment.courier_id == courier_id,
            RiderVehicleAssignment.is_primary.is_(True),
            RiderVehicleAssignment.effective_from <= today,
            or_(
                RiderVehicleAssignment.effective_to.is_(None),
                RiderVehicleAssignment.effective_to >= today,
            ),
        )
        .first()
    )
    blockers = []
    details = {}
    if not assignment:
        blockers.append("VEHICLE_ASSIGNED_IN_FUTURE")
        details["assignment"] = None
    else:
        vehicle = _same_tenant(db, Vehicle, assignment.vehicle_id, tenant_id)
        if vehicle.operational_status != "ACTIVE":
            blockers.append("VEHICLE_INACTIVE")
        documents = (
            db.query(VehicleDocument)
            .filter(
                VehicleDocument.tenant_id == tenant_id,
                VehicleDocument.vehicle_id == vehicle.id,
            )
            .all()
        )
        required = {"REGISTRATION", "INSURANCE", "LICENSE", "INSPECTION"}
        present = {row.document_type for row in documents if row.status == "VALID"}
        missing = sorted(required - present)
        expiries = {
            row.document_type: row.expiry_date
            for row in documents
            if row.expiry_date and row.expiry_date < today
        }
        for doc_type, expiry in sorted(expiries.items(), key=lambda item: item[1]):
            blockers.append(f"{doc_type}_EXPIRED")
            details[f"{doc_type}_expiry"] = expiry.isoformat()
        if missing:
            blockers.extend(doc.upper() + "_MISSING" for doc in missing)
        details["assignment"] = {
            "vehicle_id": vehicle.id,
            "plate_number": vehicle.plate_number,
            "vehicle_type": vehicle.vehicle_type,
            "documents_missing": missing,
            "documents_expired": [doc_type for doc_type in expiries],
        }
    return {
        "courier_id": courier_id,
        "as_of": today.isoformat(),
        "ready": len(blockers) == 0,
        "blockers": blockers,
        "details": details,
    }

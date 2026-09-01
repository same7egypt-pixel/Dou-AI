from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from ..database import get_db
from ..models import entities as ent, salary as sal
from .auth import get_current_user


router = APIRouter(prefix="/salary", tags=["salary"])

MANAGE_ROLES = {
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.OPERATIONS,
    ent.UserRole.HR,
}
READ_ROLES = MANAGE_ROLES | {
    ent.UserRole.ACCOUNTANT,
    ent.UserRole.VIEWER,
    ent.UserRole.PROJECT_MANAGER,
    ent.UserRole.SUPERVISOR,
}


class SalaryStructureCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name_ar: str
    name_en: Optional[str] = None
    description_ar: Optional[str] = None
    description_en: Optional[str] = None
    currency: str = "SAR"
    cycle: str = "MONTHLY"
    balance_period: bool = False


class ComponentCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name_ar: str
    name_en: Optional[str] = None
    category: str = "BASE"
    calculation: str = "FLAT"
    amount: float = 0.0
    cap_amount: Optional[float] = None
    conditions: Optional[str] = None


class SalaryStructureUpdate(BaseModel):
    name_ar: Optional[str] = None
    name_en: Optional[str] = None
    description_ar: Optional[str] = None
    description_en: Optional[str] = None
    currency: Optional[str] = None
    cycle: Optional[str] = None
    balance_period: Optional[bool] = None


class ComponentUpdate(BaseModel):
    name_ar: Optional[str] = None
    name_en: Optional[str] = None
    category: Optional[str] = None
    calculation: Optional[str] = None
    amount: Optional[float] = None
    cap_amount: Optional[float] = None
    conditions: Optional[str] = None
    is_active: Optional[bool] = None


class RiderSalaryAssignmentCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    courier_id: int
    salary_structure_id: int
    effective_from: date = date.today()


def _tenant_id(user: ent.User, manage: bool = False) -> int:
    allowed = MANAGE_ROLES if manage else READ_ROLES
    if user.role not in allowed or not user.tenant_id:
        raise HTTPException(403, "Fleet salary access required")
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


def _audit(db, user: ent.User, action: str, entity: str, entity_id: int):
    db.add(
        ent.AuditLog(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            actor_name=user.name or "—",
            actor_role=user.role.value,
            action=action,
            entity=entity,
            entity_id=entity_id,
        )
    )


def _commit(db, conflict_message: str):
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(409, conflict_message) from exc


def _structure_out(row: sal.SalaryStructure):
    return {
        "id": row.id,
        "code": row.code,
        "name_ar": row.name_ar,
        "name_en": row.name_en,
        "description_ar": row.description_ar,
        "description_en": row.description_en,
        "currency": row.currency,
        "cycle": row.cycle,
        "balance_period": row.balance_period,
        "version": row.version,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat(),
        "components": [],
    }


def _structure_out_full(row: sal.SalaryStructure):
    return {
        "id": row.id,
        "code": row.code,
        "name_ar": row.name_ar,
        "name_en": row.name_en,
        "description_ar": row.description_ar,
        "description_en": row.description_en,
        "currency": row.currency,
        "cycle": row.cycle,
        "balance_period": row.balance_period,
        "version": row.version,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat(),
        "components": [_component_out(c) for c in row.components],
    }


def _component_out(row: sal.SalaryComponent):
    return {
        "id": row.id,
        "code": row.code,
        "name_ar": row.name_ar,
        "name_en": row.name_en,
        "category": row.category,
        "calculation": row.calculation,
        "amount": row.amount,
        "cap_amount": row.cap_amount,
        "conditions": row.conditions,
        "is_active": row.is_active,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
    }


def _assignment_out(row: sal.RiderSalaryAssignment):
    return {
        "id": row.id,
        "courier_id": row.courier_id,
        "salary_structure_id": row.salary_structure_id,
        "effective_from": row.effective_from.date().isoformat()
        if row.effective_from
        else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
    }


@router.post("/structures", status_code=201)
def create_structure(
    payload: SalaryStructureCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    existing = (
        db.query(sal.SalaryStructure)
        .filter(
            sal.SalaryStructure.tenant_id == tenant_id,
            sal.SalaryStructure.code == payload.code,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Salary structure code already exists")
    row = sal.SalaryStructure(
        tenant_id=tenant_id,
        code=payload.code,
        name_ar=payload.name_ar,
        name_en=payload.name_en,
        description_ar=payload.description_ar,
        description_en=payload.description_en,
        currency=payload.currency,
        cycle=payload.cycle,
        balance_period=payload.balance_period,
    )
    db.add(row)
    db.flush()
    _audit(db, user, "create salary structure", "salary_structure", row.id)
    _commit(db, "Salary structure creation conflict")
    db.refresh(row)
    return _structure_out(row)


@router.post("/structures/{structure_id}/components", status_code=201)
def add_component(
    structure_id: int,
    payload: ComponentCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, sal.SalaryStructure, structure_id, tenant_id)
    if not row.is_active:
        raise HTTPException(409, "Salary structure is inactive")
    existing = (
        db.query(sal.SalaryComponent)
        .filter(
            sal.SalaryComponent.tenant_id == tenant_id,
            sal.SalaryComponent.salary_structure_id == structure_id,
            sal.SalaryComponent.code == payload.code,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Salary component code already exists")
    component = sal.SalaryComponent(
        tenant_id=tenant_id,
        salary_structure_id=structure_id,
        code=payload.code,
        name_ar=payload.name_ar,
        name_en=payload.name_en,
        category=payload.category,
        calculation=payload.calculation,
        amount=payload.amount,
        cap_amount=payload.cap_amount,
        conditions=payload.conditions,
    )
    db.add(component)
    db.flush()
    _audit(db, user, "add salary component", "salary_component", component.id)
    _commit(db, "Salary component creation conflict")
    db.refresh(component)
    return _component_out(component)


@router.patch("/structures/{structure_id}")
def update_structure(
    structure_id: int,
    payload: SalaryStructureUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, sal.SalaryStructure, structure_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    _audit(db, user, "update salary structure", "salary_structure", row.id)
    db.refresh(row)
    return _structure_out(row)


@router.get("/structures")
def list_structures(
    active_only: bool = Query(True),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(sal.SalaryStructure).filter(sal.SalaryStructure.tenant_id == tenant_id)
    if active_only:
        q = q.filter(sal.SalaryStructure.is_active.is_(True))
    return [_structure_out(r) for r in q.order_by(sal.SalaryStructure.code).all()]


@router.get("/structures/{structure_id}")
def get_structure(
    structure_id: int,
    full: bool = Query(False),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    row = _same_tenant(db, sal.SalaryStructure, structure_id, tenant_id)
    return _structure_out_full(row) if full else _structure_out(row)


@router.get("/riders/{courier_id}/current-structure")
def rider_current_structure(
    courier_id: int,
    as_of: date = Query(...),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    _same_tenant(db, ent.Courier, courier_id, tenant_id)
    a = (
        db.query(sal.RiderSalaryAssignment)
        .filter(
            sal.RiderSalaryAssignment.tenant_id == tenant_id,
            sal.RiderSalaryAssignment.courier_id == courier_id,
            sal.RiderSalaryAssignment.effective_from <= as_of,
            sal.RiderSalaryAssignment.effective_to.is_(None)
            | (sal.RiderSalaryAssignment.effective_to >= as_of),
        )
        .order_by(sal.RiderSalaryAssignment.effective_from.desc())
        .first()
    )
    if not a:
        return {
            "courier_id": courier_id,
            "as_of": as_of.isoformat(),
            "salary_structure": None,
        }
    s = _same_tenant(db, sal.SalaryStructure, a.salary_structure_id, tenant_id)
    return {
        "courier_id": courier_id,
        "as_of": as_of.isoformat(),
        "salary_structure": _structure_out(s),
    }


@router.post("/riders/{courier_id}/assignments", status_code=201)
def assign_rider_structure(
    courier_id: int,
    payload: RiderSalaryAssignmentCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.Courier, courier_id, tenant_id)
    if payload.courier_id != courier_id:
        raise HTTPException(403, "Courier ID mismatch")
    _same_tenant(db, sal.SalaryStructure, payload.salary_structure_id, tenant_id)
    future = (
        db.query(sal.RiderSalaryAssignment)
        .filter(
            sal.RiderSalaryAssignment.tenant_id == tenant_id,
            sal.RiderSalaryAssignment.courier_id == courier_id,
            sal.RiderSalaryAssignment.effective_from > payload.effective_from,
        )
        .first()
    )
    if future:
        raise HTTPException(409, "Future assignment already exists")
    overlapping = (
        db.query(sal.RiderSalaryAssignment)
        .filter(
            sal.RiderSalaryAssignment.tenant_id == tenant_id,
            sal.RiderSalaryAssignment.courier_id == courier_id,
            sal.RiderSalaryAssignment.effective_from <= payload.effective_from,
            sal.RiderSalaryAssignment.effective_to.is_(None)
            | (sal.RiderSalaryAssignment.effective_to >= payload.effective_from),
        )
        .first()
    )
    if overlapping:
        overlapping.effective_to = payload.effective_from - timedelta(days=1)
    row = sal.RiderSalaryAssignment(
        tenant_id=tenant_id,
        courier_id=courier_id,
        salary_structure_id=payload.salary_structure_id,
        effective_from=payload.effective_from,
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    _audit(
        db, user, "assign salary structure to rider", "rider_salary_assignment", row.id
    )
    _commit(db, "Salary assignment conflict")
    db.refresh(row)
    return _assignment_out(row)


@router.get("/riders/{courier_id}/assignments")
def rider_assignments(
    courier_id: int,
    include_history: bool = False,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    _same_tenant(db, ent.Courier, courier_id, tenant_id)
    q = db.query(sal.RiderSalaryAssignment).filter(
        sal.RiderSalaryAssignment.tenant_id == tenant_id,
        sal.RiderSalaryAssignment.courier_id == courier_id,
    )
    if include_history:
        # History mode returns all assignments ordered by effective_from desc
        pass
    else:
        today = date.today()
        q = q.filter(
            (sal.RiderSalaryAssignment.effective_to.is_(None))
            | (sal.RiderSalaryAssignment.effective_to >= today)
        )
        q = q.filter(sal.RiderSalaryAssignment.effective_from <= today)
    return [
        _assignment_out(row)
        for row in q.order_by(sal.RiderSalaryAssignment.effective_from.desc()).all()
    ]

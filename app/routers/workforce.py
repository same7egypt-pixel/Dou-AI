"""Tenant-safe teams, zones, memberships, and supervisor assignments."""

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
    OperatingZone,
    TeamMembership,
    TeamSupervisorAssignment,
    TenantOperatingCity,
    User,
    UserRole,
    WorkforceTeam,
)
from .auth import get_current_user


router = APIRouter(prefix="/workforce", tags=["workforce"])
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


class ZoneCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name_ar: str = Field(min_length=1, max_length=120)
    name_en: Optional[str] = Field(default=None, max_length=120)
    operating_city_id: int


class TeamCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name_ar: str = Field(min_length=1, max_length=120)
    name_en: Optional[str] = Field(default=None, max_length=120)
    zone_id: Optional[int] = None


class MembershipCreate(BaseModel):
    courier_id: int
    effective_from: date = Field(default_factory=date.today)
    effective_to: Optional[date] = None
    is_primary: bool = True


class TeamTransfer(BaseModel):
    team_id: int
    effective_on: date = Field(default_factory=date.today)


class SupervisorAssignmentCreate(BaseModel):
    supervisor_id: int
    effective_from: date = Field(default_factory=date.today)
    effective_to: Optional[date] = None


class WorkforceRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _tenant_id(user: User, manage: bool = False) -> int:
    allowed = MANAGE_ROLES if manage else READ_ROLES
    if user.role not in allowed or not user.tenant_id:
        raise HTTPException(403, "Tenant workforce access required")
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


def _zone_out(row: OperatingZone):
    return {
        "id": row.id,
        "code": row.code,
        "name_ar": row.name_ar,
        "name_en": row.name_en,
        "operating_city_id": row.operating_city_id,
        "is_active": row.is_active,
    }


def _team_out(row: WorkforceTeam):
    return {
        "id": row.id,
        "code": row.code,
        "name_ar": row.name_ar,
        "name_en": row.name_en,
        "zone_id": row.zone_id,
        "is_active": row.is_active,
    }


def _membership_out(row: TeamMembership):
    return {
        "id": row.id,
        "team_id": row.team_id,
        "courier_id": row.courier_id,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "is_primary": row.is_primary,
    }


def _supervisor_out(row: TeamSupervisorAssignment):
    return {
        "id": row.id,
        "team_id": row.team_id,
        "supervisor_id": row.supervisor_id,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
    }


@router.post("/zones", status_code=201)
def create_zone(
    payload: ZoneCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    city = _same_tenant(db, TenantOperatingCity, payload.operating_city_id, tenant_id)
    if not city.is_active:
        raise HTTPException(409, "Operating city is inactive")
    row = OperatingZone(
        tenant_id=tenant_id,
        operating_city_id=city.id,
        code=payload.code.strip().upper(),
        name_ar=payload.name_ar.strip(),
        name_en=payload.name_en.strip() if payload.name_en else None,
    )
    db.add(row)
    db.flush()
    _audit(db, user, "create operating zone", "operating_zone", row.id)
    _commit(db, "Zone code already exists")
    db.refresh(row)
    return _zone_out(row)


@router.get("/zones")
def list_zones(
    active_only: bool = Query(True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user)
    query = db.query(OperatingZone).filter(OperatingZone.tenant_id == tenant_id)
    if active_only:
        query = query.filter(OperatingZone.is_active.is_(True))
    return [_zone_out(row) for row in query.order_by(OperatingZone.name_ar).all()]


@router.post("/teams", status_code=201)
def create_team(
    payload: TeamCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    if payload.zone_id is not None:
        zone = _same_tenant(db, OperatingZone, payload.zone_id, tenant_id)
        if not zone.is_active:
            raise HTTPException(409, "Operating zone is inactive")
    row = WorkforceTeam(
        tenant_id=tenant_id,
        zone_id=payload.zone_id,
        code=payload.code.strip().upper(),
        name_ar=payload.name_ar.strip(),
        name_en=payload.name_en.strip() if payload.name_en else None,
    )
    db.add(row)
    db.flush()
    _audit(db, user, "create workforce team", "workforce_team", row.id)
    _commit(db, "Team code already exists")
    db.refresh(row)
    return _team_out(row)


@router.get("/teams")
def list_teams(
    zone_id: Optional[int] = None,
    active_only: bool = Query(True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user)
    query = db.query(WorkforceTeam).filter(WorkforceTeam.tenant_id == tenant_id)
    if zone_id is not None:
        _same_tenant(db, OperatingZone, zone_id, tenant_id)
        query = query.filter(WorkforceTeam.zone_id == zone_id)
    if active_only:
        query = query.filter(WorkforceTeam.is_active.is_(True))
    return [_team_out(row) for row in query.order_by(WorkforceTeam.name_ar).all()]


def _validate_dates(start: date, end: Optional[date]):
    if end is not None and end < start:
        raise HTTPException(422, "effective_to must be on or after effective_from")


def _primary_overlap(
    db: Session, tenant_id: int, courier_id: int, start: date, end: Optional[date]
):
    requested_end = end or date.max
    rows = (
        db.query(TeamMembership)
        .filter(
            TeamMembership.tenant_id == tenant_id,
            TeamMembership.courier_id == courier_id,
            TeamMembership.is_primary.is_(True),
        )
        .all()
    )
    return next(
        (
            row
            for row in rows
            if row.effective_from <= requested_end
            and start <= (row.effective_to or date.max)
        ),
        None,
    )


@router.post("/teams/{team_id}/memberships", status_code=201)
def add_team_membership(
    team_id: int,
    payload: MembershipCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    team = _same_tenant(db, WorkforceTeam, team_id, tenant_id)
    _same_tenant(db, Courier, payload.courier_id, tenant_id)
    if not team.is_active:
        raise HTTPException(409, "Workforce team is inactive")
    _validate_dates(payload.effective_from, payload.effective_to)
    if payload.is_primary and _primary_overlap(
        db, tenant_id, payload.courier_id, payload.effective_from, payload.effective_to
    ):
        raise HTTPException(
            409, "Primary team membership overlaps an existing membership"
        )
    row = TeamMembership(
        tenant_id=tenant_id,
        team_id=team.id,
        courier_id=payload.courier_id,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        is_primary=payload.is_primary,
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    _audit(db, user, "add rider to workforce team", "team_membership", row.id)
    _commit(db, "Team membership already exists")
    db.refresh(row)
    return _membership_out(row)


@router.get("/teams/{team_id}/memberships")
def list_team_memberships(
    team_id: int,
    include_history: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user)
    _same_tenant(db, WorkforceTeam, team_id, tenant_id)
    query = db.query(TeamMembership).filter(
        TeamMembership.tenant_id == tenant_id, TeamMembership.team_id == team_id
    )
    if not include_history:
        today = date.today()
        query = query.filter(
            TeamMembership.effective_from <= today,
            or_(
                TeamMembership.effective_to.is_(None),
                TeamMembership.effective_to >= today,
            ),
        )
    return [
        _membership_out(row)
        for row in query.order_by(TeamMembership.effective_from.desc()).all()
    ]


@router.post("/riders/{courier_id}/team-transfer", status_code=201)
def transfer_rider_team(
    courier_id: int,
    payload: TeamTransfer,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, Courier, courier_id, tenant_id)
    target = _same_tenant(db, WorkforceTeam, payload.team_id, tenant_id)
    if not target.is_active:
        raise HTTPException(409, "Target team is inactive")
    future = (
        db.query(TeamMembership)
        .filter(
            TeamMembership.tenant_id == tenant_id,
            TeamMembership.courier_id == courier_id,
            TeamMembership.is_primary.is_(True),
            TeamMembership.effective_from > payload.effective_on,
        )
        .first()
    )
    if future:
        raise HTTPException(409, "A future primary membership already exists")
    active = _primary_overlap(
        db, tenant_id, courier_id, payload.effective_on, payload.effective_on
    )
    if active and active.team_id == target.id:
        raise HTTPException(409, "Rider is already assigned to the target team")
    if active:
        if active.effective_from >= payload.effective_on:
            raise HTTPException(409, "Transfer date conflicts with current membership")
        active.effective_to = payload.effective_on - timedelta(days=1)
    row = TeamMembership(
        tenant_id=tenant_id,
        team_id=target.id,
        courier_id=courier_id,
        effective_from=payload.effective_on,
        is_primary=True,
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    _audit(db, user, "transfer rider workforce team", "team_membership", row.id)
    _commit(db, "Team transfer conflicts with existing history")
    db.refresh(row)
    return _membership_out(row)


@router.post("/teams/{team_id}/supervisors", status_code=201)
def assign_team_supervisor(
    team_id: int,
    payload: SupervisorAssignmentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, WorkforceTeam, team_id, tenant_id)
    supervisor = _same_tenant(db, User, payload.supervisor_id, tenant_id)
    if supervisor.role != UserRole.SUPERVISOR or not supervisor.is_active:
        raise HTTPException(409, "Active supervisor account required")
    _validate_dates(payload.effective_from, payload.effective_to)
    requested_end = payload.effective_to or date.max
    existing = (
        db.query(TeamSupervisorAssignment)
        .filter(
            TeamSupervisorAssignment.tenant_id == tenant_id,
            TeamSupervisorAssignment.team_id == team_id,
            TeamSupervisorAssignment.supervisor_id == supervisor.id,
        )
        .all()
    )
    if any(
        row.effective_from <= requested_end
        and payload.effective_from <= (row.effective_to or date.max)
        for row in existing
    ):
        raise HTTPException(
            409, "Supervisor assignment overlaps an existing assignment"
        )
    row = TeamSupervisorAssignment(
        tenant_id=tenant_id,
        team_id=team_id,
        supervisor_id=supervisor.id,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    _audit(
        db,
        user,
        "assign supervisor to workforce team",
        "team_supervisor_assignment",
        row.id,
    )
    _commit(db, "Supervisor assignment already exists")
    db.refresh(row)
    return _supervisor_out(row)


@router.get("/teams/{team_id}/supervisors")
def list_team_supervisors(
    team_id: int,
    include_history: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = _tenant_id(user)
    _same_tenant(db, WorkforceTeam, team_id, tenant_id)
    query = db.query(TeamSupervisorAssignment).filter(
        TeamSupervisorAssignment.tenant_id == tenant_id,
        TeamSupervisorAssignment.team_id == team_id,
    )
    if not include_history:
        today = date.today()
        query = query.filter(
            TeamSupervisorAssignment.effective_from <= today,
            or_(
                TeamSupervisorAssignment.effective_to.is_(None),
                TeamSupervisorAssignment.effective_to >= today,
            ),
        )
    return [
        _supervisor_out(row)
        for row in query.order_by(TeamSupervisorAssignment.effective_from.desc()).all()
    ]

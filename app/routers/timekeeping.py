"""Timekeeping and attendance corrections — W1-E4."""

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from ..database import get_db
from ..models import entities as ent
from .auth import get_current_user

router = APIRouter(prefix="/timekeeping", tags=["timekeeping"])

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


# ---------- helpers ----------


def _tenant_id(user: ent.User, manage: bool = False) -> int:
    allowed = MANAGE_ROLES if manage else READ_ROLES
    if user.role not in allowed or not user.tenant_id:
        raise HTTPException(403, "Timekeeping access required")
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


def _parse_time(value: str) -> datetime:
    try:
        return datetime.strptime((value or "").strip(), "%H:%M")
    except ValueError:
        raise HTTPException(400, "وقت غير صالح — استخدم HH:MM")


# ---------- schemas ----------


class ShiftTemplateCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name_ar: str
    name_en: Optional[str] = None
    zone: Optional[str] = None
    start_time: str
    end_time: str
    required_couriers: int = 0


class ShiftTemplateUpdate(BaseModel):
    name_ar: Optional[str] = None
    name_en: Optional[str] = None
    zone: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    required_couriers: Optional[int] = None
    is_active: Optional[bool] = None


class GenerateOccurrences(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    from_date: date
    to_date: date


class WorkSessionStart(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    courier_id: int
    shift_occurrence_id: Optional[int] = None
    session_type: str = "WORK"  # WORK / BREAK


class WorkSessionEnd(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    session_id: int


class CorrectionRequestCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    courier_id: int
    attendance_id: Optional[int] = None
    requested_check_in: Optional[datetime] = None
    requested_check_out: Optional[datetime] = None
    reason: str


class CorrectionDecision(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    decision: str  # APPROVED / REJECTED
    note: Optional[str] = None


class OvertimeCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    courier_id: int
    shift_occurrence_id: Optional[int] = None
    overtime_date: date
    requested_minutes: int


class OvertimeDecision(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    decision: str  # APPROVED / REJECTED
    approved_minutes: int = 0
    note: Optional[str] = None


# ---------- shift templates ----------


@router.post("/templates", status_code=201)
def create_template(
    payload: ShiftTemplateCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _parse_time(payload.start_time)
    _parse_time(payload.end_time)
    existing = (
        db.query(ent.ShiftTemplate)
        .filter(
            ent.ShiftTemplate.tenant_id == tenant_id,
            ent.ShiftTemplate.code == payload.code,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Shift template code already exists")
    row = ent.ShiftTemplate(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


@router.get("/templates")
def list_templates(
    active_only: bool = Query(True),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.ShiftTemplate).filter(ent.ShiftTemplate.tenant_id == tenant_id)
    if active_only:
        q = q.filter(ent.ShiftTemplate.is_active.is_(True))
    return [
        {
            "id": r.id,
            "code": r.code,
            "name_ar": r.name_ar,
            "name_en": r.name_en,
            "start_time": r.start_time,
            "end_time": r.end_time,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.ShiftTemplate.code).all()
    ]


@router.patch("/templates/{template_id}")
def update_template(
    template_id: int,
    payload: ShiftTemplateUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.ShiftTemplate, template_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


# ---------- shift occurrences ----------


def _generate_occurrences(
    db, template: ent.ShiftTemplate, from_date: date, to_date: date
) -> list:
    """Generate dated occurrences for a template within a date range."""
    if from_date > to_date:
        raise HTTPException(400, "from_date must be before to_date")
    created = []
    current = from_date
    while current <= to_date:
        # Check if occurrence already exists
        existing = (
            db.query(ent.ShiftOccurrence)
            .filter(
                ent.ShiftOccurrence.shift_template_id == template.id,
                ent.ShiftOccurrence.occurrence_date == current,
            )
            .first()
        )
        if not existing:
            start_time = _parse_time(template.start_time).time()
            end_time = _parse_time(template.end_time).time()
            start_dt = datetime.combine(current, start_time)
            end_dt = datetime.combine(current, end_time)
            # Handle overnight shifts
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)
            occ = ent.ShiftOccurrence(
                tenant_id=template.tenant_id,
                shift_template_id=template.id,
                occurrence_date=current,
                start_datetime=start_dt,
                end_datetime=end_dt,
                required_couriers=template.required_couriers,
            )
            db.add(occ)
            created.append(occ)
        current += timedelta(days=1)
    return created


@router.post("/templates/{template_id}/generate", status_code=201)
def generate_occurrences(
    template_id: int,
    payload: GenerateOccurrences,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    template = _same_tenant(db, ent.ShiftTemplate, template_id, tenant_id)
    created = _generate_occurrences(db, template, payload.from_date, payload.to_date)
    db.commit()
    return {
        "generated": len(created),
        "from": payload.from_date.isoformat(),
        "to": payload.to_date.isoformat(),
    }


@router.get("/occurrences")
def list_occurrences(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.ShiftOccurrence).filter(ent.ShiftOccurrence.tenant_id == tenant_id)
    if from_date:
        q = q.filter(ent.ShiftOccurrence.occurrence_date >= from_date)
    if to_date:
        q = q.filter(ent.ShiftOccurrence.occurrence_date <= to_date)
    return [
        {
            "id": r.id,
            "shift_template_id": r.shift_template_id,
            "occurrence_date": r.occurrence_date.isoformat(),
            "start_datetime": r.start_datetime.isoformat(),
            "end_datetime": r.end_datetime.isoformat(),
            "status": r.status,
            "required_couriers": r.required_couriers,
        }
        for r in q.order_by(ent.ShiftOccurrence.occurrence_date).all()
    ]


# ---------- work sessions ----------


@router.post("/sessions/start", status_code=201)
def start_session(
    payload: WorkSessionStart,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.Courier, payload.courier_id, tenant_id)
    if payload.session_type not in ("WORK", "BREAK"):
        raise HTTPException(400, "session_type must be WORK or BREAK")
    # Check for existing open session
    open_session = (
        db.query(ent.WorkSession)
        .filter(
            ent.WorkSession.courier_id == payload.courier_id,
            ent.WorkSession.ended_at.is_(None),
        )
        .first()
    )
    if open_session:
        raise HTTPException(409, "Courier already has an open session")
    now = datetime.utcnow()
    session = ent.WorkSession(
        tenant_id=tenant_id,
        courier_id=payload.courier_id,
        shift_occurrence_id=payload.shift_occurrence_id,
        session_type=payload.session_type,
        started_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "id": session.id,
        "courier_id": session.courier_id,
        "session_type": session.session_type,
        "started_at": session.started_at.isoformat(),
    }


@router.post("/sessions/end", status_code=201)
def end_session(
    payload: WorkSessionEnd,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    session = _same_tenant(db, ent.WorkSession, payload.session_id, tenant_id)
    if session.ended_at:
        raise HTTPException(409, "Session already ended")
    now = datetime.utcnow()
    session.ended_at = now
    session.duration_minutes = int((now - session.started_at).total_seconds() // 60)
    db.commit()
    db.refresh(session)
    return {
        "id": session.id,
        "duration_minutes": session.duration_minutes,
        "ended_at": session.ended_at.isoformat(),
    }


@router.get("/sessions/{courier_id}")
def list_sessions(
    courier_id: int,
    on_date: Optional[date] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    _same_tenant(db, ent.Courier, courier_id, tenant_id)
    q = db.query(ent.WorkSession).filter(
        ent.WorkSession.tenant_id == tenant_id,
        ent.WorkSession.courier_id == courier_id,
    )
    if on_date:
        q = q.filter(
            ent.WorkSession.started_at
            >= datetime.combine(on_date, datetime.min.time()),
            ent.WorkSession.started_at
            < datetime.combine(on_date + timedelta(days=1), datetime.min.time()),
        )
    return [
        {
            "id": r.id,
            "session_type": r.session_type,
            "started_at": r.started_at.isoformat(),
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "duration_minutes": r.duration_minutes,
        }
        for r in q.order_by(ent.WorkSession.started_at.desc()).all()
    ]


# ---------- attendance correction requests ----------


@router.post("/corrections", status_code=201)
def create_correction(
    payload: CorrectionRequestCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.Courier, payload.courier_id, tenant_id)
    if not payload.reason or not payload.reason.strip():
        raise HTTPException(400, "Reason is required")
    row = ent.AttendanceCorrectionRequest(
        tenant_id=tenant_id,
        courier_id=payload.courier_id,
        attendance_id=payload.attendance_id,
        requested_check_in=payload.requested_check_in,
        requested_check_out=payload.requested_check_out,
        reason=payload.reason,
        requested_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "courier_id": row.courier_id, "status": row.status}


@router.get("/corrections")
def list_corrections(
    status_filter: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.AttendanceCorrectionRequest).filter(
        ent.AttendanceCorrectionRequest.tenant_id == tenant_id
    )
    if status_filter:
        q = q.filter(ent.AttendanceCorrectionRequest.status == status_filter)
    return [
        {
            "id": r.id,
            "courier_id": r.courier_id,
            "status": r.status,
            "reason": r.reason,
            "requested_check_in": r.requested_check_in.isoformat()
            if r.requested_check_in
            else None,
            "requested_check_out": r.requested_check_out.isoformat()
            if r.requested_check_out
            else None,
            "decided_by": r.decided_by,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        }
        for r in q.order_by(ent.AttendanceCorrectionRequest.created_at.desc()).all()
    ]


@router.post("/corrections/{correction_id}/decide", status_code=200)
def decide_correction(
    correction_id: int,
    payload: CorrectionDecision,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.AttendanceCorrectionRequest, correction_id, tenant_id)
    if row.status != "PENDING":
        raise HTTPException(409, "Correction already decided")
    if payload.decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(400, "decision must be APPROVED or REJECTED")
    row.status = payload.decision
    row.decided_by = user.id
    row.decided_at = datetime.utcnow()
    row.decision_note = payload.note
    db.commit()
    db.refresh(row)
    return {"id": row.id, "status": row.status, "decided_by": row.decided_by}


# ---------- overtime ----------


@router.post("/overtime", status_code=201)
def create_overtime(
    payload: OvertimeCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.Courier, payload.courier_id, tenant_id)
    if payload.requested_minutes <= 0:
        raise HTTPException(400, "requested_minutes must be positive")
    row = ent.Overtime(
        tenant_id=tenant_id,
        courier_id=payload.courier_id,
        shift_occurrence_id=payload.shift_occurrence_id,
        overtime_date=payload.overtime_date,
        requested_minutes=payload.requested_minutes,
        requested_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "courier_id": row.courier_id,
        "status": row.status,
        "requested_minutes": row.requested_minutes,
    }


@router.get("/overtime")
def list_overtime(
    status_filter: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.Overtime).filter(ent.Overtime.tenant_id == tenant_id)
    if status_filter:
        q = q.filter(ent.Overtime.status == status_filter)
    return [
        {
            "id": r.id,
            "courier_id": r.courier_id,
            "overtime_date": r.overtime_date.isoformat(),
            "requested_minutes": r.requested_minutes,
            "approved_minutes": r.approved_minutes,
            "status": r.status,
        }
        for r in q.order_by(ent.Overtime.created_at.desc()).all()
    ]


@router.post("/overtime/{overtime_id}/decide", status_code=200)
def decide_overtime(
    overtime_id: int,
    payload: OvertimeDecision,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.Overtime, overtime_id, tenant_id)
    if row.status != "PENDING":
        raise HTTPException(409, "Overtime already decided")
    if payload.decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(400, "decision must be APPROVED or REJECTED")
    row.status = payload.decision
    row.approved_minutes = (
        payload.approved_minutes if payload.decision == "APPROVED" else 0
    )
    row.approved_by = user.id
    row.approved_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "status": row.status,
        "approved_minutes": row.approved_minutes,
    }

from datetime import datetime, timedelta
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import Attendance, ContractBranch, Courier, Shift, User, UserRole
from ..schemas.dou import AttendanceIn, ShiftCreate
from .auth import get_current_user
from ..services.attendance_policy import record_attendance_event


def _any_user(user: User = Depends(get_current_user)):
    return user


router = APIRouter(prefix="/shifts", tags=["shifts"], dependencies=[Depends(_any_user)])

STAFF_ROLES = (
    UserRole.COMPANY,
    UserRole.COMPANY_ADMIN,
    UserRole.OPERATIONS,
    UserRole.HR,
    UserRole.SUPERVISOR,
    UserRole.DOU_OPS,
    UserRole.DOU_ADMIN,
)


def _require_attendance_location(payload: AttendanceIn):
    if payload.lat is None or payload.lng is None:
        raise HTTPException(422, "لا يمكن تسجيل الحضور أو الانصراف بدون موقع GPS")
    if not (-90 <= payload.lat <= 90 and -180 <= payload.lng <= 180):
        raise HTTPException(422, "إحداثيات GPS غير صالحة")


def _parse_shift_time(value: str):
    try:
        return datetime.strptime((value or "").strip(), "%H:%M").time()
    except ValueError:
        raise HTTPException(400, "وقت الوردية غير صالح — استخدم HH:MM")


def _shift_window(shift: Shift, reference: datetime):
    """نافذة الوردية المتكررة حول وقت مرجعي؛ تدعم الورديات التي تعبر منتصف الليل."""
    start_time = _parse_shift_time(shift.start_time)
    end_time = _parse_shift_time(shift.end_time)
    start = datetime.combine(reference.date(), start_time)
    end = datetime.combine(reference.date(), end_time)
    overnight = end <= start
    if overnight:
        end += timedelta(days=1)
        # بعد منتصف الليل وحتى وقت نهاية الوردية، الوردية بدأت في اليوم السابق.
        if reference < datetime.combine(reference.date(), end_time):
            start -= timedelta(days=1)
            end -= timedelta(days=1)
    return start, end, overnight


def _assigned_courier_ids(shift: Shift):
    try:
        return {int(x) for x in json.loads(shift.courier_ids or "[]")}
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()


def _has_overlap(
    db: Session, tenant_id: int, courier_id: int, target_shift: Shift, exclude_shift_id: int = 0
) -> bool:
    """Check whether assigning courier_id to target_shift overlaps with another active shift."""
    target_start = _parse_shift_time(target_shift.start_time)
    target_end = _parse_shift_time(target_shift.end_time)
    today = datetime.now().date()
    target_start_dt = datetime.combine(today, target_start)
    target_end_dt = datetime.combine(today, target_end)
    if target_end_dt <= target_start_dt:
        target_end_dt += timedelta(days=1)

    for shift in (
        db.query(Shift)
        .filter(
            Shift.tenant_id == tenant_id,
            Shift.id != exclude_shift_id,
        )
        .all()
    ):
        assigned = _assigned_courier_ids(shift)
        if courier_id not in assigned:
            continue
        start_dt, end_dt, _ = _shift_window(shift, target_start_dt)
        if target_start_dt < end_dt and target_end_dt > start_dt:
            return True
    return False


def _scheduled_shift_for(db: Session, courier: Courier, reference: datetime):
    """يختار أقرب وردية مسندة للمندوب؛ ولا يسمح بربط وردية تخص زميله."""
    shifts = db.query(Shift).filter(Shift.tenant_id == courier.tenant_id).all()
    candidates = [s for s in shifts if courier.id in _assigned_courier_ids(s)]
    if not candidates:
        return None
    ranked = []
    for shift in candidates:
        start, end, _ = _shift_window(shift, reference)
        distance = min(
            abs((reference - start).total_seconds()),
            abs((reference - end).total_seconds()),
        )
        ranked.append((distance, shift))
    return min(ranked, key=lambda item: item[0])[1]


def _shift_status(db: Session, shift: Shift, now: datetime):
    if (
        db.query(Attendance)
        .filter(Attendance.shift_id == shift.id, Attendance.check_out.is_(None))
        .first()
    ):
        return "ACTIVE"
    start, end, _ = _shift_window(shift, now)
    if start <= now < end:
        return "ACTIVE"
    if now >= end and now < start + timedelta(days=1):
        return "COMPLETED"
    return "SCHEDULED"


def _shift_json(db: Session, shift: Shift, reference: datetime):
    start, end, overnight = _shift_window(shift, reference)
    return {
        "id": shift.id,
        "name": shift.name,
        "zone": shift.zone or "",
        "start_time": shift.start_time,
        "end_time": shift.end_time,
        "required_couriers": shift.required_couriers or 0,
        "courier_ids": sorted(_assigned_courier_ids(shift)),
        "scheduled_start": start.isoformat(),
        "scheduled_end": end.isoformat(),
        "overnight": overnight,
        "duration_hours": round((end - start).total_seconds() / 3600, 2),
        "status": _shift_status(db, shift, reference),
    }


def _supervisor_courier_ids(
    db: Session, supervisor_id: int, tenant_id: int
) -> set[int]:
    branch_ids = db.query(ContractBranch.id).filter(
        ContractBranch.tenant_id == tenant_id,
        ContractBranch.supervisor_id == supervisor_id,
    )
    rows = (
        db.query(Courier.id)
        .filter(
            Courier.tenant_id == tenant_id,
            or_(
                Courier.supervisor_id == supervisor_id,
                and_(
                    Courier.supervisor_id.is_(None),
                    Courier.contract_branch_id.in_(branch_ids),
                ),
            ),
        )
        .all()
    )
    return {row[0] for row in rows}


def _courier_for(user: User, courier_id: int, db: Session):
    courier = db.get(Courier, courier_id)
    if not courier:
        raise HTTPException(404, "Courier not found")
    if user.role == UserRole.COURIER and user.courier_id == courier_id:
        return courier
    if user.role in STAFF_ROLES and (
        user.role in (UserRole.DOU_OPS, UserRole.DOU_ADMIN)
        or user.tenant_id == courier.tenant_id
    ):
        if user.role == UserRole.SUPERVISOR:
            branch = (
                db.get(ContractBranch, courier.contract_branch_id)
                if courier.contract_branch_id
                else None
            )
            if courier.supervisor_id != user.id and not (
                courier.supervisor_id is None
                and branch
                and branch.supervisor_id == user.id
            ):
                raise HTTPException(404, "Courier not found")
        return courier
    raise HTTPException(404, "Courier not found")


@router.post("")
def create_shift(
    payload: ShiftCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Not authorized")
    _parse_shift_time(payload.start_time)
    _parse_shift_time(payload.end_time)
    courier_ids = {int(x) for x in (payload.courier_ids or [])}
    if payload.required_couriers < 0:
        raise HTTPException(400, "عدد المناديب المطلوب لا يمكن أن يكون سالباً")
    if courier_ids:
        valid = {
            c.id
            for c in db.query(Courier).filter(Courier.tenant_id == user.tenant_id).all()
        }
        if user.role == UserRole.SUPERVISOR:
            valid &= _supervisor_courier_ids(db, user.id, user.tenant_id)
        if not courier_ids.issubset(valid):
            raise HTTPException(400, "يوجد مندوب خارج نطاق الشركة أو فريق المشرف")
    shift = Shift(
        **payload.model_dump(exclude={"courier_ids"}),
        tenant_id=user.tenant_id,
        courier_ids=json.dumps(sorted(courier_ids)),
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return _shift_json(db, shift, datetime.utcnow())


@router.get("")
def list_shifts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Not authorized")
    q = db.query(Shift)
    if user.role not in (UserRole.DOU_OPS, UserRole.DOU_ADMIN):
        q = q.filter(Shift.tenant_id == user.tenant_id)
    shifts = q.all()
    if user.role == UserRole.SUPERVISOR:
        allowed = _supervisor_courier_ids(db, user.id, user.tenant_id)
        shifts = [shift for shift in shifts if _assigned_courier_ids(shift) & allowed]
    return [_shift_json(db, shift, datetime.utcnow()) for shift in shifts]


@router.get("/me")
def my_shifts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != UserRole.COURIER or not user.courier_id:
        raise HTTPException(403, "Courier account required")
    courier = _courier_for(user, user.courier_id, db)
    now = datetime.utcnow()
    all_shifts = db.query(Shift).filter(Shift.tenant_id == courier.tenant_id).all()

    my_assigned = []
    available_shifts = []

    for s in all_shifts:
        assigned_ids = _assigned_courier_ids(s)
        is_assigned = courier.id in assigned_ids
        slots_req = s.required_couriers or 0
        slots_left = max(0, slots_req - len(assigned_ids)) if slots_req > 0 else 999

        info = _shift_json(db, s, now)
        info["is_assigned"] = is_assigned
        info["assigned_count"] = len(assigned_ids)
        info["slots_available"] = slots_left

        if is_assigned:
            my_assigned.append(info)
        available_shifts.append(info)

    active = next(
        (row for row in my_assigned if row["status"] == "ACTIVE"),
        (my_assigned[0] if my_assigned else None),
    )
    return {"current": active, "shifts": my_assigned, "available": available_shifts}


@router.post("/{shift_id}/claim")
def claim_shift(
    shift_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Allows a courier to select/claim an available shift directly from the mobile app."""
    if user.role != UserRole.COURIER or not user.courier_id:
        raise HTTPException(403, "Courier account required")
    courier = _courier_for(user, user.courier_id, db)
    shift = (
        db.query(Shift)
        .filter(Shift.id == shift_id, Shift.tenant_id == courier.tenant_id)
        .with_for_update()
        .first()
    )
    if not shift:
        raise HTTPException(404, "Shift not found")

    assigned = _assigned_courier_ids(shift)
    if courier.id in assigned:
        return {"ok": True, "already_assigned": True, "shift_id": shift.id}

    # Capacity check
    if shift.required_couriers and len(assigned) >= shift.required_couriers:
        raise HTTPException(409, "الوردية ممتلئة — لا توجد أماكن شاغرة")

    # Overlap check
    if _has_overlap(
        db, courier.tenant_id, courier.id, shift, exclude_shift_id=shift.id
    ):
        raise HTTPException(409, "لديك وردية متداخلة مع هذا الموعد بالفعل")

    assigned.add(courier.id)
    shift.courier_ids = json.dumps(sorted(assigned))
    db.commit()
    return {"ok": True, "claimed": True, "shift_id": shift.id, "courier_id": courier.id}


@router.post("/{shift_id}/drop")
def drop_shift(
    shift_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Allows a courier to release/drop an assigned shift."""
    if user.role != UserRole.COURIER or not user.courier_id:
        raise HTTPException(403, "Courier account required")
    courier = _courier_for(user, user.courier_id, db)
    shift = db.get(Shift, shift_id)
    if not shift or shift.tenant_id != courier.tenant_id:
        raise HTTPException(404, "Shift not found")

    assigned = _assigned_courier_ids(shift)
    assigned.discard(courier.id)
    shift.courier_ids = json.dumps(sorted(assigned))
    db.commit()
    return {"ok": True, "dropped": True, "shift_id": shift.id, "courier_id": courier.id}


@router.post("/{shift_id}/start")
def start_shift(
    shift_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Not authorized")
    shift = db.get(Shift, shift_id)
    if not shift or (
        user.role not in (UserRole.DOU_OPS, UserRole.DOU_ADMIN)
        and shift.tenant_id != user.tenant_id
    ):
        raise HTTPException(404, "Shift not found")
    if user.role == UserRole.SUPERVISOR and not _assigned_courier_ids(shift).issubset(
        _supervisor_courier_ids(db, user.id, user.tenant_id)
    ):
        raise HTTPException(404, "Shift not found")
    shift.status = "ACTIVE"
    db.commit()
    return {"ok": True}


@router.post("/attendance/check-in")
def check_in(
    payload: AttendanceIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_attendance_location(payload)
    courier = _courier_for(user, payload.courier_id, db)
    if courier.employment_status != "ACTIVE":
        raise HTTPException(403, "Courier is not active for attendance")
    existing = (
        db.query(Attendance)
        .filter(Attendance.courier_id == courier.id, Attendance.check_out.is_(None))
        .order_by(Attendance.id.desc())
        .first()
    )
    if existing:
        return {
            "ok": True,
            "attendance_id": existing.id,
            "shift_id": existing.shift_id,
            "already_checked_in": True,
        }
    now = datetime.utcnow()
    shift = _scheduled_shift_for(db, courier, now)
    late_minutes = 0
    if shift:
        start, _, _ = _shift_window(shift, now)
        late_minutes = max(0, int((now - start).total_seconds() // 60))
    record = Attendance(
        courier_id=courier.id,
        shift_id=shift.id if shift else None,
        check_in=now,
        check_in_lat=payload.lat,
        check_in_lng=payload.lng,
        is_late=late_minutes > 0,
    )
    db.add(record)
    db.flush()
    if late_minutes > 0:
        record_attendance_event(
            db,
            courier,
            "LATE",
            now.date(),
            late_minutes,
            attendance_id=record.id,
            shift_id=record.shift_id,
            actor_id=user.id,
            note=f"تأخر محسوب من الوردية: {late_minutes} دقيقة",
        )
    courier.is_online = True
    courier.shift_active = True
    db.commit()
    db.refresh(record)
    return {
        "ok": True,
        "attendance_id": record.id,
        "shift_id": record.shift_id,
        "late_minutes": late_minutes,
        "is_late": record.is_late,
    }


@router.post("/attendance/check-out")
def check_out(
    payload: AttendanceIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_attendance_location(payload)
    courier = _courier_for(user, payload.courier_id, db)
    if courier.employment_status != "ACTIVE":
        raise HTTPException(403, "Courier is not active for attendance")
    record = (
        db.query(Attendance)
        .filter(Attendance.courier_id == courier.id, Attendance.check_out.is_(None))
        .order_by(Attendance.id.desc())
        .first()
    )
    if not record:
        raise HTTPException(404, "No open attendance")
    now = datetime.utcnow()
    record.check_out = now
    record.check_out_lat = payload.lat
    record.check_out_lng = payload.lng
    scheduled_end = None
    early_leave_minutes = 0
    if record.shift_id:
        shift = db.get(Shift, record.shift_id)
        if shift:
            _, scheduled_end, _ = _shift_window(shift, record.check_in or now)
            early_leave_minutes = max(
                0, int((scheduled_end - now).total_seconds() // 60)
            )
    if early_leave_minutes > 0:
        record_attendance_event(
            db,
            courier,
            "EARLY_LEAVE",
            (record.check_in or now).date(),
            early_leave_minutes,
            attendance_id=record.id,
            shift_id=record.shift_id,
            actor_id=user.id,
            note=f"انصراف مبكر محسوب من الوردية: {early_leave_minutes} دقيقة",
        )
    courier.is_online = False
    courier.shift_active = False
    db.commit()
    return {
        "ok": True,
        "attendance_id": record.id,
        "shift_id": record.shift_id,
        "worked_hours": round((now - record.check_in).total_seconds() / 3600, 2),
        "scheduled_end": scheduled_end.isoformat() if scheduled_end else None,
        "early_leave_minutes": early_leave_minutes,
    }

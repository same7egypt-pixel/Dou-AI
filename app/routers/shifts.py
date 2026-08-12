from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import Attendance, Courier, Shift, User, UserRole
from ..schemas.dou import AttendanceIn, ShiftCreate
from .auth import get_current_user

def _any_user(user: User = Depends(get_current_user)):
    return user

router = APIRouter(prefix="/shifts", tags=["shifts"], dependencies=[Depends(_any_user)])

STAFF_ROLES = (UserRole.COMPANY, UserRole.COMPANY_ADMIN, UserRole.OPERATIONS,
               UserRole.HR, UserRole.DOU_OPS, UserRole.DOU_ADMIN)


def _courier_for(user: User, courier_id: int, db: Session):
    courier = db.get(Courier, courier_id)
    if not courier:
        raise HTTPException(404, "Courier not found")
    if user.role == UserRole.COURIER and user.courier_id == courier_id:
        return courier
    if user.role in STAFF_ROLES and (user.role in (UserRole.DOU_OPS, UserRole.DOU_ADMIN) or user.tenant_id == courier.tenant_id):
        return courier
    raise HTTPException(404, "Courier not found")


@router.post("")
def create_shift(payload: ShiftCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Not authorized")
    shift = Shift(**payload.model_dump(), tenant_id=user.tenant_id)
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


@router.get("")
def list_shifts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Not authorized")
    q = db.query(Shift)
    if user.role not in (UserRole.DOU_OPS, UserRole.DOU_ADMIN):
        q = q.filter(Shift.tenant_id == user.tenant_id)
    return q.all()


@router.post("/{shift_id}/start")
def start_shift(shift_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Not authorized")
    shift = db.get(Shift, shift_id)
    if not shift or (user.role not in (UserRole.DOU_OPS, UserRole.DOU_ADMIN) and shift.tenant_id != user.tenant_id):
        raise HTTPException(404, "Shift not found")
    shift.status = "ACTIVE"
    db.commit()
    return {"ok": True}


@router.post("/attendance/check-in")
def check_in(payload: AttendanceIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    courier = _courier_for(user, payload.courier_id, db)
    existing = db.query(Attendance).filter(Attendance.courier_id == courier.id,
                                            Attendance.check_out.is_(None)).order_by(Attendance.id.desc()).first()
    if existing:
        return {"ok": True, "attendance_id": existing.id, "already_checked_in": True}
    record = Attendance(
        courier_id=courier.id,
        check_in=datetime.utcnow(),
        check_in_lat=payload.lat,
        check_in_lng=payload.lng,
        is_late=payload.is_late,
    )
    db.add(record)
    courier.is_online = True
    courier.shift_active = True
    db.commit()
    db.refresh(record)
    return {"ok": True, "attendance_id": record.id}


@router.post("/attendance/check-out")
def check_out(payload: AttendanceIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    courier = _courier_for(user, payload.courier_id, db)
    record = db.query(Attendance).filter(
        Attendance.courier_id == courier.id, Attendance.check_out.is_(None)
    ).order_by(Attendance.id.desc()).first()
    if not record:
        raise HTTPException(404, "No open attendance")
    record.check_out = datetime.utcnow()
    record.check_out_lat = payload.lat
    record.check_out_lng = payload.lng
    courier.is_online = False
    courier.shift_active = False
    db.commit()
    return {"ok": True, "attendance_id": record.id}

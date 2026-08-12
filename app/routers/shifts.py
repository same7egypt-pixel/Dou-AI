from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import Attendance, Courier, Shift, User
from ..schemas.dou import AttendanceIn, ShiftCreate
from .auth import get_current_user

def _any_user(user: User = Depends(get_current_user)):
    return user

router = APIRouter(prefix="/shifts", tags=["shifts"], dependencies=[Depends(_any_user)])


@router.post("")
def create_shift(payload: ShiftCreate, db: Session = Depends(get_db)):
    shift = Shift(**payload.model_dump())
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


@router.get("")
def list_shifts(db: Session = Depends(get_db)):
    return db.query(Shift).all()


@router.post("/{shift_id}/start")
def start_shift(shift_id: int, db: Session = Depends(get_db)):
    shift = db.get(Shift, shift_id)
    if not shift:
        raise HTTPException(404, "Shift not found")
    shift.status = "ACTIVE"
    db.commit()
    return {"ok": True}


@router.post("/attendance/check-in")
def check_in(payload: AttendanceIn, db: Session = Depends(get_db)):
    courier = db.get(Courier, payload.courier_id)
    if not courier:
        raise HTTPException(404, "Courier not found")
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
def check_out(payload: AttendanceIn, db: Session = Depends(get_db)):
    courier = db.get(Courier, payload.courier_id)
    if not courier:
        raise HTTPException(404, "Courier not found")
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

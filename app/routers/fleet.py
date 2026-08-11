from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import (
    Attendance, Courier, CourierTask, CourierTaskStatus, Merchant,
    Order, OrderStatus, Shift, ShiftStatus, Tenant, User, UserRole, Fleet,
)
from .auth import get_current_user

router = APIRouter(prefix="/fleet", tags=["fleet"])

COMPANY_ROLES = (UserRole.COMPANY, UserRole.DOU_OPS, UserRole.DOU_ADMIN)


def _scope(user: User, db: Session):
    """يعيد نطاق البيانات (tenant) حسب نوع الحساب:
    - COMPANY: مناديب وطلبات شركته فقط
    - DOU_OPS/DOU_ADMIN: كل البيانات"""
    if user.role == UserRole.COMPANY:
        return user.tenant_id
    return None


def _courier_ids(db: Session, tenant_id):
    if tenant_id is None:
        return {c.id for c in db.query(Courier).all()}
    return {c.id for c in db.query(Courier).filter(Courier.tenant_id == tenant_id).all()}


@router.get("/me")
def fleet_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """معلومات حساب الشركة + أساطيلها."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None
    fleets = []
    if tenant:
        for f in db.query(Fleet).filter(Fleet.tenant_id == tenant.id).all():
            fleets.append({"id": f.id, "name": f.name, "zone": f.zone or ""})
    return {
        "role": user.role.value,
        "tenant": {"id": tenant.id, "name": tenant.name, "country": tenant.country.value} if tenant else None,
        "fleets": fleets,
        "name": user.name or (tenant.name if tenant else "شركة"),
    }


@router.get("/overview")
def fleet_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """مؤشرات تشغيلية في نطاق الشركة."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant_id = _scope(user, db)
    ids = _courier_ids(db, tenant_id)
    couriers = db.query(Courier).filter(Courier.id.in_(ids)).all() if ids else []

    orders = db.query(Order).filter(Order.courier_id.in_(ids)).all() if ids else []
    orders = [o for o in orders if o.courier_id in ids]
    tasks = db.query(CourierTask).filter(CourierTask.courier_id.in_(ids)).all() if ids else []

    delivered = [t for t in tasks if t.status == CourierTaskStatus.DELIVERED]
    active_st = {OrderStatus.READY, OrderStatus.ACCEPTED, OrderStatus.ASSIGNED, OrderStatus.IN_TRANSIT, OrderStatus.PICKED_UP}
    unassigned = db.query(Order).filter(Order.courier_id.is_(None), Order.status == OrderStatus.PLACED).count()
    if tenant_id is not None:
        unassigned = 0

    return {
        "couriers_total": len(couriers),
        "couriers_online": sum(1 for c in couriers if c.is_online),
        "orders_total": len(orders),
        "orders_active": sum(1 for o in orders if o.status in active_st),
        "orders_unassigned": unassigned,
        "deliveries_done": len(delivered),
        "revenue_total": round(sum(o.total for o in orders), 2),
        "avg_acceptance": round(sum(c.acceptance_rate for c in couriers) / len(couriers), 1) if couriers else 0,
        "avg_score": round(sum(c.score for c in couriers) / len(couriers), 2) if couriers else 0,
        "on_time_rate": round(sum(c.on_time_rate for c in couriers) / len(couriers), 1) if couriers else 0,
        "company_couriers": sum(1 for c in couriers if c.courier_type.value == "COMPANY"),
        "freelance_couriers": sum(1 for c in couriers if c.courier_type.value == "FREELANCER"),
        "shifts_active": db.query(Shift).filter(Shift.tenant_id == user.tenant_id, Shift.status == ShiftStatus.ACTIVE).count() if user.tenant_id else db.query(Shift).count(),
    }


@router.get("/couriers")
def fleet_couriers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant_id = _scope(user, db)
    q = db.query(Courier)
    if tenant_id is not None:
        q = q.filter(Courier.tenant_id == tenant_id)
    return [
        {
            "id": c.id, "name": c.name, "phone": c.phone,
            "courier_type": c.courier_type.value, "country": c.country.value,
            "is_online": c.is_online, "is_available": c.is_available,
            "current_load": c.current_load, "acceptance_rate": c.acceptance_rate,
            "on_time_rate": c.on_time_rate, "completion_rate": c.completion_rate,
            "score": c.score, "documents_valid": c.documents_valid, "shift_active": c.shift_active,
            "lat": c.lat, "lng": c.lng,
            "fleet": (db.get(Fleet, c.fleet_id).name if c.fleet_id else None),
        }
        for c in q.all()
    ]


@router.get("/orders")
def fleet_orders(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant_id = _scope(user, db)
    ids = _courier_ids(db, tenant_id)
    orders = db.query(Order).filter(Order.courier_id.in_(ids)).all() if ids else []
    couriers = {c.id: c.name for c in db.query(Courier).all()}
    merchants = {m.id: m.name for m in db.query(Merchant).all()}
    return [
        {
            "id": o.id, "customer_name": o.customer_name, "customer_address": o.customer_address,
            "merchant_name": merchants.get(o.merchant_id),
            "status": o.status.value, "delivery_method": o.delivery_method.value,
            "distance_km": o.distance_km, "total": o.total,
            "courier_name": couriers.get(o.courier_id), "courier_id": o.courier_id,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in sorted(orders, key=lambda x: x.id, reverse=True)
    ]


@router.get("/shifts")
def fleet_shifts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    q = db.query(Shift)
    if user.tenant_id is not None:
        q = q.filter(Shift.tenant_id == user.tenant_id)
    return [
        {
            "id": s.id, "name": s.name, "zone": s.zone or "", "fleet_id": s.fleet_id,
            "fleet": (db.get(Fleet, s.fleet_id).name if s.fleet_id else None),
            "start_time": s.start_time, "end_time": s.end_time,
            "required_couriers": s.required_couriers,
            "status": s.status.value if hasattr(s.status, "value") else s.status,
        }
        for s in q.all()
    ]


@router.get("/attendance")
def fleet_attendance(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant_id = _scope(user, db)
    ids = _courier_ids(db, tenant_id)
    records = db.query(Attendance).filter(Attendance.courier_id.in_(ids)).all() if ids else []
    couriers = {c.id: c.name for c in db.query(Courier).all()}
    rows = []
    for a in records:
        hours = None
        if a.check_in and a.check_out:
            hours = round((a.check_out - a.check_in).total_seconds() / 3600, 1)
        rows.append({
            "name": couriers.get(a.courier_id),
            "check_in": a.check_in.isoformat() if a.check_in else None,
            "check_out": a.check_out.isoformat() if a.check_out else None,
            "hours": hours,
            "is_late": a.is_late,
        })
    return rows

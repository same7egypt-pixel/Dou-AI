from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import csv, io

from ..database import get_db
from ..models.entities import (
    Attendance, AppSetting, Contract, Courier, CourierTask, CourierTaskStatus, Country, CourierType, Merchant,
    Order, OrderStatus, Shift, ShiftStatus, SupportTicket, Tenant, User, UserRole, Fleet,
)
from .auth import get_current_user

router = APIRouter(prefix="/fleet", tags=["fleet"])

COMPANY_ROLES = (UserRole.COMPANY, UserRole.DOU_OPS, UserRole.DOU_ADMIN)


def _scope(user: User, db: Session):
    """يعيد نطاق البيانات (tenant) حسب نوع الحساب:
    - COMPANY: مناديب وطلبات شركته فقط
    - DOU_OPS/DOU_ADMIN: كل البيانات"""
    if user.role == UserRole.COMPANY:
        from .billing import check_active
        check_active(user, db)
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
            "base_salary": c.base_salary or 0, "per_delivery_rate": c.per_delivery_rate or 0,
            "bonus_target": c.bonus_target or 0, "employment_status": c.employment_status or "ACTIVE",
            "hired_at": c.hired_at.isoformat() if c.hired_at else None,
            "bank_iban": c.bank_iban,
            "fleet": (db.get(Fleet, c.fleet_id).name if c.fleet_id else None),
        }
        for c in q.all()
    ]


@router.post("/couriers")
def add_courier(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """إضافة مندوب جديد + إنشاء حساب دخول له في تطبيق السواقين.
    يُرجع كلمة المرور المبدئية (ترسلها الشركة للمندوب)."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    if not name or not phone:
        raise HTTPException(400, "Name and phone are required")
    if db.query(Courier).filter(Courier.phone == phone).first():
        raise HTTPException(400, "Courier phone already exists")
    country = Country(payload.get("country") or "SA")
    ctype = CourierType(payload.get("courier_type") or "COMPANY")
    tenant_id = user.tenant_id
    fleet = db.query(Fleet).filter(Fleet.tenant_id == tenant_id).first() if tenant_id else None
    courier = Courier(
        tenant_id=tenant_id, fleet_id=fleet.id if fleet else None,
        name=name, phone=phone, courier_type=ctype, country=country,
        lat=payload.get("lat"), lng=payload.get("lng"),
        base_salary=float(payload.get("base_salary") or 0),
        per_delivery_rate=float(payload.get("per_delivery_rate") or 0),
        bonus_target=float(payload.get("bonus_target") or 0),
        bank_iban=payload.get("bank_iban"),
    )
    db.add(courier)
    db.flush()
    password = payload.get("password") or "dou123456"
    from .auth import hash_password
    db.add(User(
        phone="966" + phone.lstrip("0") if not phone.startswith("966") else phone,
        name=name, password_hash=hash_password(password),
        role=UserRole.COURIER, courier_id=courier.id,
        tenant_id=tenant_id, country=country, is_active=True,
    ))
    db.commit()
    db.refresh(courier)
    login_phone = courier.phone if courier.phone.startswith("966") else "966" + courier.phone.lstrip("0")
    return {"ok": True, "id": courier.id, "login_phone": login_phone, "password": password}


@router.patch("/couriers/{cid}")
def update_courier(cid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """تعديل بيانات مندوب (راتب، بونص، حالة توظيف، مستندات…)."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    courier = db.get(Courier, cid)
    if not courier:
        raise HTTPException(404, "Courier not found")
    allowed = {
        "name", "phone", "courier_type", "base_salary", "per_delivery_rate",
        "bonus_target", "employment_status", "bank_iban", "documents_valid",
        "is_online", "is_available", "shift_active", "lat", "lng",
    }
    for k, v in payload.items():
        if k in allowed:
            setattr(courier, k, v)
    db.commit()
    return {"ok": True}


@router.get("/couriers/{cid}")
def courier_profile(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """ملف مندوب كامل: بيانات + مهام + حضور + أرباح (HR)."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    courier = db.get(Courier, cid)
    if not courier:
        raise HTTPException(404, "Courier not found")
    tasks = db.query(CourierTask).filter(CourierTask.courier_id == cid).all()
    delivered = [t for t in tasks if t.status == CourierTaskStatus.DELIVERED]
    attendances = db.query(Attendance).filter(Attendance.courier_id == cid).all()
    hours = 0.0
    for a in attendances:
        if a.check_in and a.check_out:
            hours += (a.check_out - a.check_in).total_seconds() / 3600
    per_delivery = courier.per_delivery_rate or 0
    bonus = courier.bonus_target or 0
    if bonus and delivered and courier.score and courier.score >= 4.7:
        bonus = round(bonus * 0.8, 2)
    return {
        "id": courier.id, "name": courier.name, "phone": courier.phone,
        "courier_type": courier.courier_type.value, "country": courier.country.value,
        "is_online": courier.is_online, "is_available": courier.is_available,
        "current_load": courier.current_load, "acceptance_rate": courier.acceptance_rate,
        "on_time_rate": courier.on_time_rate, "completion_rate": courier.completion_rate,
        "score": courier.score, "documents_valid": courier.documents_valid,
        "shift_active": courier.shift_active, "lat": courier.lat, "lng": courier.lng,
        "base_salary": courier.base_salary or 0, "per_delivery_rate": per_delivery,
        "bonus_target": courier.bonus_target or 0, "bonus_earned": bonus,
        "employment_status": courier.employment_status or "ACTIVE",
        "hired_at": courier.hired_at.isoformat() if courier.hired_at else None,
        "bank_iban": courier.bank_iban,
        "deliveries_done": len(delivered),
        "deliveries_total": len(tasks),
        "hours_worked": round(hours, 1),
        "attendance_days": len(attendances),
        "estimated_monthly": round((courier.base_salary or 0) + len(delivered) * per_delivery + bonus, 2),
    }


@router.get("/payouts")
def fleet_payouts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """الرواتب والبونص لكل مندوب في الشركة — بتفصيل (HR Payroll)."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant_id = _scope(user, db)
    q = db.query(Courier)
    if tenant_id is not None:
        q = q.filter(Courier.tenant_id == tenant_id)
    rows = []
    for c in q.all():
        done = db.query(CourierTask).filter(
            CourierTask.courier_id == c.id,
            CourierTask.status == CourierTaskStatus.DELIVERED,
        ).count()
        per_delivery = c.per_delivery_rate or 6.0
        fixed = c.base_salary or 0.0
        bonus = c.bonus_target or 0.0
        if bonus and c.score and c.score >= 4.7 and done > 0:
            bonus = round(bonus * 0.8, 2)
        rows.append({
            "id": c.id, "name": c.name,
            "courier_type": c.courier_type.value,
            "employment_status": c.employment_status or "ACTIVE",
            "deliveries": done,
            "fixed": round(fixed, 2),
            "per_delivery_rate": per_delivery,
            "per_delivery_earned": round(done * per_delivery, 2),
            "incentive": round(bonus, 2),
            "estimated_total": round(fixed + done * per_delivery + bonus, 2),
            "bank_iban": c.bank_iban,
        })
    return rows


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


@router.post("/shifts")
def fleet_create_shift(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Shift name is required")
    fleet = db.query(Fleet).filter(Fleet.tenant_id == user.tenant_id).first() if user.tenant_id else None
    shift = Shift(
        tenant_id=user.tenant_id, fleet_id=fleet.id if fleet else None,
        name=name, zone=payload.get("zone") or "",
        start_time=payload.get("start_time") or "09:00",
        end_time=payload.get("end_time") or "17:00",
        required_couriers=int(payload.get("required_couriers") or 0),
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return {"ok": True, "id": shift.id, "name": shift.name}


@router.post("/orders/{order_id}/reassign")
def fleet_reassign(order_id: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """إعادة تعيين طلب لمندوب معين من نطاق الشركة."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    tenant_id = _scope(user, db)
    ids = _courier_ids(db, tenant_id)
    courier_id = payload.get("courier_id")
    if courier_id and int(courier_id) not in ids:
        raise HTTPException(403, "Courier not in your fleet")
    order.courier_id = int(courier_id) if courier_id else None
    if order.courier_id:
        order.status = OrderStatus.ASSIGNED
    else:
        order.status = OrderStatus.PLACED
    db.commit()
    return {"ok": True, "order_id": order.id, "courier_id": order.courier_id}


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
            "id": a.id,
            "name": couriers.get(a.courier_id),
            "check_in": a.check_in.isoformat() if a.check_in else None,
            "check_out": a.check_out.isoformat() if a.check_out else None,
            "hours": hours,
            "is_late": a.is_late,
            "check_in_lat": a.check_in_lat, "check_in_lng": a.check_in_lng,
            "check_out_lat": a.check_out_lat, "check_out_lng": a.check_out_lng,
        })
    return rows


# ===== العقود (Contracts) =====

@router.get("/contracts")
def fleet_contracts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant_id = _scope(user, db)
    q = db.query(Contract)
    if tenant_id is not None:
        q = q.filter(Contract.tenant_id == tenant_id)
    return [
        {
            "id": c.id, "name": c.name, "contract_type": c.contract_type,
            "duration_months": c.duration_months, "couriers_count": c.couriers_count,
            "base_salary": c.base_salary or 0, "per_delivery_rate": c.per_delivery_rate or 0,
            "status": c.status, "fleet": (db.get(Fleet, c.fleet_id).name if c.fleet_id else None),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in q.all()
    ]


@router.post("/contracts")
def fleet_create_contract(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Contract name is required")
    tenant_id = _scope(user, db)
    fleet = db.query(Fleet).filter(Fleet.tenant_id == user.tenant_id).first() if user.tenant_id else None
    contract = Contract(
        tenant_id=user.tenant_id if user.tenant_id else (tenant_id if tenant_id is not None else None),
        fleet_id=fleet.id if fleet else payload.get("fleet_id"),
        name=name,
        contract_type=payload.get("contract_type") or "FIXED",
        duration_months=int(payload.get("duration_months") or 12),
        couriers_count=int(payload.get("couriers_count") or 0),
        base_salary=float(payload.get("base_salary") or 0),
        per_delivery_rate=float(payload.get("per_delivery_rate") or 6),
        status=payload.get("status") or "ACTIVE",
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return {"ok": True, "id": contract.id, "name": contract.name}


@router.patch("/contracts/{cid}")
def fleet_update_contract(cid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    contract = db.get(Contract, cid)
    if not contract:
        raise HTTPException(404, "Contract not found")
    allowed = {"name", "contract_type", "duration_months", "couriers_count",
               "base_salary", "per_delivery_rate", "status"}
    for k, v in payload.items():
        if k in allowed:
            setattr(contract, k, v)
    db.commit()
    return {"ok": True, "id": contract.id}


# ===== التذاكر (Support Tickets) =====

@router.get("/tickets")
def fleet_tickets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant_id = _scope(user, db)
    q = db.query(SupportTicket)
    if tenant_id is not None:
        q = q.filter(SupportTicket.tenant_id == tenant_id)
    couriers = {c.id: c.name for c in db.query(Courier).all()}
    return [
        {
            "id": t.id, "subject": t.subject, "message": t.message, "status": t.status,
            "reply": t.reply, "courier": couriers.get(t.courier_id),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in q.order_by(SupportTicket.id.desc()).all()
    ]


@router.post("/tickets/{tid}/reply")
def fleet_reply_ticket(tid: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    ticket = db.get(SupportTicket, tid)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    reply = (payload.get("reply") or "").strip()
    if not reply:
        raise HTTPException(400, "Reply is required")
    ticket.reply = reply
    ticket.status = "REPLIED"
    db.commit()
    return {"ok": True, "id": ticket.id, "status": ticket.status}


# ===== الإعدادات وقواعد النظام (Settings) =====

@router.get("/settings")
def fleet_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant_id = _scope(user, db)
    q = db.query(AppSetting)
    if tenant_id is not None:
        q = q.filter(AppSetting.tenant_id == tenant_id)
    return {s.key: s.value for s in q.all()}


@router.post("/settings")
def fleet_save_settings(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant_id = _scope(user, db)
    for key, value in payload.items():
        setting = db.query(AppSetting).filter(
            AppSetting.tenant_id == (user.tenant_id if user.tenant_id else 0),
            AppSetting.key == key,
        ).first()
        if setting:
            setting.value = str(value)
        else:
            db.add(AppSetting(
                tenant_id=user.tenant_id if user.tenant_id else 0,
                key=key, value=str(value),
            ))
    db.commit()
    return {"ok": True}


# ===== طلب اختباري (Test Order) =====

@router.post("/test-order")
def fleet_test_order(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """ينشئ طلباً حقيقياً ويُسنده لمندوب في نطاق الشركة (تحقق من الدورة كاملة)."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant_id = _scope(user, db)
    merchant = db.query(Merchant).filter(Merchant.is_active.is_(True)).first()
    if not merchant:
        raise HTTPException(400, "No active merchant available for a test order")
    customer_name = payload.get("customer_name") or "عميل اختباري"
    from datetime import datetime
    order = Order(
        merchant_id=merchant.id,
        customer_name=customer_name,
        customer_phone=payload.get("customer_phone") or "966500000000",
        customer_lat=payload.get("lat") or merchant.lat or 24.7136,
        customer_lng=payload.get("lng") or merchant.lng or 46.6753,
        customer_address=payload.get("address") or "عنوان اختباري — الرياض",
        delivery_method=merchant.delivery_method,
        subtotal=0, delivery_fee=8.0, total=8.0,
        status=OrderStatus.PLACED,
        created_at=datetime.utcnow(),
    )
    db.add(order)
    db.flush()
    ids = _courier_ids(db, tenant_id)
    courier = None
    if ids:
        courier = db.query(Courier).filter(Courier.id.in_(ids), Courier.is_online.is_(True)).first()
        if not courier:
            courier = db.query(Courier).filter(Courier.id.in_(ids)).first()
    if courier:
        order.courier_id = courier.id
        order.status = OrderStatus.ASSIGNED
        courier.current_load = (courier.current_load or 0) + 1
        db.add(CourierTask(
            courier_id=courier.id, order_id=order.id,
            status=CourierTaskStatus.ACCEPTED,
        ))
    db.commit()
    return {
        "ok": True, "order_id": order.id, "total": order.total,
        "courier": courier.name if courier else None,
        "status": order.status.value,
    }


# ===== تصعيد / بث (Escalate / Broadcast) =====

@router.post("/orders/{order_id}/escalate")
def fleet_escalate(order_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    order.status = OrderStatus.TIMEOUT if hasattr(OrderStatus, "TIMEOUT") else OrderStatus.PLACED
    order.courier_id = None
    db.commit()
    return {"ok": True, "order_id": order.id, "status": order.status.value if hasattr(order.status, "value") else order.status}


@router.post("/orders/{order_id}/broadcast")
def fleet_broadcast(order_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if order.courier_id:
        order.courier_id = None
    order.status = OrderStatus.PLACED
    db.commit()
    return {"ok": True, "order_id": order.id, "broadcast": True}


# ===== تصدير (Export) =====

@router.get("/export/csv")
def fleet_export_csv(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """تصدير رواتب المناديب بصيغة CSV حقيقية."""
    if user.role not in COMPANY_ROLES:
        raise HTTPException(403, "Not a fleet account")
    tenant_id = _scope(user, db)
    rows = []
    q = db.query(Courier)
    if tenant_id is not None:
        q = q.filter(Courier.tenant_id == tenant_id)
    for c in q.all():
        done = db.query(CourierTask).filter(
            CourierTask.courier_id == c.id,
            CourierTask.status == CourierTaskStatus.DELIVERED,
        ).count()
        per_delivery = c.per_delivery_rate or 6.0
        fixed = c.base_salary or 0.0
        bonus = c.bonus_target or 0.0
        if bonus and c.score and c.score >= 4.7 and done > 0:
            bonus = round(bonus * 0.8, 2)
        rows.append([
            c.name, c.phone, c.courier_type.value, c.employment_status or "ACTIVE",
            done, fixed, per_delivery, round(done * per_delivery, 2), bonus,
            round(fixed + done * per_delivery + bonus, 2), c.bank_iban or "",
        ])
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Name", "Phone", "Type", "Status", "Deliveries", "Fixed", "PerDelivery",
                     "DeliveryEarned", "Incentive", "EstimatedTotal", "IBAN"])
    writer.writerows(rows)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=fleet_payouts.csv"},
    )

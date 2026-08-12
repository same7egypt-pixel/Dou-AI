from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import (
    Courier, CourierTask, CourierTaskStatus, Merchant, Order, OrderStatus,
    SupportTicket, User, UserRole,
)
from ..schemas.dou import CourierCreate, CourierOut, TaskActionIn
from ..services.dispatch_engine import dispatch_order
from .auth import get_current_user

router = APIRouter(prefix="/couriers", tags=["couriers"])

STAFF_ROLES = (
    UserRole.COMPANY, UserRole.COMPANY_ADMIN, UserRole.OPERATIONS,
    UserRole.HR, UserRole.DOU_OPS, UserRole.DOU_ADMIN,
)


def _courier_access(courier_id: int, user: User, db: Session) -> Courier:
    courier = db.get(Courier, courier_id)
    if not courier:
        raise HTTPException(404, "Courier not found")
    if user.role == UserRole.COURIER and user.courier_id == courier_id:
        return courier
    if user.role in STAFF_ROLES:
        if user.role in (UserRole.DOU_OPS, UserRole.DOU_ADMIN) or user.tenant_id == courier.tenant_id:
            return courier
    raise HTTPException(404, "Courier not found")


@router.post("", response_model=CourierOut)
def create_courier(payload: CourierCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Not authorized")
    data = payload.model_dump(exclude_none=True)
    if user.role not in (UserRole.DOU_OPS, UserRole.DOU_ADMIN):
        data["tenant_id"] = user.tenant_id
    courier = Courier(**data)
    db.add(courier)
    db.commit()
    db.refresh(courier)
    return courier


@router.get("", response_model=list[CourierOut])
def list_couriers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Not authorized")
    q = db.query(Courier)
    if user.role not in (UserRole.DOU_OPS, UserRole.DOU_ADMIN):
        q = q.filter(Courier.tenant_id == user.tenant_id)
    return q.all()


@router.post("/{courier_id}/online")
def set_online(courier_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    courier = _courier_access(courier_id, user, db)
    courier.is_online = True
    courier.shift_active = True
    db.commit()
    return {"ok": True, "courier_id": courier_id, "online": True}


@router.post("/{courier_id}/offline")
def set_offline(courier_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    courier = _courier_access(courier_id, user, db)
    courier.is_online = False
    courier.shift_active = False
    db.commit()
    return {"ok": True, "courier_id": courier_id, "online": False}


@router.get("/me", response_model=CourierOut)
def my_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """يرجع ملف المندوب الخاص بالحساب المسجّل دخوله."""
    if user.role != UserRole.COURIER or not user.courier_id:
        raise HTTPException(403, "This account is not a courier")
    courier = db.get(Courier, user.courier_id)
    if not courier:
        raise HTTPException(404, "Courier not found")
    return courier


@router.get("/{courier_id}/tasks")
def my_tasks(courier_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _courier_access(courier_id, user, db)
    tasks = db.query(CourierTask).filter(
        CourierTask.courier_id == courier_id,
        CourierTask.status.in_([CourierTaskStatus.ACCEPTED, CourierTaskStatus.OFFERED]),
    ).all()
    rows = []
    for t in tasks:
        order = db.get(Order, t.order_id)
        merchant = db.get(Merchant, order.merchant_id) if order else None
        rows.append({
            "id": t.id, "order_id": t.order_id, "status": t.status.value,
            "offered_at": t.offered_at.isoformat() if t.offered_at else None,
            "accepted_at": t.accepted_at.isoformat() if t.accepted_at else None,
            "delivered_at": t.delivered_at.isoformat() if t.delivered_at else None,
            "batch_orders": [t.order_id],
            "customer_name": order.customer_name if order else None,
            "customer_address": order.customer_address if order else None,
            "customer_phone": order.customer_phone if order else None,
            "total": order.total if order else 0,
            "delivery_method": order.delivery_method.value if order and hasattr(order.delivery_method, "value") else (order.delivery_method if order else None),
            "distance_km": order.distance_km if order else 0,
            "merchant_name": merchant.name if merchant else None,
            "merchant_district": merchant.district if merchant else None,
        })
    return rows


@router.post("/{courier_id}/tasks/{task_id}/accept")
def accept_task(courier_id: int, task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _courier_access(courier_id, user, db)
    task = db.get(CourierTask, task_id)
    if not task or task.courier_id != courier_id:
        raise HTTPException(404, "Task not found")
    if task.status != CourierTaskStatus.OFFERED:
        raise HTTPException(400, f"Task is {task.status.value}, not offered")
    task.status = CourierTaskStatus.ACCEPTED
    from datetime import datetime
    task.accepted_at = datetime.utcnow()
    order = db.get(Order, task.order_id)
    if order:
        order.status = OrderStatus.ACCEPTED
    db.commit()
    return {"ok": True, "task_id": task.id, "status": task.status.value}


@router.post("/{courier_id}/tasks/{task_id}/reject")
def reject_task(courier_id: int, task_id: int, payload: TaskActionIn,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _courier_access(courier_id, user, db)
    task = db.get(CourierTask, task_id)
    if not task or task.courier_id != courier_id:
        raise HTTPException(404, "Task not found")
    if task.status != CourierTaskStatus.OFFERED:
        raise HTTPException(400, f"Task is {task.status.value}, not offered")
    task.status = CourierTaskStatus.REJECTED
    courier = db.get(Courier, courier_id)
    if courier:
        courier.is_available = False  # لا يرسل له مجدداً هذا الطلب
    db.commit()
    # إعادة إسناد الطلب لمندوب آخر تلقائياً
    order = db.get(Order, task.order_id)
    if order:
        order.courier_id = None
        dispatch_order(db, order)
    return {"ok": True, "reassigned": True}


@router.post("/{courier_id}/tasks/{task_id}/deliver")
def mark_delivered(courier_id: int, task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _courier_access(courier_id, user, db)
    task = db.get(CourierTask, task_id)
    if not task or task.courier_id != courier_id:
        raise HTTPException(404, "Task not found")
    if task.status not in (CourierTaskStatus.ACCEPTED, CourierTaskStatus.PICKED_UP):
        raise HTTPException(400, "Task not in deliverable state")
    task.status = CourierTaskStatus.DELIVERED
    from datetime import datetime
    task.delivered_at = datetime.utcnow()
    order = db.get(Order, task.order_id)
    if order:
        order.status = OrderStatus.DELIVERED
        courier = db.get(Courier, courier_id)
        if courier and courier.current_load > 0:
            courier.current_load -= 1
    db.commit()
    return {"ok": True, "task_id": task.id, "status": task.status.value}


@router.post("/{courier_id}/tasks/{task_id}/pickup")
def mark_picked_up(courier_id: int, task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _courier_access(courier_id, user, db)
    task = db.get(CourierTask, task_id)
    if not task or task.courier_id != courier_id:
        raise HTTPException(404, "Task not found")
    if task.status != CourierTaskStatus.ACCEPTED:
        raise HTTPException(400, f"Task is {task.status.value}, not accepted")
    task.status = CourierTaskStatus.PICKED_UP
    order = db.get(Order, task.order_id)
    if order:
        order.status = OrderStatus.PICKED_UP
    db.commit()
    return {"ok": True, "task_id": task.id, "status": task.status.value}


@router.post("/{courier_id}/tasks/{task_id}/transit")
def mark_in_transit(courier_id: int, task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _courier_access(courier_id, user, db)
    task = db.get(CourierTask, task_id)
    if not task or task.courier_id != courier_id:
        raise HTTPException(404, "Task not found")
    if task.status != CourierTaskStatus.PICKED_UP:
        raise HTTPException(400, f"Task is {task.status.value}, not picked up")
    task.status = CourierTaskStatus.IN_TRANSIT
    order = db.get(Order, task.order_id)
    if order:
        order.status = OrderStatus.IN_TRANSIT
    db.commit()
    return {"ok": True, "task_id": task.id, "status": task.status.value}


# ===== خدمات المندوب الذاتية (Self-service) =====

@router.patch("/me")
def update_my_profile(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """المندوب يعدّل ملفه: الاسم، رقم الجوال، الحساب البنكي (IBAN)."""
    if user.role != UserRole.COURIER or not user.courier_id:
        raise HTTPException(403, "This account is not a courier")
    courier = db.get(Courier, user.courier_id)
    if not courier:
        raise HTTPException(404, "Courier not found")
    allowed = {"name", "bank_iban"}
    for k, v in payload.items():
        if k in allowed and v is not None:
            setattr(courier, k, v)
            if k == "name":
                user.name = v
    db.commit()
    return {"ok": True, "name": courier.name, "bank_iban": courier.bank_iban}


@router.post("/me/tickets")
def raise_ticket(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """المندوب يرفع تذكرة دعم — تظهر لفريق الشركة في لوحة Fleet."""
    if user.role != UserRole.COURIER or not user.courier_id:
        raise HTTPException(403, "This account is not a courier")
    subject = (payload.get("subject") or "").strip()
    message = (payload.get("message") or "").strip()
    if not subject:
        raise HTTPException(400, "Subject is required")
    if not message:
        raise HTTPException(400, "Message is required")
    courier = db.get(Courier, user.courier_id)
    ticket = SupportTicket(
        tenant_id=courier.tenant_id if courier else None,
        courier_id=courier.id if courier else None,
        subject=subject, message=message, status="OPEN",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return {"ok": True, "id": ticket.id, "status": ticket.status}


@router.get("/me/tickets")
def my_tickets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != UserRole.COURIER or not user.courier_id:
        raise HTTPException(403, "This account is not a courier")
    tickets = db.query(SupportTicket).filter(SupportTicket.courier_id == user.courier_id).order_by(SupportTicket.id.desc()).all()
    return [
        {
            "id": t.id, "subject": t.subject, "message": t.message, "status": t.status,
            "reply": t.reply, "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tickets
    ]

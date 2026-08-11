from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import Courier, CourierTask, CourierTaskStatus, Merchant, Order, OrderStatus, User, UserRole
from ..schemas.dou import CourierCreate, CourierOut, TaskActionIn
from ..services.dispatch_engine import dispatch_order
from .auth import get_current_user

router = APIRouter(prefix="/couriers", tags=["couriers"])


@router.post("", response_model=CourierOut)
def create_courier(payload: CourierCreate, db: Session = Depends(get_db)):
    courier = Courier(**payload.model_dump(exclude_none=True))
    db.add(courier)
    db.commit()
    db.refresh(courier)
    return courier


@router.get("", response_model=list[CourierOut])
def list_couriers(db: Session = Depends(get_db)):
    return db.query(Courier).all()


@router.post("/{courier_id}/online")
def set_online(courier_id: int, db: Session = Depends(get_db)):
    courier = db.get(Courier, courier_id)
    if not courier:
        raise HTTPException(404, "Courier not found")
    courier.is_online = True
    courier.shift_active = True
    db.commit()
    return {"ok": True, "courier_id": courier_id, "online": True}


@router.post("/{courier_id}/offline")
def set_offline(courier_id: int, db: Session = Depends(get_db)):
    courier = db.get(Courier, courier_id)
    if not courier:
        raise HTTPException(404, "Courier not found")
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
def my_tasks(courier_id: int, db: Session = Depends(get_db)):
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
def accept_task(courier_id: int, task_id: int, db: Session = Depends(get_db)):
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
def reject_task(payload: TaskActionIn, db: Session = Depends(get_db)):
    task = db.get(CourierTask, payload.task_id)
    if not task or task.courier_id != payload.courier_id:
        raise HTTPException(404, "Task not found")
    if task.status != CourierTaskStatus.OFFERED:
        raise HTTPException(400, f"Task is {task.status.value}, not offered")
    task.status = CourierTaskStatus.REJECTED
    courier = db.get(Courier, payload.courier_id)
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
def mark_delivered(courier_id: int, task_id: int, db: Session = Depends(get_db)):
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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models.entities import (
    Attendance, Courier, CourierTask, CourierTaskStatus, CourierType,
    Merchant, Order, OrderStatus, User, UserRole,
)
from .auth import get_current_user

BUSINESS_ROLES = (UserRole.COMPANY, UserRole.DOU_OPS, UserRole.DOU_ADMIN)

def _business_only(user: User = Depends(get_current_user)):
    if user.role not in BUSINESS_ROLES:
        raise HTTPException(403, "Insufficient permissions")

router = APIRouter(tags=["analytics"], dependencies=[Depends(_business_only)])


@router.get("/analytics/overview")
def analytics_overview(db: Session = Depends(get_db)):
    couriers = db.query(Courier).all()
    orders = db.query(Order).all()
    tasks = db.query(CourierTask).all()

    delivered = [t for t in tasks if t.status == CourierTaskStatus.DELIVERED]
    on_time = [o for o in orders if o.status in (OrderStatus.DELIVERED, OrderStatus.COMPLETED)]

    return {
        "couriers_total": len(couriers),
        "couriers_online": sum(1 for c in couriers if c.is_online),
        "orders_total": len(orders),
        "orders_active": sum(1 for o in orders if o.status not in (OrderStatus.DELIVERED, OrderStatus.COMPLETED, OrderStatus.CANCELLED)),
        "deliveries_done": len(delivered),
        "orders_shipping": sum(1 for o in orders if o.delivery_method.value == "SHIPPING"),
        "orders_self": sum(1 for o in orders if o.delivery_method.value == "SELF"),
        "orders_platform": sum(1 for o in orders if o.delivery_method.value == "PLATFORM"),
        "avg_acceptance": round(sum(c.acceptance_rate for c in couriers) / len(couriers), 1) if couriers else 0,
        "avg_score": round(sum(c.score for c in couriers) / len(couriers), 2) if couriers else 0,
        "revenue_subtotal": round(sum(o.subtotal for o in orders), 2),
        "revenue_total": round(sum(o.total for o in orders), 2),
    }


@router.get("/analytics/performance")
def performance(db: Session = Depends(get_db)):
    """سكوركارد أداء المناديب — من البيانات الحية."""
    couriers = db.query(Courier).all()
    rows = []
    for c in couriers:
        done = db.query(CourierTask).filter(
            CourierTask.courier_id == c.id,
            CourierTask.status == CourierTaskStatus.DELIVERED,
        ).count()
        rows.append({
            "id": c.id, "name": c.name,
            "courier_type": c.courier_type.value,
            "acceptance_rate": c.acceptance_rate,
            "on_time_rate": c.on_time_rate,
            "completion_rate": c.completion_rate,
            "score": c.score,
            "deliveries": done,
            "current_load": c.current_load,
            "online": c.is_online,
        })
    rows.sort(key=lambda r: (-r["score"]))
    return rows


@router.get("/analytics/payouts")
def payouts(db: Session = Depends(get_db)):
    """تقدير مدفوعات المناديب (ثابت + لكل توصيلة)."""
    couriers = db.query(Courier).all()
    rows = []
    for c in couriers:
        done = db.query(CourierTask).filter(
            CourierTask.courier_id == c.id,
            CourierTask.status == CourierTaskStatus.DELIVERED,
        ).count()
        per_delivery = 6.0 if c.courier_type == CourierType.COMPANY else 8.0
        fixed = 3000.0 if c.courier_type == CourierType.COMPANY else 0.0
        incentive = 150.0 if c.score >= 4.7 and done > 0 else 0.0
        rows.append({
            "id": c.id, "name": c.name,
            "courier_type": c.courier_type.value,
            "deliveries": done,
            "fixed": round(fixed, 2),
            "per_delivery_earned": round(done * per_delivery, 2),
            "incentive": round(incentive, 2),
            "estimated_total": round(fixed + done * per_delivery + incentive, 2),
        })
    return rows


@router.get("/analytics/compliance")
def compliance(db: Session = Depends(get_db)):
    """امتثال: مستندات، حضور، تحقيقات."""
    couriers = db.query(Courier).all()
    attendances = db.query(Attendance).all()
    late = [a for a in attendances if a.is_late]
    no_show = len(couriers) - len({a.courier_id for a in attendances})
    docs_expiring = sum(1 for c in couriers if c.documents_valid is False or not c.documents_valid)
    return {
        "documents_attention": docs_expiring,
        "attendance_exceptions": len(late) + max(no_show, 0),
        "delivery_investigations": sum(1 for c in couriers if c.completion_rate < 90),
        "couriers_checked_in": len({a.courier_id for a in attendances}),
    }


@router.get("/analytics/top-merchants")
def top_merchants(db: Session = Depends(get_db)):
    """أفضل التجار حسب حجم الطلبات."""
    orders = db.query(Order).all()
    from collections import Counter
    counts = Counter(o.merchant_id for o in orders)
    revenue = {}
    for o in orders:
        revenue[o.merchant_id] = revenue.get(o.merchant_id, 0) + o.total
    rows = []
    for mid, cnt in counts.most_common(10):
        m = db.get(Merchant, mid)
        rows.append({
            "merchant_id": mid,
            "name": m.name if m else f"#{mid}",
            "orders": cnt,
            "revenue": round(revenue[mid], 2),
        })
    return rows

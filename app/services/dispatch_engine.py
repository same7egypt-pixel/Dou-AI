"""محرك الإرسال الذكي (Dispatch Engine) — قلب DOU.

يقرر من يوصّل كل طلب بناءً على:
1. خيار التاجر (وصل بنفسك / وصل عن طريقنا / شركة شحن)
2. المسافة (محلي داخل الحي / بعيد بين المدن)
3. توفر ومعايير المندوب (قرب، أداء، وردية، حمل، مستندات)
"""
import math
from sqlalchemy.orm import Session
from sqlalchemy import and_

from ..config import LOCAL_RADIUS_KM, LONG_DISTANCE_KM
from ..models.entities import (
    Courier, CourierTask, CourierTaskStatus, CourierType,
    DeliveryMethod, Order, OrderStatus,
)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    if None in (lat1, lng1, lat2, lng2):
        return 0.0
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def rank_couriers(db: Session, order: Order) -> list[Courier]:
    """مصافي اختيار المندوب الأفضل لطلب محلي."""
    q = db.query(Courier).filter(
        Courier.is_online.is_(True),
        Courier.is_available.is_(True),
        Courier.documents_valid.is_(True),
        Courier.shift_active.is_(True),
        Courier.is_on_leave.is_(False),            # لا إرسال لمن في إجازة
        Courier.employment_status.is_(None) | Courier.employment_status.isnot("SUSPENDED"),
        Courier.current_load < 3,          # حمل حالي ضمن الحد
        Courier.acceptance_rate >= 85.0,
    )
    candidates = q.all()

    def score(c: Courier) -> tuple:
        dist = haversine_km(order.merchant.lat, order.merchant.lng, c.lat, c.lng)
        # مخصص (داخل أسطول) له أولوية على الفريلانسر حسب السياق
        type_priority = 1.0 if c.courier_type == CourierType.COMPANY else 0.9
        return (dist, -c.score * type_priority)

    candidates.sort(key=lambda c: score(c))
    return candidates


def dispatch_order(db: Session, order: Order) -> Order:
    """يقرر طريقة التوصيل ويحاول إسناد طلب محلي لمندوب."""
    merchant = order.merchant

    # 1) المسافة تحدد المحلي مقابل الشحن
    order.distance_km = haversine_km(
        merchant.lat, merchant.lng, order.customer_lat, order.customer_lng
    )

    # 2) خيار التاجر الثابت
    method = order.delivery_method or merchant.delivery_method

    if order.distance_km >= LONG_DISTANCE_KM:
        # بعيد → شركة شحن عبر API (سمسا/بوسطه/أرامكس)
        method = DeliveryMethod.SHIPPING_COMPANY
        order.delivery_method = method
        order.status = OrderStatus.READY  # تنتظر إنشاء الشحنة
        db.commit()
        return order

    # 3) محلي → مناديب/فريلانسر (إلا لو التاجر يوصّل بنفسه)
    if method == DeliveryMethod.SELF:
        order.status = OrderStatus.ASSIGNED  # مندوب التاجر
        db.commit()
        return order

    candidates = rank_couriers(db, order)
    if candidates:
        best = candidates[0]
        best.current_load += 1
        task = CourierTask(order_id=order.id, courier_id=best.id)
        db.add(task)
        order.courier_id = best.id
        order.status = OrderStatus.ASSIGNED
        db.commit()
    else:
        # لا مندوب متاح → الاحتياطي: شركة شحن
        order.delivery_method = DeliveryMethod.SHIPPING_COMPANY
        order.status = OrderStatus.READY

    db.commit()
    return order

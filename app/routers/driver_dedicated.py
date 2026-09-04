from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
import jwt
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import ENABLE_OPEN_POOL, SECRET_KEY
from app.database import get_db
from app.models.entities import Courier, DailyLog, User
from app.models.merchant import (
    BookingStatus,
    BranchDispatchOrder,
    DedicatedShiftBooking,
    MerchantBranch,
    OrderStatus,
    ShiftAttendanceLog,
)
from app.utils.geo import haversine_distance_meters
from app.utils.security import security_bearer

router = APIRouter(prefix="/driver", tags=["driver"])


# ─── Auth Dependency for Rider ────────────────────────────────────────────────

def get_current_rider(
    credentials: Optional[object] = Security(security_bearer),
    db: Session = Depends(get_db),
) -> Courier:
    """
    Authenticates rider from Fleet OS bearer token.
    Rejects branch tokens (HTTP 403).
    Rejects invalid/missing tokens (HTTP 401).
    """
    if not credentials or not getattr(credentials, "credentials", None):
        raise HTTPException(status_code=401, detail="تسجيل الدخول مطلوب.")

    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="رمز المصادقة غير صالح.")

    sub = str(payload.get("sub", ""))
    if sub.startswith("merchant_branch:"):
        raise HTTPException(status_code=403, detail="رمز الفرع غير مصرح له بالوصول لمسارات السائق.")

    # 1. Look for explicit courier_id in payload
    if payload.get("courier_id"):
        courier = db.get(Courier, int(payload["courier_id"]))
        if courier:
            return courier

    # 2. Look up via User ID if sub is numeric
    try:
        user_id = int(sub)
        user = db.get(User, user_id)
        if user and user.courier_id:
            courier = db.get(Courier, user.courier_id)
            if courier:
                return courier
        # Fallback: check if sub itself corresponds directly to Courier.id
        courier = db.get(Courier, user_id)
        if courier:
            return courier
    except ValueError:
        if sub.startswith("courier:"):
            try:
                c_id = int(sub.split(":")[1])
                courier = db.get(Courier, c_id)
                if courier:
                    return courier
            except ValueError:
                pass

    raise HTTPException(status_code=403, detail="المستخدم غير مصرح له كتطبيق سائق.")


# ─── Schemas ──────────────────────────────────────────────────────────────────

class DedicatedShiftCard(BaseModel):
    booking_id: int
    merchant_name: str
    branch_name: str
    branch_address: str
    branch_lat: float
    branch_lng: float
    shift_start: str
    shift_end: str
    shift_type: str
    checkin_status: str  # "not_yet" | "checked_in" | "completed"


class CheckinRequest(BaseModel):
    lat: float
    lng: float


class CheckinResponse(BaseModel):
    validated: bool
    distance_meters: float
    message: str
    attendance_log_id: int


class OrderStatusUpdate(BaseModel):
    status: str  # "en_route" | "delivered"


class RiderOrderOut(BaseModel):
    order_id: int
    merchant_branch_id: int
    branch_name: str
    customer_name: str
    customer_phone: str
    delivery_address_text: str
    status: str
    order_source: str
    is_pool_eligible: bool
    dispatched_at: datetime
    acknowledged_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None


class PoolOrderOut(BaseModel):
    order_id: int
    merchant_branch_id: int
    branch_name: str
    branch_latitude: float
    branch_longitude: float
    distance_km: float
    external_order_id: Optional[str]
    customer_name: str
    customer_phone: str
    delivery_address_text: str
    status: str
    order_source: str
    rider_id: Optional[int]
    is_pool_eligible: bool
    dispatched_at: datetime


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/shifts/dedicated/today", response_model=Optional[DedicatedShiftCard])
def get_today_dedicated_shift(
    db: Session = Depends(get_db),
    current_rider: Courier = Depends(get_current_rider),
):
    """
    Resolves today's active DedicatedShiftBooking for the authenticated rider.
    Returns HTTP 204 No Content if no dedicated shift is booked for today.
    """
    today = date.today()
    booking = (
        db.query(DedicatedShiftBooking)
        .filter(
            DedicatedShiftBooking.rider_id == current_rider.id,
            DedicatedShiftBooking.status == BookingStatus.active,
            DedicatedShiftBooking.effective_from <= today,
            or_(
                DedicatedShiftBooking.effective_until.is_(None),
                DedicatedShiftBooking.effective_until >= today,
            ),
        )
        .first()
    )
    if not booking:
        raise HTTPException(status_code=status.HTTP_204_NO_CONTENT)

    branch = db.get(MerchantBranch, booking.merchant_branch_id)
    if not branch:
        raise HTTPException(status_code=status.HTTP_204_NO_CONTENT)

    account = branch.merchant_account

    # Check attendance log
    log = (
        db.query(ShiftAttendanceLog)
        .filter(
            ShiftAttendanceLog.dedicated_shift_booking_id == booking.id,
            ShiftAttendanceLog.rider_id == current_rider.id,
            ShiftAttendanceLog.log_date == today,
        )
        .first()
    )

    checkin_status = "not_yet"
    if log:
        if log.checkout_at is not None:
            checkin_status = "completed"
        elif log.checkin_at is not None and log.geofence_validated:
            checkin_status = "checked_in"
        else:
            checkin_status = "not_yet"

    address = f"{branch.city}, {branch.district or ''}".strip(", ")

    return DedicatedShiftCard(
        booking_id=booking.id,
        merchant_name=account.trade_name if account else "DOU Merchant",
        branch_name=branch.branch_name,
        branch_address=address,
        branch_lat=float(branch.latitude),
        branch_lng=float(branch.longitude),
        shift_start=booking.shift_start_time.strftime("%H:%M"),
        shift_end=booking.shift_end_time.strftime("%H:%M"),
        shift_type=booking.shift_type.value,
        checkin_status=checkin_status,
    )


@router.post("/shifts/dedicated/{booking_id}/checkin", response_model=CheckinResponse)
def dedicated_shift_checkin(
    booking_id: int,
    payload: CheckinRequest,
    db: Session = Depends(get_db),
    current_rider: Courier = Depends(get_current_rider),
):
    """
    Validates rider's GPS coordinates against branch geofence using Haversine formula.
    geofence_validated = True when distance <= geofence_radius_meters.
    Idempotent with Self-Correction:
      - If existing log was outside geofence, and new check-in is within geofence:
        upgrades geofence_validated to True, updates coordinates, and confirms attendance.
      - If still outside geofence: reports validated=False with distance.
    """
    booking = db.get(DedicatedShiftBooking, booking_id)
    if not booking or booking.rider_id != current_rider.id:
        raise HTTPException(status_code=404, detail="حجز الوردية المخصصة غير موجود.")

    branch = db.get(MerchantBranch, booking.merchant_branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="الفرع غير موجود.")

    today = date.today()
    distance_meters = haversine_distance_meters(
        payload.lat, payload.lng, float(branch.latitude), float(branch.longitude)
    )
    validated = distance_meters <= branch.geofence_radius_meters

    # Check existing attendance log for idempotency and self-correction
    existing_log = (
        db.query(ShiftAttendanceLog)
        .filter(
            ShiftAttendanceLog.dedicated_shift_booking_id == booking.id,
            ShiftAttendanceLog.rider_id == current_rider.id,
            ShiftAttendanceLog.log_date == today,
        )
        .first()
    )

    if existing_log:
        if existing_log.geofence_validated:
            return CheckinResponse(
                validated=True,
                distance_meters=round(distance_meters, 2),
                message="تم تسجيل حضورك مسبقاً وتأكيده داخل نطاق الفرع.",
                attendance_log_id=existing_log.id,
            )
        # Self-correction: rider previously attempted outside geofence, now within geofence!
        if validated:
            existing_log.geofence_validated = True
            existing_log.checkin_at = datetime.now(timezone.utc)
            existing_log.checkin_lat = payload.lat
            existing_log.checkin_lng = payload.lng
            db.commit()
            db.refresh(existing_log)
            return CheckinResponse(
                validated=True,
                distance_meters=round(distance_meters, 2),
                message="تم تصحيح وتأكيد حضورك بنجاح داخل النطاق الجغرافي للفرع.",
                attendance_log_id=existing_log.id,
            )
        else:
            return CheckinResponse(
                validated=False,
                distance_meters=round(distance_meters, 2),
                message=f"أنت خارج النطاق الجغرافي للفرع ({round(distance_meters)} متراً). النطاق المسموح هو {branch.geofence_radius_meters} متراً.",
                attendance_log_id=existing_log.id,
            )

    log = ShiftAttendanceLog(
        dedicated_shift_booking_id=booking.id,
        rider_id=current_rider.id,
        log_date=today,
        checkin_at=datetime.now(timezone.utc),
        checkin_lat=payload.lat,
        checkin_lng=payload.lng,
        geofence_validated=validated,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    msg = (
        "تم تسجيل حضورك بنجاح داخل النطاق الجغرافي للفرع."
        if validated
        else f"أنت خارج النطاق الجغرافي للفرع ({round(distance_meters)} متراً). يلزم التواجد أمام الفرع ({branch.geofence_radius_meters} متراً) لتأكيد الحضور واستقبال الطلبات."
    )
    return CheckinResponse(
        validated=validated,
        distance_meters=round(distance_meters, 2),
        message=msg,
        attendance_log_id=log.id,
    )


@router.get("/orders/branch/active", response_model=list[RiderOrderOut])
def get_active_branch_orders(
    db: Session = Depends(get_db),
    current_rider: Courier = Depends(get_current_rider),
):
    """
    Returns all BranchDispatchOrders assigned to this rider where
    status != 'delivered', ordered by dispatched_at ascending.
    """
    orders = (
        db.query(BranchDispatchOrder)
        .filter(
            BranchDispatchOrder.rider_id == current_rider.id,
            BranchDispatchOrder.status != OrderStatus.delivered,
        )
        .order_by(BranchDispatchOrder.dispatched_at.asc())
        .all()
    )

    results: list[RiderOrderOut] = []
    for o in orders:
        branch = db.get(MerchantBranch, o.merchant_branch_id)
        results.append(
            RiderOrderOut(
                order_id=o.id,
                merchant_branch_id=o.merchant_branch_id,
                branch_name=branch.branch_name if branch else "Branch",
                customer_name=o.customer_name,
                customer_phone=o.customer_phone,
                delivery_address_text=o.delivery_address_text,
                status=o.status.value,
                order_source=o.order_source,
                is_pool_eligible=o.is_pool_eligible,
                dispatched_at=o.dispatched_at or datetime.now(timezone.utc),
                acknowledged_at=o.acknowledged_at,
                delivered_at=o.delivered_at,
            )
        )
    return results


def _record_delivery_to_daily_log(
    order: BranchDispatchOrder,
    courier: Courier,
    db: Session,
) -> None:
    """
    Synchronizes delivered dedicated branch dispatch orders to DailyLog.
    Accredits verified_orders only (external confirmed source) without inflating
    driver_orders (which is strictly the driver's manual self-report).
    Preserves original source_type when merging with existing platform logs.
    """
    log_date = order.order_date or date.today()
    project_id = courier.primary_project_id

    query = db.query(DailyLog).filter(
        DailyLog.courier_id == courier.id,
        DailyLog.log_date == log_date,
    )
    if project_id is not None:
        query = query.filter(DailyLog.project_id == project_id)
    else:
        query = query.filter(DailyLog.project_id.is_(None))
    daily_log = query.first()

    if not daily_log:
        daily_log = DailyLog(
            courier_id=courier.id,
            tenant_id=courier.tenant_id,
            project_id=project_id,
            log_date=log_date,
            orders_count=1,
            driver_orders=0,
            verified_orders=1,
            variance=1,
            source_type="DEDICATED_BRANCH_DISPATCH",
        )
        db.add(daily_log)
    else:
        daily_log.verified_orders = (daily_log.verified_orders or 0) + 1
        daily_log.orders_count = daily_log.verified_orders
        daily_log.variance = daily_log.orders_count - (daily_log.driver_orders or 0)

        # Preserve original source_type without losing platform origin
        if not daily_log.source_type:
            daily_log.source_type = "DEDICATED_BRANCH_DISPATCH"
        elif daily_log.source_type != "DEDICATED_BRANCH_DISPATCH":
            orig = daily_log.source_type
            if "+BRANCH" not in orig and len(orig) + 7 <= 30:
                daily_log.source_type = f"{orig}+BRANCH"
            current_notes = daily_log.notes or ""
            note_tag = "[+DEDICATED_BRANCH_DISPATCH]"
            if note_tag not in current_notes:
                daily_log.notes = f"{current_notes} {note_tag}".strip()[:300]



@router.patch("/orders/{order_id}/status")
def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    db: Session = Depends(get_db),
    current_rider: Courier = Depends(get_current_rider),
):
    """
    State machine enforcement:
      pending  → en_route   (sets acknowledged_at)
      en_route → delivered  (sets delivered_at)
    Invalid transitions return HTTP 422.
    Rider can only update orders assigned to them — HTTP 403 otherwise.
    """
    order = db.get(BranchDispatchOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود.")

    if order.rider_id != current_rider.id:
        raise HTTPException(status_code=403, detail="غير مصرح: هذا الطلب مسند لمندوب آخر.")

    current_status = order.status
    target_status = payload.status

    if current_status == OrderStatus.pending:
        if target_status != "en_route":
            raise HTTPException(
                status_code=422,
                detail=f"تغيير غير صالح للحالة من {current_status.value} إلى {target_status}. المسموح: en_route",
            )
        order.status = OrderStatus.en_route
        order.acknowledged_at = datetime.now(timezone.utc)
    elif current_status == OrderStatus.en_route:
        if target_status != "delivered":
            raise HTTPException(
                status_code=422,
                detail=f"تغيير غير صالح للحالة من {current_status.value} إلى {target_status}. المسموح: delivered",
            )
        order.status = OrderStatus.delivered
        order.delivered_at = datetime.now(timezone.utc)
        _record_delivery_to_daily_log(order, current_rider, db)
    else:
        # Already delivered
        raise HTTPException(
            status_code=422,
            detail=f"الطلب مكتمل بحالة {current_status.value} مسبقاً، ولا يمكن إجراء أي تغيير إضافي.",
        )

    db.commit()
    db.refresh(order)

    return {
        "order_id": order.id,
        "status": order.status.value,
        "acknowledged_at": order.acknowledged_at,
        "delivered_at": order.delivered_at,
    }


@router.get("/orders/pool/available", response_model=list[PoolOrderOut])
def get_pool_orders(
    lat: float = Query(...),
    lng: float = Query(...),
    radius_km: float = Query(5.0),
    db: Session = Depends(get_db),
    current_rider: Courier = Depends(get_current_rider),
):
    """
    Returns BranchDispatchOrders where is_pool_eligible=True,
    rider_id IS NULL, status='pending', order_date=today.
    Filters by Haversine distance from rider's current coords to branch lat/lng.
    """
    if not ENABLE_OPEN_POOL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="سوق الطلبات الحرة (Open Pool) معطل حالياً.",
        )

    today = date.today()
    pool_orders = (
        db.query(BranchDispatchOrder)
        .filter(
            BranchDispatchOrder.is_pool_eligible.is_(True),
            BranchDispatchOrder.rider_id.is_(None),
            BranchDispatchOrder.status == OrderStatus.pending,
            BranchDispatchOrder.order_date == today,
        )
        .order_by(BranchDispatchOrder.dispatched_at.asc())
        .all()
    )

    matching_orders: list[PoolOrderOut] = []
    for order in pool_orders:
        branch = db.get(MerchantBranch, order.merchant_branch_id)
        if not branch:
            continue
        dist_m = haversine_distance_meters(lat, lng, float(branch.latitude), float(branch.longitude))
        dist_km = dist_m / 1000.0
        if dist_km <= radius_km:
            matching_orders.append(
                PoolOrderOut(
                    order_id=order.id,
                    merchant_branch_id=order.merchant_branch_id,
                    branch_name=branch.branch_name,
                    branch_latitude=float(branch.latitude),
                    branch_longitude=float(branch.longitude),
                    distance_km=round(dist_km, 2),
                    external_order_id=order.external_order_id,
                    customer_name=order.customer_name,
                    customer_phone=order.customer_phone,
                    delivery_address_text=order.delivery_address_text,
                    status=order.status.value,
                    order_source=order.order_source,
                    rider_id=order.rider_id,
                    is_pool_eligible=order.is_pool_eligible,
                    dispatched_at=order.dispatched_at or datetime.now(timezone.utc),
                )
            )

    return matching_orders


@router.patch("/orders/{order_id}/claim")
def claim_pool_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_rider: Courier = Depends(get_current_rider),
):
    """
    Atomically claims a pool order using pessimistic locking (with_for_update).
    Returns HTTP 409 if already claimed.
    """
    if not ENABLE_OPEN_POOL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="سوق الطلبات الحرة (Open Pool) معطل حالياً.",
        )

    # with_for_update locks the row in Postgres
    order = (
        db.query(BranchDispatchOrder)
        .filter(BranchDispatchOrder.id == order_id)
        .with_for_update()
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود.")

    if order.rider_id is not None or not order.is_pool_eligible or order.status != OrderStatus.pending:
        raise HTTPException(
            status_code=409,
            detail="الطلب تم استلامه من مندوب آخر مسبقاً أو غير متاح.",
        )

    order.rider_id = current_rider.id
    order.is_pool_eligible = False
    db.commit()
    db.refresh(order)

    return {
        "order_id": order.id,
        "status": order.status.value,
        "claimed_by_rider_id": current_rider.id,
        "message": "تم استلام الطلب بنجاح.",
    }

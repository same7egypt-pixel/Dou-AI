import calendar
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.entities import Courier
from app.models.merchant import (
    BookingStatus,
    BranchDispatchOrder,
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    OrderStatus,
)
from app.utils.finance import prorate
from app.utils.security import (
    create_branch_token,
    get_current_branch_id,
    get_current_merchant_account_id,
    verify_pin,
)

router = APIRouter(prefix="/merchant", tags=["merchant"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class CashierLoginRequest(BaseModel):
    branch_id: int
    pin: str


class CashierLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    branch_id: int
    branch_name: str
    today_shift_start: Optional[str] = None
    today_shift_end: Optional[str] = None


class ActiveRiderCard(BaseModel):
    rider_name: str
    rider_phone_masked: str  # e.g. "•••••• 1234"
    shift_start: str
    shift_end: str
    checkin_status: str      # "checked_in" | "not_yet" | "overdue"
    attendance_log_id: Optional[int] = None


class DispatchOrderRequest(BaseModel):
    customer_name: str
    customer_phone: str
    delivery_address: str


class DispatchOrderResponse(BaseModel):
    order_id: int
    assigned_rider_name: str
    status: str


class ActiveOrderOut(BaseModel):
    order_id: int
    customer_name: str
    customer_phone: str
    delivery_address_text: str
    status: str
    dispatched_at: datetime
    assigned_rider_name: Optional[str] = None


class StatementLineItem(BaseModel):
    branch_name: str
    shift_type: str
    rider_name: str
    active_days: int
    days_in_month: int
    prorated_fee: float


class MonthlyStatementResponse(BaseModel):
    merchant_name: str
    statement_month: str  # e.g. "June 2025"
    total_amount_due: float
    currency: str = "SAR"
    due_date: str
    line_items: list[StatementLineItem]
    settlement_status: str
    gross_fee_charged_to_merchant: float
    total_payout_to_logistics: float
    dou_net_margin: float


class POSOrderRequest(BaseModel):
    branch_id: int
    external_order_id: str
    customer_name: str
    customer_phone: str
    delivery_address_text: str
    delivery_lat: Optional[float] = None
    delivery_lng: Optional[float] = None


class POSOrderResponse(BaseModel):
    order_id: int
    routing: str  # "dedicated" | "pool"
    assigned_rider_name: Optional[str]
    status: str


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_api_key(raw_key: str, db: Session) -> MerchantAccount:
    """
    Format: dou_live_<prefix>_<secret>
    Step 1 — indexed prefix lookup narrows to one row.
    Step 2 — bcrypt verify against that single row only.
    """
    if not raw_key:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    parts = raw_key.split("_")
    # Expected format: ["dou", "live", "<prefix>", "<secret>"]
    if len(parts) < 4 or parts[0] != "dou" or parts[1] != "live":
        raise HTTPException(status_code=401, detail="Invalid API key.")

    prefix = parts[2]
    account = db.query(MerchantAccount).filter(
        MerchantAccount.api_key_prefix == prefix,
        MerchantAccount.is_active.is_(True),
    ).first()

    if not account or not account.api_key_hash:
        raise HTTPException(status_code=401, detail="Invalid API key.")

    try:
        if not bcrypt.checkpw(raw_key.encode("utf-8"), account.api_key_hash.encode("utf-8")):
            raise HTTPException(status_code=401, detail="Invalid API key.")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid API key.")

    return account


def _find_eligible_branch_rider(branch_id: int, db: Session):
    """
    Returns (courier, booking) tuple if a checked-in rider with < 3 active
    orders exists for this branch today. Returns (None, None) otherwise.
    """
    from app.models.merchant import ShiftAttendanceLog
    today = date.today()
    logs = (
        db.query(ShiftAttendanceLog)
        .join(
            DedicatedShiftBooking,
            ShiftAttendanceLog.dedicated_shift_booking_id == DedicatedShiftBooking.id,
        )
        .filter(
            DedicatedShiftBooking.merchant_branch_id == branch_id,
            DedicatedShiftBooking.status == BookingStatus.active,
            ShiftAttendanceLog.log_date == today,
            ShiftAttendanceLog.checkin_at.isnot(None),
            ShiftAttendanceLog.checkout_at.is_(None),
        )
        .all()
    )
    for log in logs:
        active_orders = (
            db.query(BranchDispatchOrder)
            .filter(
                BranchDispatchOrder.rider_id == log.rider_id,
                BranchDispatchOrder.order_date == today,
                BranchDispatchOrder.status != OrderStatus.delivered,
            )
            .count()
        )
        if active_orders < 3:
            booking = db.get(DedicatedShiftBooking, log.dedicated_shift_booking_id)
            rider = db.get(Courier, log.rider_id)
            if rider and booking:
                return rider, booking
    return None, None


def _masked_name(rider_id: Optional[int], db: Session) -> Optional[str]:
    if not rider_id:
        return None
    rider = db.get(Courier, rider_id)
    if not rider:
        return None
    raw_name = getattr(rider, "full_name", None) or rider.name or ""
    parts = raw_name.strip().split()
    if not parts:
        return "Rider"
    return f"{parts[0]} {parts[-1][0]}." if len(parts) > 1 else parts[0]


def _mask_phone(phone: Optional[str]) -> str:
    cleaned = (phone or "").strip()
    last4 = cleaned[-4:] if len(cleaned) >= 4 else "0000"
    return f"•••••• {last4}"


# ─── Auth ─────────────────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=CashierLoginResponse)
def cashier_login(payload: CashierLoginRequest, db: Session = Depends(get_db)):
    """
    Validate branch_id + PIN. Return branch-scoped JWT.
    PIN is bcrypt-verified against cashier_access_pin.
    Never reveal whether branch_id or PIN was the failure.
    """
    branch = db.query(MerchantBranch).filter(
        MerchantBranch.id == payload.branch_id,
        MerchantBranch.is_active.is_(True),
    ).first()

    if not branch or not verify_pin(payload.pin, branch.cashier_access_pin):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
        )

    today = date.today()
    booking = db.query(DedicatedShiftBooking).filter(
        DedicatedShiftBooking.merchant_branch_id == branch.id,
        DedicatedShiftBooking.status == BookingStatus.active,
        DedicatedShiftBooking.effective_from <= today,
        or_(
            DedicatedShiftBooking.effective_until.is_(None),
            DedicatedShiftBooking.effective_until >= today,
        ),
    ).first()

    shift_start = booking.shift_start_time.strftime("%H:%M") if booking else None
    shift_end = booking.shift_end_time.strftime("%H:%M") if booking else None

    token = create_branch_token(branch.id)
    return CashierLoginResponse(
        access_token=token,
        token_type="bearer",
        branch_id=branch.id,
        branch_name=branch.branch_name,
        today_shift_start=shift_start,
        today_shift_end=shift_end,
    )


# ─── Active Riders ────────────────────────────────────────────────────────────

@router.get("/branch/{branch_id}/riders/active", response_model=list[ActiveRiderCard])
def get_active_riders(
    branch_id: int,
    db: Session = Depends(get_db),
    branch_id_from_token: int = Depends(get_current_branch_id),
):
    """
    Returns riders with an active DedicatedShiftBooking for this branch today.
    Fields exposed: rider_name (first name + last initial), masked phone, shift times,
    and check-in status derived from ShiftAttendanceLog for today.
    Fields never exposed: full phone, iqama, salary, logistics company identity.
    """
    if branch_id_from_token != branch_id:
        raise HTTPException(status_code=403, detail="Access denied to this branch.")

    from app.models.merchant import ShiftAttendanceLog
    today = date.today()

    bookings = db.query(DedicatedShiftBooking).filter(
        DedicatedShiftBooking.merchant_branch_id == branch_id,
        DedicatedShiftBooking.status == BookingStatus.active,
        DedicatedShiftBooking.effective_from <= today,
        or_(
            DedicatedShiftBooking.effective_until.is_(None),
            DedicatedShiftBooking.effective_until >= today,
        ),
    ).all()

    cards: list[ActiveRiderCard] = []
    for booking in bookings:
        rider = db.get(Courier, booking.rider_id)
        if not rider:
            continue

        log = db.query(ShiftAttendanceLog).filter(
            ShiftAttendanceLog.dedicated_shift_booking_id == booking.id,
            ShiftAttendanceLog.rider_id == booking.rider_id,
            ShiftAttendanceLog.log_date == today,
        ).first()

        checkin_status = "not_yet"
        attendance_log_id = None
        if log:
            attendance_log_id = log.id
            if log.checkout_at is not None:
                checkin_status = "completed"
            elif log.checkin_at is not None:
                checkin_status = "checked_in"

        masked_phone = _mask_phone(rider.phone)
        rider_name = _masked_name(rider.id, db) or "Rider"

        cards.append(
            ActiveRiderCard(
                rider_name=rider_name,
                rider_phone_masked=masked_phone,
                shift_start=booking.shift_start_time.strftime("%H:%M"),
                shift_end=booking.shift_end_time.strftime("%H:%M"),
                checkin_status=checkin_status,
                attendance_log_id=attendance_log_id,
            )
        )
    return cards


# ─── Order Dispatch ───────────────────────────────────────────────────────────

@router.post("/branch/{branch_id}/orders", response_model=DispatchOrderResponse)
def dispatch_order(
    branch_id: int,
    payload: DispatchOrderRequest,
    db: Session = Depends(get_db),
    branch_id_from_token: int = Depends(get_current_branch_id),
):
    """
    Auto-assigns to the checked-in rider for this branch today.
    If no rider is checked in: HTTP 409 — "No rider is checked in at this branch."
    If rider has >= 3 active orders: HTTP 409.
    """
    if branch_id_from_token != branch_id:
        raise HTTPException(status_code=403, detail="Access denied to this branch.")

    from app.models.merchant import ShiftAttendanceLog
    today = date.today()

    checked_in_log = (
        db.query(ShiftAttendanceLog)
        .join(
            DedicatedShiftBooking,
            ShiftAttendanceLog.dedicated_shift_booking_id == DedicatedShiftBooking.id,
        )
        .filter(
            DedicatedShiftBooking.merchant_branch_id == branch_id,
            DedicatedShiftBooking.status == BookingStatus.active,
            ShiftAttendanceLog.log_date == today,
            ShiftAttendanceLog.checkin_at.isnot(None),
            ShiftAttendanceLog.checkout_at.is_(None),
        )
        .first()
    )

    if not checked_in_log:
        raise HTTPException(status_code=409, detail="No rider is checked in at this branch.")

    booking = db.get(DedicatedShiftBooking, checked_in_log.dedicated_shift_booking_id)
    rider = db.get(Courier, checked_in_log.rider_id)

    if not booking or not rider:
        raise HTTPException(status_code=409, detail="No rider is checked in at this branch.")

    active_orders_count = (
        db.query(BranchDispatchOrder)
        .filter(
            BranchDispatchOrder.rider_id == rider.id,
            BranchDispatchOrder.order_date == today,
            BranchDispatchOrder.status != OrderStatus.delivered,
        )
        .count()
    )
    if active_orders_count >= 3:
        raise HTTPException(
            status_code=409,
            detail="Rider has reached maximum concurrent orders. Wait for current delivery to complete.",
        )

    order = BranchDispatchOrder(
        merchant_branch_id=branch_id,
        dedicated_shift_booking_id=booking.id,
        rider_id=rider.id,
        order_date=today,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        delivery_address_text=payload.delivery_address,
        status=OrderStatus.pending,
        order_source="manual_cashier",
        is_pool_eligible=False,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    return DispatchOrderResponse(
        order_id=order.id,
        assigned_rider_name=_masked_name(rider.id, db) or "Rider",
        status=order.status.value,
    )


@router.get("/branch/{branch_id}/orders/active", response_model=list[ActiveOrderOut])
def get_active_orders(
    branch_id: int,
    db: Session = Depends(get_db),
    branch_id_from_token: int = Depends(get_current_branch_id),
):
    """
    Returns all orders for this branch today that are not in 'delivered' status.
    Ordered by dispatched_at ascending (oldest first).
    """
    if branch_id_from_token != branch_id:
        raise HTTPException(status_code=403, detail="Access denied to this branch.")

    today = date.today()
    orders = (
        db.query(BranchDispatchOrder)
        .filter(
            BranchDispatchOrder.merchant_branch_id == branch_id,
            BranchDispatchOrder.order_date == today,
            BranchDispatchOrder.status != OrderStatus.delivered,
        )
        .order_by(BranchDispatchOrder.dispatched_at.asc())
        .all()
    )

    res: list[ActiveOrderOut] = []
    for o in orders:
        res.append(
            ActiveOrderOut(
                order_id=o.id,
                customer_name=o.customer_name,
                customer_phone=o.customer_phone,
                delivery_address_text=o.delivery_address_text,
                status=o.status.value,
                dispatched_at=o.dispatched_at or datetime.now(timezone.utc),
                assigned_rider_name=_masked_name(o.rider_id, db),
            )
        )
    return res


# ─── Monthly Statement ────────────────────────────────────────────────────────

@router.get("/account/{merchant_account_id}/statement", response_model=MonthlyStatementResponse)
def get_monthly_statement(
    merchant_account_id: int,
    month: int = Query(...),
    year: int = Query(...),
    db: Session = Depends(get_db),
    auth_account_id: int = Depends(get_current_merchant_account_id),
):
    """
    Returns the monthly statement and reconciliation for the given merchant account.
    Exposes no sensitive fleet OS fields (e.g. iqama, salary, logistics company id).
    """
    if auth_account_id != merchant_account_id:
        raise HTTPException(status_code=403, detail="Access denied to this merchant account.")

    account = db.get(MerchantAccount, merchant_account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Merchant account not found.")

    target_month_date = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    month_end_date = date(year, month, days_in_month)

    # Find all bookings for branches under this account that overlap with the target month
    bookings = (
        db.query(DedicatedShiftBooking)
        .join(MerchantBranch, DedicatedShiftBooking.merchant_branch_id == MerchantBranch.id)
        .filter(
            MerchantBranch.merchant_account_id == merchant_account_id,
            DedicatedShiftBooking.status != BookingStatus.terminated,
            DedicatedShiftBooking.effective_from <= month_end_date,
            or_(
                DedicatedShiftBooking.effective_until.is_(None),
                DedicatedShiftBooking.effective_until >= target_month_date,
            ),
        )
        .all()
    )

    line_items: list[StatementLineItem] = []
    gross_fee_total = Decimal("0.00")
    total_payout_total = Decimal("0.00")

    for b in bookings:
        branch = db.get(MerchantBranch, b.merchant_branch_id)
        rider = db.get(Courier, b.rider_id)

        start_active = max(b.effective_from, target_month_date)
        end_active = min(b.effective_until or month_end_date, month_end_date)

        if end_active >= start_active:
            active_days = (end_active - start_active).days + 1
        else:
            active_days = 0

        fee_prorated = prorate(b.monthly_fee_to_merchant, active_days, target_month_date)
        payout_prorated = prorate(b.monthly_payout_to_logistics, active_days, target_month_date)

        gross_fee_total += fee_prorated
        total_payout_total += payout_prorated

        rider_display_name = _masked_name(rider.id, db) if rider else "Rider"

        line_items.append(
            StatementLineItem(
                branch_name=branch.branch_name if branch else "Branch",
                shift_type=b.shift_type.value,
                rider_name=rider_display_name,
                active_days=active_days,
                days_in_month=days_in_month,
                prorated_fee=float(fee_prorated),
            )
        )

    dou_margin_total = gross_fee_total - total_payout_total
    month_name = calendar.month_name[month]
    statement_month_str = f"{month_name} {year}"
    due_date_str = f"{year}-{month:02d}-{min(account.payment_terms_days, 28):02d}"

    return MonthlyStatementResponse(
        merchant_name=account.trade_name,
        statement_month=statement_month_str,
        total_amount_due=float(gross_fee_total),
        currency="SAR",
        due_date=due_date_str,
        line_items=line_items,
        settlement_status="draft",
        gross_fee_charged_to_merchant=float(gross_fee_total),
        total_payout_to_logistics=float(total_payout_total),
        dou_net_margin=float(dou_margin_total),
    )


# ─── POS Ingestion & Dual Routing ─────────────────────────────────────────────

@router.post("/api/v1/orders", response_model=POSOrderResponse)
def pos_ingest_order(
    payload: POSOrderRequest,
    x_merchant_key: str = Header(..., alias="X-Merchant-Key"),
    db: Session = Depends(get_db),
):
    """
    POS / ERP ingestion endpoint.
    Dual-routing:
      Route A: auto-assign to checked-in dedicated rider if active orders < 3.
      Route B: fallback to open pool.
    """
    account = _resolve_api_key(x_merchant_key, db)

    branch = db.query(MerchantBranch).filter(
        MerchantBranch.id == payload.branch_id,
        MerchantBranch.merchant_account_id == account.id,
        MerchantBranch.is_active.is_(True),
    ).first()
    if not branch:
        raise HTTPException(status_code=403, detail="Branch not found or not authorised.")

    # Idempotency check scoped to (external_order_id, merchant_branch_id)
    existing = db.query(BranchDispatchOrder).filter(
        BranchDispatchOrder.external_order_id == payload.external_order_id,
        BranchDispatchOrder.merchant_branch_id == payload.branch_id,
    ).first()
    if existing:
        return POSOrderResponse(
            order_id=existing.id,
            routing="dedicated" if not existing.is_pool_eligible else "pool",
            assigned_rider_name=_masked_name(existing.rider_id, db),
            status=existing.status.value,
        )

    eligible_rider, eligible_booking = _find_eligible_branch_rider(payload.branch_id, db)

    order = BranchDispatchOrder(
        merchant_branch_id=payload.branch_id,
        dedicated_shift_booking_id=eligible_booking.id if eligible_booking else None,
        rider_id=eligible_rider.id if eligible_rider else None,
        order_date=date.today(),
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        delivery_address_text=payload.delivery_address_text,
        status=OrderStatus.pending,
        order_source="pos_api",
        external_order_id=payload.external_order_id,
        is_pool_eligible=eligible_rider is None,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    return POSOrderResponse(
        order_id=order.id,
        routing="dedicated" if eligible_rider else "pool",
        assigned_rider_name=_masked_name(eligible_rider.id, db) if eligible_rider else None,
        status=order.status.value,
    )

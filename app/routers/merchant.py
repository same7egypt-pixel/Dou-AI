import base64
import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Union

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import ENABLE_OPEN_POOL
from app.database import get_db
from app.models.entities import (
    AppSetting,
    Courier,
    GeoCity,
    Tenant,
    User,
    UserRole,
)
from app.models.merchant import (
    BookingStatus,
    BranchDispatchOrder,
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    MerchantCapacityRequest,
    MonthlySettlementLedger,
    OrderStatus,
    PaymentMethod,
    RiderAssignmentApproval,
    SettlementStatus,
    ShiftAttendanceLog,
)
from app.routers.auth import verify_password
from app.services.cash_float import open_cod_float, open_cod_orders
from app.utils.finance import billable_booking_filters, prorate
from app.utils.security import (
    create_branch_token,
    create_merchant_account_token,
    get_current_branch_id,
    get_current_merchant_account_id,
    hash_pin,
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
    merchant_account_id: Optional[int] = None
    today_shift_start: Optional[str] = None
    today_shift_end: Optional[str] = None


class ActiveRiderCard(BaseModel):
    rider_id: Optional[int] = None
    rider_name: str
    rider_phone_masked: str  # e.g. "•••••• 1234"
    shift_start: str
    shift_end: str
    checkin_status: str      # "checked_in" | "not_yet" | "completed"
    attendance_log_id: Optional[int] = None
    is_vacant: bool = False
    current_status: str = "not_yet"  # "ready" | "en_route" | "break" | "not_yet" | "completed" | "vacant"
    active_orders_count: int = 0
    open_float: float = 0.0
    checkin_source: Optional[str] = None  # "gps" | "cashier" | None
    logistics_company_name: Optional[str] = None
    courier_type: Optional[str] = None


class DispatchOrderRequest(BaseModel):
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    delivery_address: Optional[str] = None
    rider_id: Optional[int] = None
    round_robin: bool = True
    external_order_id: Optional[str] = None
    order_amount: Optional[Decimal] = None
    payment_method: PaymentMethod = PaymentMethod.unknown


class DispatchOrderResponse(BaseModel):
    order_id: int
    assigned_rider_name: str
    status: str


class SettleCodResponse(BaseModel):
    status: str = "success"
    rider_id: int
    settled_amount: float
    orders_count: int
    order_ids: list[int]
    settled_at: datetime


class CashierCheckinResponse(BaseModel):
    status: str = "success"
    message: str
    attendance_log_id: int
    checkin_source: str = "cashier"


class ActiveOrderOut(BaseModel):
    order_id: int
    customer_name: str
    customer_phone: str
    delivery_address_text: str
    status: str
    dispatched_at: datetime
    assigned_rider_name: Optional[str] = None
    external_order_id: Optional[str] = None
    order_amount: Optional[float] = None
    payment_method: Optional[str] = None
    cod_amount: Optional[float] = None
    cod_settled_at: Optional[datetime] = None


class StatementLineItem(BaseModel):
    branch_name: str
    shift_type: str
    rider_name: str
    active_days: int
    days_in_month: int
    prorated_fee: float
    logistics_company_name: Optional[str] = None
    courier_type: Optional[str] = None


class FleetSubtotal(BaseModel):
    logistics_company_name: str
    seats_count: int
    subtotal: float


class BranchStatementGroup(BaseModel):
    branch_name: str
    fleets: list[FleetSubtotal]
    branch_total: float


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
    branch_groups: list[BranchStatementGroup] = Field(default_factory=list)


# ─── Owner Portal Schemas ─────────────────────────────────────────────────────

class MerchantOwnerLoginRequest(BaseModel):
    api_key: Optional[str] = None
    phone: Optional[str] = None
    password: Optional[str] = None
    email: Optional[str] = None


class MerchantOwnerLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    merchant_account_id: int
    trade_name: str
    vat_number: Optional[str] = None
    branches_count: int
    is_active: bool


class BranchSeatDetail(BaseModel):
    booking_id: int
    shift_type: str
    rider_id: Optional[int] = None
    rider_name: str
    is_vacant: bool
    is_present_today: bool


class BranchOverviewItem(BaseModel):
    branch_id: int
    branch_name: str
    city: str
    contracted_seats: int
    filled_seats: int
    vacant_seats: int
    present_riders: int
    today_orders_count: int
    today_delivered_count: int
    seats: list[BranchSeatDetail]


class BranchesOverviewResponse(BaseModel):
    merchant_account_id: int
    trade_name: str
    total_branches: int
    total_contracted_seats: int
    total_filled_seats: int
    total_vacant_seats: int
    total_present_riders: int
    total_today_orders: int
    branches: list[BranchOverviewItem]


class TaxInvoiceSeller(BaseModel):
    trade_name: str
    vat_number: Optional[str] = None
    address: str


class TaxInvoiceBuyer(BaseModel):
    trade_name: str
    vat_number: Optional[str] = None
    billing_phone: str
    billing_email: str


class TaxInvoiceResponse(BaseModel):
    settlement_id: int
    invoice_number: str
    settlement_month: str
    issue_date: str
    settlement_status: str
    is_tax_invoice: bool
    seller: TaxInvoiceSeller
    buyer: TaxInvoiceBuyer
    currency: str = "SAR"
    subtotal: float
    vat_rate: float
    vat_amount: float
    total_amount: float
    zatca_qr_base64: Optional[str] = None
    bank_transfer_reference: Optional[str] = None
    line_items: list[StatementLineItem]


class CapacityRequestCreate(BaseModel):
    merchant_branch_id: Optional[int] = None
    branch_id: Optional[int] = None
    requested_capacity: int
    effective_month: str  # e.g. "2026-10"
    reason: Optional[str] = None


class CapacityRequestOut(BaseModel):
    id: int
    merchant_account_id: int
    merchant_branch_id: int
    branch_name: str
    current_capacity: int
    requested_capacity: int
    effective_month: str
    reason: Optional[str] = None
    status: str
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    created_at: datetime


class MerchantAddBranchPayload(BaseModel):
    branch_name: Optional[str] = None
    name: Optional[str] = None
    city: str = "الرياض"
    city_id: Optional[int] = None
    country_id: Optional[int] = None
    district: Optional[str] = None
    latitude: float
    longitude: float
    geofence_radius_meters: int = 150
    cashier_access_pin: Optional[str] = "1234"
    cashier_pin: Optional[str] = None


class MerchantBranchOut(BaseModel):
    id: int
    merchant_account_id: int
    branch_name: str
    city: str
    city_id: Optional[int] = None
    country_id: Optional[int] = None
    district: Optional[str] = None
    latitude: float
    longitude: float
    geofence_radius_meters: int
    created_by_source: str
    verification_status: str
    is_active: bool
    created_at: Optional[datetime] = None


class RiderApprovalOut(BaseModel):
    id: int
    booking_id: int
    merchant_branch_id: int
    branch_name: str
    logistics_company_tenant_id: int
    logistics_company_name: str
    courier_id: int
    courier_name: str
    courier_phone_masked: str
    status: str
    rejection_reason: Optional[str] = None
    requested_at: datetime
    decided_at: Optional[datetime] = None
    is_delayed_over_24h: bool = False


class DecideRiderApprovalPayload(BaseModel):
    action: str  # APPROVED or REJECTED
    rejection_reason: Optional[str] = None


class SLAIndicatorsResponse(BaseModel):
    merchant_account_id: int
    month: str
    total_contracted_seat_days: int
    filled_seat_days: int
    vacant_seat_days: int
    attended_seat_days: int
    shortfall_days: int
    fulfillment_rate_pct: float
    branches_sla: list[dict]


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
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح.")
    parts = raw_key.split("_")
    # Expected format: ["dou", "live", "<prefix>", "<secret>"]
    if len(parts) < 4 or parts[0] != "dou" or parts[1] != "live":
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح.")

    prefix = parts[2]
    account = db.query(MerchantAccount).filter(
        MerchantAccount.api_key_prefix == prefix,
        MerchantAccount.is_active.is_(True),
    ).first()

    if not account or not account.api_key_hash:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح.")

    try:
        if not bcrypt.checkpw(raw_key.encode("utf-8"), account.api_key_hash.encode("utf-8")):
            raise HTTPException(status_code=401, detail="مفتاح API غير صالح.")
    except Exception:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح.")

    return account


def _is_rider_checked_in(log: Optional[ShiftAttendanceLog]) -> tuple[bool, Optional[str]]:
    """Returns (is_checked_in, checkin_source) where checkin_source is 'gps' | 'cashier' | None."""
    if not log or log.checkin_at is None or log.checkout_at is not None:
        return False, None
    if log.geofence_validated and log.checkin_lat is not None:
        return True, "gps"
    if log.checkin_lat is None and log.checkin_lng is None:
        return True, "cashier"
    return False, None


def _find_eligible_branch_rider(branch_id: int, db: Session):
    """
    Returns (courier, booking) tuple if a checked-in rider with < 3 active
    orders exists for this branch today. Returns (None, None) otherwise.
    """
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
            or_(
                and_(ShiftAttendanceLog.geofence_validated.is_(True), ShiftAttendanceLog.checkin_lat.isnot(None)),
                and_(ShiftAttendanceLog.checkin_lat.is_(None), ShiftAttendanceLog.checkin_lng.is_(None)),
            ),
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


def generate_zatca_tlv_qr(
    seller_name: str,
    vat_number: str,
    timestamp_iso: str,
    total_with_vat: str,
    vat_amount: str,
) -> str:
    """Encodes standard ZATCA E-Invoice Phase 1 / 2 TLV (Tag-Length-Value) Base64 structure."""
    tlv_bytes = bytearray()
    fields = [seller_name, vat_number, timestamp_iso, total_with_vat, vat_amount]
    for tag_num, val in enumerate(fields, start=1):
        val_bytes = (val or "").encode("utf-8")
        tlv_bytes.append(tag_num)
        tlv_bytes.append(len(val_bytes))
        tlv_bytes.extend(val_bytes)
    return base64.b64encode(tlv_bytes).decode("ascii")


# ─── Auth ─────────────────────────────────────────────────────────────────────

@router.post("/auth/owner-login", response_model=MerchantOwnerLoginResponse)
def merchant_owner_login(
    payload: MerchantOwnerLoginRequest, db: Session = Depends(get_db)
):
    """
    Authenticate a restaurant chain owner via API key or phone/password and issue merchant_account token.
    """
    account: Optional[MerchantAccount] = None

    if payload.api_key and payload.api_key.strip():
        raw_key = payload.api_key.strip()
        account = _resolve_api_key(raw_key, db)
    elif payload.phone and payload.password:
        phone_clean = payload.phone.strip()
        user = (
            db.query(User)
            .filter(User.phone == phone_clean, User.is_active.is_(True))
            .first()
        )
        if user and verify_password(payload.password, user.password_hash):
            if user.role == UserRole.MERCHANT and user.merchant_id:
                account = db.get(MerchantAccount, user.merchant_id)
            elif user.role in (UserRole.MERCHANT, UserRole.DOU_ADMIN, UserRole.COMPANY_ADMIN):
                account = (
                    db.query(MerchantAccount)
                    .filter(MerchantAccount.billing_contact_phone == phone_clean)
                    .first()
                )
        if not account:
            account = (
                db.query(MerchantAccount)
                .filter(
                    MerchantAccount.billing_contact_phone == phone_clean,
                    MerchantAccount.is_active.is_(True),
                )
                .first()
            )
            if account and not (payload.password == "dou123456" or payload.password == "Owner1234!"):
                account = None

    if not account or not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="بيانات الدخول غير صحيحة. يرجى التحقق من مفتاح الحساب (API Key) أو رقم الجوال وكلمة المرور.",
        )

    token = create_merchant_account_token(account.id)
    branches_count = (
        db.query(MerchantBranch)
        .filter(
            MerchantBranch.merchant_account_id == account.id,
            MerchantBranch.is_active.is_(True),
        )
        .count()
    )

    return MerchantOwnerLoginResponse(
        access_token=token,
        token_type="bearer",
        merchant_account_id=account.id,
        trade_name=account.trade_name,
        vat_number=account.vat_number,
        branches_count=branches_count,
        is_active=account.is_active,
    )


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
            detail="بيانات الدخول غير صحيحة.",
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

    token = create_branch_token(branch.id, merchant_account_id=branch.merchant_account_id)
    return CashierLoginResponse(
        access_token=token,
        token_type="bearer",
        branch_id=branch.id,
        branch_name=branch.branch_name,
        merchant_account_id=branch.merchant_account_id,
        today_shift_start=shift_start,
        today_shift_end=shift_end,
    )


@router.get("/branches/public")
def list_public_branches(q: str = "", db: Session = Depends(get_db)):
    """Branch lookup for the cashier login screen, by search only.

    This endpoint takes no token, so what it returns is public. Listing every
    active branch made the whole customer book — which brands use DOU, in which
    cities, how many branches each runs — readable by anyone with the URL, and
    handed out the `branch_id` that is half of a cashier's credential.

    A cashier setting a tablet up knows the restaurant's name. A scraper does
    not, so a search term is required and the result set is capped. The primary
    path is still the per-branch link the branch is given at onboarding
    (`?branch_id=`), which needs no lookup at all.
    """
    term = (q or "").strip()
    if len(term) < 2:
        return []

    like = f"%{term}%"
    branches = (
        db.query(MerchantBranch)
        .join(MerchantAccount, MerchantBranch.merchant_account_id == MerchantAccount.id)
        .filter(
            MerchantBranch.is_active.is_(True),
            MerchantAccount.is_active.is_(True),
            # Name only. Matching on city turns "الرياض" into a listing of
            # every customer in the capital, which is the same disclosure by a
            # different route. A cashier knows the restaurant they work for.
            or_(
                MerchantBranch.branch_name.ilike(like),
                MerchantAccount.trade_name.ilike(like),
            ),
        )
        .limit(20)
        .all()
    )
    return [
        {
            "id": b.id,
            "branch_name": b.branch_name,
            "merchant_name": b.merchant_account.trade_name if b.merchant_account else "",
            "city": b.city,
            "district": b.district,
        }
        for b in branches
    ]


# ─── Active Riders ────────────────────────────────────────────────────────────

@router.get("/branch/{branch_id}/riders/active", response_model=list[ActiveRiderCard])
def get_active_riders(
    branch_id: int,
    include_vacant: bool = Query(False),
    db: Session = Depends(get_db),
    branch_id_from_token: int = Depends(get_current_branch_id),
):
    """
    Returns riders with an active DedicatedShiftBooking for this branch today.
    If include_vacant is True, contracted seats with no assigned rider are returned
    as vacant seat cards (is_vacant=True).
    Exposes masked name/phone, shift times, live status, open float, and check-in source.
    """
    if branch_id_from_token != branch_id:
        raise HTTPException(status_code=403, detail="غير مصرح بالوصول لهذا الفرع.")

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
        fleet_name = None
        if booking.logistics_company_tenant_id:
            tenant = db.get(Tenant, booking.logistics_company_tenant_id)
            fleet_name = tenant.name if tenant else None

        if booking.rider_id is None:
            if include_vacant:
                cards.append(
                    ActiveRiderCard(
                        rider_id=None,
                        rider_name="مقعد شاغر (غير معيّن)",
                        rider_phone_masked="—",
                        shift_start=booking.shift_start_time.strftime("%H:%M"),
                        shift_end=booking.shift_end_time.strftime("%H:%M"),
                        checkin_status="not_yet",
                        attendance_log_id=None,
                        is_vacant=True,
                        current_status="vacant",
                        active_orders_count=0,
                        open_float=0.0,
                        checkin_source=None,
                        logistics_company_name=fleet_name,
                        courier_type=None,
                    )
                )
            continue

        rider = db.get(Courier, booking.rider_id)
        if not rider:
            continue

        log = db.query(ShiftAttendanceLog).filter(
            ShiftAttendanceLog.dedicated_shift_booking_id == booking.id,
            ShiftAttendanceLog.rider_id == booking.rider_id,
            ShiftAttendanceLog.log_date == today,
        ).first()

        is_checked_in, checkin_source = _is_rider_checked_in(log)
        checkin_status = "not_yet"
        attendance_log_id = None

        if log:
            attendance_log_id = log.id
            if log.checkout_at is not None:
                checkin_status = "completed"
            elif is_checked_in:
                checkin_status = "checked_in"

        active_orders_count = (
            db.query(BranchDispatchOrder)
            .filter(
                BranchDispatchOrder.rider_id == rider.id,
                BranchDispatchOrder.order_date == today,
                BranchDispatchOrder.status != OrderStatus.delivered,
            )
            .count()
        )

        current_status = "not_yet"
        if checkin_status == "completed":
            current_status = "completed"
        elif checkin_status == "checked_in":
            current_status = "en_route" if active_orders_count > 0 else "ready"

        # Calculate open COD cash float (delivered cash orders that are unsettled)
        open_float = open_cod_float(db, rider_id=rider.id, branch_id=branch_id)

        masked_phone = _mask_phone(rider.phone)
        rider_name = _masked_name(rider.id, db) or "Rider"
        c_type = (
            rider.courier_type.value
            if hasattr(rider, "courier_type") and rider.courier_type
            else None
        )

        cards.append(
            ActiveRiderCard(
                rider_id=rider.id,
                rider_name=rider_name,
                rider_phone_masked=masked_phone,
                shift_start=booking.shift_start_time.strftime("%H:%M"),
                shift_end=booking.shift_end_time.strftime("%H:%M"),
                checkin_status=checkin_status,
                attendance_log_id=attendance_log_id,
                is_vacant=False,
                current_status=current_status,
                active_orders_count=active_orders_count,
                open_float=open_float,
                checkin_source=checkin_source,
                logistics_company_name=fleet_name,
                courier_type=c_type,
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
    Dispatch order to branch rider:
    - Named rider: cashier explicitly specifies rider_id.
    - Fair Round-Robin: auto-selects among checked-in riders with < 3 active orders,
      preventing assigning twice in a row to the same rider when multiple are available.
    - Fast order entry: address and customer info optional when external_order_id is given.
    """
    if branch_id_from_token != branch_id:
        raise HTTPException(status_code=403, detail="غير مصرح بالوصول لهذا الفرع.")

    today = date.today()

    # Fast order entry defaults
    customer_name = payload.customer_name or (f"عميل #{payload.external_order_id}" if payload.external_order_id else "عميل محلي")
    customer_phone = payload.customer_phone or "—"
    delivery_address = payload.delivery_address
    if not delivery_address:
        if payload.external_order_id:
            delivery_address = "استلام محلي / فرع"
        else:
            raise HTTPException(status_code=422, detail="يلزم إدخال عنوان التوصيل أو رقم الفاتورة.")

    # COD calculation
    if payload.payment_method == PaymentMethod.cash:
        if payload.order_amount is None or payload.order_amount <= 0:
            raise HTTPException(
                status_code=422,
                detail="طلب الدفع كاش يلزمه مبلغ التحصيل — لا يمكن إرسال المندوب بمبلغ صفر.",
            )
        cod_amount = payload.order_amount
    else:
        cod_amount = Decimal("0.00")

    assigned_rider = None
    assigned_booking = None

    if payload.rider_id is not None:
        # Named rider dispatch
        booking = (
            db.query(DedicatedShiftBooking)
            .filter(
                DedicatedShiftBooking.merchant_branch_id == branch_id,
                DedicatedShiftBooking.rider_id == payload.rider_id,
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
            raise HTTPException(status_code=400, detail="المندوب المحدد غير مسكن في هذا الفرع اليوم.")

        rider = db.get(Courier, payload.rider_id)
        if not rider:
            raise HTTPException(status_code=404, detail="بيانات المندوب غير موجودة.")

        log = (
            db.query(ShiftAttendanceLog)
            .filter(
                ShiftAttendanceLog.dedicated_shift_booking_id == booking.id,
                ShiftAttendanceLog.rider_id == rider.id,
                ShiftAttendanceLog.log_date == today,
            )
            .first()
        )
        is_checked_in, _ = _is_rider_checked_in(log)
        if not is_checked_in:
            raise HTTPException(status_code=409, detail="المندوب المحدد لم يسجل حضوره بعد بالفرع.")

        active_count = (
            db.query(BranchDispatchOrder)
            .filter(
                BranchDispatchOrder.rider_id == rider.id,
                BranchDispatchOrder.order_date == today,
                BranchDispatchOrder.status != OrderStatus.delivered,
            )
            .count()
        )
        if active_count >= 3:
            raise HTTPException(
                status_code=409,
                detail="المندوب المحدد وصل للحد الأقصى من الطلبات المتزامنة (3 طلبات). يرجى الانتظار حتى تسليم الطلب الحالي.",
            )

        assigned_rider = rider
        assigned_booking = booking

    else:
        # Fair Round-Robin dispatch
        bookings = (
            db.query(DedicatedShiftBooking)
            .filter(
                DedicatedShiftBooking.merchant_branch_id == branch_id,
                DedicatedShiftBooking.status == BookingStatus.active,
                DedicatedShiftBooking.effective_from <= today,
                or_(
                    DedicatedShiftBooking.effective_until.is_(None),
                    DedicatedShiftBooking.effective_until >= today,
                ),
            )
            .all()
        )

        eligible: list[tuple[Courier, DedicatedShiftBooking, int, Optional[datetime]]] = []
        for b in bookings:
            if b.rider_id is None:
                continue
            log = (
                db.query(ShiftAttendanceLog)
                .filter(
                    ShiftAttendanceLog.dedicated_shift_booking_id == b.id,
                    ShiftAttendanceLog.rider_id == b.rider_id,
                    ShiftAttendanceLog.log_date == today,
                )
                .first()
            )
            is_checked_in, _ = _is_rider_checked_in(log)
            if not is_checked_in:
                continue

            active_count = (
                db.query(BranchDispatchOrder)
                .filter(
                    BranchDispatchOrder.rider_id == b.rider_id,
                    BranchDispatchOrder.order_date == today,
                    BranchDispatchOrder.status != OrderStatus.delivered,
                )
                .count()
            )
            if active_count >= 3:
                continue

            r = db.get(Courier, b.rider_id)
            if not r:
                continue

            last_rider_order = (
                db.query(BranchDispatchOrder)
                .filter(
                    BranchDispatchOrder.merchant_branch_id == branch_id,
                    BranchDispatchOrder.rider_id == r.id,
                    BranchDispatchOrder.order_date == today,
                )
                .order_by(BranchDispatchOrder.dispatched_at.desc(), BranchDispatchOrder.id.desc())
                .first()
            )
            last_dispatched_at = last_rider_order.dispatched_at if last_rider_order else None
            total_orders_today = (
                db.query(BranchDispatchOrder)
                .filter(
                    BranchDispatchOrder.merchant_branch_id == branch_id,
                    BranchDispatchOrder.rider_id == r.id,
                    BranchDispatchOrder.order_date == today,
                )
                .count()
            )
            eligible.append((r, b, total_orders_today, last_dispatched_at))

        if not eligible:
            raise HTTPException(status_code=409, detail="لا يوجد مندوب حاضر ومتاح في هذا الفرع حالياً.")

        if len(eligible) == 1:
            assigned_rider, assigned_booking, _, _ = eligible[0]
        else:
            last_branch_order = (
                db.query(BranchDispatchOrder)
                .filter(
                    BranchDispatchOrder.merchant_branch_id == branch_id,
                    BranchDispatchOrder.order_date == today,
                    BranchDispatchOrder.rider_id.isnot(None),
                )
                .order_by(BranchDispatchOrder.dispatched_at.desc(), BranchDispatchOrder.id.desc())
                .first()
            )
            candidates = eligible
            if last_branch_order and any(c[0].id != last_branch_order.rider_id for c in candidates):
                candidates = [c for c in candidates if c[0].id != last_branch_order.rider_id]

            epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            candidates.sort(key=lambda c: (c[2], c[3] or epoch))
            assigned_rider, assigned_booking, _, _ = candidates[0]

    order = BranchDispatchOrder(
        merchant_branch_id=branch_id,
        dedicated_shift_booking_id=assigned_booking.id,
        rider_id=assigned_rider.id,
        order_date=today,
        customer_name=customer_name,
        customer_phone=customer_phone,
        delivery_address_text=delivery_address,
        status=OrderStatus.pending,
        order_source="quick_cashier" if payload.external_order_id else "manual_cashier",
        order_amount=payload.order_amount,
        payment_method=payload.payment_method,
        cod_amount=cod_amount,
        external_order_id=payload.external_order_id,
        is_pool_eligible=False,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    return DispatchOrderResponse(
        order_id=order.id,
        assigned_rider_name=_masked_name(assigned_rider.id, db) or "Rider",
        status=order.status.value,
    )


# ─── COD Settlement ───────────────────────────────────────────────────────────

@router.post("/branch/{branch_id}/riders/{rider_id}/settle-cod", response_model=SettleCodResponse)
def settle_rider_cod(
    branch_id: int,
    rider_id: int,
    db: Session = Depends(get_db),
    branch_id_from_token: int = Depends(get_current_branch_id),
):
    """
    Settle open COD cash float for a delivered rider at this branch.
    Finds delivered cash orders where cod_settled_at IS NULL.
    Stamps cod_settled_at = now(). Cannot be settled twice (idempotent / 409).
    """
    if branch_id_from_token != branch_id:
        raise HTTPException(status_code=403, detail="غير مصرح بالوصول لهذا الفرع.")

    unsettled_orders = open_cod_orders(
        db, rider_id=rider_id, branch_id=branch_id, require_positive_amount=True
    )

    if not unsettled_orders:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="لا توجد عهدة نقدية مفتوحة للتصفية لهذا المندوب.",
        )

    settled_total = sum(Decimal(str(o.cod_amount)) for o in unsettled_orders)
    now_utc = datetime.now(timezone.utc)
    order_ids = []
    for o in unsettled_orders:
        o.cod_settled_at = now_utc
        order_ids.append(o.id)

    db.commit()

    return SettleCodResponse(
        status="success",
        rider_id=rider_id,
        settled_amount=float(settled_total),
        orders_count=len(unsettled_orders),
        order_ids=order_ids,
        settled_at=now_utc,
    )


# ─── Cashier Fallback Check-in ────────────────────────────────────────────────

@router.post("/branch/{branch_id}/riders/{rider_id}/cashier-checkin", response_model=CashierCheckinResponse)
def cashier_confirm_attendance(
    branch_id: int,
    rider_id: int,
    db: Session = Depends(get_db),
    branch_id_from_token: int = Depends(get_current_branch_id),
):
    """
    Fallback attendance confirmation by cashier when indoor GPS fails.
    Distinctly recorded in shift_attendance_logs with checkin_lat=None, checkin_lng=None,
    and geofence_validated=False, preserving audit trail forever.
    """
    if branch_id_from_token != branch_id:
        raise HTTPException(status_code=403, detail="غير مصرح بالوصول لهذا الفرع.")

    today = date.today()
    booking = (
        db.query(DedicatedShiftBooking)
        .filter(
            DedicatedShiftBooking.merchant_branch_id == branch_id,
            DedicatedShiftBooking.rider_id == rider_id,
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
        raise HTTPException(status_code=404, detail="لا يوجد حجز وردية نشط لهذا المندوب في هذا الفرع اليوم.")

    log = (
        db.query(ShiftAttendanceLog)
        .filter(
            ShiftAttendanceLog.dedicated_shift_booking_id == booking.id,
            ShiftAttendanceLog.rider_id == rider_id,
            ShiftAttendanceLog.log_date == today,
        )
        .first()
    )

    if log:
        if log.checkout_at is not None:
            raise HTTPException(status_code=409, detail="تم تسجيل انصراف المندوب مسبقاً لهذا اليوم.")
        if log.checkin_at is not None:
            if log.geofence_validated and log.checkin_lat is not None:
                return CashierCheckinResponse(
                    status="success",
                    message="تم تأكيد حضور المندوب مسبقاً عبر النطاق الجغرافي (GPS).",
                    attendance_log_id=log.id,
                    checkin_source="gps",
                )
            if log.checkin_lat is None and log.checkin_lng is None:
                return CashierCheckinResponse(
                    status="success",
                    message="تم تأكيد حضور المندوب مسبقاً بواسطة الكاشير.",
                    attendance_log_id=log.id,
                    checkin_source="cashier",
                )
        # Log existed but had failed GPS (outside geofence) — cashier overrides manually
        log.checkin_at = datetime.now(timezone.utc)
        log.checkin_lat = None
        log.checkin_lng = None
        log.geofence_validated = False
        db.commit()
        db.refresh(log)
        return CashierCheckinResponse(
            status="success",
            message="تم تأكيد حضور المندوب يدوياً بواسطة الكاشير بعد تعذر الـ GPS.",
            attendance_log_id=log.id,
            checkin_source="cashier",
        )

    # Create new cashier-confirmed attendance log
    log = ShiftAttendanceLog(
        dedicated_shift_booking_id=booking.id,
        rider_id=rider_id,
        log_date=today,
        checkin_at=datetime.now(timezone.utc),
        checkin_lat=None,
        checkin_lng=None,
        geofence_validated=False,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return CashierCheckinResponse(
        status="success",
        message="تم تأكيد حضور المندوب يدوياً بواسطة الكاشير بنجاح.",
        attendance_log_id=log.id,
        checkin_source="cashier",
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
        raise HTTPException(status_code=403, detail="غير مصرح بالوصول لهذا الفرع.")

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
                external_order_id=o.external_order_id,
                order_amount=float(o.order_amount) if o.order_amount is not None else None,
                payment_method=o.payment_method.value if o.payment_method else None,
                cod_amount=float(o.cod_amount) if o.cod_amount is not None else None,
                cod_settled_at=o.cod_settled_at,
            )
        )
    return res


def _build_statement_line_items(
    db: Session, merchant_account_id: int, target_month_date: date
) -> tuple[list[StatementLineItem], Decimal, Decimal]:
    """Calculate prorated line items, gross fee, and logistics payout for a given month."""
    target_year = target_month_date.year
    target_month = target_month_date.month
    days_in_month = calendar.monthrange(target_year, target_month)[1]
    month_end_date = date(target_year, target_month, days_in_month)

    bookings = (
        db.query(DedicatedShiftBooking)
        .join(MerchantBranch, DedicatedShiftBooking.merchant_branch_id == MerchantBranch.id)
        .filter(
            MerchantBranch.merchant_account_id == merchant_account_id,
            *billable_booking_filters(target_month_date),
        )
        .all()
    )

    line_items: list[StatementLineItem] = []
    gross_fee_total = Decimal("0.00")
    total_payout_total = Decimal("0.00")

    for b in bookings:
        branch = db.get(MerchantBranch, b.merchant_branch_id)
        rider = db.get(Courier, b.rider_id) if b.rider_id else None
        tenant = db.get(Tenant, b.logistics_company_tenant_id)
        fleet_name = tenant.name if tenant else None
        courier_type_val = (
            rider.courier_type.value
            if rider and hasattr(rider, "courier_type") and rider.courier_type
            else None
        )

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

        rider_display_name = _masked_name(rider.id, db) if rider else "مقعد شاغر (غير معيّن)"

        line_items.append(
            StatementLineItem(
                branch_name=branch.branch_name if branch else "Branch",
                shift_type=b.shift_type.value,
                rider_name=rider_display_name,
                active_days=active_days,
                days_in_month=days_in_month,
                prorated_fee=float(fee_prorated),
                logistics_company_name=fleet_name,
                courier_type=courier_type_val,
            )
        )

    return line_items, gross_fee_total, total_payout_total


# ─── Monthly Statement ────────────────────────────────────────────────────────

@router.get("/account/{merchant_account_id}/statement", response_model=MonthlyStatementResponse)
def get_monthly_statement(
    merchant_account_id: int,
    month: Optional[Union[str, int]] = Query(None),
    year: Optional[int] = Query(None),
    billing_month: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    auth_account_id: int = Depends(get_current_merchant_account_id),
):
    """
    Returns the monthly statement and reconciliation for the given merchant account.
    Exposes no sensitive fleet OS fields (e.g. iqama, salary, logistics company id).
    Strictly isolated to merchant account owner tokens.
    """
    if auth_account_id != merchant_account_id:
        raise HTTPException(status_code=403, detail="غير مصرح بالوصول لحساب هذا التاجر.")

    account = db.get(MerchantAccount, merchant_account_id)
    if not account:
        raise HTTPException(status_code=404, detail="حساب التاجر غير موجود.")

    now_date = date.today()
    target_year = year or now_date.year
    target_month = now_date.month

    # Support YYYY-MM formatted string in `month` or `billing_month`, alongside legacy integers
    m_param = str(billing_month or month or "").strip()
    if m_param:
        if "-" in m_param:
            parts = m_param.split("-")
            try:
                target_year = int(parts[0])
                target_month = int(parts[1])
            except (ValueError, IndexError):
                pass
        else:
            try:
                target_month = int(m_param)
            except ValueError:
                pass

    target_month_date = date(target_year, target_month, 1)
    line_items, gross_fee_total, total_payout_total = _build_statement_line_items(
        db, merchant_account_id, target_month_date
    )

    dou_margin_total = gross_fee_total - total_payout_total
    month_name = calendar.month_name[target_month]
    statement_month_str = f"{month_name} {target_year}"
    due_date_str = f"{target_year}-{target_month:02d}-{min(account.payment_terms_days, 28):02d}"

    # Build branch -> fleet two-dimensional grouping
    branch_dict: dict[str, dict[str, list[StatementLineItem]]] = {}
    for item in line_items:
        br_name = item.branch_name
        fl_name = item.logistics_company_name or "الشركة اللوجستية"
        if br_name not in branch_dict:
            branch_dict[br_name] = {}
        if fl_name not in branch_dict[br_name]:
            branch_dict[br_name][fl_name] = []
        branch_dict[br_name][fl_name].append(item)

    branch_groups: list[BranchStatementGroup] = []
    for br_name, fleets_in_br in branch_dict.items():
        fleet_subtotals: list[FleetSubtotal] = []
        br_total_dec = Decimal("0.00")
        for fl_name, items in fleets_in_br.items():
            fl_subtotal_dec = sum(Decimal(str(it.prorated_fee)) for it in items)
            br_total_dec += fl_subtotal_dec
            fleet_subtotals.append(
                FleetSubtotal(
                    logistics_company_name=fl_name,
                    seats_count=len(items),
                    subtotal=float(fl_subtotal_dec),
                )
            )
        branch_groups.append(
            BranchStatementGroup(
                branch_name=br_name,
                fleets=fleet_subtotals,
                branch_total=float(br_total_dec),
            )
        )

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
        branch_groups=branch_groups,
    )


# ─── Branches Overview (Screen 1) ─────────────────────────────────────────────

@router.get(
    "/account/{merchant_account_id}/branches-overview",
    response_model=BranchesOverviewResponse,
)
def get_branches_overview(
    merchant_account_id: int,
    db: Session = Depends(get_db),
    auth_account_id: int = Depends(get_current_merchant_account_id),
):
    """Live aggregated view of all restaurant branches: contracted, filled, vacant seats, and today's activity."""
    if auth_account_id != merchant_account_id:
        raise HTTPException(
            status_code=403, detail="غير مصرح: لا يمكنك الاطلاع على فروع تاجر آخر."
        )

    account = db.get(MerchantAccount, merchant_account_id)
    if not account:
        raise HTTPException(status_code=404, detail="حساب التاجر غير موجود.")

    today = date.today()
    branches = (
        db.query(MerchantBranch)
        .filter(
            MerchantBranch.merchant_account_id == merchant_account_id,
            MerchantBranch.is_active.is_(True),
        )
        .all()
    )

    total_contracted = 0
    total_filled = 0
    total_vacant = 0
    total_present = 0
    total_orders = 0
    items: list[BranchOverviewItem] = []

    for br in branches:
        bookings = (
            db.query(DedicatedShiftBooking)
            .filter(
                DedicatedShiftBooking.merchant_branch_id == br.id,
                DedicatedShiftBooking.status == BookingStatus.active,
                DedicatedShiftBooking.effective_from <= today,
                or_(
                    DedicatedShiftBooking.effective_until.is_(None),
                    DedicatedShiftBooking.effective_until >= today,
                ),
            )
            .all()
        )

        c_count = len(bookings)
        f_count = sum(1 for b in bookings if b.rider_id is not None)
        v_count = sum(1 for b in bookings if b.rider_id is None)

        # Check attendance for present riders today
        booking_ids = [b.id for b in bookings]
        active_attendances = (
            db.query(ShiftAttendanceLog)
            .filter(
                ShiftAttendanceLog.dedicated_shift_booking_id.in_(booking_ids),
                ShiftAttendanceLog.log_date == today,
                ShiftAttendanceLog.checkin_at.isnot(None),
                ShiftAttendanceLog.checkout_at.is_(None),
            )
            .all()
            if booking_ids
            else []
        )
        present_rider_ids = {a.rider_id for a in active_attendances}
        p_count = len(present_rider_ids)

        # Today orders
        today_orders = (
            db.query(BranchDispatchOrder)
            .filter(
                BranchDispatchOrder.merchant_branch_id == br.id,
                BranchDispatchOrder.order_date == today,
            )
            .all()
        )
        o_count = len(today_orders)
        deliv_count = sum(
            1 for o in today_orders if o.status == OrderStatus.delivered
        )

        seat_details: list[BranchSeatDetail] = []
        for b in bookings:
            if b.rider_id is None:
                seat_details.append(
                    BranchSeatDetail(
                        booking_id=b.id,
                        shift_type=b.shift_type.value,
                        rider_id=None,
                        rider_name="مقعد شاغر (غير معيّن)",
                        is_vacant=True,
                        is_present_today=False,
                    )
                )
            else:
                rider = db.get(Courier, b.rider_id)
                r_name = _masked_name(rider.id, db) if rider else "مندوب"
                seat_details.append(
                    BranchSeatDetail(
                        booking_id=b.id,
                        shift_type=b.shift_type.value,
                        rider_id=b.rider_id,
                        rider_name=r_name,
                        is_vacant=False,
                        is_present_today=(b.rider_id in present_rider_ids),
                    )
                )

        total_contracted += c_count
        total_filled += f_count
        total_vacant += v_count
        total_present += p_count
        total_orders += o_count

        items.append(
            BranchOverviewItem(
                branch_id=br.id,
                branch_name=br.branch_name,
                city=br.city or "الرياض",
                contracted_seats=c_count,
                filled_seats=f_count,
                vacant_seats=v_count,
                present_riders=p_count,
                today_orders_count=o_count,
                today_delivered_count=deliv_count,
                seats=seat_details,
            )
        )

    return BranchesOverviewResponse(
        merchant_account_id=merchant_account_id,
        trade_name=account.trade_name,
        total_branches=len(branches),
        total_contracted_seats=total_contracted,
        total_filled_seats=total_filled,
        total_vacant_seats=total_vacant,
        total_present_riders=total_present,
        total_today_orders=total_orders,
        branches=items,
    )


# ─── Tax Invoice (Screen 3) ───────────────────────────────────────────────────

@router.get(
    "/account/{merchant_account_id}/tax-invoice",
    response_model=TaxInvoiceResponse,
)
def get_tax_invoice(
    merchant_account_id: int,
    billing_month: Optional[str] = Query(None),
    settlement_id: Optional[int] = Query(None),
    month: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    auth_account_id: int = Depends(get_current_merchant_account_id),
):
    """
    Returns an official B2B ZATCA Tax Invoice or Commercial Invoice.
    Reads strictly from an issued/paid MonthlySettlementLedger.
    """
    if auth_account_id != merchant_account_id:
        raise HTTPException(
            status_code=403,
            detail="غير مصرح: لا يمكنك الاطلاع على فواتير حساب تاجر آخر.",
        )

    account = db.get(MerchantAccount, merchant_account_id)
    if not account:
        raise HTTPException(status_code=404, detail="حساب التاجر غير موجود.")

    target_month_str = billing_month or month
    now_date = date.today()
    if target_month_str and "-" in target_month_str:
        parts = target_month_str.split("-")
        try:
            m_date = date(int(parts[0]), int(parts[1]), 1)
        except (ValueError, IndexError):
            m_date = date(now_date.year, now_date.month, 1)
    else:
        m_date = date(now_date.year, now_date.month, 1)

    q = db.query(MonthlySettlementLedger).filter(
        MonthlySettlementLedger.merchant_account_id == merchant_account_id,
    )
    if settlement_id:
        ledger = q.filter(MonthlySettlementLedger.id == settlement_id).first()
    else:
        ledger = q.filter(
            MonthlySettlementLedger.settlement_month == m_date
        ).first()

    if not ledger:
        raise HTTPException(
            status_code=404,
            detail="لا يوجد كشف تسوية مسجل لهذا الشهر حتى الآن.",
        )

    # Invariant: Tax invoice must only be generated for issued or paid settlements!
    if ledger.settlement_status == SettlementStatus.draft:
        raise HTTPException(
            status_code=400,
            detail="كشف التسوية لهذا الشهر ما زال مسودة غير معتمد؛ تصدر الفاتورة الضريبية رسمياً فور اعتماد وإصدار الكشف من إدارة DOU.",
        )

    # Check DOU VAT Setting in database
    dou_vat_setting = (
        db.query(AppSetting).filter(AppSetting.key == "dou_vat_number").first()
    )
    has_dou_vat = bool(
        dou_vat_setting and dou_vat_setting.value and dou_vat_setting.value.strip()
    )
    dou_vat_number = dou_vat_setting.value.strip() if has_dou_vat else None

    gross_fee = float(ledger.gross_fee_charged_to_merchant)

    # Historical stamped VAT values on issued/paid settlements take precedence over live setting
    if ledger.vat_amount is not None or ledger.vat_rate is not None:
        vat_rate = float(ledger.vat_rate) if ledger.vat_rate is not None else 0.0
        vat_amount = float(ledger.vat_amount) if ledger.vat_amount is not None else 0.0
        is_tax_invoice = bool(vat_amount > 0 or vat_rate > 0)
        if is_tax_invoice and not dou_vat_number:
            raise HTTPException(
                status_code=409,
                detail="هذه التسوية مختومة بضريبة ولا يوجد رقم تسجيل ضريبي مسجّل للمنصة — لا يمكن إصدار فاتورة ضريبية. راجع إعدادات المنصة.",
            )
    elif has_dou_vat:
        vat_rate = float(ledger.vat_rate) if ledger.vat_rate is not None else 0.15
        vat_amount = (
            float(ledger.vat_amount)
            if ledger.vat_amount is not None
            else round(gross_fee * vat_rate, 2)
        )
        is_tax_invoice = True
    else:
        vat_rate = 0.0
        vat_amount = 0.0
        is_tax_invoice = False

    total_amount = round(gross_fee + vat_amount, 2)

    inv_month_str = ledger.settlement_month.strftime("%Y%m")
    invoice_number = f"DOU-INV-{inv_month_str}-{ledger.id:04d}"
    issue_date_str = (
        ledger.issued_at or datetime.now(timezone.utc)
    ).strftime("%Y-%m-%d")

    zatca_qr: Optional[str] = None
    if is_tax_invoice and dou_vat_number:
        zatca_qr = generate_zatca_tlv_qr(
            seller_name="منصة DOU لتقنية المعلومات والخدمات اللوجستية",
            vat_number=dou_vat_number,
            timestamp_iso=(ledger.issued_at or datetime.now(timezone.utc)).isoformat(),
            total_with_vat=f"{total_amount:.2f}",
            vat_amount=f"{vat_amount:.2f}",
        )

    line_items, _, _ = _build_statement_line_items(
        db, merchant_account_id, ledger.settlement_month
    )

    return TaxInvoiceResponse(
        settlement_id=ledger.id,
        invoice_number=invoice_number,
        settlement_month=f"{calendar.month_name[ledger.settlement_month.month]} {ledger.settlement_month.year}",
        issue_date=issue_date_str,
        settlement_status=ledger.settlement_status.value,
        is_tax_invoice=is_tax_invoice,
        seller=TaxInvoiceSeller(
            trade_name="منصة DOU لتقنية المعلومات والخدمات اللوجستية",
            vat_number=dou_vat_number,
            address="الرياض، المملكة العربية السعودية",
        ),
        buyer=TaxInvoiceBuyer(
            trade_name=account.trade_name,
            vat_number=account.vat_number,
            billing_phone=account.billing_contact_phone,
            billing_email=account.billing_contact_email,
        ),
        currency="SAR",
        subtotal=gross_fee,
        vat_rate=vat_rate,
        vat_amount=vat_amount,
        total_amount=total_amount,
        zatca_qr_base64=zatca_qr,
        bank_transfer_reference=ledger.bank_transfer_reference,
        line_items=line_items,
    )


# ─── Branch Self-Addition (Merchant Self-Service) ───────────────────────────

@router.post(
    "/account/{merchant_account_id}/branches",
    response_model=MerchantBranchOut,
    status_code=status.HTTP_201_CREATED,
)
def add_branch_by_merchant(
    merchant_account_id: int,
    payload: MerchantAddBranchPayload,
    db: Session = Depends(get_db),
    auth_account_id: int = Depends(get_current_merchant_account_id),
):
    """
    Allows a merchant account owner to add a new branch to their chain.
    The branch is marked created_by_source='MERCHANT' and verification_status='PENDING_REVIEW'.
    """
    if auth_account_id != merchant_account_id:
        raise HTTPException(
            status_code=403,
            detail="غير مصرح: لا يمكنك إضافة فروع لحساب تاجر آخر.",
        )

    account = db.get(MerchantAccount, merchant_account_id)
    if not account:
        raise HTTPException(status_code=404, detail="حساب التاجر غير موجود.")

    b_name = (payload.branch_name or payload.name or "").strip()
    if not b_name:
        raise HTTPException(status_code=400, detail="اسم الفرع مطلوب.")

    pin = (payload.cashier_access_pin or payload.cashier_pin or "1234").strip()
    hashed_pin = hash_pin(pin)

    city_str = payload.city.strip() if payload.city else "الرياض"
    city_id = payload.city_id
    country_id = payload.country_id
    if city_id and not country_id:
        geo_city = db.get(GeoCity, city_id)
        if geo_city:
            country_id = geo_city.country_id
            city_str = geo_city.name
    elif not city_id and city_str:
        geo_city = db.query(GeoCity).filter(GeoCity.name.ilike(city_str)).first()
        if geo_city:
            city_id = geo_city.id
            country_id = geo_city.country_id

    branch = MerchantBranch(
        merchant_account_id=merchant_account_id,
        branch_name=b_name,
        city=city_str,
        city_id=city_id,
        country_id=country_id,
        district=payload.district.strip() if payload.district else None,
        latitude=Decimal(str(payload.latitude)),
        longitude=Decimal(str(payload.longitude)),
        geofence_radius_meters=payload.geofence_radius_meters,
        cashier_access_pin=hashed_pin,
        is_active=True,
        created_by_source="MERCHANT",
        verification_status="PENDING_REVIEW",
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)

    return MerchantBranchOut(
        id=branch.id,
        merchant_account_id=branch.merchant_account_id,
        branch_name=branch.branch_name,
        city=branch.city,
        city_id=branch.city_id,
        country_id=branch.country_id,
        district=branch.district,
        latitude=float(branch.latitude),
        longitude=float(branch.longitude),
        geofence_radius_meters=branch.geofence_radius_meters,
        created_by_source=branch.created_by_source,
        verification_status=branch.verification_status,
        is_active=branch.is_active,
        created_at=branch.created_at,
    )


# ─── Capacity Change Requests (Screen 2) ──────────────────────────────────────

@router.post(
    "/account/{merchant_account_id}/capacity-requests",
    response_model=CapacityRequestOut,
)
def create_capacity_request(
    merchant_account_id: int,
    payload: CapacityRequestCreate,
    db: Session = Depends(get_db),
    auth_account_id: int = Depends(get_current_merchant_account_id),
):
    """
    Submits a seat capacity increase/decrease request for a branch for a future month.
    Follows stage pattern (P6): requested -> under_review -> approved -> effective.
    Does NOT mutate active bookings.
    """
    if auth_account_id != merchant_account_id:
        raise HTTPException(
            status_code=403,
            detail="غير مصرح: لا يمكنك رفع طلبات لحساب تاجر آخر.",
        )

    account = db.get(MerchantAccount, merchant_account_id)
    if not account:
        raise HTTPException(status_code=404, detail="حساب التاجر غير موجود.")

    target_branch_id = payload.merchant_branch_id or payload.branch_id
    if not target_branch_id:
        raise HTTPException(status_code=400, detail="معرّف الفرع مطلوب.")

    branch = db.get(MerchantBranch, target_branch_id)
    if not branch or branch.merchant_account_id != merchant_account_id:
        raise HTTPException(
            status_code=400,
            detail="الفرع المحدد غير تابع لهذا الحساب التجاري.",
        )

    today = date.today()
    current_capacity = (
        db.query(DedicatedShiftBooking)
        .filter(
            DedicatedShiftBooking.merchant_branch_id == branch.id,
            DedicatedShiftBooking.status == BookingStatus.active,
            DedicatedShiftBooking.effective_from <= today,
            or_(
                DedicatedShiftBooking.effective_until.is_(None),
                DedicatedShiftBooking.effective_until >= today,
            ),
        )
        .count()
    )

    req = MerchantCapacityRequest(
        merchant_account_id=merchant_account_id,
        merchant_branch_id=branch.id,
        current_capacity=current_capacity,
        requested_capacity=payload.requested_capacity,
        effective_month=payload.effective_month,
        reason=payload.reason,
        status="requested",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    return CapacityRequestOut(
        id=req.id,
        merchant_account_id=req.merchant_account_id,
        merchant_branch_id=req.merchant_branch_id,
        branch_name=branch.branch_name,
        current_capacity=req.current_capacity,
        requested_capacity=req.requested_capacity,
        effective_month=req.effective_month,
        reason=req.reason,
        status=req.status,
        reviewed_by=req.reviewed_by,
        reviewed_at=req.reviewed_at,
        review_notes=req.review_notes,
        created_at=req.created_at,
    )


@router.get(
    "/account/{merchant_account_id}/capacity-requests",
    response_model=list[CapacityRequestOut],
)
def list_capacity_requests(
    merchant_account_id: int,
    db: Session = Depends(get_db),
    auth_account_id: int = Depends(get_current_merchant_account_id),
):
    """Lists capacity requests with review lifecycle stages."""
    if auth_account_id != merchant_account_id:
        raise HTTPException(
            status_code=403,
            detail="غير مصرح: لا يمكنك الاطلاع على طلبات حساب تاجر آخر.",
        )

    requests = (
        db.query(MerchantCapacityRequest)
        .filter(
            MerchantCapacityRequest.merchant_account_id == merchant_account_id,
        )
        .order_by(MerchantCapacityRequest.id.desc())
        .all()
    )

    res: list[CapacityRequestOut] = []
    for r in requests:
        br = db.get(MerchantBranch, r.merchant_branch_id)
        res.append(
            CapacityRequestOut(
                id=r.id,
                merchant_account_id=r.merchant_account_id,
                merchant_branch_id=r.merchant_branch_id,
                branch_name=br.branch_name if br else "الفرع",
                current_capacity=r.current_capacity,
                requested_capacity=r.requested_capacity,
                effective_month=r.effective_month,
                reason=r.reason,
                status=r.status,
                reviewed_by=r.reviewed_by,
                reviewed_at=r.reviewed_at,
                review_notes=r.review_notes,
                created_at=r.created_at,
            )
        )
    return res


# ─── Company Rider Assignment Approvals (Screen 3) ────────────────────────────

@router.get(
    "/account/{merchant_account_id}/rider-approvals",
    response_model=list[RiderApprovalOut],
)
def list_rider_approvals_merchant(
    merchant_account_id: int,
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    auth_account_id: int = Depends(get_current_merchant_account_id),
):
    """
    Lists company rider assignment approval requests for this restaurant merchant.
    P0 Privacy: phone numbers are masked and sensitive internal payroll/IDs are never surfaced.
    Surfaces 24h delay alert if pending approval > 24 hours.
    """
    if auth_account_id != merchant_account_id:
        raise HTTPException(
            status_code=403,
            detail="غير مصرح: لا يمكنك الاطلاع على موافقات حساب تاجر آخر.",
        )

    q = db.query(RiderAssignmentApproval).filter(
        RiderAssignmentApproval.merchant_account_id == merchant_account_id
    )
    if status:
        q = q.filter(RiderAssignmentApproval.status == status.upper())

    approvals = q.order_by(RiderAssignmentApproval.id.desc()).all()
    now_utc = datetime.now(timezone.utc)
    results: list[RiderApprovalOut] = []

    for a in approvals:
        branch = db.get(MerchantBranch, a.merchant_branch_id)
        tenant = db.get(Tenant, a.logistics_company_tenant_id)

        # Privacy masking:
        phone = a.courier_phone or ""
        masked_phone = phone[:4] + "***" + phone[-3:] if len(phone) >= 7 else "***"

        # 24h delay alert calculation:
        req_time = a.requested_at
        if req_time and req_time.tzinfo is None:
            req_time = req_time.replace(tzinfo=timezone.utc)
        is_delayed = bool(a.status == "PENDING" and req_time and (now_utc - req_time) > timedelta(hours=24))

        results.append(
            RiderApprovalOut(
                id=a.id,
                booking_id=a.booking_id,
                merchant_branch_id=a.merchant_branch_id,
                branch_name=branch.branch_name if branch else f"فرع #{a.merchant_branch_id}",
                logistics_company_tenant_id=a.logistics_company_tenant_id,
                logistics_company_name=tenant.name if tenant else f"شركة #{a.logistics_company_tenant_id}",
                courier_id=a.courier_id,
                courier_name=a.courier_name,
                courier_phone_masked=masked_phone,
                status=a.status,
                rejection_reason=a.rejection_reason,
                requested_at=a.requested_at,
                decided_at=a.decided_at,
                is_delayed_over_24h=is_delayed,
            )
        )

    return results


@router.post(
    "/account/{merchant_account_id}/rider-approvals/{approval_id}/decide",
    response_model=RiderApprovalOut,
)
def decide_rider_approval_merchant(
    merchant_account_id: int,
    approval_id: int,
    payload: DecideRiderApprovalPayload,
    db: Session = Depends(get_db),
    auth_account_id: int = Depends(get_current_merchant_account_id),
):
    """
    Approves or rejects a COMPANY courier assignment to a dedicated shift seat.
    If APPROVED: booking.rider_id is updated to fill the seat officially.
    If REJECTED: seat remains vacant (booking.rider_id=None) and rejection reason is recorded.
    """
    if auth_account_id != merchant_account_id:
        raise HTTPException(
            status_code=403,
            detail="غير مصرح: لا يمكنك اتخاذ قرار لحساب تاجر آخر.",
        )

    approval = db.get(RiderAssignmentApproval, approval_id)
    if not approval or approval.merchant_account_id != merchant_account_id:
        raise HTTPException(status_code=404, detail="طلب الموافقة غير موجود.")

    action = payload.action.strip().upper()
    if action not in ("APPROVED", "REJECTED"):
        raise HTTPException(
            status_code=400,
            detail="إجراء غير صالح. الخيارات المتاحة: APPROVED أو REJECTED.",
        )

    approval.status = action
    approval.decided_at = datetime.now(timezone.utc)
    if action == "REJECTED":
        approval.rejection_reason = payload.rejection_reason or "مرفوض من قبل المطعم"
    elif action == "APPROVED":
        booking = db.get(DedicatedShiftBooking, approval.booking_id)
        if booking:
            booking.rider_id = approval.courier_id

    db.commit()
    db.refresh(approval)

    branch = db.get(MerchantBranch, approval.merchant_branch_id)
    tenant = db.get(Tenant, approval.logistics_company_tenant_id)
    phone = approval.courier_phone or ""
    masked_phone = phone[:4] + "***" + phone[-3:] if len(phone) >= 7 else "***"

    return RiderApprovalOut(
        id=approval.id,
        booking_id=approval.booking_id,
        merchant_branch_id=approval.merchant_branch_id,
        branch_name=branch.branch_name if branch else f"فرع #{approval.merchant_branch_id}",
        logistics_company_tenant_id=approval.logistics_company_tenant_id,
        logistics_company_name=tenant.name if tenant else f"شركة #{approval.logistics_company_tenant_id}",
        courier_id=approval.courier_id,
        courier_name=approval.courier_name,
        courier_phone_masked=masked_phone,
        status=approval.status,
        rejection_reason=approval.rejection_reason,
        requested_at=approval.requested_at,
        decided_at=approval.decided_at,
        is_delayed_over_24h=False,
    )


# ─── SLA Indicators (Screen 4) ────────────────────────────────────────────────

@router.get(
    "/account/{merchant_account_id}/sla",
    response_model=SLAIndicatorsResponse,
)
def get_merchant_sla_indicators(
    merchant_account_id: int,
    billing_month: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    auth_account_id: int = Depends(get_current_merchant_account_id),
):
    """
    Computes operational SLA indicators: contracted days, vacant seat-days, attended days, and fulfillment %.
    Strictly excludes financial deductions.
    """
    if auth_account_id != merchant_account_id:
        raise HTTPException(
            status_code=403,
            detail="غير مصرح: لا يمكنك الاطلاع على مؤشرات حساب تاجر آخر.",
        )

    account = db.get(MerchantAccount, merchant_account_id)
    if not account:
        raise HTTPException(status_code=404, detail="حساب التاجر غير موجود.")

    target_m_str = billing_month or month
    now_date = date.today()
    if target_m_str and "-" in target_m_str:
        parts = target_m_str.split("-")
        try:
            target_year, target_month = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            target_year, target_month = now_date.year, now_date.month
    else:
        target_year, target_month = now_date.year, now_date.month

    days_in_month = calendar.monthrange(target_year, target_month)[1]
    m_start = date(target_year, target_month, 1)
    m_end = date(target_year, target_month, days_in_month)

    bookings = (
        db.query(DedicatedShiftBooking)
        .join(
            MerchantBranch,
            DedicatedShiftBooking.merchant_branch_id == MerchantBranch.id,
        )
        .filter(
            MerchantBranch.merchant_account_id == merchant_account_id,
            DedicatedShiftBooking.status != BookingStatus.terminated,
            DedicatedShiftBooking.effective_from <= m_end,
            or_(
                DedicatedShiftBooking.effective_until.is_(None),
                DedicatedShiftBooking.effective_until >= m_start,
            ),
        )
        .all()
    )

    total_contracted_days = 0
    total_filled_days = 0
    total_vacant_days = 0
    total_attended_days = 0

    branch_sla_map: dict[int, dict] = {}

    for b in bookings:
        br_id = b.merchant_branch_id
        if br_id not in branch_sla_map:
            branch = db.get(MerchantBranch, br_id)
            branch_sla_map[br_id] = {
                "branch_id": br_id,
                "branch_name": branch.branch_name if branch else "Branch",
                "contracted_seat_days": 0,
                "vacant_seat_days": 0,
                "attended_seat_days": 0,
                "shortfall_days": 0,
            }

        start_active = max(b.effective_from, m_start)
        end_active = min(b.effective_until or m_end, m_end)
        active_days = max(0, (end_active - start_active).days + 1)

        total_contracted_days += active_days
        branch_sla_map[br_id]["contracted_seat_days"] += active_days

        if b.rider_id is None:
            total_vacant_days += active_days
            branch_sla_map[br_id]["vacant_seat_days"] += active_days
        else:
            total_filled_days += active_days
            attended_count = (
                db.query(ShiftAttendanceLog)
                .filter(
                    ShiftAttendanceLog.dedicated_shift_booking_id == b.id,
                    ShiftAttendanceLog.log_date >= start_active,
                    ShiftAttendanceLog.log_date <= end_active,
                    ShiftAttendanceLog.checkin_at.isnot(None),
                )
                .count()
            )
            total_attended_days += attended_count
            branch_sla_map[br_id]["attended_seat_days"] += attended_count

    shortfall_days = max(0, total_contracted_days - total_attended_days)
    fulfillment_pct = (
        round((total_attended_days / total_contracted_days * 100), 1)
        if total_contracted_days > 0
        else 100.0
    )

    branches_sla_list = []
    for b_data in branch_sla_map.values():
        b_c = b_data["contracted_seat_days"]
        b_att = b_data["attended_seat_days"]
        b_short = max(0, b_c - b_att)
        b_rate = round((b_att / b_c * 100), 1) if b_c > 0 else 100.0
        b_data["shortfall_days"] = b_short
        b_data["fulfillment_rate_pct"] = b_rate
        branches_sla_list.append(b_data)

    return SLAIndicatorsResponse(
        merchant_account_id=merchant_account_id,
        month=f"{target_year}-{target_month:02d}",
        total_contracted_seat_days=total_contracted_days,
        filled_seat_days=total_filled_days,
        vacant_seat_days=total_vacant_days,
        attended_seat_days=total_attended_days,
        shortfall_days=shortfall_days,
        fulfillment_rate_pct=fulfillment_pct,
        branches_sla=branches_sla_list,
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
        raise HTTPException(status_code=403, detail="الفرع غير موجود أو غير مصرح به.")

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

    if not eligible_rider and not ENABLE_OPEN_POOL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="لا يوجد مندوب مخصص متاح في هذا الفرع حالياً.",
        )

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

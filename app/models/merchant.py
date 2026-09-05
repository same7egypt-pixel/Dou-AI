import enum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base

# ─── Enums ────────────────────────────────────────────────────────────────────

class ShiftType(str, enum.Enum):
    peak_3h     = "peak_3h"
    full_day_8h = "full_day_8h"


class BookingStatus(str, enum.Enum):
    active     = "active"
    paused     = "paused"
    terminated = "terminated"


class OrderStatus(str, enum.Enum):
    pending   = "pending"
    en_route  = "en_route"
    delivered = "delivered"


class SettlementStatus(str, enum.Enum):
    draft  = "draft"
    issued = "issued"
    paid   = "paid"


class PaymentMethod(str, enum.Enum):
    """How the customer paid, which decides whether the rider carries cash.

    `unknown` is the honest default for an order the cashier entered before the
    quick-entry form existed. A rider must never be told to collect an amount
    the system is only guessing at.
    """

    cash     = "cash"
    card     = "card"
    prepaid  = "prepaid"
    unknown  = "unknown"


# ─── MerchantAccount ──────────────────────────────────────────────────────────

class MerchantAccount(Base):
    """
    A restaurant chain or F&B brand that purchases dedicated shift packages
    from DOU. This entity is DOU's direct billing counterpart — invisible
    to any logistics company tenant.
    """
    __tablename__ = "merchant_accounts"

    id                    = Column(Integer, primary_key=True, index=True)
    trade_name            = Column(String(255), nullable=False)
    vat_number            = Column(String(20),  nullable=True)
    billing_contact_email = Column(String(255), nullable=False)
    billing_contact_phone = Column(String(20),  nullable=False)
    payment_terms_days    = Column(Integer,      nullable=False, default=30)
    api_key_prefix        = Column(String(16),   nullable=True,  index=True)
    api_key_hash          = Column(String(255),  nullable=True,  unique=True, index=True)
    is_active             = Column(Boolean,      nullable=False, default=True)
    created_at            = Column(DateTime(timezone=True), server_default=func.now())

    branches   = relationship("MerchantBranch", back_populates="merchant_account")
    statements = relationship("MonthlySettlementLedger", back_populates="merchant_account")


# ─── MerchantBranch ───────────────────────────────────────────────────────────

class MerchantBranch(Base):
    """
    Individual restaurant branch where a rider is physically stationed.
    Geofence fields drive check-in validation via Haversine distance check.
    cashier_access_pin is bcrypt-hashed before storage.
    """
    __tablename__ = "merchant_branches"

    id                     = Column(Integer, primary_key=True, index=True)
    merchant_account_id    = Column(Integer, ForeignKey("merchant_accounts.id"), nullable=False)
    branch_name            = Column(String(255), nullable=False)
    city                   = Column(String(100), nullable=False)
    city_id                = Column(Integer, ForeignKey("geo_cities.id"), nullable=True)
    country_id             = Column(Integer, ForeignKey("geo_countries.id"), nullable=True)
    district               = Column(String(100), nullable=True)
    latitude               = Column(Numeric(10, 7), nullable=False)
    longitude              = Column(Numeric(10, 7), nullable=False)
    geofence_radius_meters = Column(Integer, nullable=False, default=150)
    cashier_access_pin     = Column(String(255), nullable=False)  # bcrypt hash
    tablet_device_id       = Column(String(255), nullable=True)
    is_active              = Column(Boolean, nullable=False, default=True)
    created_at             = Column(DateTime(timezone=True), server_default=func.now())

    merchant_account = relationship("MerchantAccount", back_populates="branches")
    bookings         = relationship("DedicatedShiftBooking", back_populates="branch")
    orders           = relationship("BranchDispatchOrder", back_populates="branch")
    geo_city         = relationship("GeoCity", foreign_keys=[city_id])
    geo_country      = relationship("GeoCountry", foreign_keys=[country_id])


# ─── DedicatedShiftBooking ────────────────────────────────────────────────────

class DedicatedShiftBooking(Base):
    """
    The commercial contract between DOU and a restaurant branch.
    """
    __tablename__ = "dedicated_shift_bookings"

    id                          = Column(Integer, primary_key=True, index=True)
    merchant_branch_id          = Column(Integer, ForeignKey("merchant_branches.id"), nullable=False)
    logistics_company_tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    # NULL is a contracted seat nobody fills yet. A branch that bought ten and
    # is staffed with eight had no way to say so, and an SLA shortfall you
    # cannot record is a shortfall you cannot bill for. Read paths already
    # skip or mask a seat with no rider, so it stays invisible to the cashier
    # and to the driver app until someone is assigned.
    rider_id                    = Column(Integer, ForeignKey("couriers.id"), nullable=True)
    supervisor_id               = Column(Integer, ForeignKey("users.id"), nullable=True)

    shift_type                  = Column(Enum(ShiftType, name="shifttype"), nullable=False)
    shift_start_time            = Column(Time, nullable=False)
    shift_end_time              = Column(Time, nullable=False)

    effective_from              = Column(Date, nullable=False)
    effective_until             = Column(Date, nullable=True)  # NULL = open-ended

    monthly_fee_to_merchant     = Column(Numeric(10, 2), nullable=False)  # Charged to merchant
    monthly_payout_to_logistics = Column(Numeric(10, 2), nullable=False)  # Payout to logistics company
    dou_margin                  = Column(Numeric(10, 2), nullable=False)  # Net DOU margin

    status                      = Column(Enum(BookingStatus, name="bookingstatus"), nullable=False, default=BookingStatus.active)
    created_at                  = Column(DateTime(timezone=True), server_default=func.now())
    terminated_at               = Column(DateTime(timezone=True), nullable=True)
    termination_reason          = Column(Text, nullable=True)

    branch          = relationship("MerchantBranch", back_populates="bookings")
    attendance_logs = relationship("ShiftAttendanceLog", back_populates="booking")
    orders          = relationship("BranchDispatchOrder", back_populates="booking")
    supervisor      = relationship("User", foreign_keys=[supervisor_id])


# ─── ShiftAttendanceLog ───────────────────────────────────────────────────────

class ShiftAttendanceLog(Base):
    """
    Branch-level check-in / check-out per rider per day.
    dedicated_shift_booking_id is strictly non-nullable.
    """
    __tablename__ = "shift_attendance_logs"

    id                         = Column(Integer, primary_key=True, index=True)
    dedicated_shift_booking_id = Column(Integer, ForeignKey("dedicated_shift_bookings.id"), nullable=False)
    rider_id                   = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    log_date                   = Column(Date, nullable=False)

    checkin_at                 = Column(DateTime(timezone=True), nullable=True)
    checkin_lat                = Column(Numeric(10, 7), nullable=True)
    checkin_lng                = Column(Numeric(10, 7), nullable=True)
    geofence_validated         = Column(Boolean, nullable=False, default=False)

    checkout_at                = Column(DateTime(timezone=True), nullable=True)
    checkout_lat               = Column(Numeric(10, 7), nullable=True)
    checkout_lng               = Column(Numeric(10, 7), nullable=True)

    created_at                 = Column(DateTime(timezone=True), server_default=func.now())

    booking = relationship("DedicatedShiftBooking", back_populates="attendance_logs")


# ─── BranchDispatchOrder ──────────────────────────────────────────────────────

class BranchDispatchOrder(Base):
    """
    A 1-click order from cashier or POS API.
    dedicated_shift_booking_id and rider_id are nullable to accommodate pool orders.
    """
    __tablename__ = "branch_dispatch_orders"
    __table_args__ = (
        Index("ix_branch_dispatch_orders_external_order_id", "external_order_id"),
    )

    id                         = Column(Integer, primary_key=True, index=True)
    merchant_branch_id         = Column(Integer, ForeignKey("merchant_branches.id"), nullable=False)
    dedicated_shift_booking_id = Column(Integer, ForeignKey("dedicated_shift_bookings.id"), nullable=True)
    rider_id                   = Column(Integer, ForeignKey("couriers.id"), nullable=True)

    order_date                 = Column(Date, nullable=False)
    customer_name              = Column(String(255), nullable=False)
    customer_phone             = Column(String(20), nullable=False)
    delivery_address_text      = Column(Text, nullable=False)

    status                     = Column(Enum(OrderStatus, name="branchorderstatus"), nullable=False, default=OrderStatus.pending)
    order_source               = Column(String(50), nullable=False, default="manual_cashier")
    # A branch order carried no money at all, so the rider could not be told
    # whether to collect, the cashier could not clear the rider's float, and
    # nobody could reconcile a day's cash. `cod_amount` is what the rider must
    # take from the customer; `cod_settled_at` is when the cashier took it back.
    order_amount               = Column(Numeric(10, 2), nullable=True)
    payment_method             = Column(
        Enum(PaymentMethod, name="branchorderpaymentmethod"),
        nullable=False,
        default=PaymentMethod.unknown,
        server_default=PaymentMethod.unknown.value,
    )
    cod_amount                 = Column(Numeric(10, 2), nullable=False, default=0, server_default="0")
    cod_settled_at             = Column(DateTime(timezone=True), nullable=True)
    external_order_id          = Column(String(100), nullable=True)
    is_pool_eligible           = Column(Boolean, nullable=False, default=False)

    dispatched_at              = Column(DateTime(timezone=True), server_default=func.now())
    acknowledged_at            = Column(DateTime(timezone=True), nullable=True)
    delivered_at               = Column(DateTime(timezone=True), nullable=True)

    created_at                 = Column(DateTime(timezone=True), server_default=func.now())

    branch  = relationship("MerchantBranch", back_populates="orders")
    booking = relationship("DedicatedShiftBooking", back_populates="orders")


# ─── MonthlySettlementLedger ──────────────────────────────────────────────────

class MonthlySettlementLedger(Base):
    """
    B2B financial reconciliation per merchant account per calendar month.
    """
    __tablename__ = "monthly_settlement_ledger"

    id                            = Column(Integer, primary_key=True, index=True)
    merchant_account_id           = Column(Integer, ForeignKey("merchant_accounts.id"), nullable=False)
    settlement_month              = Column(Date, nullable=False)  # 1st of month

    total_rider_shift_months      = Column(Numeric(8, 4), nullable=False)
    gross_fee_charged_to_merchant = Column(Numeric(12, 2), nullable=False)
    total_payout_to_logistics     = Column(Numeric(12, 2), nullable=False)
    dou_net_margin                = Column(Numeric(12, 2), nullable=False)

    settlement_status             = Column(Enum(SettlementStatus, name="settlementstatus"), nullable=False, default=SettlementStatus.draft)
    issued_at                     = Column(DateTime(timezone=True), nullable=True)
    vat_rate                      = Column(Numeric(5, 4), nullable=True)
    vat_amount                    = Column(Numeric(12, 2), nullable=True)
    paid_at                       = Column(DateTime(timezone=True), nullable=True)
    bank_transfer_reference       = Column(String(255), nullable=True)

    created_at                    = Column(DateTime(timezone=True), server_default=func.now())

    merchant_account = relationship("MerchantAccount", back_populates="statements")


# ─── MerchantCapacityRequest ──────────────────────────────────────────────────

class MerchantCapacityRequest(Base):
    """
    Capacity increase or decrease request submitted by a merchant account owner
    for a specific branch and future month, under a multi-stage review pattern.
    """
    __tablename__ = "merchant_capacity_requests"

    id                  = Column(Integer, primary_key=True, index=True)
    merchant_account_id = Column(Integer, ForeignKey("merchant_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    merchant_branch_id  = Column(Integer, ForeignKey("merchant_branches.id", ondelete="CASCADE"), nullable=False, index=True)
    current_capacity    = Column(Integer, nullable=False)
    requested_capacity  = Column(Integer, nullable=False)
    effective_month     = Column(String(7), nullable=False)  # "YYYY-MM"
    reason              = Column(Text, nullable=True)
    status              = Column(String(20), nullable=False, default="requested")  # requested, under_review, approved, rejected
    reviewed_by         = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at         = Column(DateTime(timezone=True), nullable=True)
    review_notes        = Column(Text, nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())

    merchant_account = relationship("MerchantAccount", backref="capacity_requests")
    branch           = relationship("MerchantBranch", backref="capacity_requests")
    reviewer         = relationship("User", foreign_keys=[reviewed_by])


def compute_and_set_margin(booking: DedicatedShiftBooking) -> None:
    """Computes and stores dou_margin as monthly_fee_to_merchant - monthly_payout_to_logistics."""
    if booking.monthly_fee_to_merchant is not None and booking.monthly_payout_to_logistics is not None:
        booking.dou_margin = booking.monthly_fee_to_merchant - booking.monthly_payout_to_logistics

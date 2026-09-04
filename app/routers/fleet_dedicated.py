import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.entities import Courier, Tenant, User, UserRole
from app.models.merchant import (
    BookingStatus,
    BranchDispatchOrder,
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    OrderStatus,
    ShiftAttendanceLog,
)
from app.routers.auth import get_current_user
from app.services.financial_calculations import month_bounds
from app.utils.finance import prorate

router = APIRouter(prefix="/fleet/dedicated", tags=["fleet_dedicated"])


def _resolve_tenant_id(user: User, tenant_id_query: Optional[int] = None) -> int:
    """
    Returns the tenant_id for the current user.
    If superadmin (DOU_ADMIN), optionally allows querying any tenant via query param.
    Otherwise strictly enforces user.tenant_id.
    """
    if user.role == UserRole.DOU_ADMIN:
        resolved_t = tenant_id_query if isinstance(tenant_id_query, int) else None
        return resolved_t or user.tenant_id or 1
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="المستخدم لا يتبع شركة لوجستية مسجلة.",
        )
    return user.tenant_id


# ─── Schemas ──────────────────────────────────────────────────────────────────

class BookingRiderInfo(BaseModel):
    rider_id: int
    name: str
    rider_name: Optional[str] = None
    phone: Optional[str] = None
    national_id: Optional[str] = None


class TodayAttendanceInfo(BaseModel):
    checkin_status: str  # "checked_in" | "completed" | "not_yet"
    checkin_at: Optional[datetime] = None
    geofence_validated: bool = False


class FleetDedicatedBookingOut(BaseModel):
    id: int
    merchant_name: str
    branch_name: str
    branch_city: str
    branch_district: Optional[str]
    branch_address: str
    shift_type: str
    shift_start: str
    shift_end: str
    monthly_payout: float
    effective_from: date
    effective_until: Optional[date]
    status: str
    supervisor_id: Optional[int] = None
    supervisor_name: Optional[str] = None
    rider: Optional[BookingRiderInfo]
    today_attendance: TodayAttendanceInfo
    today_orders_count: int


class AssignRiderPayload(BaseModel):
    rider_id: int


class EligibleRiderOut(BaseModel):
    id: int
    name: str
    phone: Optional[str]
    national_id: Optional[str]
    is_active: bool


class FleetSettlementLineItem(BaseModel):
    booking_id: int
    merchant_name: str
    branch_name: str
    rider_name: str
    shift_type: str
    active_days: int
    days_in_month: int
    monthly_payout_rate: float
    prorated_payout: float


class FleetSettlementOut(BaseModel):
    tenant_name: str
    settlement_month: str
    total_payout_due: float
    currency: str
    settlement_status: str
    line_items: list[FleetSettlementLineItem]


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/bookings", response_model=list[FleetDedicatedBookingOut])
def get_fleet_bookings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant_id: Optional[int] = Query(None),
):
    """
    Returns all dedicated restaurant shift bookings assigned to the authenticated
    logistics company (tenant). Displays branch details, assigned courier, today's
    geofence attendance, and today's delivery count.
    """
    target_tenant_id = _resolve_tenant_id(current_user, tenant_id)
    today = date.today()

    bookings = (
        db.query(DedicatedShiftBooking)
        .join(MerchantBranch, DedicatedShiftBooking.merchant_branch_id == MerchantBranch.id)
        .filter(
            DedicatedShiftBooking.logistics_company_tenant_id == target_tenant_id,
            DedicatedShiftBooking.status != BookingStatus.terminated,
        )
        .order_by(DedicatedShiftBooking.id.desc())
        .all()
    )

    results: list[FleetDedicatedBookingOut] = []
    for b in bookings:
        branch = db.get(MerchantBranch, b.merchant_branch_id)
        account = db.get(MerchantAccount, branch.merchant_account_id) if branch else None
        rider = db.get(Courier, b.rider_id) if b.rider_id else None

        # Today's attendance
        today_log = (
            db.query(ShiftAttendanceLog)
            .filter(
                ShiftAttendanceLog.dedicated_shift_booking_id == b.id,
                ShiftAttendanceLog.log_date == today,
            )
            .first()
        )

        checkin_status = "not_yet"
        checkin_at = None
        geofence_validated = False
        if today_log:
            checkin_at = today_log.checkin_at
            geofence_validated = bool(today_log.geofence_validated)
            if today_log.checkout_at is not None:
                checkin_status = "completed"
            elif today_log.checkin_at is not None and geofence_validated:
                checkin_status = "checked_in"

        # Today's completed orders
        orders_count = 0
        if b.rider_id:
            orders_count = (
                db.query(BranchDispatchOrder)
                .filter(
                    BranchDispatchOrder.dedicated_shift_booking_id == b.id,
                    BranchDispatchOrder.rider_id == b.rider_id,
                    BranchDispatchOrder.order_date == today,
                    BranchDispatchOrder.status == OrderStatus.delivered,
                )
                .count()
            )

        branch_addr = f"{branch.city}, {branch.district or ''}".strip(", ") if branch else "المملكة العربية السعودية"

        results.append(
            FleetDedicatedBookingOut(
                id=b.id,
                merchant_name=account.trade_name if account else "مطعم شريك",
                branch_name=branch.branch_name if branch else f"فرع #{b.merchant_branch_id}",
                branch_city=branch.city if branch else "الرياض",
                branch_district=branch.district if branch else None,
                branch_address=branch_addr,
                shift_type=b.shift_type.value,
                shift_start=b.shift_start_time.strftime("%H:%M"),
                shift_end=b.shift_end_time.strftime("%H:%M"),
                monthly_payout=float(b.monthly_payout_to_logistics),
                effective_from=b.effective_from,
                effective_until=b.effective_until,
                status=b.status.value,
                supervisor_id=b.supervisor_id,
                supervisor_name=db.get(User, b.supervisor_id).name if b.supervisor_id and db.get(User, b.supervisor_id) else None,
                rider=BookingRiderInfo(
                    rider_id=rider.id,
                    name=rider.name,
                    rider_name=rider.name,
                    phone=rider.phone,
                    national_id=getattr(rider, "national_id", None) or getattr(rider, "iqama", None),
                ) if rider else None,
                today_attendance=TodayAttendanceInfo(
                    checkin_status=checkin_status,
                    checkin_at=checkin_at,
                    geofence_validated=geofence_validated,
                ),
                today_orders_count=orders_count,
            )
        )

    return results


@router.get("/eligible-riders", response_model=list[EligibleRiderOut])
def get_eligible_riders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant_id: Optional[int] = Query(None),
):
    """
    Returns all active couriers belonging to this logistics company
    available for dedicated shift assignment.
    """
    target_tenant_id = _resolve_tenant_id(current_user, tenant_id)
    riders = (
        db.query(Courier)
        .filter(
            Courier.tenant_id == target_tenant_id,
            Courier.employment_status == "ACTIVE",
        )
        .order_by(Courier.name.asc())
        .all()
    )

    return [
        EligibleRiderOut(
            id=r.id,
            name=r.name,
            phone=r.phone,
            national_id=getattr(r, "national_id", None) or getattr(r, "iqama", None),
            is_active=(r.employment_status == "ACTIVE"),
        )
        for r in riders
    ]


@router.post("/bookings/{booking_id}/assign-rider")
def assign_rider_to_booking(
    booking_id: int,
    payload: AssignRiderPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant_id: Optional[int] = Query(None),
):
    """
    Assigns or changes the courier assigned to an active dedicated shift booking.
    Strictly verifies that the courier belongs to the same logistics company.
    """
    target_tenant_id = _resolve_tenant_id(current_user, tenant_id)

    booking = db.get(DedicatedShiftBooking, booking_id)
    if not booking or booking.logistics_company_tenant_id != target_tenant_id:
        raise HTTPException(status_code=404, detail="عقد الوردية غير موجود أو غير مصرح به.")

    rider = db.get(Courier, payload.rider_id)
    if not rider or rider.tenant_id != target_tenant_id:
        raise HTTPException(
            status_code=400,
            detail="المندوب غير مسجل لدى شركتكم اللوجستية.",
        )

    booking.rider_id = rider.id
    db.commit()
    db.refresh(booking)

    return {
        "ok": True,
        "success": True,
        "message": f"تم إسناد المندوب {rider.name} للوردية بنجاح.",
        "booking_id": booking.id,
        "rider_id": rider.id,
        "rider_name": rider.name,
    }


@router.get("/settlement", response_model=FleetSettlementOut)
def get_fleet_monthly_settlement(
    month: Optional[str] = Query(None, description="Month in YYYY-MM format"),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant_id: Optional[int] = Query(None),
):
    """
    Generates the monthly B2B financial settlement statement showing total payouts
    due from DOU to the logistics company for all active dedicated shift bookings.
    """
    target_tenant_id = _resolve_tenant_id(current_user, tenant_id)
    tenant = db.get(Tenant, target_tenant_id)
    tenant_name = tenant.name if tenant else "الشركة اللوجستية"

    now = datetime.now(timezone.utc)
    if isinstance(month, str) and "-" in month:
        month_str = month.strip()
    elif isinstance(month, (int, str)) and str(month).isdigit():
        resolved_year = year or now.year
        month_str = f"{resolved_year}-{int(month):02d}"
    else:
        month_str = f"{now.year}-{now.month:02d}"

    try:
        start_date, next_month_date = month_bounds(month_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    days_in_month = (next_month_date - start_date).days
    month_end_date = next_month_date - timedelta(days=1)

    # Find bookings overlapping with target month
    bookings = (
        db.query(DedicatedShiftBooking)
        .join(MerchantBranch, DedicatedShiftBooking.merchant_branch_id == MerchantBranch.id)
        .filter(
            DedicatedShiftBooking.logistics_company_tenant_id == target_tenant_id,
            DedicatedShiftBooking.status != BookingStatus.terminated,
            DedicatedShiftBooking.effective_from <= month_end_date,
            or_(
                DedicatedShiftBooking.effective_until.is_(None),
                DedicatedShiftBooking.effective_until >= start_date,
            ),
        )
        .all()
    )

    line_items: list[FleetSettlementLineItem] = []
    total_payout = Decimal("0.00")

    for b in bookings:
        branch = db.get(MerchantBranch, b.merchant_branch_id)
        account = db.get(MerchantAccount, branch.merchant_account_id) if branch else None
        rider = db.get(Courier, b.rider_id) if b.rider_id else None

        start_active = max(b.effective_from, start_date)
        end_active = min(b.effective_until or month_end_date, month_end_date)

        if end_active >= start_active:
            active_days = (end_active - start_active).days + 1
        else:
            active_days = 0

        payout_prorated = prorate(b.monthly_payout_to_logistics, active_days, start_date)
        total_payout += payout_prorated

        line_items.append(
            FleetSettlementLineItem(
                booking_id=b.id,
                merchant_name=account.trade_name if account else "مطعم شريك",
                branch_name=branch.branch_name if branch else f"فرع #{b.merchant_branch_id}",
                rider_name=rider.name if rider else "غير مسند",
                shift_type=b.shift_type.value,
                active_days=active_days,
                days_in_month=days_in_month,
                monthly_payout_rate=float(b.monthly_payout_to_logistics),
                prorated_payout=float(payout_prorated),
            )
        )

    month_name_en = calendar.month_name[start_date.month]
    statement_str = f"{month_name_en} {start_date.year}"

    return FleetSettlementOut(
        tenant_name=tenant_name,
        settlement_month=statement_str,
        total_payout_due=float(total_payout),
        currency="SAR",
        settlement_status="draft",
        line_items=line_items,
    )

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.entities import Courier, CourierType, Tenant, User, UserRole
from app.models.merchant import (
    BookingStatus,
    BranchDispatchOrder,
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    OrderStatus,
    RiderAssignmentApproval,
    ShiftAttendanceLog,
)
from app.routers.auth import get_current_user
from app.services.financial_calculations import month_bounds
from app.utils.finance import calculate_booking_active_days, prorate

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


class CourierTypeMetrics(BaseModel):
    total_riders: int = 0
    active_riders: int = 0
    total_shifts: int = 0
    attendance_rate: float = 100.0
    total_deliveries: int = 0
    avg_deliveries_per_shift: float = 0.0


class FleetPerformanceBreakdownOut(BaseModel):
    tenant_id: int
    company: CourierTypeMetrics
    freelancer: CourierTypeMetrics
    comparison_summary: str = ""


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

    c_type_str = str(getattr(rider, "courier_type", "COMPANY") or "COMPANY").upper()
    is_freelancer = (rider.courier_type == CourierType.FREELANCER or "FREELANCER" in c_type_str)

    if is_freelancer:
        booking.rider_id = rider.id
        db.commit()
        db.refresh(booking)
        return {
            "ok": True,
            "success": True,
            "message": f"تم إسناد المندوب الفريلانسر {rider.name} للوردية بنجاح ومباشرة العمل فوراً.",
            "booking_id": booking.id,
            "rider_id": rider.id,
            "rider_name": rider.name,
            "courier_type": "FREELANCER",
            "approval_status": "INSTANT_ASSIGNED",
        }
    else:
        # Company rider: requires merchant approval, seat remains vacant
        branch = db.get(MerchantBranch, booking.merchant_branch_id)
        account_id = branch.merchant_account_id if branch else 1

        existing_appr = (
            db.query(RiderAssignmentApproval)
            .filter(
                RiderAssignmentApproval.booking_id == booking.id,
                RiderAssignmentApproval.status == "PENDING",
            )
            .first()
        )
        if existing_appr:
            existing_appr.courier_id = rider.id
            existing_appr.courier_name = rider.name
            existing_appr.courier_phone = rider.phone or ""
            existing_appr.requested_at = datetime.now(timezone.utc)
            approval = existing_appr
        else:
            approval = RiderAssignmentApproval(
                booking_id=booking.id,
                merchant_branch_id=booking.merchant_branch_id,
                merchant_account_id=account_id,
                logistics_company_tenant_id=target_tenant_id,
                courier_id=rider.id,
                courier_name=rider.name,
                courier_phone=rider.phone or "",
                status="PENDING",
                requested_at=datetime.now(timezone.utc),
            )
            db.add(approval)

        db.commit()
        db.refresh(approval)

        return {
            "ok": True,
            "success": True,
            "message": f"تم رفع طلب إسناد المندوب (كفالة الشركة) {rider.name} إلى إدارة المطعم للاعتماد.",
            "booking_id": booking.id,
            "rider_id": rider.id,
            "rider_name": rider.name,
            "courier_type": "COMPANY",
            "approval_id": approval.id,
            "approval_status": "PENDING",
        }


@router.get("/performance-breakdown", response_model=FleetPerformanceBreakdownOut)
def get_fleet_performance_breakdown(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant_id: Optional[int] = Query(None),
):
    """
    Compares operational and delivery performance breakdown between company riders and freelancers.
    """
    target_tenant_id = _resolve_tenant_id(current_user, tenant_id)

    couriers = db.query(Courier).filter(Courier.tenant_id == target_tenant_id).all()

    company_riders = [
        c for c in couriers
        if c.courier_type == CourierType.COMPANY or "COMPANY" in str(c.courier_type).upper()
    ]
    freelancer_riders = [
        c for c in couriers
        if c.courier_type == CourierType.FREELANCER or "FREELANCER" in str(c.courier_type).upper()
    ]

    comp_ids = {c.id for c in company_riders}
    free_ids = {c.id for c in freelancer_riders}

    bookings = (
        db.query(DedicatedShiftBooking)
        .filter(
            DedicatedShiftBooking.logistics_company_tenant_id == target_tenant_id,
            DedicatedShiftBooking.status != BookingStatus.terminated,
        )
        .all()
    )
    booking_ids = [b.id for b in bookings]

    attendance_logs = (
        db.query(ShiftAttendanceLog)
        .filter(ShiftAttendanceLog.dedicated_shift_booking_id.in_(booking_ids))
        .all()
        if booking_ids
        else []
    )

    orders = (
        db.query(BranchDispatchOrder)
        .filter(
            BranchDispatchOrder.dedicated_shift_booking_id.in_(booking_ids),
            BranchDispatchOrder.status == OrderStatus.delivered,
        )
        .all()
        if booking_ids
        else []
    )

    comp_logs = [log for log in attendance_logs if log.rider_id in comp_ids]
    free_logs = [log for log in attendance_logs if log.rider_id in free_ids]

    comp_orders = [o for o in orders if o.rider_id in comp_ids]
    free_orders = [o for o in orders if o.rider_id in free_ids]

    def _build(r_list, l_list, o_list):
        total_r = len(r_list)
        active_r = len([r for r in r_list if r.employment_status == "ACTIVE"])
        total_s = len(l_list)
        valid_s = len([log for log in l_list if log.geofence_validated or log.checkin_at is not None])
        att_rate = round((valid_s / total_s * 100.0), 1) if total_s > 0 else 100.0
        total_deliv = len(o_list)
        avg_deliv = (
            round((total_deliv / total_s), 1)
            if total_s > 0
            else (round(total_deliv / max(1, total_r), 1) if total_deliv > 0 else 0.0)
        )
        return CourierTypeMetrics(
            total_riders=total_r,
            active_riders=active_r,
            total_shifts=total_s,
            attendance_rate=att_rate,
            total_deliveries=total_deliv,
            avg_deliveries_per_shift=avg_deliv,
        )

    return FleetPerformanceBreakdownOut(
        tenant_id=target_tenant_id,
        company=_build(company_riders, comp_logs, comp_orders),
        freelancer=_build(freelancer_riders, free_logs, free_orders),
        comparison_summary="مقارنة أداء مناديب الكفالة مقارنة بالفريلانسر وفق معدلات الحضور والإنتاجية.",
    )


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

    booking_ids = [b.id for b in bookings]
    approvals = (
        db.query(RiderAssignmentApproval)
        .filter(RiderAssignmentApproval.booking_id.in_(booking_ids))
        .all()
        if booking_ids
        else []
    )
    approvals_by_booking: dict[int, list[RiderAssignmentApproval]] = {}
    for a in approvals:
        approvals_by_booking.setdefault(a.booking_id, []).append(a)

    for b in bookings:
        branch = db.get(MerchantBranch, b.merchant_branch_id)
        account = db.get(MerchantAccount, branch.merchant_account_id) if branch else None
        rider = db.get(Courier, b.rider_id) if b.rider_id else None

        active_days = calculate_booking_active_days(
            b, start_date, approvals=approvals_by_booking.get(b.id, [])
        )

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

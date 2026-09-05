import calendar
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional


def prorate(monthly_rate: Decimal, active_days: int, month_date: date) -> Decimal:
    """
    Symmetrical daily proration formula.
    prorated = (active_days / days_in_month) * monthly_rate
    Quantized to 0.01 SAR using ROUND_HALF_UP.
    """
    days_in_month = calendar.monthrange(month_date.year, month_date.month)[1]
    result = (Decimal(active_days) / Decimal(days_in_month)) * Decimal(str(monthly_rate))
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def billable_booking_filters(month_date: date):
    """
    Unified SQLAlchemy filter conditions for billable dedicated shift bookings
    across merchant statements, admin settlements, and fleet payouts.
    """
    from sqlalchemy import or_

    from app.models.merchant import BookingStatus, DedicatedShiftBooking

    days_in_month = calendar.monthrange(month_date.year, month_date.month)[1]
    month_start_date = date(month_date.year, month_date.month, 1)
    month_end_date = date(month_date.year, month_date.month, days_in_month)

    return [
        DedicatedShiftBooking.status != BookingStatus.terminated,
        DedicatedShiftBooking.effective_from <= month_end_date,
        or_(
            DedicatedShiftBooking.effective_until.is_(None),
            DedicatedShiftBooking.effective_until >= month_start_date,
        ),
    ]


def is_booking_billable_for_month(booking, month_date: date) -> bool:
    """
    Unified in-memory predicate to determine if a dedicated shift booking
    is billable for the target month.
    """
    from app.models.merchant import BookingStatus

    if booking.status == BookingStatus.terminated:
        return False
    days_in_month = calendar.monthrange(month_date.year, month_date.month)[1]
    month_start_date = date(month_date.year, month_date.month, 1)
    month_end_date = date(month_date.year, month_date.month, days_in_month)

    if booking.effective_from > month_end_date:
        return False
    if booking.effective_until and booking.effective_until < month_start_date:
        return False
    return True


def calculate_booking_active_days(
    booking,
    month_date: date,
    db=None,
    approvals=None,
    today_date: Optional[date] = None,
) -> int:
    """
    Unified calculation of active billable days for a dedicated shift booking in a target month.

    Rules:
    - Base window is [max(effective_from, month_start), min(effective_until or month_end, month_end)].
    - If base window is invalid (end < start), returns 0.
    - Any calendar days within the base window where the seat is waiting for merchant rider
      approval (from approval requested_at date up to decided_at date, or today_date if still pending)
      are unbillable and deducted symmetrically from merchant billing and fleet payout.
    - Completely vacant seats (with no approval requests) remain 100% billable under SLA.
    """
    days_in_month = calendar.monthrange(month_date.year, month_date.month)[1]
    month_start_date = date(month_date.year, month_date.month, 1)
    month_end_date = date(month_date.year, month_date.month, days_in_month)

    start_active = max(booking.effective_from, month_start_date)
    end_active = min(booking.effective_until or month_end_date, month_end_date)

    if end_active < start_active:
        return 0

    base_active_days = (end_active - start_active).days + 1

    if approvals is None and db is not None and getattr(booking, "id", None):
        from app.models.merchant import RiderAssignmentApproval

        approvals = (
            db.query(RiderAssignmentApproval)
            .filter(RiderAssignmentApproval.booking_id == booking.id)
            .all()
        )

    if not approvals:
        return base_active_days

    if today_date is None:
        today_date = date.today()

    unbillable_dates = set()
    for appr in approvals:
        if not appr.requested_at:
            continue
        req_date = (
            appr.requested_at.date()
            if isinstance(appr.requested_at, datetime)
            else appr.requested_at
        )

        if appr.decided_at is not None:
            dec_date = (
                appr.decided_at.date()
                if isinstance(appr.decided_at, datetime)
                else appr.decided_at
            )
        else:
            if today_date >= end_active:
                dec_date = end_active + timedelta(days=1)
            elif today_date >= req_date:
                dec_date = today_date + timedelta(days=1)
            else:
                dec_date = req_date

        window_start = max(req_date, start_active)
        window_end = min(dec_date, end_active + timedelta(days=1))

        curr = window_start
        while curr < window_end:
            unbillable_dates.add(curr)
            curr += timedelta(days=1)

    return max(0, base_active_days - len(unbillable_dates))


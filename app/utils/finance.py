import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal


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


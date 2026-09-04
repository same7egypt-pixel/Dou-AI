import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


def prorate(monthly_rate: Decimal, active_days: int, month_date: date) -> Decimal:
    """
    Symmetrical daily proration formula.
    prorated = (active_days / days_in_month) * monthly_rate
    Quantized to 0.01 SAR using ROUND_HALF_UP.
    """
    days_in_month = calendar.monthrange(month_date.year, month_date.month)[1]
    result = (Decimal(active_days) / Decimal(days_in_month)) * Decimal(str(monthly_rate))
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

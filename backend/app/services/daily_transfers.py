"""Shanghai calendar-day accounting. Persist changes only under execution locks."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

SHANGHAI = timezone(timedelta(hours=8))
EXECUTION_TIME_KEY = "transfer_execution_time"


def utc_now():
    return datetime.now(timezone.utc)


def banking_day(now=None):
    instant = utc_now() if now is None else now
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Banking time must include a timezone")
    return instant.astimezone(SHANGHAI).date()


def effective_total(account, now=None):
    """Read-only view: yesterday's counter is zero today, even before a write.

    Unknown or future dates conservatively retain the stored amount. Migration
    initializes legacy unknown dates without discarding their existing totals.
    """
    day = banking_day(now)
    if account.daily_transfer_date is not None and account.daily_transfer_date < day:
        return Decimal("0.00")
    return account.daily_transfer_total


def prepare_day(account, now):
    """Initialize/roll forward the locked account; return reset details for audit."""
    day = banking_day(now)
    previous_day = account.daily_transfer_date
    if previous_day is not None and previous_day > day:
        raise ValueError("Banking clock precedes the stored transfer day")
    reset = None
    if previous_day is not None and previous_day < day:
        reset = {"previous_day": previous_day.isoformat(), "day": day.isoformat(),
                 "previous_total": f"{account.daily_transfer_total:.2f}"}
        account.daily_transfer_total = Decimal("0.00")
    account.daily_transfer_date = day
    return reset

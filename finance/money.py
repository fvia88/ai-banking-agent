"""Exact money and time helpers. Decimal only; binary floats are never used."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

# Reporting timezone: contracts store aware datetimes; months are bucketed in China
# Standard Time (Asia/Shanghai = fixed UTC+08:00, no DST since 1991). A fixed offset
# avoids a tzdata dependency and gives identical results on every OS.
REPORTING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

_PERIOD_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def to_amount(raw: object) -> Decimal | None:
    """Positive, finite, cent-exact Decimal, or None. The contract (PositiveMoney)
    already guarantees this for validated Transactions; this is defense in depth
    for objects built without validation (e.g. model_construct)."""
    try:
        value = raw if isinstance(raw, Decimal) else Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not value.is_finite() or value <= 0 or value != value.quantize(CENT):
        return None
    return value.quantize(CENT)


def to_aware(raw: object) -> datetime | None:
    """Aware datetime or None (naive/unparseable). Accepts datetime or ISO string."""
    if isinstance(raw, str):
        try:
            raw = datetime.fromisoformat(raw.strip())
        except ValueError:
            return None
    if not isinstance(raw, datetime) or raw.tzinfo is None or raw.utcoffset() is None:
        return None
    return raw


def money(value: Decimal) -> Decimal:
    """Quantize to cents (Decimal stays Decimal; contract serializes it as '123.45')."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def format_money(value: Decimal) -> str:
    return f"{money(value):.2f}"


def period_of(dt: datetime) -> str:
    local = dt.astimezone(REPORTING_TZ)
    return f"{local.year:04d}-{local.month:02d}"


def validate_period(period: object) -> str:
    if not isinstance(period, str) or not _PERIOD_RE.match(period):
        raise ValueError("period must be a string formatted YYYY-MM (e.g. '2026-10')")
    return period


def shift_period(period: str, months: int) -> str:
    y, m = int(period[:4]), int(period[5:7])
    idx = y * 12 + (m - 1) + months
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def period_range(start: str, end: str) -> list[str]:
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur = shift_period(cur, 1)
    return out

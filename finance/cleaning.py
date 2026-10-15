"""Normalize validated contract Transactions into exact internal records.

The shared `Transaction` model already rejects non-positive / non-cent amounts and
naive timestamps. This module adds what the model cannot see: duplicate IDs across
records, month bucketing, categorization, refund detection. It also re-checks
amount/timestamp defensively for objects built without validation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from contracts.models import Transaction

from .categories import CategoryResult, categorize, clean_text
from .money import period_of, to_amount, to_aware

REFUND_LABELS = frozenset({"refund", "refunds", "reversal", "chargeback", "退款"})
_REFUND_MERCHANT_RE = re.compile(r"(?<![a-z])(refund|reversal|chargeback)(?![a-z])|退款")


@dataclass(frozen=True)
class Flag:
    """Internal, richer form of a finding. Converted to contract `Anomaly`
    (transaction_id + reason) by analytics.py."""
    code: str
    kind: str  # "spending" | "data_quality" | "info"
    severity: str  # "warning" | "info"
    message: str  # template text only; never contains merchant/note text
    transaction_id: str = ""  # "" for period-level notes
    period: str | None = None  # None => relevant to every period


@dataclass(frozen=True)
class CleanTxn:
    transaction_id: str
    account_id: str
    timestamp: datetime
    period: str
    amount: Decimal
    direction: str  # "debit" | "credit"
    merchant_key: str  # normalized merchant, for matching only
    category: CategoryResult
    is_refund: bool


@dataclass
class CleanResult:
    records: list[CleanTxn] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)


def _direction(value: object) -> str:
    return str(getattr(value, "value", value)).lower()


def _fingerprint(t: Transaction) -> str:
    return json.dumps(t.model_dump(mode="json"), sort_keys=True, default=str)


def clean_transactions(transactions: list[Transaction]) -> CleanResult:
    result = CleanResult()

    by_id: dict[str, list[Transaction]] = {}
    for t in transactions:
        by_id.setdefault(str(t.transaction_id), []).append(t)

    unique: list[Transaction] = []
    for tid in sorted(by_id):  # order-independent
        copies = by_id[tid]
        ts = to_aware(copies[0].timestamp)
        p = period_of(ts) if ts else None
        if len(copies) == 1:
            unique.append(copies[0])
        elif len({_fingerprint(c) for c in copies}) == 1:
            unique.append(copies[0])
            result.flags.append(Flag(
                "DUPLICATE_TRANSACTION_ID", "data_quality", "info",
                f"{len(copies)} identical records share this transaction ID; counted once.",
                tid, p))
        else:
            result.flags.append(Flag(
                "CONFLICTING_DUPLICATE_ID", "data_quality", "warning",
                f"{len(copies)} records share this transaction ID but differ in content; all "
                "copies are excluded from totals until the source data is corrected.",
                tid, p))

    for t in unique:
        tid = str(t.transaction_id)
        ts = to_aware(t.timestamp)
        if ts is None:
            result.flags.append(Flag(
                "INVALID_TIMESTAMP", "data_quality", "warning",
                "Timestamp is missing or has no timezone; excluded because it cannot be "
                "assigned to a month.", tid, None))
            continue
        period = period_of(ts)
        amount = to_amount(t.amount)
        direction = _direction(t.direction)
        if amount is None or direction not in ("debit", "credit"):
            result.flags.append(Flag(
                "INVALID_AMOUNT", "data_quality", "warning",
                "Amount is not a positive value with at most 2 decimals, or direction is "
                "invalid; excluded from totals.", tid, period))
            continue
        merchant_key = clean_text(t.merchant, limit=256).casefold()
        label = clean_text(t.category).casefold()
        result.records.append(CleanTxn(
            transaction_id=tid,
            account_id=str(t.account_id),
            timestamp=ts,
            period=period,
            amount=amount,
            direction=direction,
            merchant_key=merchant_key,
            category=categorize(t.category, t.merchant),
            is_refund=direction == "credit" and (
                label in REFUND_LABELS or bool(_REFUND_MERCHANT_RE.search(merchant_key))),
        ))

    result.records.sort(key=lambda r: (r.timestamp, r.transaction_id))
    return result

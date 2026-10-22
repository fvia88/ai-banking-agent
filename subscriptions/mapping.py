"""Candidate -> stored-record mapping and cancellation decision (P5).

Pure calculation, like the rest of this package: it reads values passed in,
returns a result, and never writes, calls a service or cancels anything.

Why this exists: the detector only sees transactions, so a candidate says
nothing about whether the merchant supports cancellation or whether the
subscription is still active. Those facts live in the stored Subscription
record (owned by the backend). This module decides which stored record a
candidate refers to and whether cancelling it may be proposed.

The stored record is the single source of truth for `status` and
`cancellation_supported`. The flag on a candidate is never trusted.
"""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence

from contracts.models import (
    CancellationAssessment,
    Subscription,
    SubscriptionCandidate,
    SubscriptionReport,
)
from subscriptions.detector import AMOUNT_TOLERANCE
from subscriptions.eligibility import assess_cancellation

# Reason codes added on top of ELIGIBLE / CANCELLATION_NOT_SUPPORTED.
# They need P2's agreement before the backend relies on them.
NOT_FOUND = "SUBSCRIPTION_NOT_FOUND"
AMBIGUOUS = "AMBIGUOUS_SUBSCRIPTION"
ALREADY_CANCELLED = "ALREADY_CANCELLED"


class MatchStatus(str, Enum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class StoredMatch:
    status: MatchStatus
    record: Optional[Subscription] = None


@dataclass(frozen=True)
class CancellationDecision:
    eligible: bool
    reason_code: str
    stored_subscription_id: Optional[str] = None
    requires_confirmation: bool = True  # always: a person must confirm


def _norm(text: str) -> str:
    return text.strip().casefold()


def _similar_price(a: Decimal, b: Decimal) -> bool:
    low, high = min(a, b), max(a, b)
    if low <= 0:
        return low == high
    return high <= low * AMOUNT_TOLERANCE


def _result(matches: list) -> StoredMatch:
    if len(matches) == 1:
        return StoredMatch(MatchStatus.MATCHED, matches[0])
    return StoredMatch(MatchStatus.AMBIGUOUS if matches else MatchStatus.NOT_FOUND)


def match_stored(candidate: SubscriptionCandidate,
                 stored: Sequence[Subscription],
                 user_id: str) -> StoredMatch:
    """Find the stored record a candidate refers to, among this user's records only."""
    own = [s for s in stored if s.user_id == user_id]
    merchant = _norm(candidate.merchant)

    # 1. Same id AND same merchant. An id alone is not enough.
    by_id = [s for s in own
             if s.subscription_id == candidate.subscription_id and _norm(s.merchant) == merchant]
    if by_id:
        return _result(by_id)

    # 2. Same merchant name; if several, the price must pick exactly one.
    same_merchant = [s for s in own if _norm(s.merchant) == merchant]
    if len(same_merchant) <= 1:
        return _result(same_merchant)
    by_price = [s for s in same_merchant
                if _similar_price(s.estimated_amount, candidate.estimated_amount)]
    return _result(by_price)


def assess_stored_cancellation(candidate: SubscriptionCandidate,
                               stored: Sequence[Subscription],
                               user_id: str) -> CancellationDecision:
    """Decide whether cancelling this candidate may be proposed for confirmation.

    Order matters: unknown/ambiguous first, then status, then support.
    Calling it again after the record became `cancelled` gives ALREADY_CANCELLED,
    so a repeated cancellation is refused instead of executed twice.
    """
    match = match_stored(candidate, stored, user_id)
    if match.status is MatchStatus.NOT_FOUND:
        return CancellationDecision(False, NOT_FOUND)
    if match.status is MatchStatus.AMBIGUOUS:
        return CancellationDecision(False, AMBIGUOUS)

    record = match.record
    if record.status != "active":
        return CancellationDecision(False, ALREADY_CANCELLED, record.subscription_id)

    # Support comes from the stored record, never from the detector's flag.
    checked = candidate.model_copy(update={"cancellation_supported": record.cancellation_supported})
    assessment: CancellationAssessment = assess_cancellation(checked)
    return CancellationDecision(assessment.eligible, assessment.reason_code, record.subscription_id)


def enrich_candidates(report: SubscriptionReport,
                      stored: Sequence[Subscription],
                      user_id: str) -> SubscriptionReport:
    """Copy of the report with `cancellation_supported` filled from stored records.

    True only for a candidate that matches exactly one active, supported record
    of this user. Everything else stays False.
    """
    enriched = []
    for c in report.candidates:
        m = match_stored(c, stored, user_id)
        ok = (m.status is MatchStatus.MATCHED
              and m.record.status == "active"
              and m.record.cancellation_supported)
        enriched.append(c.model_copy(update={"cancellation_supported": bool(ok)}))
    return SubscriptionReport(candidates=enriched)

"""Recurring-charge detector (P5).

Pure calculation: reads transactions, returns a report. It never writes to a
database, never calls external services and never cancels anything.
Transaction notes are never read, so text inside them cannot influence results.
"""
import re
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from statistics import median

from contracts.enums import Cadence, Direction
from contracts.models import (
    SubscriptionCandidate,
    SubscriptionReport,
    Transaction,
)

# Allowed gap (in days) between two consecutive charges for each cadence.
CADENCE_GAP_DAYS = {
    Cadence.WEEKLY: (6, 8),
    Cadence.MONTHLY: (27, 33),
    Cadence.ANNUAL: (360, 370),
}

# Amounts within this ratio of the cluster minimum count as "the same price".
AMOUNT_TOLERANCE = Decimal("1.05")

MIN_CHARGES = 2  # one charge alone is never evidence of recurrence

# Conservative confidence by number of matching charges.
BASE_CONFIDENCE = {2: 0.40, 3: 0.70, 4: 0.85}
MAX_CONFIDENCE = 0.90
VARYING_AMOUNT_PENALTY = 0.10

CENT = Decimal("0.01")


def detect_subscriptions(transactions: list[Transaction]) -> SubscriptionReport:
    debits = _dedupe([t for t in transactions if t.direction == Direction.DEBIT])

    by_merchant: dict[str, list[Transaction]] = defaultdict(list)
    for t in debits:
        by_merchant[t.merchant.strip().casefold()].append(t)

    candidates: list[SubscriptionCandidate] = []
    for key in sorted(by_merchant):
        group = by_merchant[key]
        merchant_name = group[0].merchant.strip()
        found = [
            c
            for cluster in _cluster_by_amount(group)
            if (c := _analyze_cluster(merchant_name, cluster)) is not None
        ]
        base_id = "sub_" + _slug(merchant_name)
        for c in found:
            # Same merchant, several services (different prices): keep ids unique.
            suffix = "" if len(found) == 1 else "_" + _slug(str(c["amount"]))
            candidates.append(_build(base_id + suffix, merchant_name, c))

    candidates.sort(key=lambda c: c.subscription_id)
    return SubscriptionReport(candidates=candidates)


def _dedupe(transactions: list[Transaction]) -> list[Transaction]:
    """Drop repeated ids and double-posted identical charges."""
    seen_ids: set[str] = set()
    seen_keys: set[tuple] = set()
    result = []
    for t in sorted(transactions, key=lambda t: (t.timestamp, t.transaction_id)):
        key = (t.merchant.strip().casefold(), t.timestamp, t.amount)
        if t.transaction_id in seen_ids or key in seen_keys:
            continue
        seen_ids.add(t.transaction_id)
        seen_keys.add(key)
        result.append(t)
    return result


def _cluster_by_amount(group: list[Transaction]) -> list[list[Transaction]]:
    """Split one merchant's charges into groups of similar price."""
    clusters: list[list[Transaction]] = []
    for t in sorted(group, key=lambda t: t.amount):
        if clusters and t.amount <= min(x.amount for x in clusters[-1]) * AMOUNT_TOLERANCE:
            clusters[-1].append(t)
        else:
            clusters.append([t])
    return clusters


def _analyze_cluster(merchant: str, cluster: list[Transaction]):
    if len(cluster) < MIN_CHARGES:
        return None
    ordered = sorted(cluster, key=lambda t: (t.timestamp, t.transaction_id))
    gaps = [(b.timestamp - a.timestamp) / timedelta(days=1)
            for a, b in zip(ordered, ordered[1:])]
    cadence = _match_cadence(gaps)
    if cadence is None:
        return None  # irregular dates: not asserted as a subscription

    amounts = [t.amount for t in ordered]
    estimated = Decimal(median(amounts)).quantize(CENT, rounding=ROUND_HALF_UP)
    confidence = BASE_CONFIDENCE.get(len(ordered), MAX_CONFIDENCE)
    if len(set(amounts)) > 1:
        confidence -= VARYING_AMOUNT_PENALTY
    return {
        "amount": estimated,
        "cadence": cadence,
        "confidence": round(confidence, 2),
        "evidence": [t.transaction_id for t in ordered],
    }


def _match_cadence(gaps: list[float]):
    for cadence, (low, high) in CADENCE_GAP_DAYS.items():
        if all(low <= g <= high for g in gaps):
            return cadence
    return None


def _build(subscription_id: str, merchant: str, c: dict) -> SubscriptionCandidate:
    return SubscriptionCandidate(
        subscription_id=subscription_id,
        merchant=merchant,
        estimated_amount=c["amount"],
        cadence=c["cadence"],
        confidence=c["confidence"],
        evidence_transaction_ids=c["evidence"],
        # The detector only sees transactions, so it can never know this.
        # The backend fills it from stored subscription records.
        cancellation_supported=False,
    )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")

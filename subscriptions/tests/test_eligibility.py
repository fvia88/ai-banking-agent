from decimal import Decimal

from contracts.enums import Cadence
from contracts.models import SubscriptionCandidate
from subscriptions.eligibility import assess_cancellation


def make_candidate(**overrides) -> SubscriptionCandidate:
    data = {
        "subscription_id": "sub_1",
        "merchant": "Netflix",
        "estimated_amount": Decimal("68.00"),
        "cadence": Cadence.MONTHLY,
        "confidence": 0.9,
        "evidence_transaction_ids": ["t1", "t2", "t3"],
        "cancellation_supported": True,
    }
    data.update(overrides)
    return SubscriptionCandidate(**data)


def test_supported_candidate_is_eligible_and_needs_confirmation():
    result = assess_cancellation(make_candidate())
    assert result.eligible is True
    assert result.requires_confirmation is True
    assert result.reason_code == "ELIGIBLE"


def test_unsupported_candidate_is_not_eligible():
    result = assess_cancellation(make_candidate(cancellation_supported=False))
    assert result.eligible is False
    assert result.requires_confirmation is True
    assert result.reason_code == "CANCELLATION_NOT_SUPPORTED"
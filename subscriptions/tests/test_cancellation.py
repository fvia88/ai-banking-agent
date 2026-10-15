from decimal import Decimal

from contracts.enums import Cadence
from contracts.models import Subscription
from subscriptions.cancellation import assess_cancellation


def make_subscription(**overrides) -> Subscription:
    data = {
        "subscription_id": "sub_1",
        "user_id": "user_1",
        "merchant": "Netflix",
        "estimated_amount": Decimal("68.00"),
        "cadence": Cadence.MONTHLY,
        "status": "active",
        "cancellation_supported": True,
    }
    data.update(overrides)
    return Subscription(**data)


def test_active_supported_subscription_is_eligible():
    result = assess_cancellation(make_subscription())
    assert result.eligible is True
    assert result.requires_confirmation is True
    assert result.reason_code == "ELIGIBLE"


def test_already_cancelled_is_not_eligible():
    result = assess_cancellation(make_subscription(status="cancelled"))
    assert result.eligible is False
    assert result.reason_code == "ALREADY_CANCELLED"


def test_unsupported_cancellation_is_not_eligible():
    result = assess_cancellation(make_subscription(cancellation_supported=False))
    assert result.eligible is False
    assert result.reason_code == "CANCELLATION_NOT_SUPPORTED"
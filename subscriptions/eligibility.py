"""Cancellation eligibility (pure; never executes a cancellation)."""
from contracts.models import CancellationAssessment, SubscriptionCandidate


def assess_cancellation(subscription: SubscriptionCandidate) -> CancellationAssessment:
    if not subscription.cancellation_supported:
        return CancellationAssessment(
            eligible=False, reason_code="CANCELLATION_NOT_SUPPORTED"
        )
    return CancellationAssessment(eligible=True, reason_code="ELIGIBLE")
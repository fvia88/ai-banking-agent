"""Simulated subscription cancellation assessment (P5)."""
from contracts.models import CancellationAssessment, Subscription


def assess_cancellation(subscription: Subscription) -> CancellationAssessment:
    """Decide if a subscription may be cancelled. Never cancels anything itself."""
    if subscription.status == "cancelled":
        return CancellationAssessment(
            eligible=False, reason_code="ALREADY_CANCELLED"
        )
    if not subscription.cancellation_supported:
        return CancellationAssessment(
            eligible=False, reason_code="CANCELLATION_NOT_SUPPORTED"
        )
    return CancellationAssessment(eligible=True, reason_code="ELIGIBLE")
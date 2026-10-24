"""Insert known synthetic records, never infer active status from detected charges."""
import json

from contracts.models import Subscription
from app.db.models import AccountModel, ActionApprovalModel, SubscriptionModel

DEMO_SUBSCRIPTION = {
    "subscription_id": "sub_iQIYI_01", "user_id": "usr_demo_01",
    "merchant": "iQIYI VIP Monthly", "estimated_amount": "45.00", "cadence": "monthly",
    "status": "active", "cancellation_supported": True,
}


def seed_subscriptions(db, fixture_records):
    """Backfill missing IDs only for existing known accounts; caller commits.

    Preserve existing cancellations, including completed cancellation actions from
    the old audit-only executor, so an upgrade does not revive those subscriptions.
    """
    for raw in [*fixture_records, DEMO_SUBSCRIPTION]:
        subscription = Subscription.model_validate(raw)
        if db.get(SubscriptionModel, subscription.subscription_id) is not None:
            continue
        accounts = db.query(AccountModel).filter(AccountModel.user_id == subscription.user_id).all()
        expected_id = "acc_cny_001" if subscription.user_id == "usr_demo_01" else "account_001"
        account = next((a for a in accounts if a.account_id == expected_id), None)
        if account is None:
            continue  # Never create a user/account or attach to an arbitrary account.
        cancelled = False
        for action in db.query(ActionApprovalModel).filter(
            ActionApprovalModel.user_id == subscription.user_id,
            ActionApprovalModel.tool == "request_subscription_cancel",
            ActionApprovalModel.status == "COMPLETED",
        ).all():
            try:
                if json.loads(action.payload_json).get("subscription_id") == subscription.subscription_id:
                    cancelled = True
                    break
            except (ValueError, AttributeError):
                continue
        values = subscription.model_dump()
        values["cadence"] = subscription.cadence.value
        if cancelled:
            values["status"] = "cancelled"
        db.add(SubscriptionModel(**values, account_id=account.account_id,
                                 cancelled_at=None))

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.db.models import ActionApprovalModel, SubscriptionModel, UserModel, AccountModel
from app.db.subscription_seed import seed_subscriptions


def test_backfill_preserves_balance_and_cancelled_state(db_session):
    account = db_session.get(AccountModel, "acc_cny_001")
    account.balance = Decimal("123.45")
    seed_subscriptions(db_session, [])
    db_session.commit()
    stored = db_session.get(SubscriptionModel, "sub_iQIYI_01")
    assert stored.account_id == "acc_cny_001" and stored.status == "active"
    stored.status = "cancelled"
    stored.cancellation_supported = False
    db_session.commit()
    seed_subscriptions(db_session, [])
    db_session.commit()
    assert stored.status == "cancelled" and stored.cancellation_supported is False
    assert account.balance == Decimal("123.45")
    assert db_session.query(SubscriptionModel).count() == 1


def test_completed_legacy_cancellation_is_not_resurrected(db_session):
    db_session.query(SubscriptionModel).delete()
    now = datetime.now(timezone.utc)
    db_session.add(ActionApprovalModel(
        action_id="legacy_cancel", user_id="usr_demo_01", tool="request_subscription_cancel",
        payload_json=json.dumps({"subscription_id": "sub_iQIYI_01"}), action_digest="0" * 64,
        status="COMPLETED", created_at=now, expires_at=now + timedelta(minutes=10),
    ))
    db_session.commit()
    seed_subscriptions(db_session, [])
    db_session.commit()
    row = db_session.get(SubscriptionModel, "sub_iQIYI_01")
    assert row.status == "cancelled" and row.cancelled_at is None


def test_fixture_records_only_added_when_their_owned_account_exists(db_session):
    fixture = {"subscription_id": "sub_streambox", "user_id": "user_001",
               "merchant": "StreamBox", "estimated_amount": "39.00", "cadence": "monthly",
               "status": "active", "cancellation_supported": True}
    seed_subscriptions(db_session, [fixture])
    db_session.commit()
    assert db_session.get(SubscriptionModel, "sub_streambox") is None
    db_session.add(UserModel(user_id="user_001", username="Fixture user", is_locked=False))
    db_session.add(AccountModel(account_id="account_001", user_id="user_001", account_number="fixture"))
    db_session.commit()
    seed_subscriptions(db_session, [fixture])
    db_session.commit()
    assert db_session.get(SubscriptionModel, "sub_streambox").user_id == "user_001"

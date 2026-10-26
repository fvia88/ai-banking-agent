"""Exercise P5's real functions through HTTP and persisted cancellation."""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.models import AccountModel, ActionApprovalModel, AuditLogModel, SubscriptionModel, TransactionModel, UserModel
from app.services.adapters import agent_service, subscriptions_service, SubscriptionsAdapterService
from contracts.models import ActionProposal, AgentResult


@pytest.fixture(autouse=True)
def real_services(monkeypatch):
    monkeypatch.setattr(subscriptions_service, "use_mock", False)
    monkeypatch.setattr(agent_service, "use_mock", False)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")


def chat(client, message, user="usr_demo_01"):
    response = client.post("/api/v1/chat", headers={"X-Demo-User-Id": user}, json={
        "conversation_id": "p5_" + uuid4().hex, "message": message,
    })
    assert response.status_code == 200, response.text
    return response.json()


def proposal(client):
    result = chat(client, "Cancel iQIYI VIP Monthly subscription")
    assert result["status"] == "PENDING_CONFIRMATION", result
    return result["actions"][0]


def confirm(client, action):
    return client.post(f'/api/v1/actions/{action["approval"]["action_id"]}/confirm', json={
        "idempotency_key": "test_request",
        "confirmation_id": "p5_confirmation", "action_digest": action["approval"]["action_digest"],
    })


def recurrence(db, account="acc_cny_001", merchant="iQIYI VIP Monthly", prefix="p5", months=(9, 10)):
    for month in months:
        db.add(TransactionModel(
            transaction_id=f"{prefix}_{month}", account_id=account,
            timestamp=f"2026-{month:02d}-05T14:15:00+08:00", amount=Decimal("45.00"),
            direction="debit", merchant=merchant, category="Entertainment",
        ))
    db.commit()


def test_real_mode_is_default_and_mock_is_explicit(monkeypatch):
    monkeypatch.delenv("USE_MOCK_SUBSCRIPTIONS", raising=False)
    assert SubscriptionsAdapterService().use_mock is False
    monkeypatch.setenv("USE_MOCK_SUBSCRIPTIONS", "true")
    assert SubscriptionsAdapterService().use_mock is True


def test_actual_detector_and_mapping_feed_dashboard_and_p1(client, db_session, monkeypatch):
    from subscriptions import detector, mapping
    recurrence(db_session)
    calls, results = [], []
    original_detect, original_enrich = detector.detect_subscriptions, mapping.enrich_candidates
    def detect(transactions):
        calls.append(transactions)
        return original_detect(transactions)
    enrich_calls = []
    def enrich(report, stored, user_id):
        enrich_calls.append(user_id)
        return original_enrich(report, stored, user_id)
    monkeypatch.setattr(detector, "detect_subscriptions", detect)
    monkeypatch.setattr(mapping, "enrich_candidates", enrich)
    original_turn = agent_service.process_turn
    def turn(*args, **kwargs):
        if kwargs.get("tool_results"):
            results.extend(kwargs["tool_results"])
        return original_turn(*args, **kwargs)
    monkeypatch.setattr(agent_service, "process_turn", turn)
    report = client.get("/api/v1/subscriptions").json()
    candidate = report["candidates"][0]
    assert candidate["subscription_id"] != "sub_iQIYI_01"  # Detector and stored IDs differ.
    assert candidate["confidence"] == 0.4 and candidate["cancellation_supported"] is True
    assert candidate["evidence_transaction_ids"] == ["p5_9", "p5_10"]
    result = chat(client, "List my subscriptions")
    assert result["actions"] == []
    assert results[0]["data"] == report
    assert len(calls) == len(enrich_calls) == 2
    assert all(t.account_id == "acc_cny_001" for batch in calls for t in batch)
    assert client.get("/api/v1/subscriptions/records").json()[0]["status"] == "active"


def test_detection_never_creates_verified_records_or_grants_cancellation(client, db_session):
    recurrence(db_session, merchant="Unknown Merchant", prefix="unknown", months=(7, 8, 9, 10))
    candidate = client.get("/api/v1/subscriptions").json()["candidates"][0]
    assert candidate["confidence"] == 0.85 and candidate["cancellation_supported"] is False
    assert db_session.query(SubscriptionModel).count() == 1
    result = chat(client, "Cancel my Unknown Merchant subscription")
    assert result["actions"] == []
    assert db_session.query(ActionApprovalModel).count() == 0


def test_no_cross_account_or_cross_user_recurrence(client, db_session):
    db_session.add(AccountModel(account_id="zz_second", user_id="usr_demo_01", account_number="second"))
    db_session.add(UserModel(user_id="other", username="Other", is_locked=False))
    db_session.add(AccountModel(account_id="other_acc", user_id="other", account_number="other"))
    db_session.commit()
    recurrence(db_session, months=(9,))
    recurrence(db_session, account="zz_second", prefix="second", months=(10,))
    recurrence(db_session, account="other_acc", prefix="other", months=(9, 10))
    assert client.get("/api/v1/subscriptions").json() == {"candidates": []}
    assert client.get("/api/v1/subscriptions?account_id=zz_second").json() == {"candidates": []}
    assert client.get("/api/v1/subscriptions?account_id=other_acc").status_code == 404
    assert client.get("/api/v1/subscriptions/records?account_id=other_acc").status_code == 404


def test_cancellation_is_confirmed_persisted_and_does_not_credit_savings(client, db_session, monkeypatch):
    from subscriptions import mapping, eligibility
    recurrence(db_session)
    assess_calls, eligible_calls = [], []
    original_assess, original_eligible = mapping.assess_stored_cancellation, eligibility.assess_cancellation
    def assess(*args):
        assess_calls.append(args)
        return original_assess(*args)
    def eligible(candidate):
        eligible_calls.append(candidate)
        return original_eligible(candidate)
    monkeypatch.setattr(mapping, "assess_stored_cancellation", assess)
    # Mapping imports the underlying function into its own module namespace.
    monkeypatch.setattr(mapping, "assess_cancellation", eligible)
    before = db_session.query(TransactionModel).count()
    action = proposal(client)
    assert action["approval"]["tier"] == "YELLOW"
    assert db_session.get(SubscriptionModel, "sub_iQIYI_01").status == "active"
    first = confirm(client, action)
    assert first.status_code == 200 and first.json()["status"] == "COMPLETED"
    assert len(assess_calls) >= 3 and len(eligible_calls) >= 3
    assert db_session.get(SubscriptionModel, "sub_iQIYI_01").status == "cancelled"
    assert db_session.get(SubscriptionModel, "sub_iQIYI_01").cancelled_at is not None
    db_session.expire_all()  # Reload state from storage, not a cached Python object.
    assert client.get("/api/v1/subscriptions/records").json()[0]["status"] == "cancelled"
    history = client.get("/api/v1/subscriptions").json()["candidates"][0]
    assert history["cancellation_supported"] is False and len(history["evidence_transaction_ids"]) == 2
    replay = confirm(client, action)
    assert replay.json()["audit_id"] == first.json()["audit_id"]
    assert chat(client, "Cancel iQIYI VIP Monthly subscription")["actions"] == []
    assert db_session.get(AccountModel, "acc_cny_001").balance == Decimal("15250.00")
    assert db_session.query(TransactionModel).count() == before
    assert db_session.query(AuditLogModel).filter_by(action_type="SUBSCRIPTION_CANCELLED").count() == 1


@pytest.mark.parametrize("change, reason", [("unsupported", "CANCELLATION_NOT_SUPPORTED"), ("cancelled", "ALREADY_CANCELLED"), ("foreign", "SUBSCRIPTION_NOT_FOUND")])
def test_changed_state_blocks_pending_cancellation(client, db_session, change, reason):
    action = proposal(client)
    row = db_session.get(SubscriptionModel, "sub_iQIYI_01")
    if change == "unsupported":
        row.cancellation_supported = False
    elif change == "cancelled":
        row.status = "cancelled"
    else:
        db_session.add(UserModel(user_id="other", username="Other", is_locked=False))
        db_session.flush()
        row.user_id = "other"
    db_session.commit()
    response = confirm(client, action)
    assert response.status_code == 403 and reason in response.json()["detail"]
    assert db_session.query(AuditLogModel).filter_by(action_type="SUBSCRIPTION_CANCELLED").count() == 0


def test_second_pending_cancellation_cannot_execute_again(client, db_session):
    first, second = proposal(client), proposal(client)
    assert confirm(client, first).json()["status"] == "COMPLETED"
    response = confirm(client, second)
    assert response.status_code == 403 and "ALREADY_CANCELLED" in response.json()["detail"]


@pytest.mark.parametrize("subscription_id", ["missing", "foreign_sub"])
def test_untrusted_proposals_cannot_cancel_missing_or_foreign_records(client, db_session, monkeypatch, subscription_id):
    db_session.add(UserModel(user_id="other", username="Other", is_locked=False))
    db_session.add(AccountModel(account_id="other_acc", user_id="other", account_number="other"))
    db_session.flush()
    db_session.add(SubscriptionModel(subscription_id="foreign_sub", user_id="other", account_id="other_acc",
                                    merchant="Foreign", estimated_amount=Decimal("10.00"), cadence="monthly",
                                    status="active", cancellation_supported=True))
    db_session.commit()
    monkeypatch.setattr(agent_service, "use_mock", True)
    monkeypatch.setattr(agent_service, "process", lambda *a, **kw: AgentResult(reply="Proposed", proposals=[
        ActionProposal(proposal_id="untrusted", tool="request_subscription_cancel", arguments={"subscription_id": subscription_id})
    ]))
    result = chat(client, "Cancel")
    assert result["status"] == "REJECTED" and result["actions"] == []
    assert "SUBSCRIPTION_NOT_FOUND" in result["reply"]


def test_annual_detection_gets_full_history(client, db_session):
    for year in (2025, 2026):
        db_session.add(TransactionModel(transaction_id=f"annual_{year}", account_id="acc_cny_001",
            timestamp=f"{year}-10-05T10:00:00+08:00", amount=Decimal("100.00"),
            direction="debit", merchant="Annual Service", category="Subscriptions"))
    db_session.commit()
    candidate = client.get("/api/v1/subscriptions").json()["candidates"][0]
    assert candidate["cadence"] == "annual" and candidate["confidence"] == 0.4


@pytest.mark.parametrize("state, reason", [("unsupported", "CANCELLATION_NOT_SUPPORTED"), ("cancelled", "ALREADY_CANCELLED")])
def test_backend_rejects_ineligible_proposal_even_if_agent_proposes_it(client, db_session, monkeypatch, state, reason):
    row = db_session.get(SubscriptionModel, "sub_iQIYI_01")
    if state == "unsupported":
        row.cancellation_supported = False
    else:
        row.status = "cancelled"
    db_session.commit()
    monkeypatch.setattr(agent_service, "use_mock", True)
    monkeypatch.setattr(agent_service, "process", lambda *a, **kw: AgentResult(reply="Proposed", proposals=[
        ActionProposal(proposal_id="untrusted", tool="request_subscription_cancel", arguments={"subscription_id": "sub_iQIYI_01"})
    ]))
    result = chat(client, "Cancel")
    assert result["status"] == "REJECTED" and reason in result["reply"]
    assert db_session.query(ActionApprovalModel).count() == 0


def test_new_lock_blocks_cancellation_at_confirmation(client, db_session):
    action = proposal(client)
    db_session.get(UserModel, "usr_demo_01").is_locked = True
    db_session.commit()
    response = confirm(client, action)
    assert response.status_code == 403 and "ACCOUNT_LOCKED" in response.json()["detail"]
    assert db_session.get(SubscriptionModel, "sub_iQIYI_01").status == "active"


def test_stale_rejection_cannot_overwrite_completed_action(client, db_session, monkeypatch):
    from app.api import approvals
    from app.services.subscriptions import SubscriptionUnavailable
    action = proposal(client)
    action_id = action["approval"]["action_id"]
    def completed_elsewhere(*args, **kwargs):
        # Model a completion becoming visible after this request loaded its
        # pending action snapshot but before it sees the cancelled subscription.
        db_session.query(ActionApprovalModel).filter_by(action_id=action_id).update(
            {"status": "COMPLETED"}, synchronize_session=False,
        )
        db_session.flush()
        raise SubscriptionUnavailable("ALREADY_CANCELLED")
    monkeypatch.setattr(approvals, "cancellation_record", completed_elsewhere)
    response = confirm(client, action)
    assert response.status_code == 409
    db_session.expire_all()
    assert db_session.get(ActionApprovalModel, action_id).status == "COMPLETED"

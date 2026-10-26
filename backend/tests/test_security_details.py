"""Real default policy selection and atomic, exactly-once escalation auditing."""
import json
from decimal import Decimal

import pytest

from app.db.models import AccountModel, ActionApprovalModel, AuditLogModel, TransactionModel
from app.services.adapters import agent_service, policy_service, SecurityAdapterService


@pytest.fixture(autouse=True)
def default_real_policy(monkeypatch):
    monkeypatch.delenv("USE_MOCK_SECURITY", raising=False)
    monkeypatch.setattr(policy_service, "use_mock", SecurityAdapterService().use_mock)
    monkeypatch.setattr(agent_service, "use_mock", True)


def proposal(client):
    response = client.post("/api/v1/chat", json={"conversation_id": "security_details", "message": "Transfer 500 CNY to Bob"})
    assert response.status_code == 200
    return response.json()["actions"][0]


def confirm(client, action):
    return client.post(f'/api/v1/actions/{action["arguments"]["action_id"]}/confirm', json={
        "confirmation_id": "security_details", "action_digest": action["arguments"]["action_digest"],
    })


def events(db, event_type):
    return db.query(AuditLogModel).filter_by(action_type=event_type).all()


def raise_daily_total(db):
    db.get(AccountModel, "acc_cny_001").daily_transfer_total = Decimal("800.00")
    db.commit()


def test_unset_flag_reaches_actual_p4_from_http(client, monkeypatch):
    from security import policy
    evaluate = policy.evaluate_action
    calls = []
    def spy(proposed, context):
        calls.append((proposed, context))
        return evaluate(proposed, context)
    monkeypatch.setattr(policy, "evaluate_action", spy)
    assert policy_service.use_mock is False
    assert proposal(client)["arguments"]["tier"] == "YELLOW"
    assert len(calls) == 1 and calls[0][1].user_id == "usr_demo_01"


def test_escalation_audit_identifies_exact_transition_without_debit(client, db_session):
    action = proposal(client)
    assert action["arguments"]["tier"] == "YELLOW"
    raise_daily_total(db_session)
    result = confirm(client, action)
    assert result.status_code == 200 and result.json()["status"] == "PENDING_MFA"
    record = db_session.get(ActionApprovalModel, action["arguments"]["action_id"])
    escalation, = events(db_session, "ESCALATED_TO_RED")
    challenge, = events(db_session, "MFA_CHALLENGE_ISSUED")
    assert record.status == "PENDING_MFA" and record.tier == "RED"
    assert escalation.action_id == challenge.action_id == record.action_id
    assert escalation.user_id == "usr_demo_01" and escalation.payload_digest == record.action_digest
    assert escalation.reason_code == "TRANSFER_EXCEEDS_DAILY_LIMIT"
    assert json.loads(escalation.details) == {"previous_tier": "YELLOW", "new_tier": "RED", "trigger": "confirmation_policy_recheck"}
    assert result.json()["audit_id"] == challenge.audit_id  # Preserve the existing response contract.
    assert db_session.get(AccountModel, "acc_cny_001").balance == Decimal("15250.00")
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 0
    assert "ESCALATED_TO_RED" in [event["event_type"] for event in client.get("/api/v1/audit").json()["events"]]


@pytest.mark.parametrize("initial_total, expected_status", [("0.00", "COMPLETED"), ("800.00", "PENDING_MFA")])
def test_no_escalation_event_when_tier_does_not_increase(client, db_session, initial_total, expected_status):
    db_session.get(AccountModel, "acc_cny_001").daily_transfer_total = Decimal(initial_total)
    db_session.commit()
    action = proposal(client)
    assert confirm(client, action).json()["status"] == expected_status
    assert events(db_session, "ESCALATED_TO_RED") == []


def test_repeated_confirmation_verification_and_replay_do_not_duplicate_escalation(client, db_session):
    action = proposal(client)
    raise_daily_total(db_session)
    assert confirm(client, action).json()["status"] == "PENDING_MFA"
    assert confirm(client, action).status_code == 400
    action_id = action["arguments"]["action_id"]
    code = client.get("/api/v1/demo/otp-inbox").json()[0]["code"]
    first = client.post(f"/api/v1/actions/{action_id}/verify", json={"verification_code": code}).json()
    assert first["status"] == "COMPLETED"
    assert confirm(client, action).json()["audit_id"] == first["audit_id"]
    assert client.post(f"/api/v1/actions/{action_id}/verify", json={"verification_code": code}).json()["audit_id"] == first["audit_id"]
    assert len(events(db_session, "ESCALATED_TO_RED")) == len(events(db_session, "MFA_CHALLENGE_ISSUED")) == 1
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 1


def test_failed_challenge_commit_rolls_back_escalation_and_can_retry(client, db_session, monkeypatch):
    action = proposal(client)
    raise_daily_total(db_session)
    commit = db_session.commit
    def fail_commit():
        raise RuntimeError("Simulated challenge commit failure")
    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="challenge commit failure"):
        confirm(client, action)
    monkeypatch.setattr(db_session, "commit", commit)
    db_session.expire_all()
    record = db_session.get(ActionApprovalModel, action["arguments"]["action_id"])
    assert record.status == "PENDING_CONFIRMATION" and record.tier == "YELLOW"
    assert record.verification_code is None and record.mfa_issued_at is None
    assert events(db_session, "ESCALATED_TO_RED") == events(db_session, "MFA_CHALLENGE_ISSUED") == []
    assert confirm(client, action).json()["status"] == "PENDING_MFA"
    assert len(events(db_session, "ESCALATED_TO_RED")) == len(events(db_session, "MFA_CHALLENGE_ISSUED")) == 1

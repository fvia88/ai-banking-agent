"""Shared transaction/replay guarantees, including Yellow failure handling."""
from decimal import Decimal

from fastapi import HTTPException
import pytest

from app.api import approvals
from app.db.models import AccountModel, ActionApprovalModel, AuditLogModel, TransactionModel
from app.services.adapters import agent_service, policy_service


@pytest.fixture(autouse=True)
def real_policy_mock_agent(monkeypatch):
    monkeypatch.setattr(agent_service, "use_mock", True)
    monkeypatch.setattr(policy_service, "use_mock", False)


def propose(client):
    response = client.post("/api/v1/chat", json={"conversation_id": "execution_test", "message": "Transfer 500 CNY to Bob"})
    assert response.status_code == 200
    return response.json()["actions"][0]


def confirm(client, action, digest=None):
    return client.post(f'/api/v1/actions/{action["approval"]["action_id"]}/confirm', json={
        "idempotency_key": "test_request",
        "confirmation_id": "confirm", "action_digest": digest or action["approval"]["action_digest"],
    })


def assert_no_execution(db, action, status):
    db.expire_all()
    record = db.get(ActionApprovalModel, action["approval"]["action_id"])
    assert record.status == status and record.audit_id is None
    assert db.get(AccountModel, "acc_cny_001").balance == Decimal("15250.00")
    assert db.get(AccountModel, "acc_cny_001").daily_transfer_total == Decimal("0.00")
    assert db.query(TransactionModel).filter_by(category="Transfers").count() == 0
    assert db.query(AuditLogModel).filter_by(action_type="TRANSFER_EXECUTED_ATOMIC").count() == 0


def test_yellow_expected_refusal_rolls_back_partial_writes_and_fails(client, db_session, monkeypatch):
    action = propose(client)
    execute = approvals.execute_transfer
    def debit_then_refuse(db, user, record):
        execute(db, user, record)
        raise HTTPException(status_code=400, detail="Simulated executor refusal")
    monkeypatch.setattr(approvals, "execute_transfer", debit_then_refuse)
    assert confirm(client, action).status_code == 400
    assert_no_execution(db_session, action, "FAILED")
    monkeypatch.setattr(approvals, "execute_transfer", execute)
    assert confirm(client, action).status_code == 400
    assert_no_execution(db_session, action, "FAILED")


def test_yellow_unexpected_crash_rolls_back_and_can_retry_same_action(client, db_session, monkeypatch):
    action = propose(client)
    execute = approvals.execute_transfer
    def debit_then_crash(db, user, record):
        execute(db, user, record)
        raise RuntimeError("Simulated crash after financial writes")
    monkeypatch.setattr(approvals, "execute_transfer", debit_then_crash)
    with pytest.raises(RuntimeError, match="Simulated crash"):
        confirm(client, action)
    assert_no_execution(db_session, action, "PENDING_CONFIRMATION")
    monkeypatch.setattr(approvals, "execute_transfer", execute)
    assert confirm(client, action).json()["status"] == "COMPLETED"
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 1


@pytest.mark.parametrize("commit_landed", [False, True])
def test_commit_failure_retry_obeys_durable_action_state(client, db_session, monkeypatch, commit_landed):
    action = propose(client)
    original_commit = db_session.commit
    def failing_commit():
        if commit_landed:
            original_commit()
        raise RuntimeError("Simulated commit acknowledgement failure")
    monkeypatch.setattr(db_session, "commit", failing_commit)
    with pytest.raises(RuntimeError, match="commit acknowledgement"):
        confirm(client, action)
    monkeypatch.setattr(db_session, "commit", original_commit)
    db_session.expire_all()
    record = db_session.get(ActionApprovalModel, action["approval"]["action_id"])
    assert record.status == ("COMPLETED" if commit_landed else "PENDING_CONFIRMATION")
    response = confirm(client, action)
    assert response.status_code == 200 and response.json()["status"] == "COMPLETED"
    assert db_session.get(AccountModel, "acc_cny_001").balance == Decimal("14750.00")
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 1
    assert db_session.query(AuditLogModel).filter_by(action_type="TRANSFER_EXECUTED_ATOMIC").count() == 1


def test_bad_digest_cannot_change_completed_action(client, db_session):
    action = propose(client)
    first = confirm(client, action).json()
    assert first["status"] == "COMPLETED"
    assert confirm(client, action, "wrong_digest").status_code == 400
    db_session.expire_all()
    record = db_session.get(ActionApprovalModel, action["approval"]["action_id"])
    assert record.status == "COMPLETED" and record.audit_id == first["audit_id"]
    assert confirm(client, action).json()["audit_id"] == first["audit_id"]

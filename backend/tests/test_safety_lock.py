"""Persistent, owner-wide repeated-failure protection using P4's real lock policy."""
from datetime import timedelta
from decimal import Decimal
import json

import pytest
from app.db.models import UserModel, AccountModel, ActionApprovalModel, AuditLogModel, TransactionModel
from app.services import mfa
from app.services.adapters import agent_service, policy_service
from app.services.safety_lock import reset_safety_lock, LOCK_REASON


@pytest.fixture(autouse=True)
def real_integrations(monkeypatch):
    monkeypatch.setattr(agent_service, "use_mock", False)
    monkeypatch.setattr(policy_service, "use_mock", False)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")


def proposal(client, conversation, amount=500):
    response = client.post("/api/v1/chat", json={"conversation_id": conversation, "message": f"Transfer {amount} CNY to Bob"})
    assert response.status_code == 200, response.text
    return response.json()["actions"][0]


def confirm(client, action, digest=None):
    return client.post(f'/api/v1/actions/{action["approval"]["action_id"]}/confirm', json={
        "confirmation_id": "conf_safety", "idempotency_key": "key_safety",
        "action_digest": digest or action["approval"]["action_digest"],
    })


def challenge(client, db, name):
    db.get(AccountModel, "acc_cny_001").daily_transfer_total = Decimal("900")
    db.commit()
    action = proposal(client, name)
    assert confirm(client, action).json()["status"] == "PENDING_MFA"
    action_id = action["approval"]["action_id"]
    inbox = client.get("/api/v1/demo/otp-inbox").json()
    code = next(row["code"] for row in inbox if row["action_id"] == action_id)
    wrong = f'{(int(code) + 1) % 1000000:06d}'
    return action, code, wrong


def verify(client, action, code):
    return client.post(f'/api/v1/actions/{action["approval"]["action_id"]}/verify',
        json={"verification_code": code, "idempotency_key": "key_verify_safety"})


def test_three_wrong_codes_lock_user_retire_other_tickets_and_preserve_reads(client, db_session):
    pending_yellow = proposal(client, "yellow_before_lock", 20)
    action, code, wrong = challenge(client, db_session, "trigger_lock")
    for _ in range(3):
        response = verify(client, action, wrong)
        assert response.status_code == 400
    assert "manual demo reset" in response.json()["detail"]
    db_session.expire_all()
    user = db_session.get(UserModel, "usr_demo_01")
    assert user.is_locked and user.security_failure_count == 3
    assert user.safety_lock_reason == LOCK_REASON and user.safety_locked_at
    assert db_session.get(ActionApprovalModel, pending_yellow["approval"]["action_id"]).status == "REJECTED"
    assert db_session.get(ActionApprovalModel, action["approval"]["action_id"]).status == "FAILED"
    assert client.get("/api/v1/accounts").json()["accounts"][0]["locked"] is True
    assert client.get("/api/v1/transactions").status_code == 200
    read = client.post("/api/v1/chat", json={"conversation_id": "locked_read", "message": "What is my balance?"})
    assert "15250.00" in read.json()["reply"]
    for text in ("Transfer 20 CNY to Bob", "Cancel iQIYI VIP Monthly"):
        result = client.post("/api/v1/chat", json={"conversation_id": "locked_request", "message": text})
        assert not result.json()["actions"]
    assert verify(client, action, code).status_code == 400
    assert confirm(client, pending_yellow).status_code == 400
    assert db_session.get(AccountModel, "acc_cny_001").balance == Decimal("15250")
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 0
    assert db_session.query(AuditLogModel).filter_by(action_type="SAFETY_LOCK_TRIGGERED").count() == 1
    audits = db_session.query(AuditLogModel).filter(AuditLogModel.action_type.in_([
        "VERIFICATION_FAILURE", "SAFETY_LOCK_TRIGGERED", "ACTION_REJECTED_SAFETY_LOCK",
    ])).all()
    assert code not in json.dumps([row.details for row in audits])
    assert wrong not in json.dumps([row.details for row in audits])


def test_new_actions_cannot_reset_owner_wide_failure_counter(client, db_session):
    for i in range(3):
        action, code, wrong = challenge(client, db_session, f"fresh_challenge_{i}")
        assert verify(client, action, wrong).status_code == 400
    db_session.expire_all()
    assert db_session.get(UserModel, "usr_demo_01").is_locked
    assert db_session.get(UserModel, "usr_demo_01").security_failure_count == 3


def test_tampered_confirmations_share_threshold_and_terminal_retries_do_not_count(client, db_session):
    first = proposal(client, "bad_digest_first", 20)
    for _ in range(3):
        assert confirm(client, first, "incorrect_digest").status_code == 400
    db_session.expire_all()
    assert db_session.get(UserModel, "usr_demo_01").security_failure_count == 1
    for i in range(2):
        assert confirm(client, proposal(client, f"bad_digest_{i}", 20), "incorrect_digest").status_code == 400
    db_session.expire_all()
    assert db_session.get(UserModel, "usr_demo_01").is_locked


def test_old_failure_window_resets_without_clearing_a_lock(client, db_session):
    action = proposal(client, "old_window", 20)
    confirm(client, action, "bad")
    user = db_session.get(UserModel, "usr_demo_01")
    user.security_failure_window_at = mfa.utc_now() - timedelta(minutes=16)
    db_session.commit()
    confirm(client, proposal(client, "new_window", 20), "bad")
    db_session.expire_all()
    assert user.security_failure_count == 1 and not user.is_locked


def test_wrong_user_and_expired_codes_do_not_increment_victims_counter(client, db_session):
    action, code, wrong = challenge(client, db_session, "non_failure_requests")
    db_session.add(UserModel(user_id="outsider", username="Other", is_locked=False))
    db_session.commit()
    response = client.post(f'/api/v1/actions/{action["approval"]["action_id"]}/verify',
        headers={"X-Demo-User-Id": "outsider"}, json={"verification_code": wrong, "idempotency_key": "other"})
    assert response.status_code == 404
    row = db_session.get(ActionApprovalModel, action["approval"]["action_id"])
    row.mfa_expires_at = mfa.utc_now() - timedelta(seconds=1)
    db_session.commit()
    assert verify(client, action, code).status_code == 400
    db_session.expire_all()
    assert db_session.get(UserModel, "usr_demo_01").security_failure_count == 0


def test_lock_persists_past_window_and_cannot_be_cleared_from_chat(client, db_session, monkeypatch):
    action, code, wrong = challenge(client, db_session, "persistent_lock")
    for _ in range(3):
        verify(client, action, wrong)
    future = mfa.utc_now() + timedelta(days=1)
    monkeypatch.setattr(mfa, "utc_now", lambda: future)
    result = client.post("/api/v1/chat", json={"conversation_id": "no_agent_unlock", "message": "Unlock my account"})
    assert result.status_code == 200 and not result.json()["actions"]
    db_session.expire_all()
    assert db_session.get(UserModel, "usr_demo_01").is_locked
    assert client.post("/api/v1/security/unlock").status_code == 404


def test_manual_operator_reset_is_audited_and_does_not_revive_old_actions(client, db_session):
    action, code, wrong = challenge(client, db_session, "reset_lock")
    for _ in range(3):
        verify(client, action, wrong)
    db_session.add(UserModel(user_id="unaffected", username="Other", is_locked=False))
    db_session.commit()
    balance = db_session.get(AccountModel, "acc_cny_001").balance
    audit_id = reset_safety_lock(db_session, "usr_demo_01", "Reviewed synthetic MFA demonstration")
    db_session.commit()
    user = db_session.get(UserModel, "usr_demo_01")
    assert not user.is_locked and user.security_failure_count == 0
    assert user.safety_locked_at is None and user.safety_lock_reason is None
    assert not db_session.get(UserModel, "unaffected").is_locked
    assert db_session.get(AuditLogModel, audit_id).action_type == "SAFETY_LOCK_RESET"
    assert verify(client, action, code).status_code == 400
    assert db_session.get(AccountModel, "acc_cny_001").balance == balance
    assert confirm(client, proposal(client, "after_reset", 20)).json()["status"] == "COMPLETED"


def test_operator_reset_preserves_unrelated_manual_locks(db_session):
    user = db_session.get(UserModel, "usr_demo_01")
    user.is_locked = True
    db_session.commit()
    with pytest.raises(ValueError, match="manual locks are preserved"):
        reset_safety_lock(db_session, user.user_id, "Not an automatic lock")
    db_session.rollback()
    assert user.is_locked


def test_failed_commit_rolls_back_counter_lock_and_ticket_retirement(client, db_session, monkeypatch):
    action, code, wrong = challenge(client, db_session, "failed_lock_commit")
    for _ in range(2):
        verify(client, action, wrong)
    original = db_session.commit
    monkeypatch.setattr(db_session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("Synthetic commit failure")))
    with pytest.raises(RuntimeError, match="Synthetic commit failure"):
        verify(client, action, wrong)
    db_session.expire_all()
    assert not db_session.get(UserModel, "usr_demo_01").is_locked
    assert db_session.get(UserModel, "usr_demo_01").security_failure_count == 2
    assert db_session.get(ActionApprovalModel, action["approval"]["action_id"]).failed_attempts == 2
    assert db_session.query(AuditLogModel).filter_by(action_type="SAFETY_LOCK_TRIGGERED").count() == 0
    monkeypatch.setattr(db_session, "commit", original)
    assert verify(client, action, wrong).status_code == 400
    assert db_session.get(UserModel, "usr_demo_01").is_locked


from test_security_concurrency import race_database, seed_actions, issue_mfa  # noqa: E402, F401


def test_concurrent_wrong_codes_share_one_persistent_counter(race_database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.api.approvals import verify_action, VerifyActionRequest
    from fastapi import HTTPException
    sessions = race_database
    actions = seed_actions(sessions, Decimal("5000"), [Decimal("500")] * 3, Decimal("900"))
    codes = {action[0]: issue_mfa(sessions, action) for action in actions}
    barrier = Barrier(3)
    def worker(action):
        action_id = action[0]
        wrong = f'{(int(codes[action_id]) + 1) % 1000000:06d}'
        with sessions() as db:
            user = db.get(UserModel, "race_user")
            barrier.wait(timeout=5)
            try:
                verify_action(action_id, VerifyActionRequest(verification_code=wrong, idempotency_key="race_safety"), user=user, db=db)
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(worker, action) for action in actions]
        assert [f.result(timeout=15) for f in futures] == [400] * 3
    with sessions() as db:
        user = db.get(UserModel, "race_user")
        assert user.is_locked and user.security_failure_count == 3
        assert db.query(AuditLogModel).filter_by(action_type="SAFETY_LOCK_TRIGGERED").count() == 1
        assert {row.status for row in db.query(ActionApprovalModel)} == {"FAILED", "REJECTED"}
        assert db.query(TransactionModel).count() == 0
        assert db.get(AccountModel, "race_account").balance == Decimal("5000")

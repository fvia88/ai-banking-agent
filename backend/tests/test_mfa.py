# backend/tests/test_mfa.py
"""P3: OTP/MFA challenge lifecycle tests, run through the HTTP endpoints with P2's real executor."""
from datetime import timedelta
from decimal import Decimal
from contracts.enums import ActionStatus, ToolName
from app.db.models import AccountModel, ActionApprovalModel, TransactionModel, UserModel
from app.services import mfa

ALICE = {"X-Demo-User-Id": "usr_demo_01"}
START_BALANCE = Decimal("15250.00")


def _balance(db_session) -> Decimal:
    acc = db_session.query(AccountModel).filter(AccountModel.account_id == "acc_cny_001").first()
    db_session.refresh(acc)
    return acc.balance


def _transfer_count(db_session) -> int:
    return db_session.query(TransactionModel).filter(TransactionModel.category == "Transfers").count()


def _record(db_session, action_id) -> ActionApprovalModel:
    record = db_session.query(ActionApprovalModel).filter(ActionApprovalModel.action_id == action_id).first()
    db_session.refresh(record)
    return record


def _red_action_pending_mfa(client, db_session, conversation_id):
    """Propose a RED transfer (800 already sent today + 500) and confirm it into PENDING_MFA."""
    acc = db_session.query(AccountModel).filter(AccountModel.account_id == "acc_cny_001").first()
    acc.daily_transfer_total = Decimal("800.00")
    db_session.commit()

    chat_resp = client.post("/api/v1/chat", json={
        "conversation_id": conversation_id,
        "message": "Transfer 500 CNY to Bob"
    }, headers=ALICE)
    action = chat_resp.json()["actions"][0]
    action_id = action["arguments"]["action_id"]
    assert action["arguments"]["tier"] == "RED"
    assert _balance(db_session) == START_BALANCE  # no debit after chat

    confirm_resp = client.post(
        f"/api/v1/actions/{action_id}/confirm",
        json={"confirmation_id": f"conf_{conversation_id}", "action_digest": action["arguments"]["action_digest"]},
        headers=ALICE
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == ActionStatus.PENDING_MFA.value
    assert _balance(db_session) == START_BALANCE  # no debit after confirm
    return action_id, confirm_resp.json()


def _verify(client, action_id, code=mfa.SIMULATED_OTP_CODE, headers=ALICE):
    return client.post(f"/api/v1/actions/{action_id}/verify", json={"verification_code": code}, headers=headers)


def test_red_transfer_debits_once_only_after_valid_mfa(client, db_session):
    action_id, confirm_body = _red_action_pending_mfa(client, db_session, "c_mfa_happy")
    assert "simulated" in confirm_body["message"].lower()

    record = _record(db_session, action_id)
    assert record.mfa_issued_at is not None
    assert record.mfa_expires_at is not None
    assert record.mfa_consumed_at is None

    resp = _verify(client, action_id)
    assert resp.status_code == 200
    assert resp.json()["status"] == ActionStatus.COMPLETED.value
    assert _balance(db_session) == START_BALANCE - Decimal("500.00")
    assert _transfer_count(db_session) == 1

    record = _record(db_session, action_id)
    assert record.mfa_consumed_at is not None
    assert record.audit_id == resp.json()["audit_id"]


def test_duplicate_verify_does_not_debit_twice_and_returns_same_audit_id(client, db_session):
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_replay")
    first = _verify(client, action_id)
    second = _verify(client, action_id)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["audit_id"] == first.json()["audit_id"]
    assert _balance(db_session) == START_BALANCE - Decimal("500.00")
    assert _transfer_count(db_session) == 1


def test_concurrent_verify_loser_is_rejected_without_debit(client, db_session):
    """Simulates a second request that passed the code check after another request consumed the challenge."""
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_race")
    record = _record(db_session, action_id)

    assert mfa.claim_challenge(db_session, record, mfa.utc_now()) is True
    assert mfa.claim_challenge(db_session, record, mfa.utc_now()) is False
    db_session.commit()

    resp = _verify(client, action_id)
    assert resp.status_code == 409
    assert _balance(db_session) == START_BALANCE
    assert _transfer_count(db_session) == 0


def test_expired_challenge_rejects_correct_code(client, db_session):
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_expired")
    record = _record(db_session, action_id)
    record.mfa_expires_at = mfa.utc_now() - timedelta(seconds=1)
    db_session.commit()

    resp = _verify(client, action_id)
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()
    assert _record(db_session, action_id).status == ActionStatus.CANCELLED.value
    assert _balance(db_session) == START_BALANCE

    # Retrying afterwards cannot execute either
    assert _verify(client, action_id).status_code == 400
    assert _balance(db_session) == START_BALANCE


def test_expired_action_rejects_correct_code(client, db_session):
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_action_expired")
    record = _record(db_session, action_id)
    record.expires_at = mfa.utc_now() - timedelta(seconds=1)
    db_session.commit()

    resp = _verify(client, action_id)
    assert resp.status_code == 400
    assert _balance(db_session) == START_BALANCE


def test_challenge_never_outlives_action():
    now = mfa.utc_now()
    record = ActionApprovalModel(expires_at=now + timedelta(minutes=1), failed_attempts=0)
    mfa.issue_challenge(record, now)
    assert record.mfa_expires_at == now + timedelta(minutes=1)
    assert record.status == ActionStatus.PENDING_MFA.value


def test_third_wrong_code_fails_and_correct_code_cannot_recover(client, db_session):
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_lockout")
    assert "2 attempt(s) remaining" in _verify(client, action_id, "000000").json()["detail"]
    assert "1 attempt(s) remaining" in _verify(client, action_id, "111111").json()["detail"]
    third = _verify(client, action_id, "222222")
    assert third.status_code == 400
    assert "FAILED" in third.json()["detail"]

    after = _verify(client, action_id)
    assert after.status_code == 400
    assert _record(db_session, action_id).status == ActionStatus.FAILED.value
    assert _balance(db_session) == START_BALANCE


def test_wrong_user_cannot_verify(client, db_session):
    db_session.add(UserModel(user_id="usr_other_02", username="Mallory", is_locked=False))
    db_session.commit()
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_wrong_user")

    resp = _verify(client, action_id, headers={"X-Demo-User-Id": "usr_other_02"})
    assert resp.status_code == 404
    assert _record(db_session, action_id).status == ActionStatus.PENDING_MFA.value
    assert _balance(db_session) == START_BALANCE


def test_account_locked_after_confirm_blocks_execution(client, db_session):
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_locked")
    user = db_session.query(UserModel).filter(UserModel.user_id == "usr_demo_01").first()
    user.is_locked = True
    db_session.commit()

    resp = _verify(client, action_id)
    assert resp.status_code == 403
    assert _record(db_session, action_id).status == ActionStatus.REJECTED.value
    assert _balance(db_session) == START_BALANCE


def test_unknown_tool_fails_closed_at_verify(client, db_session):
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_unknown_tool")
    record = _record(db_session, action_id)
    record.tool = ToolName.GET_BALANCE.value
    db_session.commit()

    resp = _verify(client, action_id)
    assert resp.status_code == 400
    assert _record(db_session, action_id).status == ActionStatus.FAILED.value
    assert _balance(db_session) == START_BALANCE


def test_executor_failure_consumes_challenge_without_retry_debit(client, db_session):
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_insufficient")
    acc = db_session.query(AccountModel).filter(AccountModel.account_id == "acc_cny_001").first()
    acc.balance = Decimal("100.00")
    db_session.commit()

    resp = _verify(client, action_id)
    assert resp.status_code == 400
    assert "insufficient" in resp.json()["detail"].lower()
    assert _record(db_session, action_id).status == ActionStatus.FAILED.value

    acc.balance = START_BALANCE
    db_session.commit()
    assert _verify(client, action_id).status_code == 400
    assert _balance(db_session) == START_BALANCE

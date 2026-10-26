# backend/tests/test_mfa.py
"""P3: OTP/MFA challenge lifecycle tests, run through the HTTP endpoints with P2's real executor."""
import json
import threading
from datetime import timedelta
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contracts.enums import ActionStatus, Tier, ToolName
from app.api import approvals
from app.db.models import AccountModel, ActionApprovalModel, TransactionModel, UserModel
from app.db.session import Base
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
    _issued_codes[action_id] = _inbox_code(client, action_id)
    return action_id, confirm_resp.json()


_issued_codes: dict[str, str] = {}


def _inbox_code(client, action_id, headers=ALICE):
    """Read the code the way the demo user would: from their demo inbox."""
    inbox = client.get("/api/v1/demo/otp-inbox", headers=headers).json()
    return next(m["code"] for m in inbox if m["action_id"] == action_id)


def _wrong_code(action_id):
    real = _issued_codes[action_id]
    return f"{(int(real) + 1) % 10 ** mfa.OTP_CODE_DIGITS:0{mfa.OTP_CODE_DIGITS}d}"


def _verify(client, action_id, code=None, headers=ALICE):
    code = code if code is not None else _issued_codes[action_id]
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


def test_code_is_random_printed_to_console_and_not_in_confirm_response(client, db_session, capsys):
    action_id, confirm_body = _red_action_pending_mfa(client, db_session, "c_mfa_delivery")
    code = _issued_codes[action_id]

    assert len(code) == mfa.OTP_CODE_DIGITS and code.isdigit()
    assert code not in confirm_body["message"]
    assert "demo inbox" in confirm_body["message"].lower()
    assert f"action={action_id} code={code}" in capsys.readouterr().out

    codes = {mfa.generate_code() for _ in range(20)}
    assert len(codes) > 1


def test_demo_inbox_is_owner_scoped_and_drops_used_codes(client, db_session):
    db_session.add(UserModel(user_id="usr_other_02", username="Mallory", is_locked=False))
    db_session.commit()
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_inbox")

    inbox = client.get("/api/v1/demo/otp-inbox", headers=ALICE).json()
    assert [m["action_id"] for m in inbox] == [action_id]
    assert inbox[0]["attempts_remaining"] == mfa.MAX_FAILED_ATTEMPTS
    assert client.get("/api/v1/demo/otp-inbox", headers={"X-Demo-User-Id": "usr_other_02"}).json() == []

    assert _verify(client, action_id).status_code == 200
    assert client.get("/api/v1/demo/otp-inbox", headers=ALICE).json() == []


def test_demo_inbox_hides_expired_codes(client, db_session):
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_inbox_expired")
    record = _record(db_session, action_id)
    record.mfa_expires_at = mfa.utc_now() - timedelta(seconds=1)
    db_session.commit()

    assert client.get("/api/v1/demo/otp-inbox", headers=ALICE).json() == []


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
    wrong = _wrong_code(action_id)
    assert "2 attempt(s) remaining" in _verify(client, action_id, wrong).json()["detail"]
    assert "1 attempt(s) remaining" in _verify(client, action_id, wrong).json()["detail"]
    third = _verify(client, action_id, wrong)
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
    assert resp.status_code == 403
    assert _record(db_session, action_id).status == ActionStatus.REJECTED.value
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


def test_unexpected_executor_crash_leaves_no_debit_and_code_still_usable(client, db_session, monkeypatch):
    """A crash mid-execution must not strand the action: nothing commits, the code stays usable."""
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_crash")
    real_execute = approvals.execute_transfer

    def debit_then_crash(db, user, record):
        real_execute(db, user, record)  # partial writes: balance, ledger, audit
        raise RuntimeError("simulated DB/process failure after debit")

    monkeypatch.setattr(approvals, "execute_transfer", debit_then_crash)
    try:
        _verify(client, action_id)
        assert False, "expected the simulated failure to propagate"
    except RuntimeError:
        pass

    assert _balance(db_session) == START_BALANCE
    assert _transfer_count(db_session) == 0
    record = _record(db_session, action_id)
    assert record.status == ActionStatus.PENDING_MFA.value
    assert record.mfa_consumed_at is None
    assert [m["action_id"] for m in client.get("/api/v1/demo/otp-inbox", headers=ALICE).json()] == [action_id]

    # Retry with the same code after the fault clears: exactly one debit
    monkeypatch.setattr(approvals, "execute_transfer", real_execute)
    resp = _verify(client, action_id)
    assert resp.status_code == 200
    assert resp.json()["status"] == ActionStatus.COMPLETED.value
    assert _balance(db_session) == START_BALANCE - Decimal("500.00")
    assert _transfer_count(db_session) == 1


def test_executor_refusal_rolls_back_partial_writes(client, db_session, monkeypatch):
    """An executor that writes and then refuses must leave no ledger/audit residue."""
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_partial_refusal")
    real_execute = approvals.execute_transfer

    def debit_then_refuse(db, user, record):
        real_execute(db, user, record)
        raise HTTPException(status_code=400, detail="Refused after partial write")

    monkeypatch.setattr(approvals, "execute_transfer", debit_then_refuse)
    assert _verify(client, action_id).status_code == 400

    record = _record(db_session, action_id)
    assert record.status == ActionStatus.FAILED.value
    assert record.mfa_consumed_at is not None
    assert _balance(db_session) == START_BALANCE
    assert _transfer_count(db_session) == 0


def test_legacy_stranded_challenge_is_retired_not_stuck(client, db_session):
    """Rows left by the old two-commit flow (consumed, never completed) resolve to FAILED with no debit."""
    action_id, _ = _red_action_pending_mfa(client, db_session, "c_mfa_stranded")
    record = _record(db_session, action_id)
    record.mfa_consumed_at = mfa.utc_now()
    db_session.commit()

    resp = _verify(client, action_id)
    assert resp.status_code == 409
    assert "no money was moved" in resp.json()["detail"].lower()
    assert _record(db_session, action_id).status == ActionStatus.FAILED.value
    assert _balance(db_session) == START_BALANCE

    # Further retries get a definite terminal answer instead of "being processed"
    again = _verify(client, action_id)
    assert again.status_code == 400
    assert "FAILED" in again.json()["detail"]


def test_truly_concurrent_verifies_debit_once(tmp_path, monkeypatch):
    """
    Two threads, each with its own DB session on a shared file-based SQLite DB,
    both load the pending action before entering the database execution guard.
    Synchronize before locking; pausing inside OTP checking would deadlock a
    correctly serialized implementation.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'race.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(bind=engine)
    SessionFactory = sessionmaker(bind=engine)

    setup = SessionFactory()
    setup.add(UserModel(user_id="usr_demo_01", username="Alice Wang", is_locked=False))
    setup.add(AccountModel(
        account_id="acc_cny_001", user_id="usr_demo_01", account_number="6222021001009988",
        currency="CNY", balance=START_BALANCE, daily_transfer_total=Decimal("800.00"),
    ))
    now = mfa.utc_now()
    record = ActionApprovalModel(
        action_id="act_race", user_id="usr_demo_01", tool=ToolName.REQUEST_TRANSFER.value,
        tier=Tier.RED.value, action_digest="0" * 64, expires_at=now + timedelta(minutes=10),
        payload_json=json.dumps({"source_account_id": "acc_cny_001", "recipient_id": "rcp_bob", "amount": "500.00"}),
    )
    mfa.issue_challenge(record, now)
    issued_code = record.verification_code
    from app.services.actions import compute_action_digest
    record.action_digest = compute_action_digest(record.tool, json.loads(record.payload_json))
    setup.add(record)
    setup.commit()
    setup.close()

    barrier = threading.Barrier(2, timeout=5)
    from app.services import action_execution
    original_claim = action_execution.claim_pending_action

    def wait_then_claim(*args, **kwargs):
        barrier.wait()  # both requests loaded the old pending snapshot
        return original_claim(*args, **kwargs)

    monkeypatch.setattr(action_execution, "claim_pending_action", wait_then_claim)

    outcomes = []

    def verify_in_thread():
        session = SessionFactory()
        try:
            user = session.query(UserModel).filter(UserModel.user_id == "usr_demo_01").first()
            result = approvals.verify_action(
                "act_race", approvals.VerifyActionRequest(verification_code=issued_code),
                user=user, db=session,
            )
            outcomes.append(("ok", result.status))
        except HTTPException as exc:
            outcomes.append(("http", exc.status_code))
        except Exception as exc:  # surface DB lock errors etc. as test failures
            outcomes.append(("error", repr(exc)))
        finally:
            session.close()

    threads = [threading.Thread(target=verify_in_thread) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not any(t.is_alive() for t in threads), "Verification worker did not terminate"
    assert sorted(outcomes) == [("http", 409), ("ok", ActionStatus.COMPLETED)], outcomes

    check = SessionFactory()
    acc = check.query(AccountModel).filter(AccountModel.account_id == "acc_cny_001").first()
    assert acc.balance == START_BALANCE - Decimal("500.00")
    assert check.query(TransactionModel).filter(TransactionModel.category == "Transfers").count() == 1
    assert check.query(ActionApprovalModel).filter(ActionApprovalModel.action_id == "act_race").first().status \
        == ActionStatus.COMPLETED.value
    check.close()
    engine.dispose()

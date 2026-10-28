"""Revoke a pending ticket without executing or reversing its banking operation."""
from datetime import timedelta
from decimal import Decimal
import json

from fastapi import HTTPException
import pytest

from app.api.approvals import cancel_action, confirm_action, verify_action
from app.api.schemas import CancelApprovalRequest
from app.db.models import (AccountModel, ActionApprovalModel, AuditLogModel,
    ConversationModel, SubscriptionModel, TransactionModel, UserModel)
from app.services.adapters import agent_service, policy_service
from app.services import mfa
from contracts.api_schemas import ConfirmActionRequest, VerifyActionRequest


@pytest.fixture(autouse=True)
def real_modules(monkeypatch):
    monkeypatch.setattr(agent_service, "use_mock", False)
    monkeypatch.setattr(policy_service, "use_mock", False)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")


def propose(client, message="Transfer 20 CNY to Bob", conversation="cancel_approval"):
    response = client.post("/api/v1/chat", json={"conversation_id": conversation, "message": message})
    assert response.status_code == 200, response.text
    return response.json()["actions"][0]


def post(client, action, operation="cancel", **fields):
    approval = action["approval"]
    payload = {"idempotency_key": f"key_{operation}", **fields}
    if operation in ("cancel", "confirm"):
        payload.setdefault("action_digest", approval["action_digest"])
    if operation == "confirm":
        payload.setdefault("confirmation_id", "conf_cancel_test")
    return client.post(f'/api/v1/actions/{approval["action_id"]}/{operation}', json=payload)


def row(db, action):
    db.expire_all()
    return db.get(ActionApprovalModel, action["approval"]["action_id"])


def test_cancel_yellow_replays_same_audit_and_never_debits(client, db_session):
    action = propose(client)
    before = row(db_session, action)
    payload, digest = before.payload_json, before.action_digest
    cancelled = post(client, action)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"
    assert row(db_session, action).status == "CANCELLED"
    assert (row(db_session, action).payload_json, row(db_session, action).action_digest) == (payload, digest)
    replay = post(client, action, idempotency_key="another_request_key")
    assert replay.status_code == 200
    assert replay.json()["audit_id"] == cancelled.json()["audit_id"]
    assert db_session.query(AuditLogModel).filter_by(action_type="APPROVAL_CANCELLED_BY_USER").count() == 1
    assert post(client, action, "confirm").status_code == 400
    assert post(client, action, "verify", verification_code="123456").status_code == 400
    account = db_session.get(AccountModel, "acc_cny_001")
    assert account.balance == Decimal("15250") and account.daily_transfer_total == Decimal("0")
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 0
    metadata = client.get(f'/api/v1/actions/{action["approval"]["action_id"]}').json()
    assert metadata == {**action["approval"], "status": "CANCELLED"}


def test_cancel_mfa_revokes_correct_code_and_removes_demo_inbox_entry(client, db_session):
    db_session.get(AccountModel, "acc_cny_001").daily_transfer_total = Decimal("990")
    db_session.commit()
    action = propose(client)
    assert post(client, action, "confirm").json()["status"] == "PENDING_MFA"
    code = client.get("/api/v1/demo/otp-inbox").json()[0]["code"]
    cancelled = post(client, action)
    assert cancelled.status_code == 200
    record = row(db_session, action)
    assert record.status == "CANCELLED" and record.verification_code is None
    assert record.mfa_consumed_at is not None
    assert client.get("/api/v1/demo/otp-inbox").json() == []
    assert post(client, action, "verify", verification_code=code).status_code == 400
    audit = db_session.get(AuditLogModel, cancelled.json()["audit_id"])
    assert json.loads(audit.details)["previous_status"] == "PENDING_MFA"
    assert code not in audit.details
    assert db_session.get(UserModel, "usr_demo_01").security_failure_count == 0
    assert db_session.get(AccountModel, "acc_cny_001").balance == Decimal("15250")


def test_withdraw_subscription_approval_does_not_cancel_subscription(client, db_session):
    action = propose(client, "Cancel iQIYI VIP Monthly")
    assert post(client, action).json()["status"] == "CANCELLED"
    assert db_session.get(SubscriptionModel, "sub_iQIYI_01").status == "active"
    assert db_session.get(AccountModel, "acc_cny_001").balance == Decimal("15250")


def test_completed_operation_cannot_be_cancelled_or_reversed(client, db_session):
    action = propose(client)
    executed = post(client, action, "confirm")
    assert executed.json()["status"] == "COMPLETED"
    response = post(client, action)
    assert response.status_code == 409 and "cannot be reversed" in response.json()["detail"]
    record = row(db_session, action)
    assert record.status == "COMPLETED" and record.audit_id == executed.json()["audit_id"]
    assert db_session.get(AccountModel, "acc_cny_001").balance == Decimal("15230")
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 1
    assert db_session.query(AuditLogModel).filter_by(action_type="APPROVAL_CANCELLED_BY_USER").count() == 0


@pytest.mark.parametrize("status", ["FAILED", "REJECTED", "CANCELLED"])
def test_other_terminal_status_is_preserved(client, db_session, status):
    action = propose(client)
    record = row(db_session, action)
    record.status = status
    db_session.commit()
    assert post(client, action).status_code == 409
    assert row(db_session, action).status == status


def test_wrong_digest_does_not_revoke_ticket_or_change_security_counter(client, db_session):
    action = propose(client)
    assert post(client, action, action_digest="wrong").status_code == 400
    assert row(db_session, action).status == "PENDING_CONFIRMATION"
    assert db_session.get(UserModel, "usr_demo_01").security_failure_count == 0
    assert post(client, action, "confirm").json()["status"] == "COMPLETED"


@pytest.mark.parametrize("payload", [
    {}, {"action_digest": "digest"}, {"action_digest": "digest", "idempotency_key": ""},
    {"action_digest": "digest", "idempotency_key": "k", "user_id": "other"},
    {"action_digest": "digest", "idempotency_key": "k", "status": "CANCELLED"},
])
def test_cancel_body_is_strict(client, db_session, payload):
    action = propose(client)
    response = client.post(f'/api/v1/actions/{action["approval"]["action_id"]}/cancel', json=payload)
    assert response.status_code == 422
    assert row(db_session, action).status == "PENDING_CONFIRMATION"


def test_wrong_owner_and_unknown_ids_do_not_reveal_or_cancel_ticket(client, db_session):
    action = propose(client)
    db_session.add(UserModel(user_id="other", username="Other", is_locked=False))
    db_session.commit()
    path = f'/api/v1/actions/{action["approval"]["action_id"]}'
    assert client.get(path, headers={"X-Demo-User-Id": "other"}).status_code == 404
    assert client.post(path + "/cancel", headers={"X-Demo-User-Id": "other"},
        json={"action_digest": action["approval"]["action_digest"], "idempotency_key": "other"}).status_code == 404
    assert client.get("/api/v1/actions/missing").status_code == 404
    assert client.post("/api/v1/actions/missing/cancel", json={"action_digest": "unknown", "idempotency_key": "k"}).status_code == 404
    assert row(db_session, action).status == "PENDING_CONFIRMATION"


def test_locked_or_expired_pending_ticket_can_still_be_revoked(client, db_session):
    action = propose(client)
    record = row(db_session, action)
    record.expires_at = mfa.utc_now() - timedelta(minutes=1)
    db_session.get(UserModel, "usr_demo_01").is_locked = True
    db_session.commit()
    assert post(client, action).status_code == 200
    assert row(db_session, action).status == "CANCELLED"
    assert db_session.get(UserModel, "usr_demo_01").is_locked


def test_cancel_commit_failure_rolls_back_status_audit_and_mfa_retirement(client, db_session, monkeypatch):
    db_session.get(AccountModel, "acc_cny_001").daily_transfer_total = Decimal("990")
    db_session.commit()
    action = propose(client)
    post(client, action, "confirm")
    original_code = row(db_session, action).verification_code
    original_commit = db_session.commit
    def fail_commit():
        raise RuntimeError("Synthetic cancellation commit failure")
    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="cancellation commit failure"):
        post(client, action)
    record = row(db_session, action)
    assert record.status == "PENDING_MFA" and record.verification_code == original_code
    assert record.mfa_consumed_at is None and record.audit_id is None
    assert db_session.query(AuditLogModel).filter_by(action_type="APPROVAL_CANCELLED_BY_USER").count() == 0
    monkeypatch.setattr(db_session, "commit", original_commit)
    assert post(client, action).status_code == 200


def test_cancelled_plan_stops_before_transfer_and_preserves_matching_audit(client, db_session):
    action = propose(client, "Cancel iQIYI VIP Monthly then transfer 45 CNY to Bob")
    cancelled = post(client, action)
    response = post(client, action, "continue")
    assert response.status_code == 200, response.text
    assert response.json()["execution"]["status"] == "CANCELLED"
    assert response.json()["execution"]["audit_id"] == cancelled.json()["audit_id"]
    assert response.json()["chat"]["actions"] == []
    assert "Remaining plan steps stopped" in response.json()["chat"]["reply"]
    state = json.loads(db_session.get(ConversationModel, ("usr_demo_01", "cancel_approval")).state_json)
    assert state["pending_plan"] is None and not state["pending_tool_requests"]
    assert db_session.get(SubscriptionModel, "sub_iQIYI_01").status == "active"


def test_cancel_transfer_step_does_not_reverse_already_completed_subscription(client, db_session):
    action = propose(client, "Cancel iQIYI VIP Monthly then transfer 45 CNY to Bob")
    post(client, action, "confirm")
    next_turn = post(client, action, "continue")
    transfer = next_turn.json()["chat"]["actions"][0]
    assert post(client, transfer).status_code == 200
    finished = post(client, transfer, "continue")
    assert finished.status_code == 200 and not finished.json()["chat"]["actions"]
    assert db_session.get(SubscriptionModel, "sub_iQIYI_01").status == "cancelled"
    assert db_session.get(AccountModel, "acc_cny_001").balance == Decimal("15250")


def test_missed_cancellation_notification_recovers_on_next_chat(client, db_session):
    action = propose(client, "Cancel iQIYI VIP Monthly then transfer 45 CNY to Bob")
    assert post(client, action).status_code == 200
    response = client.post("/api/v1/chat", json={"conversation_id": "cancel_approval", "message": "What is my balance?"})
    assert response.status_code == 200
    assert "request has been cancelled" in response.json()["reply"] and "15250.00" in response.json()["reply"]
    assert not response.json()["actions"]
    assert db_session.query(ActionApprovalModel).count() == 1


def test_agent_outage_cannot_undo_cancellation(client, db_session, monkeypatch):
    action = propose(client)
    post(client, action)
    actual = agent_service.process_turn
    def outage(*args, **kwargs):
        raise RuntimeError("Synthetic agent outage")
    monkeypatch.setattr(agent_service, "process_turn", outage)
    with pytest.raises(RuntimeError, match="agent outage"):
        post(client, action, "continue")
    assert row(db_session, action).status == "CANCELLED"
    assert client.get(f'/api/v1/actions/{action["approval"]["action_id"]}').json()["status"] == "CANCELLED"
    monkeypatch.setattr(agent_service, "process_turn", actual)
    assert post(client, action, "continue").json()["execution"]["status"] == "CANCELLED"


from test_security_concurrency import race_database, seed_actions, issue_mfa  # noqa: E402, F401


@pytest.mark.parametrize("winner,competitor", [
    ("cancel", "confirm"), ("confirm", "cancel"),
    ("cancel", "verify"), ("verify", "cancel"), ("cancel", "cancel"),
])
def test_cancellation_serializes_with_execution_and_duplicate_cancellation(race_database, monkeypatch, winner, competitor):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlalchemy import event
    from app.services import action_execution
    sessions = race_database
    red = "verify" in (winner, competitor)
    starting_daily = Decimal("900") if red else Decimal("0")
    action_id, digest = seed_actions(sessions, Decimal("5000"), [Decimal("500")], starting_daily)[0]
    code = issue_mfa(sessions, (action_id, digest)) if red else None
    winner_ready, loser_claiming = Event(), Event()
    actual_claim = action_execution.claim_pending_action
    def observed_claim(db, *args):
        if db.info.get("cancel_race_role") == "loser":
            loser_claiming.set()
        return actual_claim(db, *args)
    monkeypatch.setattr(action_execution, "claim_pending_action", observed_claim)
    def before_flush(db, *_):
        if db.info.get("cancel_race_role") != "winner" or db.info.get("rendezvous_done"):
            return
        if not any(isinstance(item, ActionApprovalModel) and item.status in ("CANCELLED", "COMPLETED") for item in db.dirty):
            return
        db.info["rendezvous_done"] = True
        winner_ready.set()
        # The competing request reads the original pending row and attempts the
        # real claim before the winner is allowed to commit. Both orders are
        # exercised deterministically, rather than hoping for a scheduler race.
        assert loser_claiming.wait(timeout=5)
    def worker(operation, role):
        with sessions() as db:
            db.info["cancel_race_role"] = role
            user = db.get(UserModel, "race_user")
            if role == "loser":
                assert winner_ready.wait(timeout=5)
            try:
                if operation == "cancel":
                    result = cancel_action(action_id, CancelApprovalRequest(action_digest=digest, idempotency_key="cancel_race"), user=user, db=db)
                elif operation == "confirm":
                    result = confirm_action(action_id, ConfirmActionRequest(confirmation_id="conf_race", action_digest=digest, idempotency_key="confirm_race"), user=user, db=db)
                else:
                    result = verify_action(action_id, VerifyActionRequest(verification_code=code, idempotency_key="verify_race"), user=user, db=db)
                return (200, result.status.value)
            except HTTPException as exc:
                return (exc.status_code, None)
    event.listen(sessions, "before_flush", before_flush)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, winner, "winner"), pool.submit(worker, competitor, "loser")]
            outcomes = [future.result(timeout=15) for future in futures]
    finally:
        event.remove(sessions, "before_flush", before_flush)
    assert outcomes == [(200, "CANCELLED" if winner == "cancel" else "COMPLETED"), (409, None)]
    with sessions() as db:
        record = db.get(ActionApprovalModel, action_id)
        cancelled = record.status == "CANCELLED"
        assert cancelled or record.status == "COMPLETED"
        cancellation_count = db.query(AuditLogModel).filter_by(action_type="APPROVAL_CANCELLED_BY_USER").count()
        execution_count = db.query(AuditLogModel).filter_by(action_type="TRANSFER_EXECUTED_ATOMIC").count()
        assert (cancellation_count, execution_count) == ((1, 0) if cancelled else (0, 1))
        assert db.query(TransactionModel).count() == (0 if cancelled else 1)
        assert db.get(AccountModel, "race_account").balance == Decimal("5000" if cancelled else "4500")
        assert db.get(AccountModel, "race_account").daily_transfer_total == starting_daily + (0 if cancelled else Decimal("500"))
        if winner == "cancel" and competitor == "cancel":
            assert cancelled
            replay = cancel_action(action_id, CancelApprovalRequest(action_digest=digest, idempotency_key="retry_cancel"),
                                   user=db.get(UserModel, "race_user"), db=db)
            assert replay.audit_id == record.audit_id

"""Trusted approval results re-enter P1 without executing dependent proposals."""
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from app.db.models import (AccountModel, ActionApprovalModel, AuditLogModel,
    ConversationModel, TransactionModel, UserModel)
from app.services.adapters import agent_service
from app.services.session_store import clear_conversation_state, conversation_key
from app.services import mfa

ALICE = {"X-Demo-User-Id": "usr_demo_01"}


@pytest.fixture(autouse=True)
def real_p1(monkeypatch):
    monkeypatch.setattr(agent_service, "use_mock", False)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")


def propose(client, message="Transfer 20 CNY to Bob", conversation="continuation"):
    response = client.post("/api/v1/chat", headers=ALICE, json={
        "conversation_id": conversation, "message": message,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["actions"]) == 1, body
    return body["actions"][0]


def confirm(client, action):
    return client.post(f'/api/v1/actions/{action["approval"]["action_id"]}/confirm',
        headers=ALICE, json={"idempotency_key": "test_request", "confirmation_id": "conf_test",
                             "action_digest": action["approval"]["action_digest"]})


def deliver(client, action, headers=ALICE):
    return client.post(f'/api/v1/actions/{action["approval"]["action_id"]}/continue', headers=headers)


def saved(db, conversation="continuation"):
    db.expire_all()
    return json.loads(db.get(ConversationModel, ("usr_demo_01", conversation)).state_json)


def test_completion_consumes_original_and_replay_is_cached(client, db_session, monkeypatch):
    action = propose(client)
    assert "action_id" not in saved(db_session)["pending_tool_requests"][0]["proposal"]["arguments"]
    assert confirm(client, action).json()["status"] == "COMPLETED"
    result = deliver(client, action)
    assert result.status_code == 200, result.text
    assert result.json()["execution"]["status"] == "COMPLETED"
    assert "is complete" in result.json()["chat"]["reply"]
    assert not saved(db_session)["pending_tool_requests"]
    monkeypatch.setattr(agent_service, "process_turn", lambda *a, **kw: pytest.fail("replay called P1"))
    assert deliver(client, action).json() == result.json()
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 1


def test_mfa_waits_then_completes_without_forwarding_secret(client, db_session, monkeypatch):
    account = db_session.get(AccountModel, "acc_cny_001")
    account.daily_transfer_total = Decimal("900")
    db_session.commit()
    action = propose(client, "Transfer 500 CNY to Bob")
    assert confirm(client, action).json()["status"] == "PENDING_MFA"
    code = client.get("/api/v1/demo/otp-inbox", headers=ALICE).json()[0]["code"]
    actual = agent_service.process_turn
    received = []
    def capture(*args, **kwargs):
        received.append(kwargs["tool_results"])
        return actual(*args, **kwargs)
    monkeypatch.setattr(agent_service, "process_turn", capture)
    pending = deliver(client, action)
    assert pending.status_code == 200, pending.text
    assert pending.json()['execution']['status'] == 'PENDING_MFA'
    assert "verify your identity" in pending.json()["chat"]["reply"]
    assert len(saved(db_session)["pending_tool_requests"]) == 1
    action_id = action["approval"]["action_id"]
    verified = client.post(f"/api/v1/actions/{action_id}/verify", headers=ALICE,
                          json={"idempotency_key": "test_request", "verification_code": code})
    assert verified.json()["status"] == "COMPLETED"
    assert deliver(client, action).json()["execution"]["status"] == "COMPLETED"
    assert not saved(db_session)["pending_tool_requests"]
    assert code not in json.dumps(received)
    assert "verification_code" not in json.dumps(received)


@pytest.mark.parametrize("failure", ["locked", "expired", "insufficient"])
def test_terminal_failure_is_consumed_honestly(client, db_session, failure):
    action = propose(client)
    if failure == "locked":
        db_session.get(UserModel, "usr_demo_01").is_locked = True
    elif failure == "expired":
        db_session.get(ActionApprovalModel, action["approval"]["action_id"]).expires_at = mfa.utc_now() - timedelta(seconds=1)
    else:
        db_session.get(AccountModel, "acc_cny_001").balance = Decimal("1")
    db_session.commit()
    assert confirm(client, action).status_code >= 400
    update = deliver(client, action)
    assert update.status_code == 200, update.text
    assert update.json()["execution"]["status"] in {"REJECTED", "FAILED", "CANCELLED"}
    expected = {'REJECTED': "wasn't approved", 'FAILED': "couldn't confirm", 'CANCELLED': 'request has been cancelled'}
    assert expected[update.json()['execution']['status']] in update.json()["chat"]["reply"]
    assert 'is complete.' not in update.json()['chat']['reply']
    assert not saved(db_session)["pending_tool_requests"]
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 0


def test_wrong_owner_cannot_continue(client, db_session):
    action = propose(client)
    db_session.add(UserModel(user_id="other", username="Other", is_locked=False))
    db_session.commit()
    assert deliver(client, action, {"X-Demo-User-Id": "other"}).status_code == 404
    assert len(saved(db_session)["pending_tool_requests"]) == 1


def test_restart_retains_original_conversation(client, db_session):
    action = propose(client)
    clear_conversation_state(conversation_key("usr_demo_01", "continuation"))
    confirm(client, action)
    assert deliver(client, action).status_code == 200
    assert not saved(db_session)["pending_tool_requests"]


def test_agent_failure_cannot_roll_back_transfer_and_retry_recovers(client, db_session, monkeypatch):
    action = propose(client)
    confirm(client, action)
    actual = agent_service.process_turn
    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic provider outage")
    monkeypatch.setattr(agent_service, "process_turn", fail)
    with pytest.raises(RuntimeError, match="Synthetic provider outage"):
        deliver(client, action)
    assert db_session.get(ActionApprovalModel, action["approval"]["action_id"]).status == "COMPLETED"
    assert len(saved(db_session)["pending_tool_requests"]) == 1
    monkeypatch.setattr(agent_service, "process_turn", actual)
    assert deliver(client, action).status_code == 200
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 1


def test_plan_continues_to_new_approval_without_moving_money(client, db_session):
    action = propose(client, "Cancel iQIYI VIP Monthly then transfer 45 CNY to Bob")
    assert action["tool"] == "request_subscription_cancel"
    assert confirm(client, action).json()["status"] == "COMPLETED"
    result = deliver(client, action)
    assert result.status_code == 200, result.text
    followup = result.json()["chat"]["actions"][0]
    assert followup["tool"] == "request_transfer"
    assert followup["approval"]["action_id"] != action["approval"]["action_id"]
    assert db_session.get(AccountModel, "acc_cny_001").balance == Decimal("15250")
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 0
    assert deliver(client, action).json() == result.json()
    assert db_session.query(ActionApprovalModel).count() == 2
    assert confirm(client, followup).json()["status"] == "COMPLETED"
    assert "Plan completed" in deliver(client, followup).json()["chat"]["reply"]


def test_paused_plan_does_not_issue_next_action(client, db_session):
    action = propose(client, "Cancel iQIYI VIP Monthly then transfer 45 CNY to Bob")
    client.post("/api/v1/chat", headers=ALICE, json={"conversation_id": "continuation", "message": "pause plan"})
    confirm(client, action)
    result = deliver(client, action)
    assert result.status_code == 200, result.text
    assert result.json()["chat"]["actions"] == []
    assert "paused" in result.json()["chat"]["reply"]


def test_rejected_dependent_proposal_is_reported_and_does_not_stick(client, db_session, monkeypatch):
    action = propose(client, "Cancel iQIYI VIP Monthly then transfer 45 CNY to Bob")
    assert confirm(client, action).json()["status"] == "COMPLETED"
    actual = agent_service.process_turn
    def lock_after_proposal(*args, **kwargs):
        turn = actual(*args, **kwargs)
        if turn.result.proposals:
            # The next proposal must still pass real P4 policy, even after P1
            # saw an unlocked account. Simulate a lock at that boundary.
            db_session.get(UserModel, "usr_demo_01").is_locked = True
        return turn
    monkeypatch.setattr(agent_service, "process_turn", lock_after_proposal)
    response = deliver(client, action)
    assert response.status_code == 200, response.text
    assert response.json()["execution"]["status"] == "COMPLETED"
    assert response.json()["chat"]["status"] == "REJECTED"
    assert "Action blocked" in response.json()["chat"]["reply"]
    assert not saved(db_session)["pending_tool_requests"]
    assert saved(db_session)["pending_plan"] is None
    assert db_session.query(ActionApprovalModel).count() == 1


def test_continuation_commit_failure_rolls_back_next_ticket_and_retry_recovers(client, db_session, monkeypatch):
    action = propose(client, "Cancel iQIYI VIP Monthly then transfer 45 CNY to Bob")
    confirm(client, action)
    actual_commit = db_session.commit
    def broken_commit():
        raise RuntimeError("Synthetic continuation commit failure")
    monkeypatch.setattr(db_session, "commit", broken_commit)
    with pytest.raises(RuntimeError, match="continuation commit failure"):
        deliver(client, action)
    assert db_session.query(ActionApprovalModel).count() == 1
    assert len(saved(db_session)["pending_tool_requests"]) == 1
    assert db_session.get(ActionApprovalModel, action["approval"]["action_id"]).status == "COMPLETED"
    monkeypatch.setattr(db_session, "commit", actual_commit)
    assert deliver(client, action).status_code == 200
    assert db_session.query(ActionApprovalModel).count() == 2


def test_corrupted_link_or_digest_never_reaches_agent(client, db_session, monkeypatch):
    action = propose(client)
    confirm(client, action)
    record = db_session.get(ActionApprovalModel, action["approval"]["action_id"])
    record.action_digest = "corrupt"
    db_session.commit()
    monkeypatch.setattr(agent_service, "process_turn", lambda *a, **kw: pytest.fail("unverified result reached P1"))
    assert deliver(client, action).status_code == 409


def test_no_conversation_cross_talk(client, db_session):
    first = propose(client, conversation="first")
    propose(client, conversation="second")
    confirm(client, first)
    result = deliver(client, first)
    assert result.json()["chat"]["conversation_id"] == "first"
    assert not saved(db_session, "first")["pending_tool_requests"]
    assert len(saved(db_session, "second")["pending_tool_requests"]) == 1


def test_missed_callback_recovers_on_next_chat(client, db_session):
    action = propose(client)
    confirm(client, action)
    result = client.post("/api/v1/chat", headers=ALICE, json={
        "conversation_id": "continuation", "message": "What is my balance?",
    })
    assert result.status_code == 200, result.text
    assert "is complete" in result.json()["reply"]
    assert "15230.00" in result.json()["reply"]
    assert not saved(db_session)["pending_tool_requests"]


def test_recovery_preserves_dependent_approval_instead_of_processing_new_message(client, db_session):
    action = propose(client, "Cancel iQIYI VIP Monthly then transfer 45 CNY to Bob")
    confirm(client, action)
    result = client.post("/api/v1/chat", headers=ALICE, json={
        "conversation_id": "continuation", "message": "What is my balance?",
    })
    assert result.status_code == 200, result.text
    assert len(result.json()["actions"]) == 1
    assert result.json()["actions"][0]["tool"] == "request_transfer"
    assert "latest message has not been processed" in result.json()["reply"]
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 0


# Reuse the existing disposable SQLite/PostgreSQL fixture, never the app DB.
from test_security_concurrency import race_database  # noqa: E402, F401


def test_concurrent_continuations_across_worker_locks_generate_one_next_ticket(race_database, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import nullcontext
    from threading import Barrier
    from app.api.chat import handle_chat
    from app.api import continuation
    from app.api.approvals import confirm_action, ConfirmActionRequest
    from app.db.subscription_seed import seed_subscriptions
    from contracts.models import ChatInput

    sessions = race_database
    with sessions() as db:
        db.add(UserModel(user_id="usr_demo_01", username="Alice", is_locked=False))
        db.add(AccountModel(account_id="acc_cny_001", user_id="usr_demo_01", account_number="synthetic",
                            balance=Decimal("15250"), daily_transfer_total=Decimal("0")))
        db.commit()
        seed_subscriptions(db, [])
        db.commit()
        user = db.get(UserModel, "usr_demo_01")
        result = handle_chat(ChatInput(conversation_id="race_continuation",
            message="Cancel iQIYI VIP Monthly then transfer 45 CNY to Bob"), user=user, db=db)
        args = result.actions[0].approval.model_dump(mode="json")
        confirm_action(args["action_id"], ConfirmActionRequest(
            confirmation_id="conf_race", action_digest=args["action_digest"], idempotency_key="test_request"), user=user, db=db)
    # Separate processes do not share Python locks. Exercise only the DB guard.
    monkeypatch.setattr(continuation, "conversation_session", lambda key: nullcontext())
    actual = agent_service.process_turn
    calls = []
    def capture(*a, **kw):
        calls.append(kw["tool_results"])
        return actual(*a, **kw)
    monkeypatch.setattr(agent_service, "process_turn", capture)
    barrier = Barrier(2)
    def worker():
        with sessions() as db:
            user = db.get(UserModel, "usr_demo_01")
            barrier.wait(timeout=5)
            return continuation.continue_action(args["action_id"], user=user, db=db).model_dump(mode="json")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert results[0] == results[1]
    assert len(calls) == 1
    with sessions() as db:
        assert db.query(ActionApprovalModel).count() == 2
        assert db.query(TransactionModel).count() == 0
        assert db.get(AccountModel, "acc_cny_001").balance == Decimal("15250")

"""HTTP evidence that P2 invokes P4 with canonical proposals and current context."""
import json
from decimal import Decimal

import pytest

from contracts.enums import Tier, ToolName
from contracts.models import ActionProposal, AgentResult, PolicyDecision
from app.db.models import AccountModel, ActionApprovalModel, UserModel
from app.services.adapters import SecurityAdapterService, agent_service, policy_service


@pytest.fixture(autouse=True)
def real_policy(monkeypatch):
    monkeypatch.setattr(policy_service, "use_mock", False)
    monkeypatch.setattr(agent_service, "use_mock", True)


def chat(client, message="Transfer 500 to Bob"):
    return client.post("/api/v1/chat", json={"conversation_id": "security_test", "message": message})


def proposed(client):
    response = chat(client)
    assert response.status_code == 200
    return response.json()["actions"][0]


def confirm(client, action):
    return client.post(f'/api/v1/actions/{action["approval"]["action_id"]}/confirm', json={
        "confirmation_id": "confirm_test", "action_digest": action["approval"]["action_digest"],
        "idempotency_key": "security_test",
    })


def account(db):
    return db.get(AccountModel, "acc_cny_001")


def spy_on_p4(monkeypatch):
    from security import policy
    original = policy.evaluate_action
    calls = []
    def evaluate(proposal, context):
        from contracts.tool_schemas import validate_tool_arguments
        validate_tool_arguments(proposal.tool, proposal.arguments)
        calls.append((proposal.model_copy(deep=True), context.model_copy(deep=True)))
        return original(proposal, context)
    monkeypatch.setattr(policy, "evaluate_action", evaluate)
    return calls


def test_mode_selection_is_explicit(monkeypatch):
    monkeypatch.delenv("USE_MOCK_SECURITY", raising=False)
    assert SecurityAdapterService().use_mock is False
    monkeypatch.setenv("USE_MOCK_SECURITY", "true")
    assert SecurityAdapterService().use_mock is True
    assert SecurityAdapterService(use_mock=False).use_mock is False


@pytest.mark.parametrize("daily, expected", [("500.00", "YELLOW"), ("500.01", "RED"), ("800.00", "RED")])
def test_http_proposals_call_actual_policy_at_threshold(client, db_session, monkeypatch, daily, expected):
    calls = spy_on_p4(monkeypatch)
    account(db_session).daily_transfer_total = Decimal(daily)
    db_session.commit()
    action = proposed(client)
    assert action["approval"]["tier"] == expected
    assert len(calls) == 1
    proposal, context = calls[0]
    assert context.user_id == "usr_demo_01"
    assert context.daily_transfer_total == Decimal(daily)
    assert proposal.arguments["source_account_id"] == "acc_cny_001"
    assert "action_id" not in proposal.arguments
    assert account(db_session).balance == Decimal("15250.00")


def test_confirm_rechecks_real_policy_and_replays_without_new_debit(client, db_session, monkeypatch):
    calls = spy_on_p4(monkeypatch)
    action = proposed(client)
    first = confirm(client, action)
    assert first.status_code == 200 and first.json()["status"] == "COMPLETED"
    assert len(calls) == 2
    assert confirm(client, action).json()["audit_id"] == first.json()["audit_id"]
    assert account(db_session).balance == Decimal("14750.00")


def test_two_pending_yellow_actions_escalate_after_first_executes(client, db_session, monkeypatch):
    calls = spy_on_p4(monkeypatch)
    account(db_session).daily_transfer_total = Decimal("100.00")
    db_session.commit()
    first, second = proposed(client), proposed(client)
    assert first["approval"]["tier"] == second["approval"]["tier"] == "YELLOW"
    assert confirm(client, first).json()["status"] == "COMPLETED"
    response = confirm(client, second)
    assert response.status_code == 200 and response.json()["status"] == "PENDING_MFA"
    assert calls[-1][1].daily_transfer_total == Decimal("600.00")
    assert account(db_session).balance == Decimal("14750.00")
    action_id = second["approval"]["action_id"]
    code = next(m["code"] for m in client.get("/api/v1/demo/otp-inbox").json() if m["action_id"] == action_id)
    verified = client.post(f"/api/v1/actions/{action_id}/verify", json={"idempotency_key": "test_request", "verification_code": code})
    assert verified.status_code == 200 and verified.json()["status"] == "COMPLETED"
    assert calls[-1][1].daily_transfer_total == Decimal("600.00")
    assert account(db_session).balance == Decimal("14250.00")


def test_new_lock_blocks_yellow_confirm(client, db_session):
    action = proposed(client)
    db_session.get(UserModel, "usr_demo_01").is_locked = True
    db_session.commit()
    response = confirm(client, action)
    assert response.status_code == 403 and "ACCOUNT_LOCKED" in response.json()["detail"]
    assert account(db_session).balance == Decimal("15250.00")


@pytest.mark.parametrize("updates, reason", [
    ({"source_account_id": "foreign_account"}, "SOURCE_ACCOUNT_MISMATCH"),
    ({"amount": "-1.00"}, "INVALID_TOOL_ARGUMENTS"),
    ({"amount": "1.001"}, "INVALID_TOOL_ARGUMENTS"),
    ({"user_id": "foreign_user"}, "INVALID_TOOL_ARGUMENTS"),
    ({"action_id": "llm_action"}, "INVALID_TOOL_ARGUMENTS"),
])
def test_invalid_agent_arguments_do_not_issue_tickets(client, db_session, monkeypatch, updates, reason):
    arguments = {"source_account_id": "acc_cny_001", "recipient_id": "usr_bob_01", "amount": "500.00", "currency": "CNY"}
    arguments.update(updates)
    monkeypatch.setattr(agent_service, "process", lambda *a, **kw: AgentResult(reply="Proposed", proposals=[
        ActionProposal(proposal_id="invalid", tool=ToolName.REQUEST_TRANSFER, arguments=arguments)
    ]))
    result = chat(client).json()
    assert result["status"] == "REJECTED" and result["actions"] == []
    assert reason in result["reply"] and "account is currently locked" not in result["reply"]
    assert db_session.query(ActionApprovalModel).count() == 0


def test_stored_payload_tampering_blocks_execution(client, db_session):
    action = proposed(client)
    record = db_session.get(ActionApprovalModel, action["approval"]["action_id"])
    payload = json.loads(record.payload_json)
    payload["amount"] = "999.00"
    record.payload_json = json.dumps(payload)
    db_session.commit()
    response = confirm(client, action)
    assert response.status_code == 403 and "INVALID_STORED_ACTION" in response.json()["detail"]
    assert account(db_session).balance == Decimal("15250.00")


def test_policy_rejection_at_verify_cannot_be_overridden_by_correct_otp(client, db_session, monkeypatch):
    action = proposed(client)
    account(db_session).daily_transfer_total = Decimal("800.00")
    db_session.commit()
    assert confirm(client, action).json()["status"] == "PENDING_MFA"
    action_id = action["approval"]["action_id"]
    code = client.get("/api/v1/demo/otp-inbox").json()[0]["code"]
    from security import policy
    monkeypatch.setattr(policy, "evaluate_action", lambda *a: PolicyDecision(
        tier=Tier.RED, allowed_to_proceed=False, requires_confirmation=False,
        requires_mfa=False, reason_code="POLICY_CHANGED",
    ))
    response = client.post(f"/api/v1/actions/{action_id}/verify", json={"idempotency_key": "test_request", "verification_code": code})
    assert response.status_code == 403 and "POLICY_CHANGED" in response.json()["detail"]
    assert db_session.get(ActionApprovalModel, action_id).mfa_consumed_at is None
    assert account(db_session).balance == Decimal("15250.00")


def test_locked_balance_read_still_calls_real_p4(client, db_session, monkeypatch):
    calls = spy_on_p4(monkeypatch)
    db_session.get(UserModel, "usr_demo_01").is_locked = True
    db_session.commit()
    response = chat(client, "What is my balance?")
    assert response.status_code == 200 and response.json()["status"] == "COMPLETED"
    assert calls[0][0].tool == ToolName.GET_BALANCE
    assert calls[0][1].account_locked is True


def test_real_p1_and_real_p4_transfer_roundtrip(client, db_session, monkeypatch):
    monkeypatch.setattr(agent_service, "use_mock", False)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    calls = spy_on_p4(monkeypatch)
    action = proposed(client)
    assert action["approval"]["tier"] == "YELLOW"
    assert confirm(client, action).json()["status"] == "COMPLETED"
    assert len(calls) == 2
    assert account(db_session).balance == Decimal("14750.00")

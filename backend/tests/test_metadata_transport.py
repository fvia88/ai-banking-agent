"""P2 HTTP metadata is isolated from P1 arguments, digests, and approval inputs."""
import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.api.approvals import ConfirmActionRequest, VerifyActionRequest
from app.api.schemas import AppChatOutput
from app.db.models import ActionApprovalModel, AccountModel, TransactionModel
from app.services.actions import compute_action_digest
from app.services.adapters import agent_service
from contracts.api_schemas import ConfirmActionRequest as SharedConfirm, VerifyActionRequest as SharedVerify
from contracts.tool_schemas import validate_tool_arguments


def chat(client, text, conversation="metadata"):
    response = client.post("/api/v1/chat", json={"conversation_id": conversation, "message": text})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, action):
    approval = action["approval"]
    response = client.post(f'/api/v1/actions/{approval["action_id"]}/confirm', json={
        "confirmation_id": "conf_metadata", "idempotency_key": "idemp_metadata",
        "action_digest": approval["action_digest"],
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("use_mock", [True, False])
@pytest.mark.parametrize("message", ["Transfer 20 CNY to Bob", "Cancel iQIYI VIP Monthly"])
def test_http_arguments_match_the_shared_schema_and_stored_digest(client, db_session, monkeypatch, use_mock, message):
    monkeypatch.setattr(agent_service, "use_mock", use_mock)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    body = chat(client, message)
    action = body["actions"][0]
    assert set(action["approval"]) == {"action_id", "action_digest", "tier", "status"}
    assert action["approval"]["status"] == "PENDING_CONFIRMATION"
    typed = validate_tool_arguments(action["tool"], action["arguments"])
    record = db_session.get(ActionApprovalModel, action["approval"]["action_id"])
    assert typed.model_dump(mode="json") == json.loads(record.payload_json)
    assert compute_action_digest(action["tool"], action["arguments"]) == record.action_digest
    assert record.proposal_id == action["proposal_id"]
    assert action["approval"]["action_digest"] == record.action_digest
    if not use_mock:
        from app.db.models import ConversationModel
        state = json.loads(db_session.get(ConversationModel, ("usr_demo_01", "metadata")).state_json)
        assert state["pending_tool_requests"][0]["proposal"]["arguments"] == action["arguments"]
        assert "approval" not in state["pending_tool_requests"][0]["proposal"]


def test_presentation_does_not_mutate_p1s_original_result(client, monkeypatch):
    from contracts.models import AgentResult, ActionProposal
    proposal = ActionProposal(proposal_id="unchanged_proposal", tool="request_transfer",
        arguments={"source_account_id": "acc_cny_001", "recipient_id": "usr_bob_01", "amount": "20.00", "currency": "CNY"})
    original = proposal.model_dump(mode="json")
    monkeypatch.setattr(agent_service, "use_mock", True)
    monkeypatch.setattr(agent_service, "process", lambda *a, **kw: AgentResult(reply="Review transfer", proposals=[proposal]))
    result = chat(client, "Transfer 20 CNY to Bob")
    assert result["actions"][0]["approval"]["action_id"]
    assert proposal.model_dump(mode="json") == original


@pytest.mark.parametrize("field,value", [("action_id", "forged"), ("action_digest", "a" * 64), ("tier", "GREEN"), ("status", "COMPLETED")])
def test_proposal_with_injected_metadata_is_rejected_before_storage(client, db_session, monkeypatch, field, value):
    from contracts.models import AgentResult, ActionProposal
    monkeypatch.setattr(agent_service, "use_mock", True)
    result = AgentResult(reply="Review transfer", proposals=[ActionProposal(
        proposal_id="injected_proposal", tool="request_transfer", arguments={
            "source_account_id": "acc_cny_001", "recipient_id": "usr_bob_01",
            "amount": "20.00", "currency": "CNY", field: value,
        })])
    monkeypatch.setattr(agent_service, "process", lambda *a, **kw: result)
    body = chat(client, "Transfer 20 CNY to Bob")
    assert body["status"] == "REJECTED" and body["actions"] == []
    assert db_session.query(ActionApprovalModel).count() == 0


def test_http_schema_rejects_legacy_metadata_in_arguments(client):
    body = chat(client, "Transfer 20 CNY to Bob")
    body["actions"][0]["arguments"]["tier"] = "GREEN"
    with pytest.raises(ValidationError):
        AppChatOutput.model_validate(body)


def test_approval_endpoints_use_shared_request_classes():
    assert ConfirmActionRequest is SharedConfirm
    assert VerifyActionRequest is SharedVerify


@pytest.mark.parametrize("operation,payload", [
    ("confirm", {"confirmation_id": "c", "action_digest": "a" * 64}),
    ("verify", {"verification_code": "123456"}),
    ("confirm", {"confirmation_id": "", "action_digest": "a" * 64, "idempotency_key": "k"}),
    ("verify", {"verification_code": "123456", "idempotency_key": ""}),
    ("confirm", {"confirmation_id": "c", "action_digest": "a" * 64, "idempotency_key": "k", "user_id": "other"}),
    ("verify", {"verification_code": "123456", "idempotency_key": "k", "tier": "GREEN"}),
])
def test_malformed_approval_requests_are_rejected_before_execution(client, db_session, operation, payload):
    action = chat(client, "Transfer 20 CNY to Bob")["actions"][0]
    record = db_session.get(ActionApprovalModel, action["approval"]["action_id"])
    response = client.post(f'/api/v1/actions/{record.action_id}/{operation}', json=payload)
    assert response.status_code == 422, response.text
    db_session.refresh(record)
    assert record.status == "PENDING_CONFIRMATION"
    assert db_session.get(AccountModel, "acc_cny_001").balance == Decimal("15250")
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 0


@pytest.mark.parametrize("legacy", [False, True])
def test_cached_followup_is_upgraded_without_new_agent_calls_or_tickets(client, db_session, monkeypatch, legacy):
    monkeypatch.setattr(agent_service, "use_mock", False)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    parent = chat(client, "Cancel iQIYI VIP Monthly then transfer 45 CNY to Bob")["actions"][0]
    confirm(client, parent)
    path = f'/api/v1/actions/{parent["approval"]["action_id"]}/continue'
    first = client.post(path)
    assert first.status_code == 200, first.text
    followup = first.json()["chat"]["actions"][0]
    if legacy:
        record = db_session.get(ActionApprovalModel, parent["approval"]["action_id"])
        cached = json.loads(record.continuation_json)
        item = cached["chat"]["actions"][0]
        approval = item.pop("approval")
        item["arguments"].update({key: approval[key] for key in ("action_id", "action_digest", "tier")})
        record.continuation_json = json.dumps(cached)
        db_session.commit()
    # Make current ticket metadata differ from the earlier cached response.
    db_session.get(AccountModel, "acc_cny_001").daily_transfer_total = Decimal("990")
    db_session.commit()
    assert confirm(client, followup)["status"] == "PENDING_MFA"
    monkeypatch.setattr(agent_service, "process_turn", lambda *a, **kw: pytest.fail("cached replay called P1"))
    replay = client.post(path)
    assert replay.status_code == 200, replay.text
    refreshed = replay.json()["chat"]["actions"][0]
    assert refreshed["approval"]["action_id"] == followup["approval"]["action_id"]
    assert refreshed["approval"]["tier"] == "RED"
    assert refreshed["approval"]["status"] == "PENDING_MFA"
    assert replay.json()["chat"]["status"] == "PENDING_MFA"
    assert refreshed["arguments"] == followup["arguments"]
    assert db_session.query(ActionApprovalModel).count() == 2
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 0


def test_cached_followup_cannot_borrow_another_conversations_ticket(client, db_session, monkeypatch):
    monkeypatch.setattr(agent_service, "use_mock", False)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    parent = chat(client, "Cancel iQIYI VIP Monthly then transfer 45 CNY to Bob")["actions"][0]
    confirm(client, parent)
    path = f'/api/v1/actions/{parent["approval"]["action_id"]}/continue'
    assert client.post(path).status_code == 200
    other = chat(client, "Transfer 5 CNY to Bob", conversation="other_conversation")["actions"][0]
    record = db_session.get(ActionApprovalModel, parent["approval"]["action_id"])
    cached = json.loads(record.continuation_json)
    cached["chat"]["actions"] = [other]
    record.continuation_json = json.dumps(cached)
    db_session.commit()
    monkeypatch.setattr(agent_service, "process_turn", lambda *a, **kw: pytest.fail("invalid replay called P1"))
    assert client.post(path).status_code == 409
    assert db_session.query(ActionApprovalModel).count() == 3
    assert db_session.get(ActionApprovalModel, parent["approval"]["action_id"]).status == "COMPLETED"
    assert db_session.query(TransactionModel).filter_by(category="Transfers").count() == 0

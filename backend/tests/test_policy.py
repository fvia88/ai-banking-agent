# backend/tests/test_policy.py
import pytest
import json
from app.services.actions import create_action_record
from decimal import Decimal
from contracts.enums import ToolName, Tier, ActionStatus
from contracts.models import ActionProposal, BankingContext
from app.mocks.security import MockSecurityAdapter
from app.db.models import UserModel, ActionApprovalModel
from app.services.adapters import build_tool_catalog

def test_t02_transfer_under_daily_limit_is_yellow():
    """T02: Transfer 500 with 0 daily total -> YELLOW (requires confirmation, no MFA)."""
    proposal = ActionProposal(
        proposal_id="p1",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={"amount": "500.00", "recipient_id": "usr_bob_01"}
    )
    context = BankingContext(
        user_id="u1",
        account_id="acc1",
        daily_transfer_total="0.00",
        account_balance="10000.00",
        account_locked=False
    )
    decision = MockSecurityAdapter.evaluate_action(proposal, context)
    assert decision.tier == Tier.YELLOW
    assert decision.allowed_to_proceed is True
    assert decision.requires_confirmation is True
    assert decision.requires_mfa is False

def test_t03_transfer_over_daily_limit_is_red():
    """T03: Transfer 500 with 800 daily total (cumulative 1,300) -> RED (requires MFA)."""
    proposal = ActionProposal(
        proposal_id="p2",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={"amount": "500.00", "recipient_id": "usr_bob_01"}
    )
    context = BankingContext(
        user_id="u1",
        account_id="acc1",
        daily_transfer_total="800.00",
        account_balance="10000.00",
        account_locked=False
    )
    decision = MockSecurityAdapter.evaluate_action(proposal, context)
    assert decision.tier == Tier.RED
    assert decision.allowed_to_proceed is True
    assert decision.requires_mfa is True

def test_t11_locked_account_blocked():
    """T11: Locked account cannot perform state-changing operations."""
    proposal = ActionProposal(
        proposal_id="p3",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={"amount": "100.00", "recipient_id": "usr_bob_01"}
    )
    context = BankingContext(
        user_id="u1",
        account_id="acc1",
        daily_transfer_total="0.00",
        account_balance="10000.00",
        account_locked=True
    )
    decision = MockSecurityAdapter.evaluate_action(proposal, context)
    assert decision.allowed_to_proceed is False
    assert decision.reason_code == "ACCOUNT_LOCKED"

def test_missing_recipient_id_rejected():
    """Validation test: missing recipient_id raises ValueError and halts execution."""
    proposal = ActionProposal(
        proposal_id="p_bad",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={"amount": "100.00"}  # No recipient_id!
    )
    context = BankingContext(
        user_id="u1",
        account_id="acc1",
        daily_transfer_total="0.00",
        account_balance="1000.00",
        account_locked=False
    )
    with pytest.raises(ValueError, match="INVALID_TOOL_ARGUMENTS"):
        create_action_record("u1", proposal, "acc1", context)

def test_locked_user_can_check_balance_but_cannot_transfer(client, db_session):
    """T11: Locked user can chat/read balance, but transfer proposals are REJECTED."""
    # 1. Lock demo user in DB
    user = db_session.query(UserModel).filter(UserModel.user_id == "usr_demo_01").first()
    user.is_locked = True
    db_session.commit()

    # 2. Check balance query -> Succeeds!
    bal_resp = client.post("/api/v1/chat", json={
        "conversation_id": "c_lock_bal",
        "message": "What is my balance?"
    }, headers={"X-Demo-User-Id": "usr_demo_01"})
    assert bal_resp.status_code == 200
    assert "15250.00" in bal_resp.json()["reply"].replace(",", "")

    # 3. Attempt transfer -> Gracefully REJECTED by security policy (not a 403 crash)
    tx_resp = client.post("/api/v1/chat", json={
        "conversation_id": "c_lock_tx",
        "message": "Transfer 500 CNY to Bob"
    }, headers={"X-Demo-User-Id": "usr_demo_01"})
    assert tx_resp.status_code == 200
    body = tx_resp.json()
    assert body["status"] == ActionStatus.REJECTED.value
    assert "locked" in body["reply"].lower()

def test_build_tool_catalog_includes_user_accounts():
    catalog = build_tool_catalog(
        account_id="acc_cny_001",
        account_locked=False,
        recipients=[{
            "recipient_id": "usr_bob_01",
            "user_id": "usr_demo_01",
            "display_name": "Bob Li",
            "account_number_masked": "**** 5678"
        }]
    )
    assert len(catalog) == 5
    tool_names = [t["name"] for t in catalog]
    assert "request_transfer" in tool_names
    assert "get_balance" in tool_names

    # Check that context is attached properly to every entry
    first_entry_context = catalog[0]["context"]
    assert first_entry_context["account_ids"] == ["acc_cny_001"]
    assert first_entry_context["account_locked"] is False
    assert len(first_entry_context["recipients"]) == 1
    assert first_entry_context["recipients"][0]["display_name"] == "Bob Li"

def test_agent_clean_payload_and_proposal_binding(client, db_session):
    """
    Verifies that ActionApprovalModel binds proposal_id and stores
    strictly pure financial arguments in payload_json without metadata pollution.
    """
    chat_resp = client.post("/api/v1/chat", json={
        "conversation_id": "c_stage4_test",
        "message": "Transfer 500 CNY to Bob"
    }, headers={"X-Demo-User-Id": "usr_demo_01"})
    
    assert chat_resp.status_code == 200
    action = chat_resp.json()["actions"][0]
    action_id = action["arguments"]["action_id"]

    # Query the database record directly
    record = db_session.query(ActionApprovalModel).filter(ActionApprovalModel.action_id == action_id).first()
    assert record is not None
    assert record.proposal_id == action["proposal_id"]  # Proposal ID is bound!
    
    # Verify stored payload contains ONLY pure financial fields
    stored_payload = json.loads(record.payload_json)
    assert "recipient_id" in stored_payload
    assert "amount" in stored_payload
    assert "action_id" not in stored_payload  # No server metadata pollution!
    assert "action_digest" not in stored_payload
    assert "tier" not in stored_payload

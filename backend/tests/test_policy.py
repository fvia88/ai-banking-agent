# backend/tests/test_policy.py
import pytest
from app.services.actions import create_action_record
from decimal import Decimal
from contracts.enums import ToolName, Tier, ActionStatus
from contracts.models import ActionProposal, BankingContext
from app.mocks.security import MockSecurityAdapter
from app.db.models import UserModel
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
    with pytest.raises(ValueError, match="Missing or empty required field: 'recipient_id'"):
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
    assert "15,250.00" in bal_resp.json()["reply"]

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
        account_ids=["acc_cny_001", "acc_cny_002"],
        verified_recipients=[{"recipient_id": "usr_bob_01"}]
    )
    assert len(catalog) == 5
    tool_names = [t["name"] for t in catalog]
    assert "request_transfer" in tool_names
    assert "get_balance" in tool_names
    
    # Check that user account IDs are injected into request_transfer properties
    transfer_tool = next(t for t in catalog if t["name"] == "request_transfer")
    account_enum = transfer_tool["parameters"]["properties"]["source_account_id"]["enum"]
    assert "acc_cny_001" in account_enum
    assert "acc_cny_002" in account_enum
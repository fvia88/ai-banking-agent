# backend/tests/test_policy.py
from decimal import Decimal
from contracts.enums import ToolName, Tier
from contracts.models import ActionProposal, BankingContext
from app.mocks.security import MockSecurityAdapter

def test_t02_transfer_under_daily_limit_is_yellow():
    """T02: Transfer 500 with 0 daily total -> YELLOW (requires confirmation, no MFA)."""
    proposal = ActionProposal(
        proposal_id="p1",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={"amount": "500.00", "recipient": "Bob"}
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
        arguments={"amount": "500.00", "recipient": "Bob"}
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
        arguments={"amount": "100.00", "recipient": "Bob"}
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
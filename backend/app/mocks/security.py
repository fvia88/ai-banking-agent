# backend/app/mocks/security.py
from decimal import Decimal
from contracts.enums import Tier, ToolName
from contracts.models import ActionProposal, BankingContext, PolicyDecision

class MockSecurityAdapter:
    """
    Mock policy engine fulfilling Person 4's module contract (security/policy.py).
    Enforces the Green/Yellow/Red tiers and account locking rules.
    """
    @staticmethod
    def evaluate_action(proposal: ActionProposal, context: BankingContext) -> PolicyDecision:
        # Rule 1: State-changing operations blocked if account is locked (Test Vector T11)
        if context.account_locked and proposal.tool in [ToolName.REQUEST_TRANSFER, ToolName.REQUEST_SUBSCRIPTION_CANCEL]:
            return PolicyDecision(
                tier=Tier.RED,
                allowed_to_proceed=False,
                requires_confirmation=False,
                requires_mfa=False,
                reason_code="ACCOUNT_LOCKED"
            )

        # Rule 2: Smart Transfers Tier Logic (Test Vectors T02 & T03)
        if proposal.tool == ToolName.REQUEST_TRANSFER:
            amount = Decimal(str(proposal.arguments.get("amount", "0.00")))
            daily_total = Decimal(str(context.daily_transfer_total))
            projected_total = daily_total + amount

            if projected_total > Decimal("1000.00"):
                return PolicyDecision(
                    tier=Tier.RED,
                    allowed_to_proceed=True,
                    requires_confirmation=True,
                    requires_mfa=True,
                    reason_code="TRANSFER_EXCEEDS_DAILY_LIMIT_REQUIRES_MFA"
                )
            
            return PolicyDecision(
                tier=Tier.YELLOW,
                allowed_to_proceed=True,
                requires_confirmation=True,
                requires_mfa=False,
                reason_code="TRANSFER_WITHIN_DAILY_LIMIT_CONFIRMATION_REQUIRED"
            )

        # Rule 3: Subscriptions Cancellation -> YELLOW
        if proposal.tool == ToolName.REQUEST_SUBSCRIPTION_CANCEL:
            return PolicyDecision(
                tier=Tier.YELLOW,
                allowed_to_proceed=True,
                requires_confirmation=True,
                requires_mfa=False,
                reason_code="SUBSCRIPTION_CANCEL_REQUIRES_CONFIRMATION"
            )

        # Rule 4: Read-only queries -> GREEN (Automatic, allowed even if locked)
        return PolicyDecision(
            tier=Tier.GREEN,
            allowed_to_proceed=True,
            requires_confirmation=False,
            requires_mfa=False,
            reason_code="READ_ONLY_AUTOMATIC"
        )
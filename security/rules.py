"""Security rules, constants, and configuration for the AI Banking Agent policy module.

This module defines the risk tier mapping rules, threshold constants, reason codes,
and configuration options according to frozen contracts v1.0.0.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from contracts.enums import Tier, ToolName
from contracts.models import ActionProposal, BankingContext, PolicyDecision
from contracts.tool_schemas import validate_tool_arguments


class SecurityReasonCode:
    """Canonical reason codes returned in PolicyDecision."""

    # Read-only policy decisions
    READ_ONLY_ACCESS = "READ_ONLY_ACCESS"

    # Transfer policy decisions
    TRANSFER_WITHIN_DAILY_LIMIT = "TRANSFER_WITHIN_DAILY_LIMIT"
    TRANSFER_EXCEEDS_DAILY_LIMIT = "TRANSFER_EXCEEDS_DAILY_LIMIT"

    # Subscription policy decisions
    SUBSCRIPTION_CANCEL_CONFIRMATION_REQUIRED = (
        "SUBSCRIPTION_CANCEL_CONFIRMATION_REQUIRED"
    )

    # Rejection and security violation reason codes
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    SOURCE_ACCOUNT_MISMATCH = "SOURCE_ACCOUNT_MISMATCH"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    INVALID_TOOL_ARGUMENTS = "INVALID_TOOL_ARGUMENTS"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    INVALID_CONTEXT = "INVALID_CONTEXT"
    MALFORMED_INPUT = "MALFORMED_INPUT"
    INTERNAL_POLICY_ERROR = "INTERNAL_POLICY_ERROR"


@dataclass(frozen=True)
class PolicyConfig:
    """Configurable policy thresholds and behaviors.

    Default values conform exactly to the baseline specification:
    - Daily transfer limit before MFA: CNY 1,000.00
    - Primary currency: CNY
    - Account lock denies mutations: True
    """

    daily_transfer_threshold: Decimal = Decimal("1000.00")
    supported_currency: str = "CNY"
    lock_denies_read_only: bool = False
    enforce_account_matching: bool = True


# Standard default configuration instance
DEFAULT_CONFIG = PolicyConfig()

# Classification of tools
READ_ONLY_TOOLS = frozenset(
    {
        ToolName.GET_BALANCE,
        ToolName.ANALYZE_SPENDING,
        ToolName.LIST_SUBSCRIPTIONS,
    }
)

MUTATION_TOOLS = frozenset(
    {
        ToolName.REQUEST_TRANSFER,
        ToolName.REQUEST_SUBSCRIPTION_CANCEL,
    }
)


def is_read_only_tool(tool: ToolName) -> bool:
    """Return True if tool does not mutate banking state."""
    return tool in READ_ONLY_TOOLS


def is_mutation_tool(tool: ToolName) -> bool:
    """Return True if tool initiates a state change / mutation."""
    return tool in MUTATION_TOOLS


def make_rejection_decision(reason_code: str) -> PolicyDecision:
    """Construct a fail-closed rejection PolicyDecision.

    Rejections always deny permission to proceed, require no confirmation/MFA,
    and are classified under Tier.RED.
    """
    return PolicyDecision(
        tier=Tier.RED,
        allowed_to_proceed=False,
        requires_confirmation=False,
        requires_mfa=False,
        reason_code=reason_code,
    )

# backend/app/services/adapters.py
import os
from contracts.models import ChatInput, AgentResult, ActionProposal, BankingContext, PolicyDecision, Transaction, SpendingReport, SubscriptionReport
from contracts.tool_schemas import TOOL_ARGUMENT_MODELS
from app.mocks.agent import MockAgentAdapter
from app.mocks.security import MockSecurityAdapter
from app.mocks.finance import MockFinanceAdapter
from app.mocks.subscriptions import MockSubscriptionsAdapter
from typing import Any
from decimal import Decimal
from contracts.enums import ToolName, Cadence
from datetime import datetime

def build_tool_catalog(
    account_id: str | None = None,
    account_ids: list[str] | None = None,
    account_locked: bool = False,
    recipients: list[dict[str, Any]] | None = None,
    subscriptions: list[dict[str, Any]] | None = None,
    pending_proposal_ids: list[str] | None = None,
    conversation_state: dict[str, Any] | None = None,
    clarification_request: str | None = None,
) -> list[dict[str, Any]]:
    """
    Builds the canonical tool catalog and context expected by Person 1's agent/service.py.
    """
    # Pick the primary account (P1 strictly requires exactly 1 account)
    selected_account = account_id or (account_ids[0] if account_ids else None) or "acc_cny_001"

    default_recipients = [
        {
            "recipient_id": "usr_bob_01",
            "user_id": "usr_demo_01",
            "display_name": "Bob Li",
            "account_number_masked": "**** 5678",
        }
    ]

    default_subscriptions = [
        {
            "subscription_id": "sub_iQIYI_01",
            "user_id": "usr_demo_01",
            "merchant": "iQIYI VIP Monthly",
            "estimated_amount": "45.00",
            "cadence": Cadence.MONTHLY.value,
            "status": "active",
            "cancellation_supported": True,
        }
    ]

    context: dict[str, Any] = {
        "account_ids": [selected_account],  # Guaranteed len == 1 for P1
        "account_locked": account_locked,
        "recipients": recipients if recipients is not None else default_recipients,
        "subscriptions": subscriptions if subscriptions is not None else default_subscriptions,
        "pending_proposal_ids": pending_proposal_ids or [],
    }

    if clarification_request:
        context["clarification_request"] = clarification_request
    if conversation_state:
        context["conversation_state"] = conversation_state

    return [
        {
            "name": tool.value,
            "parameters": model.model_json_schema(),
            "context": dict(context),
        }
        for tool, model in TOOL_ARGUMENT_MODELS.items()
    ]


class AgentAdapterService:
    def __init__(self, use_mock: bool | None = None):
        # Reads USE_MOCK_AGENT env var (default: True)
        if use_mock is not None:
            self.use_mock = use_mock
        else:
            self.use_mock = os.getenv("USE_MOCK_AGENT", "true").lower() == "true"

    def process(
        self,
        chat: ChatInput,
        account_id: str | None = None,
        account_ids: list[str] | None = None,
        account_locked: bool = False,
        recipients: list[dict[str, Any]] | None = None,
        subscriptions: list[dict[str, Any]] | None = None,
        pending_proposal_ids: list[str] | None = None,
        conversation_state: dict[str, Any] | None = None,
        clarification_request: str | None = None,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        tool_catalog = build_tool_catalog(
            account_id=account_id,
            account_ids=account_ids,
            account_locked=account_locked,
            recipients=recipients,
            subscriptions=subscriptions,
            pending_proposal_ids=pending_proposal_ids,
            conversation_state=conversation_state,
            clarification_request=clarification_request,
        )

        if self.use_mock:
            return MockAgentAdapter.process_message(
                chat, tool_catalog=tool_catalog, tool_results=tool_results
            )

        # Calls Person 1's real implementation in agent/service.py!
        from agent.service import process_message as p1_process_message
        return p1_process_message(chat, tool_catalog=tool_catalog, tool_results=tool_results)

class SecurityAdapterService:
    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock

    def evaluate(self, proposal: ActionProposal, context: BankingContext) -> PolicyDecision:
        if self.use_mock:
            return MockSecurityAdapter.evaluate_action(proposal, context)
        # When Person 4's code is merged:
        # from security.policy import evaluate_action
        # return evaluate_action(proposal, context)
        return MockSecurityAdapter.evaluate_action(proposal, context)

def calculate_history_periods(period: str, extra_months: int = 3) -> list[str]:
    """
    Given a period 'YYYY-MM', returns a list containing the requested period
    plus the preceding `extra_months` (handles year boundaries cleanly).
    Example: '2026-10' -> ['2026-07', '2026-08', '2026-09', '2026-10']
    """
    year, month = map(int, period.split("-"))
    periods = []
    
    for i in range(extra_months, -1, -1):
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        periods.append(f"{y:04d}-{m:02d}")
        
    return periods

class FinanceAdapterService:
    """Bridge for Person 3's Finance Analytics engine."""
    def __init__(self, use_mock: bool | None = None):
        # Reads USE_MOCK_FINANCE env var (default: False -> real P3 engine)
        if use_mock is not None:
            self.use_mock = use_mock
        else:
            self.use_mock = os.getenv("USE_MOCK_FINANCE", "false").lower() == "true"

    def analyze(self, transactions: list[Transaction], period: str) -> SpendingReport:
        if self.use_mock:
            return MockFinanceAdapter.analyze_spending(transactions, period)

        # Calls Person 3's real implementation in finance/analytics.py
        from finance.analytics import analyze_spending
        return analyze_spending(transactions, period)

class SubscriptionsAdapterService:
    """Bridge for Person 5's Subscription Detection engine."""
    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock

    def detect(self, transactions: list[Transaction]) -> SubscriptionReport:
        if self.use_mock:
            return MockSubscriptionsAdapter.detect_subscriptions(transactions)
        # When Person 5's code is merged:
        # from subscriptions.detector import detect_subscriptions
        # return detect_subscriptions(transactions)
        return MockSubscriptionsAdapter.detect_subscriptions(transactions)

agent_service = AgentAdapterService(use_mock=True)
policy_service = SecurityAdapterService(use_mock=True)
finance_service = FinanceAdapterService()
subscriptions_service = SubscriptionsAdapterService(use_mock=True)
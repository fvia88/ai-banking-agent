# backend/app/services/adapters.py
import os
from contracts.models import ChatInput, AgentResult, ActionProposal, BankingContext, PolicyDecision, Transaction, SpendingReport, SubscriptionReport
from contracts.tool_schemas import TOOL_ARGUMENT_MODELS
from app.mocks.agent import MockAgentAdapter
from app.mocks.security import MockSecurityAdapter
from app.mocks.finance import MockFinanceAdapter
from app.mocks.subscriptions import MockSubscriptionsAdapter
from typing import Any, TYPE_CHECKING
from decimal import Decimal
from contracts.enums import ToolName, Cadence
from datetime import datetime

if TYPE_CHECKING:
    from agent.conversation import ConversationTurn

def build_tool_catalog(
    account_id: str | None = None,
    account_ids: list[str] | None = None,
    account_locked: bool = False,
    recipients: list[dict[str, Any]] | None = None,
    subscriptions: list[dict[str, Any]] | None = None,
    pending_proposal_ids: list[str] | None = None,
    conversation_state: dict[str, Any] | None = None,
    clarification_request: str | None = None,
    allow_demo_defaults: bool = True,
) -> list[dict[str, Any]]:
    """
    Builds the canonical tool catalog and context expected by Person 1's agent/service.py.
    """
    # Pick the primary account (P1 strictly requires exactly 1 account)
    if allow_demo_defaults:
        selected_accounts = [account_id or (account_ids[0] if account_ids else None) or "acc_cny_001"]
    else:
        # Real callers must supply the selected, owned account. Do not invent
        # an account or silently select the first of several accounts.
        selected_accounts = [account_id] if account_id else list(account_ids or [])

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
        "account_ids": selected_accounts,
        "account_locked": account_locked,
        "recipients": recipients if recipients is not None else (default_recipients if allow_demo_defaults else []),
        "subscriptions": subscriptions if subscriptions is not None else (default_subscriptions if allow_demo_defaults else []),
        "pending_proposal_ids": pending_proposal_ids or [],
    }

    if clarification_request:
        context["clarification_request"] = clarification_request
    if conversation_state is not None:
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
        # Legacy route compatibility: preserve its existing demo context and
        # AgentResult return type until chat.py migrates to the stateful method.
        from agent.service import process_turn as p1_process_turn
        return p1_process_turn(chat, tool_catalog=tool_catalog, tool_results=tool_results).result

    def process_turn(
        self, chat: ChatInput, *, tool_results: list[dict[str, Any]] | None = None,
        **context: Any,
    ) -> "ConversationTurn":
        """Real P1 bridge; caller owns saving the returned state after every call.

        Context keywords match build_tool_catalog. This never executes tools,
        stores sessions, or turns pending IDs into fabricated proposal records.
        """
        if self.use_mock:
            raise ValueError("process_turn requires USE_MOCK_AGENT=false or use_mock=False")
        # Force real mode to use only caller-provided trusted context.
        context.pop("allow_demo_defaults", None)
        tool_catalog = build_tool_catalog(**context, allow_demo_defaults=False)
        from agent.service import process_turn as p1_process_turn
        return p1_process_turn(chat, tool_catalog=tool_catalog, tool_results=tool_results)

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
    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock

    def analyze(self, transactions: list[Transaction], period: str) -> SpendingReport:
        if self.use_mock:
            return MockFinanceAdapter.analyze_spending(transactions, period)
        # When Person 3's code is merged:
        # from finance.analytics import analyze_spending
        # return analyze_spending(transactions, period)
        return MockFinanceAdapter.analyze_spending(transactions, period)

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

agent_service = AgentAdapterService()
policy_service = SecurityAdapterService(use_mock=True)
finance_service = FinanceAdapterService(use_mock=True)
subscriptions_service = SubscriptionsAdapterService(use_mock=True)

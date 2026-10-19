# backend/app/services/adapters.py
from contracts.models import ChatInput, AgentResult, ActionProposal, BankingContext, PolicyDecision, Transaction, SpendingReport
from app.mocks.agent import MockAgentAdapter
from app.mocks.security import MockSecurityAdapter
from app.mocks.finance import MockFinanceAdapter
from typing import Any
from contracts.enums import ToolName
from datetime import datetime

def build_tool_catalog(
    account_ids: list[str] | None = None,
    verified_recipients: list[dict[str, str]] | None = None
) -> list[dict[str, Any]]:
    """
    Builds the tool catalog passed to Person 1's agent.service.process_message.
    Injects user account IDs and verified payees so the LLM proposes valid arguments.
    """
    acc_list = account_ids or ["acc_cny_001"]
    recipient_hint = (
        [r.get("recipient_id") for r in verified_recipients]
        if verified_recipients
        else ["usr_bob_01"]
    )

    return [
        {
            "name": ToolName.GET_BALANCE.value,
            "description": "Check current balance of user accounts",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "enum": acc_list}
                }
            }
        },
        {
            "name": ToolName.REQUEST_TRANSFER.value,
            "description": "Propose a funds transfer to a recipient",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_account_id": {"type": "string", "enum": acc_list},
                    "recipient_id": {"type": "string", "description": f"Known recipients: {recipient_hint}"},
                    "amount": {"type": "string", "description": "Decimal string format e.g. 500.00"},
                    "currency": {"type": "string", "enum": ["CNY"], "default": "CNY"}
                },
                "required": ["source_account_id", "recipient_id", "amount", "currency"]
            }
        },
        {
            "name": ToolName.ANALYZE_SPENDING.value,
            "description": "Generate spending categorization and anomaly report",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "description": "Target month in YYYY-MM format"}
                },
                "required": ["period"]
            }
        },
        {
            "name": ToolName.LIST_SUBSCRIPTIONS.value,
            "description": "Detect and list active recurring charges",
            "parameters": {"type": "object", "properties": {}}
        },
        {
            "name": ToolName.REQUEST_SUBSCRIPTION_CANCEL.value,
            "description": "Propose cancelling an active subscription",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string"}
                },
                "required": ["subscription_id"]
            }
        }
    ]

class AgentAdapterService:
    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock

    def process(
        self,
        chat: ChatInput,
        account_ids: list[str] | None = None,
        verified_recipients: list[dict[str, str]] | None = None
    ) -> AgentResult:
        # Build standard tool catalog with context
        tool_catalog = build_tool_catalog(account_ids, verified_recipients)
        
        if self.use_mock:
            return MockAgentAdapter.process_message(chat, tool_catalog=tool_catalog)
        
        # When Person 1's code is merged:
        # from agent.service import process_message
        # return process_message(chat, tool_catalog=tool_catalog)
        return MockAgentAdapter.process_message(chat, tool_catalog=tool_catalog)

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

agent_service = AgentAdapterService(use_mock=True)
policy_service = SecurityAdapterService(use_mock=True)
finance_service = FinanceAdapterService(use_mock=True)
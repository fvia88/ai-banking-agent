# backend/app/services/adapters.py
from contracts.models import ChatInput, AgentResult, ActionProposal, BankingContext, PolicyDecision
from app.mocks.agent import MockAgentAdapter
from app.mocks.security import MockSecurityAdapter

class AgentAdapterService:
    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock

    def process(self, chat: ChatInput) -> AgentResult:
        return MockAgentAdapter.process_message(chat)

class SecurityAdapterService:
    """Bridge for Person 4's Risk Policy engine."""
    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock

    def evaluate(self, proposal: ActionProposal, context: BankingContext) -> PolicyDecision:
        return MockSecurityAdapter.evaluate_action(proposal, context)

agent_service = AgentAdapterService(use_mock=True)
policy_service = SecurityAdapterService(use_mock=True)
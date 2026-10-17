# backend/app/services/adapters.py
from contracts.models import ChatInput, AgentResult
from app.mocks.agent import MockAgentAdapter

class AgentAdapterService:
    """Composition adapter root for P1 Agent module."""
    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock

    def process(self, chat: ChatInput) -> AgentResult:
        if self.use_mock:
            return MockAgentAdapter.process_message(chat)
        # When integration day arrives:
        # from agent.service import process_message
        # return process_message(chat, tool_catalog=[])
        return MockAgentAdapter.process_message(chat)

agent_service = AgentAdapterService(use_mock=True)
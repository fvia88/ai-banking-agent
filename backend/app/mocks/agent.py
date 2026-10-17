# backend/app/mocks/agent.py
import uuid
from contracts.enums import ToolName, ActionStatus
from contracts.models import ChatInput, AgentResult, ActionProposal

class MockAgentAdapter:
    """
    Stateless mock agent fulfilling P1 module contracts.
    Swappable with real agent/service.py once P1 completes their milestone.
    """
    @staticmethod
    def process_message(chat: ChatInput, tool_catalog: list[dict] | None = None) -> AgentResult:
        msg = chat.message.lower().strip()
        
        # Pattern 1: Balance inquiry
        if "balance" in msg:
            return AgentResult(
                reply="Your current primary account balance is CNY 15,250.00.",
                proposals=[
                    ActionProposal(
                        proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
                        tool=ToolName.GET_BALANCE,
                        arguments={"currency": "CNY"},
                        rationale="User requested balance check"
                    )
                ],
                needs_clarification=False
            )
        
        # Pattern 2: Transfer proposal (Smart Transfer)
        if "transfer" in msg:
            return AgentResult(
                reply="I have prepared a transfer of CNY 500.00 to Bob. Please review and confirm.",
                proposals=[
                    ActionProposal(
                        proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
                        tool=ToolName.REQUEST_TRANSFER,
                        arguments={"recipient_id": "Bob", "amount": "500.00", "currency": "CNY"},
                        rationale="Drafted requested transfer"
                    )
                ],
                needs_clarification=False
            )
            
        # Default fallback / greeting
        return AgentResult(
            reply=f"Hello! I am your AI Banking Assistant. You said: '{chat.message}'. How can I assist with your bills, transfers, or subscriptions today?",
            proposals=[],
            needs_clarification=False
        )
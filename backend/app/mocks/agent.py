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

        # Pattern 4: Cross-scenario orchestration (Cancel subscription + Transfer savings)
        if "savings" in msg or ("cancel" in msg and "transfer" in msg):
            sub_id = "sub_iQIYI_01"
            return AgentResult(
                reply="I have detected your iQIYI VIP subscription (45.00 CNY/mo). I have prepared two actions: (1) cancel the subscription, and (2) transfer the 45.00 CNY monthly savings to your savings vault.",
                proposals=[
                    ActionProposal(
                        proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
                        tool=ToolName.REQUEST_SUBSCRIPTION_CANCEL,
                        arguments={"subscription_id": sub_id},
                        rationale="Cancel recurring iQIYI subscription"
                    ),
                    ActionProposal(
                        proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
                        tool=ToolName.REQUEST_TRANSFER,
                        arguments={
                            "recipient_id": "usr_savings_vault",
                            "amount": "45.00",
                            "currency": "CNY"
                        },
                        rationale="Transfer projected monthly savings to savings vault"
                    )
                ],
                needs_clarification=False
            )
        
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

        # Pattern 3: Subscription cancellation
        if "cancel" in msg:
            sub_id = "sub_iQIYI_01"
            return AgentResult(
                reply=f"I have prepared a cancellation request for subscription '{sub_id}'. Please review and confirm.",
                proposals=[
                    ActionProposal(
                        proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
                        tool=ToolName.REQUEST_SUBSCRIPTION_CANCEL,
                        arguments={"subscription_id": sub_id},
                        rationale="User requested subscription cancellation"
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
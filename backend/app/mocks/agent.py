# backend/app/mocks/agent.py
import uuid
from contracts.enums import ToolName, ActionStatus
from contracts.models import ChatInput, AgentResult, ActionProposal
from decimal import Decimal

class MockAgentAdapter:
    """
    Stateless mock agent fulfilling P1 module contracts.
    Swappable with real agent/service.py once P1 completes their milestone.
    """
    @staticmethod
    def process_message(
        chat: ChatInput,
        tool_catalog: list[dict] | None = None,
        tool_results: list[dict] | None = None,
    ) -> AgentResult:
      # --- Handle Read Tool Results ---
      if tool_results:
            res = tool_results[0]
            tool = res.get("tool")
            data = res.get("data", {})

            if tool == ToolName.GET_BALANCE.value:
                bal = Decimal(str(data.get("balance", "0.00")))
                return AgentResult(reply=f"Verified balance: CNY {bal:.2f}.", proposals=[])

            if tool == ToolName.ANALYZE_SPENDING.value:
                tot = Decimal(str(data.get("total_spending", "0.00")))
                period = data.get("period", "")
                return AgentResult(reply=f"Verified spending for {period}: CNY {tot:.2f}.", proposals=[])

            if tool == ToolName.LIST_SUBSCRIPTIONS.value:
                count = len(data.get("candidates", []))
                return AgentResult(
                    reply=f"Found {count} recurring-charge candidates. These are not proof of active subscriptions.",
                    proposals=[]
                )
            
      msg = chat.message.lower().strip()

      # Extract clarification context if passed by backend
      clarification_req = None
      if tool_catalog:
        clarification_req = tool_catalog[0].get("context", {}).get(
            "clarification_request"
        )

      # 1. SPECIFIC: Cross-scenario orchestration (Cancel subscription + Transfer savings)
      if "savings" in msg or ("cancel" in msg and "transfer" in msg):
        sub_id = "sub_iQIYI_01"
        return AgentResult(
            reply=(
                "I have detected your iQIYI VIP subscription (45.00 CNY/mo). I"
                " have prepared two actions: (1) cancel the subscription, and"
                " (2) transfer the 45.00 CNY monthly savings to your savings"
                " vault."
            ),
            proposals=[
                ActionProposal(
                    proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
                    tool=ToolName.REQUEST_SUBSCRIPTION_CANCEL,
                    arguments={"subscription_id": sub_id},
                    rationale="Cancel recurring iQIYI subscription",
                ),
                ActionProposal(
                    proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
                    tool=ToolName.REQUEST_TRANSFER,
                    arguments={
                        "source_account_id": tool_catalog[0]["context"]["account_ids"][0],
                        "recipient_id": "usr_savings_vault",
                        "amount": "45.00",
                        "currency": "CNY",
                    },
                    rationale=(
                        "Transfer projected monthly savings to savings vault"
                    ),
                ),
            ],
            needs_clarification=False,
        )

      # 2. Balance inquiry
      if "balance" in msg:
        return AgentResult(
            reply="Your current primary account balance is CNY 15,250.00.",
            proposals=[
                ActionProposal(
                    proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
                    tool=ToolName.GET_BALANCE,
                    arguments={"account_id": "acc_cny_001"},
                    rationale="User requested balance check",
                )
            ],
            needs_clarification=False,
        )

      # 3. Single Subscription cancellation
      if "cancel" in msg:
        sub_id = "sub_iQIYI_01"
        return AgentResult(
            reply=(
                f"I have prepared a cancellation request for subscription"
                f" '{sub_id}'. Please review and confirm."
            ),
            proposals=[
                ActionProposal(
                    proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
                    tool=ToolName.REQUEST_SUBSCRIPTION_CANCEL,
                    arguments={"subscription_id": sub_id},
                    rationale="User requested subscription cancellation",
                )
            ],
            needs_clarification=False,
        )

      # 4. Continuation: User answered with amount after a previous clarification
      if clarification_req and any(char.isdigit() for char in msg):
        import re

        match = re.search(r"\d+(?:\.\d+)?", msg)
        amt_str = f"{Decimal(match.group(0)):.2f}" if match else "500.00"
        return AgentResult(
            reply=(
                f"I have prepared a transfer of CNY {amt_str} to Bob. Please"
                " review and confirm."
            ),
            proposals=[
                ActionProposal(
                    proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
                    tool=ToolName.REQUEST_TRANSFER,
                    arguments={
                        "source_account_id": tool_catalog[0]["context"]["account_ids"][0],
                        "recipient_id": "usr_bob_01",
                        "amount": amt_str,
                        "currency": "CNY",
                    },
                    rationale="Drafted transfer after receiving amount",
                )
            ],
            needs_clarification=False,
        )

      # 5. Clarification: Transfer request missing amount (Test Vector T05)
      if "transfer" in msg and not any(char.isdigit() for char in msg):
        return AgentResult(
            reply="How much CNY would you like to transfer?",
            proposals=[],
            needs_clarification=True,
        )

      # 6. Single Transfer proposal (complete with amount)
      if "transfer" in msg:
        return AgentResult(
            reply=(
                "I have prepared a transfer of CNY 500.00 to Bob. Please review"
                " and confirm."
            ),
            proposals=[
                ActionProposal(
                    proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
                    tool=ToolName.REQUEST_TRANSFER,
                    arguments={
                        "source_account_id": tool_catalog[0]["context"]["account_ids"][0],
                        "recipient_id": "usr_bob_01",
                        "amount": "500.00",
                        "currency": "CNY",
                    },
                    rationale="Drafted requested transfer",
                )
            ],
            needs_clarification=False,
        )

      # Fallback greeting
      return AgentResult(
          reply=(
              f"Hello! I am your AI Banking Assistant. You said:"
              f" '{chat.message}'. How can I assist with your bills, transfers,"
              " or subscriptions today?"
          ),
          proposals=[],
          needs_clarification=False,
      )
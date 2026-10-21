# backend/app/api/chat.py
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from contracts.models import ChatInput, ChatOutput, BankingContext
from contracts.enums import ActionStatus, Direction, ToolName
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel, AccountModel, TransactionModel
from app.services.adapters import agent_service, finance_service, subscriptions_service, build_tool_catalog
from app.config import settings
from app.services.actions import create_action_record
from app.services.session_store import (
    get_conversation_state,
    set_conversation_state,
    clear_conversation_state,
)
from decimal import Decimal
from contracts.models import Account, Transaction

router = APIRouter()

@router.post("/chat", response_model=ChatOutput)
def handle_chat(
    chat_input: ChatInput,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
  # 1. Draft Abandonment ("never mind" / "nevermind")
  if agent_service.use_mock and chat_input.message.strip().lower() in ["never mind", "nevermind"]:
    clear_conversation_state(chat_input.conversation_id)
    return ChatOutput(
        conversation_id=chat_input.conversation_id,
        reply="Draft cancelled. What else can I help you with?",
        actions=[],
        status=ActionStatus.COMPLETED,
    )

  # 2. Retrieve conversation memory
  real_agent = not agent_service.use_mock
  # Namespaced keys isolate real P1 snapshots by resolved user AND conversation.
  # Session-store persistence/locking remains a separate integration step.
  state_key = (json.dumps(["p1", user.user_id, chat_input.conversation_id])
               if real_agent else chat_input.conversation_id)
  saved_state = get_conversation_state(state_key)
  clarification_req = saved_state.get("clarification_request")

  # 3. Fetch primary account
  user_accounts = (
      db.query(AccountModel).filter(AccountModel.user_id == user.user_id).all()
  )
  primary_acc = user_accounts[0] if user_accounts else None
  account_id = primary_acc.account_id if primary_acc else None

  # 4. Generate proposal with conversation context
  if real_agent:
    # The current DB has no recipient/subscription tables. Keep P2's explicit
    # synthetic demo records only for the configured demo user; never supply
    # those records to other users or promote detector candidates to active.
    demo_context = (build_tool_catalog()[0]["context"]
                    if user.user_id == settings.DEFAULT_DEMO_USER_ID else {})
    agent_context = dict(
        account_id=account_id,
        account_locked=user.is_locked,
        recipients=[r for r in demo_context.get("recipients", []) if r["user_id"] == user.user_id],
        subscriptions=[s for s in demo_context.get("subscriptions", []) if s["user_id"] == user.user_id],
    )
    turn = agent_service.process_turn(
        chat_input, conversation_state=saved_state or None, **agent_context,
    )
    set_conversation_state(state_key, turn.state.model_dump(mode="json"))
    result = turn.result
  else:
    result = agent_service.process(
        chat_input, account_id=account_id, account_locked=user.is_locked,
        clarification_request=clarification_req,
    )

  # 5. Manage Conversation Memory
  if result.needs_clarification and not real_agent:
    # Save current message so next turn remembers it
    set_conversation_state(
        chat_input.conversation_id,
        {"clarification_request": chat_input.message},
    )
    return ChatOutput(
        conversation_id=chat_input.conversation_id,
        reply=result.reply,
        actions=[],
        status=ActionStatus.COMPLETED,
    )
  elif not real_agent:
    # Action proposed or completed -> Clear clarification memory
    clear_conversation_state(chat_input.conversation_id)

  # 6. Check if the proposal is a Read Tool (Automatic Green Double-Hop)
  READ_TOOLS = [
        ToolName.GET_BALANCE.value,
        ToolName.ANALYZE_SPENDING.value,
        ToolName.LIST_SUBSCRIPTIONS.value,
  ]

  if len(result.proposals) == 1 and result.proposals[0].tool.value in READ_TOOLS:
        proposal = result.proposals[0]
        tool_name = proposal.tool.value
        tool_data = {}

        if tool_name == ToolName.GET_BALANCE.value:
            acc_id = proposal.arguments.get("account_id", account_id)
            acc_record = db.query(AccountModel).filter(
                AccountModel.account_id == acc_id, AccountModel.user_id == user.user_id,
            ).first()
            if acc_record:
                tool_data = Account(
                    account_id=acc_record.account_id,
                    user_id=acc_record.user_id,
                    currency="CNY",
                    balance=Decimal(str(acc_record.balance)),
                    locked=user.is_locked,
                ).model_dump(mode="json")

        elif tool_name == ToolName.ANALYZE_SPENDING.value:
            period = str(proposal.arguments.get("period", "2026-10"))
            tx_records = (
                db.query(TransactionModel)
                .filter(TransactionModel.account_id == account_id)
                .all()
            )
            parsed_txs = [
                Transaction(
                    transaction_id=t.transaction_id,
                    account_id=t.account_id,
                    timestamp=datetime.fromisoformat(t.timestamp),
                    amount=Decimal(str(t.amount)),
                    direction=Direction(t.direction.lower()),
                    merchant=t.merchant,
                    category=t.category,
                )
                for t in tx_records
            ]
            report = finance_service.analyze(parsed_txs, period)
            tool_data = report.model_dump(mode="json")

        elif tool_name == ToolName.LIST_SUBSCRIPTIONS.value:
            tx_records = (
                db.query(TransactionModel)
                .filter(TransactionModel.account_id == account_id)
                .all()
            )
            parsed_txs = [
                Transaction(
                    transaction_id=t.transaction_id,
                    account_id=t.account_id,
                    timestamp=datetime.fromisoformat(t.timestamp),
                    amount=Decimal(str(t.amount)),
                    direction=Direction(t.direction.lower()),
                    merchant=t.merchant,
                    category=t.category,
                )
                for t in tx_records
            ]
            sub_report = subscriptions_service.detect(parsed_txs)
            tool_data = sub_report.model_dump(mode="json")

        # Hop 2: Feed verified tool result back to the Agent
        tool_result = {
            "conversation_id": chat_input.conversation_id,
            "proposal_id": proposal.proposal_id,
            "tool": tool_name,
            "arguments": proposal.arguments,
            "status": "success",
            "data": tool_data,
        }

        if real_agent:
            final_turn = agent_service.process_turn(
                chat_input, conversation_state=get_conversation_state(state_key),
                tool_results=[tool_result], **agent_context,
            )
            set_conversation_state(state_key, final_turn.state.model_dump(mode="json"))
            final_result = final_turn.result
        else:
            final_result = agent_service.process(
                chat_input, account_id=account_id, account_locked=user.is_locked,
                pending_proposal_ids=[proposal.proposal_id], tool_results=[tool_result],
            )

        return ChatOutput(
            conversation_id=chat_input.conversation_id,
            reply=final_result.reply,
            actions=[],
            status=ActionStatus.COMPLETED,
        )

  # 7. Otherwise: Mutation Action Proposals (Transfers & Cancellations)
  has_pending_actions = False
  if result.proposals:
      balance_str = f"{primary_acc.balance:.2f}" if primary_acc else "0.00"
      daily_total_str = f"{primary_acc.daily_transfer_total:.2f}" if primary_acc else "0.00"

      context = BankingContext(
          user_id=user.user_id,
          account_id=account_id,
          daily_transfer_total=daily_total_str,
          account_balance=balance_str,
          account_locked=user.is_locked,
      )

      for proposal in result.proposals:
          try:
              action_record, digest, tier = create_action_record(
                  user_id=user.user_id,
                  proposal=proposal,
                  source_account_id=account_id,
                  context=context,
              )

              if tier in ["YELLOW", "RED"]:
                  db.add(action_record)
                  proposal.arguments["action_id"] = action_record.action_id
                  proposal.arguments["action_digest"] = digest
                  proposal.arguments["tier"] = tier
                  has_pending_actions = True
              else:
                  proposal.arguments["tier"] = "GREEN"

          except ValueError as e:
              return ChatOutput(
                  conversation_id=chat_input.conversation_id,
                  reply="Action blocked: Your account is currently locked for state-changing operations.",
                  actions=[],
                  status=ActionStatus.REJECTED,
              )

      db.commit()
      status = ActionStatus.PENDING_CONFIRMATION if has_pending_actions else ActionStatus.COMPLETED
  else:
      status = ActionStatus.COMPLETED

  return ChatOutput(
      conversation_id=chat_input.conversation_id,
      reply=result.reply,
      actions=result.proposals,
      status=status,
  )

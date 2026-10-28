# backend/app/api/chat.py
from datetime import datetime
import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from contracts.models import ChatInput, BankingContext
from app.api.schemas import AppChatOutput as ChatOutput
from contracts.enums import ActionStatus, Direction, ToolName
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel, AccountModel, TransactionModel, ActionApprovalModel
from app.services.adapters import agent_service, finance_service
from app.services.actions import PolicyRejected
from app.services.session_store import (
    get_conversation_state,
    set_conversation_state,
    clear_conversation_state,
    conversation_key,
    conversation_session,
)
from decimal import Decimal
from contracts.models import Account, Transaction
from contracts.tool_schemas import validate_tool_arguments
from app.services.adapters import policy_service
from app.services.subscriptions import selected_account, stored_records, subscription_report
from app.services.daily_transfers import effective_total
from app.services.chat_history import save_turn

router = APIRouter()

@router.post("/chat", response_model=ChatOutput)
def handle_chat(
    chat_input: ChatInput,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
  state_key = (conversation_key(user.user_id, chat_input.conversation_id)
               if not agent_service.use_mock else chat_input.conversation_id)
  # Keep the lock until all processing/result handling and state saves finish.
  with conversation_session(state_key):
    if agent_service.use_mock:
      response = _handle_chat_turn(chat_input, user, db, state_key)
      save_turn(db, user.user_id, chat_input, response)
      db.commit()
      return response
    from app.services.session_store import lock_conversation
    from app.api.continuation import continue_action
    # Recover a committed result even when the browser missed its callback.
    # Read-only tools already complete within their ordinary chat turn.
    ready = db.query(ActionApprovalModel).filter_by(
        user_id=user.user_id, conversation_id=chat_input.conversation_id,
    ).filter(ActionApprovalModel.status.in_([
        "PENDING_MFA", "COMPLETED", "FAILED", "REJECTED", "CANCELLED",
    ])).order_by(ActionApprovalModel.created_at, ActionApprovalModel.action_id).all()
    recovered = []
    for action in ready:
      if action.continuation_status != action.status:
        update = continue_action(action.action_id, user=user, db=db)
        recovered.append(update.chat.reply)
        if update.chat.actions:
          response = update.chat.model_copy(update={"reply": update.chat.reply +
              " Your latest message has not been processed; review this next approval, then resend your message."})
          # The continuation already saved the approval card. Record this new
          # unprocessed message and notice without duplicating that card.
          save_turn(db, user.user_id, chat_input, response.model_copy(update={'actions': []}))
          db.commit()
          return response
    row = lock_conversation(db, user.user_id, chat_input.conversation_id)
    set_conversation_state(state_key, json.loads(row.state_json))
    try:
      response = _handle_chat_turn(chat_input, user, db, state_key)
      row.state_json = json.dumps(get_conversation_state(state_key))
      save_turn(db, user.user_id, chat_input, response)
      db.commit()
      if recovered:
        response = response.model_copy(update={"reply": " ".join(recovered) + " " + response.reply})
      return response
    except Exception:
      db.rollback()
      clear_conversation_state(state_key)
      raise


def _handle_chat_turn(chat_input: ChatInput, user: UserModel, db: Session, state_key: str):
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
  # The route holds the session lock for this entire read/process/write cycle.
  saved_state = get_conversation_state(state_key)
  clarification_req = saved_state.get("clarification_request")

  # 3. Fetch primary account
  primary_acc = selected_account(db, user.user_id)
  account_id = primary_acc.account_id if primary_acc else None

  # 4. Generate proposal with conversation context
  if real_agent:
    from app.services.agent_context import trusted_agent_context
    primary_acc, agent_context = trusted_agent_context(db, user)
    turn = agent_service.process_turn(
        chat_input, conversation_state=saved_state or None, **agent_context,
    )
    set_conversation_state(state_key, turn.state.model_dump(mode="json"))
    result = turn.result
  else:
    result = agent_service.process(
        chat_input, account_id=account_id, account_locked=user.is_locked,
        clarification_request=clarification_req,
        subscriptions=[s.model_dump(mode="json") for s in stored_records(db, user.user_id, account_id)],
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
        if primary_acc is None:
            return ChatOutput(conversation_id=chat_input.conversation_id,
                              reply="No owned account is available.", actions=[], status=ActionStatus.REJECTED)
        try:
            validate_tool_arguments(proposal.tool, proposal.arguments)
            read_context = BankingContext(
                user_id=user.user_id, account_id=account_id,
                account_balance=primary_acc.balance,
                daily_transfer_total=effective_total(primary_acc),
                account_locked=user.is_locked,
            )
            decision = policy_service.evaluate(proposal, read_context)
            if not decision.allowed_to_proceed or decision.requires_confirmation or decision.requires_mfa:
                raise PolicyRejected(decision.reason_code)
        except ValueError as exc:
            reason = exc.reason_code if isinstance(exc, PolicyRejected) else "INVALID_TOOL_ARGUMENTS"
            return ChatOutput(conversation_id=chat_input.conversation_id,
                              reply=f"Read blocked by security policy: {reason}",
                              actions=[], status=ActionStatus.REJECTED)
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
            sub_report = subscription_report(db, user.user_id, account_id)
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

  from app.services.proposals import present_proposals
  response = present_proposals(chat_input, user, db, result, primary_acc)
  if agent_service.use_mock:
    db.commit()
  return response

# backend/app/api/chat.py
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
from app.services.actions import create_action_record, PolicyRejected
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
from app.services.subscriptions import selected_account, stored_records, subscription_report, cancellation_record
from app.services.daily_transfers import effective_total

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
    return _handle_chat_turn(chat_input, user, db, state_key)


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
    # Recipients remain demo context; subscriptions come from owned DB records.
    demo_context = (build_tool_catalog()[0]["context"]
                    if user.user_id == settings.DEFAULT_DEMO_USER_ID else {})
    agent_context = dict(
        account_id=account_id,
        account_locked=user.is_locked,
        recipients=[r for r in demo_context.get("recipients", []) if r["user_id"] == user.user_id],
        subscriptions=[s.model_dump(mode="json") for s in stored_records(db, user.user_id, account_id)],
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

  # 7. Otherwise: Mutation Action Proposals (Transfers & Cancellations)
  has_pending_actions = False
  pending_records = []
  if result.proposals:
      if primary_acc is None:
          return ChatOutput(conversation_id=chat_input.conversation_id,
                            reply="No owned account is available.", actions=[], status=ActionStatus.REJECTED)
      balance_str = f"{primary_acc.balance:.2f}" if primary_acc else "0.00"
      daily_total_str = f"{effective_total(primary_acc):.2f}" if primary_acc else "0.00"

      context = BankingContext(
          user_id=user.user_id,
          account_id=account_id,
          daily_transfer_total=daily_total_str,
          account_balance=balance_str,
          account_locked=user.is_locked,
      )

      for proposal in result.proposals:
          try:
              if proposal.tool == ToolName.REQUEST_SUBSCRIPTION_CANCEL:
                  args = validate_tool_arguments(proposal.tool, proposal.arguments)
                  cancellation_record(db, user.user_id, args.subscription_id, account_id)
              action_record, digest, tier = create_action_record(
                  user_id=user.user_id,
                  proposal=proposal,
                  source_account_id=account_id,
                  context=context,
              )

              if tier in ["YELLOW", "RED"]:
                  pending_records.append(action_record)
                  proposal.arguments["action_id"] = action_record.action_id
                  proposal.arguments["action_digest"] = digest
                  proposal.arguments["tier"] = tier
                  has_pending_actions = True
              else:
                  proposal.arguments["tier"] = "GREEN"

          except ValueError as e:
              reason = getattr(e, "reason_code", "INVALID_TOOL_ARGUMENTS")
              explanation = {
                  "ACCOUNT_LOCKED": "Your account is currently locked for state-changing operations.",
                  "SOURCE_ACCOUNT_MISMATCH": "The source account does not match your selected account.",
                  "ACCOUNT_MISMATCH": "The account does not match your authenticated context.",
                  "INVALID_TOOL_ARGUMENTS": "The proposed action contains invalid or unexpected fields.",
                  "SUBSCRIPTION_NOT_FOUND": "No verified subscription was found for this account.",
                  "ALREADY_CANCELLED": "This subscription has already been cancelled.",
                  "CANCELLATION_NOT_SUPPORTED": "Cancellation is not supported for this subscription.",
                  "AMBIGUOUS_SUBSCRIPTION": "More than one subscription matches; please clarify.",
              }.get(reason, "The action did not pass the security policy.")
              return ChatOutput(
                  conversation_id=chat_input.conversation_id,
                  reply=f"Action blocked ({reason}): {explanation}",
                  actions=[],
                  status=ActionStatus.REJECTED,
              )

      db.add_all(pending_records)
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

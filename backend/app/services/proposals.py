"""Validate and ticket proposals from either a user turn or trusted continuation."""
from contracts.models import ChatOutput, BankingContext
from contracts.enums import ActionStatus, ToolName
from contracts.tool_schemas import validate_tool_arguments
from app.services.actions import create_action_record
from app.services.adapters import agent_service
from app.services.subscriptions import cancellation_record
from app.services.daily_transfers import effective_total


def present_proposals(chat_input, user, db, result, primary_acc):
  account_id = primary_acc.account_id if primary_acc else None
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
                  if not agent_service.use_mock:
                      action_record.conversation_id = chat_input.conversation_id
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
      status = ActionStatus.PENDING_CONFIRMATION if has_pending_actions else ActionStatus.COMPLETED
  else:
      status = ActionStatus.COMPLETED

  return ChatOutput(
      conversation_id=chat_input.conversation_id,
      reply=result.reply,
      actions=result.proposals,
      status=status,
  )

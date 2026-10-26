"""Validate and ticket proposals from either a user turn or trusted continuation."""
import json

from contracts.models import ActionProposal, BankingContext
from app.api.schemas import AppChatOutput as ChatOutput, ApprovalMetadata, PresentedAction
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
  presented = []
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
              action_record, _, tier = create_action_record(
                  user_id=user.user_id,
                  proposal=proposal,
                  source_account_id=account_id,
                  context=context,
              )

              if tier in ["YELLOW", "RED"]:
                  if not agent_service.use_mock:
                      action_record.conversation_id = chat_input.conversation_id
                  pending_records.append(action_record)
                  presented.append(present_action(proposal, action_record))
                  has_pending_actions = True
              else:
                  raise ValueError("Mutation requires an approval ticket")

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
      actions=presented,
      status=status,
  )


def present_action(proposal, record):
    """Build a separate output model, never modify P1's proposal or digest input."""
    return PresentedAction(
        **proposal.model_dump(mode="python"),
        approval=ApprovalMetadata(action_id=record.action_id,
            action_digest=record.action_digest, tier=record.tier, status=record.status),
    )


def restore_cached_chat(db, user_id, conversation_id, cached):
    """Read old/new server caches using verified owned tickets, without calling P1.

    Old caches placed three metadata fields inside arguments. Only this stored
    response compatibility boundary removes them; incoming proposals remain strict.
    Current ticket status/tier are returned even if the cached reply is older.
    """
    from fastapi import HTTPException
    from app.db.models import ActionApprovalModel
    from app.services.actions import compute_action_digest

    if cached.get("conversation_id") != conversation_id:
        raise HTTPException(409, "Cached conversation could not be verified")
    restored = []
    for item in cached.get("actions", []):
        arguments = dict(item["arguments"])
        metadata = item.get("approval")
        if metadata is None:
            metadata = {key: arguments.pop(key, None)
                        for key in ("action_id", "action_digest", "tier")}
        record = db.query(ActionApprovalModel).filter_by(
            action_id=metadata.get("action_id"), user_id=user_id,
            conversation_id=conversation_id, proposal_id=item["proposal_id"],
            tool=item["tool"],
        ).populate_existing().first()
        if (record is None or metadata.get("action_digest") != record.action_digest
            or compute_action_digest(record.tool, json.loads(record.payload_json)) != record.action_digest
            or validate_tool_arguments(item["tool"], arguments).model_dump(mode="json") != json.loads(record.payload_json)):
            raise HTTPException(409, "Cached follow-up approval could not be verified")
        proposal = ActionProposal(proposal_id=item["proposal_id"], tool=item["tool"],
                                  arguments=arguments, rationale=item.get("rationale", ""))
        restored.append(present_action(proposal, record))
    result = {**cached, "actions": restored}
    if restored:
        statuses = {item.approval.status for item in restored}
        result["status"] = next(status for status in (
            ActionStatus.PENDING_MFA, ActionStatus.PENDING_CONFIRMATION,
            ActionStatus.FAILED, ActionStatus.REJECTED, ActionStatus.CANCELLED,
            ActionStatus.COMPLETED,
        ) if status in statuses)
    return ChatOutput(**result)

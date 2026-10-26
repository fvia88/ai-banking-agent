"""Deliver DB-verified outcomes after the financial transaction has committed."""
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import ActionApprovalModel, AuditLogModel, UserModel
from app.db.session import get_db
from app.services.actions import compute_action_digest
from app.services.adapters import agent_service
from app.services.agent_context import trusted_agent_context
from app.services.proposals import present_proposals, restore_cached_chat
from app.api.schemas import AppChatOutput
from app.services.session_store import (conversation_key, conversation_session,
    lock_conversation, set_conversation_state)
from contracts.models import ChatInput, ExecutionResult
from contracts.tool_schemas import validate_tool_arguments

router = APIRouter()
TERMINAL = {"COMPLETED", "FAILED", "REJECTED", "CANCELLED"}


class ContinuationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execution: ExecutionResult
    chat: AppChatOutput


def owned_action(db, user_id, action_id):
    record = db.query(ActionApprovalModel).filter_by(
        user_id=user_id, action_id=action_id,
    ).populate_existing().first()
    if record is None:
        raise HTTPException(404, "Action not found")
    return record


@router.post("/actions/{action_id}/continue", response_model=ContinuationOutput)
def continue_action(action_id: str, user: UserModel = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    record = owned_action(db, user.user_id, action_id)
    if agent_service.use_mock or not record.conversation_id:
        raise HTTPException(409, "This action has no real-agent conversation link")
    conversation_id = record.conversation_id
    key = conversation_key(user.user_id, conversation_id)
    with conversation_session(key):
        try:
            row = lock_conversation(db, user.user_id, conversation_id)
            record = owned_action(db, user.user_id, action_id)
            status = record.status
            if record.continuation_status == status and record.continuation_json:
                cached = json.loads(record.continuation_json)
                response = ContinuationOutput(execution=cached["execution"], chat=restore_cached_chat(
                    db, user.user_id, conversation_id, cached["chat"],
                ))
                record.continuation_json = response.model_dump_json()
                db.commit()
                return response
            state = json.loads(row.state_json)
            pending = next((item["proposal"] for item in state.get("pending_tool_requests", [])
                            if item["proposal"]["proposal_id"] == record.proposal_id), None)
            arguments = json.loads(record.payload_json)
            if (pending is None or pending["tool"] != record.tool
                or validate_tool_arguments(record.tool, pending["arguments"]).model_dump(mode="json") != arguments
                or compute_action_digest(record.tool, arguments) != record.action_digest):
                raise HTTPException(409, "Original agent proposal could not be verified")

            audit = db.query(AuditLogModel).filter_by(
                user_id=user.user_id, action_id=action_id, payload_digest=record.action_digest,
            )
            if status == "COMPLETED":
                audit_record = audit.filter_by(audit_id=record.audit_id).first() if record.audit_id else None
                if audit_record is None:
                    raise HTTPException(409, "Completion audit could not be verified")
            else:
                # This is evidence of observed status, never an execution audit.
                audit_record = AuditLogModel(
                    audit_id="aud_" + uuid4().hex, user_id=user.user_id,
                    action_id=action_id, action_type="ACTION_STATUS_OBSERVED",
                    payload_digest=record.action_digest, reason_code=status,
                    details=json.dumps({"status": status, "conversation_id": conversation_id}),
                )
                db.add(audit_record)
            execution = ExecutionResult(
                action_id=action_id, status=status, audit_id=audit_record.audit_id,
                message=("Backend confirmed completion." if status == "COMPLETED"
                         else f"Backend action status: {status}. Completion is not confirmed."),
            )
            account, context = trusted_agent_context(db, user)
            chat = ChatInput(conversation_id=conversation_id, message="Backend action status update")
            turn = agent_service.process_turn(chat, conversation_state=state, tool_results=[{
                "conversation_id": conversation_id, "proposal_id": record.proposal_id,
                "tool": record.tool, "arguments": arguments, "status": "success",
                "data": execution.model_dump(mode="json"),
            }], **context)
            next_state = turn.state.model_dump(mode="json")
            still_pending = any(item["proposal"]["proposal_id"] == record.proposal_id
                                for item in next_state.get("pending_tool_requests", []))
            if (status in TERMINAL) == still_pending:
                raise HTTPException(409, "Agent did not accept the verified status update")
            response = ContinuationOutput(execution=execution, chat=present_proposals(
                chat, user, db, turn.result, account,
            ))
            if response.chat.status.value == "REJECTED" and turn.result.proposals:
                # A dependent proposal can itself fail P2/P4 validation. Tell P1
                # it was refused rather than leaving an unticketed step pending.
                rejected_reply = response.chat.reply
                for proposal in turn.result.proposals:
                    original = next(item["proposal"] for item in next_state["pending_tool_requests"]
                                    if item["proposal"]["proposal_id"] == proposal.proposal_id)
                    refused = agent_service.process_turn(chat, conversation_state=next_state,
                        tool_results=[{
                            "conversation_id": conversation_id, "proposal_id": proposal.proposal_id,
                            "tool": original["tool"], "arguments": original["arguments"],
                            "status": "error", "data": {"code": "PROPOSAL_REJECTED"},
                        }], **context)
                    next_state = refused.state.model_dump(mode="json")
                    if any(item["proposal"]["proposal_id"] == proposal.proposal_id
                           for item in next_state["pending_tool_requests"]):
                        raise HTTPException(409, "Agent did not accept the proposal refusal")
                response.chat = response.chat.model_copy(update={
                    "reply": execution.message + " " + rejected_reply + " " + refused.result.reply,
                })
            row.state_json = json.dumps(next_state)
            # Do not deliver stale MFA/pending status if execution changed while
            # P1 was processing. All follow-up proposals/state roll back on a race.
            changed = db.query(ActionApprovalModel).filter_by(
                action_id=action_id, user_id=user.user_id, status=status,
            ).update({"continuation_status": status,
                      "continuation_json": response.model_dump_json()}, synchronize_session=False)
            if changed != 1:
                raise HTTPException(409, "Action status changed; retry conversation update")
            db.commit()
            set_conversation_state(key, next_state)
            return response
        except Exception:
            db.rollback()
            raise

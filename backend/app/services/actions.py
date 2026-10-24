"""Validate canonical mutation payloads before policy and approval storage."""
import json
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from contracts.enums import ToolName, ActionStatus
from contracts.models import ActionProposal, BankingContext
from contracts.tool_schemas import validate_tool_arguments
from app.db.models import ActionApprovalModel
from app.services.adapters import policy_service


class PolicyRejected(ValueError):
    def __init__(self, reason_code):
        self.reason_code = reason_code
        super().__init__(f"Action blocked by policy: {reason_code}")


def compute_action_digest(tool: str, payload: dict) -> str:
    """
    Computes a deterministic SHA-256 digest of the canonicalized payload.
    Keys are sorted so dictionary order doesn't change the hash.
    """
    canonical_json = json.dumps(
        {"tool": tool, "payload": payload},
        sort_keys=True,
        default=str
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

def create_action_record(
    user_id: str, proposal: ActionProposal, source_account_id: str,
    context: BankingContext,
) -> tuple[ActionApprovalModel, str, str]:
    if user_id != context.user_id or source_account_id != context.account_id:
        raise PolicyRejected("ACCOUNT_MISMATCH")
    if proposal.tool not in (ToolName.REQUEST_TRANSFER, ToolName.REQUEST_SUBSCRIPTION_CANCEL):
        raise PolicyRejected("UNKNOWN_TOOL")
    try:
        arguments = validate_tool_arguments(proposal.tool, proposal.arguments)
    except ValueError as exc:
        raise PolicyRejected("INVALID_TOOL_ARGUMENTS") from exc
    payload = arguments.model_dump(mode="json")
    canonical = proposal.model_copy(update={"arguments": payload})
    decision = policy_service.evaluate(canonical, context)
    if not decision.allowed_to_proceed:
        raise PolicyRejected(decision.reason_code)
    if not decision.requires_confirmation or decision.tier.value not in ("YELLOW", "RED"):
        raise PolicyRejected("INVALID_MUTATION_POLICY")
    now = datetime.now(timezone.utc)
    digest = compute_action_digest(proposal.tool.value, payload)
    record = ActionApprovalModel(
        action_id=f"act_{uuid.uuid4().hex[:12]}", proposal_id=proposal.proposal_id,
        user_id=user_id, tool=proposal.tool.value, tier=decision.tier.value,
        payload_json=json.dumps(payload), action_digest=digest,
        status=ActionStatus.PENDING_CONFIRMATION.value, failed_attempts=0,
        created_at=now, expires_at=now + timedelta(minutes=10),
    )
    return record, digest, decision.tier.value

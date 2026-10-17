# backend/app/services/actions.py
import json
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field
from contracts.enums import ToolName, ActionStatus
from contracts.models import ActionProposal
from app.db.models import ActionApprovalModel
from contracts.models import BankingContext
from app.services.adapters import policy_service

# Section 5 requirement: Strict typed models for proposed actions
class TransferArgs(BaseModel):
    recipient_id: str = Field(min_length=1)
    amount: Decimal = Field(gt=Decimal("0.00"))  # Prevents T04: Negative transfers
    currency: Literal["CNY"] = "CNY"
    source_account_id: str

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
    user_id: str,
    proposal: ActionProposal,
    source_account_id: str,
    context: BankingContext  # <-- Add context parameter
) -> tuple[ActionApprovalModel, str, str]:
    """
    Validates proposal arguments, evaluates risk policy tier,
    hashes payload, and prepares DB action record.
    """
    # 1. Evaluate risk tier (Green / Yellow / Red / Lock)
    decision = policy_service.evaluate(proposal, context)
    if not decision.allowed_to_proceed:
        raise ValueError(f"Action blocked by policy: {decision.reason_code}")

    action_id = f"act_{uuid.uuid4().hex[:12]}"
    
    # 2. Validate typed arguments strictly
    if proposal.tool == ToolName.REQUEST_TRANSFER:
        raw_recipient = proposal.arguments.get("recipient_id")
        if not raw_recipient or not str(raw_recipient).strip():
            raise ValueError("Missing or empty required field: 'recipient_id'")

        raw_amount = proposal.arguments.get("amount")
        if raw_amount is None:
            raise ValueError("Missing required field: 'amount'")

        validated_args = TransferArgs(
            recipient_id=str(raw_recipient).strip(),
            amount=Decimal(str(raw_amount)),
            currency=proposal.arguments.get("currency", "CNY"),
            source_account_id=source_account_id
        )
        payload_dict = {
            "recipient_id": validated_args.recipient_id,
            "amount": f"{validated_args.amount:.2f}",
            "currency": validated_args.currency,
            "source_account_id": validated_args.source_account_id
        }
    else:
        payload_dict = proposal.arguments

    # 3. Compute canonical SHA-256 digest
    digest = compute_action_digest(proposal.tool.value, payload_dict)

    # 4. Create database record with evaluated Tier
    now = datetime.now(timezone.utc)
    record = ActionApprovalModel(
        action_id=action_id,
        user_id=user_id,
        tool=proposal.tool.value,
        tier=decision.tier.value,  # Stored as "YELLOW" or "RED"
        payload_json=json.dumps(payload_dict, default=str),
        action_digest=digest,
        status=ActionStatus.PENDING_CONFIRMATION.value,
        failed_attempts=0,
        created_at=now,
        expires_at=now + timedelta(minutes=10)
    )

    return record, digest, decision.tier.value
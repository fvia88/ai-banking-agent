"""Private, caller-owned snapshots for the local conversation harness.

No database or global state. The caller retains the returned state between turns.
These are not replacements for the frozen shared request/response models.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from contracts.models import ID, PositiveMoney, AgentResult


class PendingTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original_message: str = Field(min_length=1, max_length=4000)
    source_account_id: ID | None = None
    recipient_text: str | None = None  # E.g. Alice: still unresolved, not an ID.
    recipient_id: ID | None = None  # Only fill after matching trusted recipients.
    amount: PositiveMoney | None = None  # Accepted amount; invalid input is not stored.


class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: ID
    pending_transfer: PendingTransfer | None = None
    awaiting: Literal["amount", "recipient"] | None = None

    @model_validator(mode="after")
    def clarification_requires_pending_transfer(self):
        if self.awaiting is not None and self.pending_transfer is None:
            raise ValueError("A clarification field requires a pending transfer")
        if self.pending_transfer:
            if self.awaiting == "amount" and self.pending_transfer.amount is not None:
                raise ValueError("An accepted amount cannot also be missing")
            if self.awaiting == "recipient" and self.pending_transfer.recipient_id is not None:
                raise ValueError("A resolved recipient cannot also be missing")
        return self


class ConversationTurn(BaseModel):
    """Private P1 helper output; does not change the public AgentResult DTO."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: AgentResult
    state: ConversationState

"""Private, caller-owned snapshots for the local conversation harness.

No database or global state. The caller retains the returned state between turns.
These are not replacements for the frozen shared request/response models.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from contracts.models import ID, PositiveMoney, AgentResult, ActionProposal
from contracts.tool_schemas import validate_tool_arguments


class PendingTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original_message: str = Field(min_length=1, max_length=4000)
    source_account_id: ID | None = None
    recipient_text: str | None = None  # E.g. Alice: still unresolved, not an ID.
    recipient_id: ID | None = None  # Only fill after matching trusted recipients.
    amount: PositiveMoney | None = None  # Accepted amount; invalid input is not stored.


class PendingToolRequest(BaseModel):
    """Original canonical proposal retained by the trusted caller, not the LLM."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    proposal: ActionProposal

    @model_validator(mode="after")
    def canonical_arguments_required(self):
        validate_tool_arguments(self.proposal.tool, self.proposal.arguments)
        return self


class PendingSpending(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original_message: str = Field(min_length=1, max_length=4000)
    account_id: ID


class PendingCancellation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original_message: str = Field(min_length=1, max_length=4000)


class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: ID
    pending_transfer: PendingTransfer | None = None
    pending_spending: PendingSpending | None = None
    pending_cancellation: PendingCancellation | None = None
    awaiting: Literal["amount", "recipient", "period", "subscription"] | None = None
    pending_tool_requests: tuple[PendingToolRequest, ...] = ()

    @model_validator(mode="after")
    def clarification_requires_matching_draft(self):
        ids = [request.proposal.proposal_id for request in self.pending_tool_requests]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate pending proposal IDs")
        if sum(draft is not None for draft in (self.pending_transfer, self.pending_spending,
                                               self.pending_cancellation)) > 1:
            raise ValueError("Only one unfinished draft is allowed")
        if (self.awaiting == "subscription") != (self.pending_cancellation is not None):
            raise ValueError("Subscription clarification requires a cancellation draft")
        if self.awaiting == "period" and self.pending_spending is None:
            raise ValueError("A month clarification requires a pending spending request")
        if self.pending_spending is not None and self.awaiting != "period":
            raise ValueError("Pending spending must await a month")
        if self.pending_transfer is not None and self.awaiting == "period":
            raise ValueError("A transfer cannot await a spending month")
        if self.awaiting in {"amount", "recipient"} and self.pending_transfer is None:
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

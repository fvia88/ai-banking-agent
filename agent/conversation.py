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


class PlanStep(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    step_id: Literal['cancel', 'transfer']
    request: str = Field(min_length=1, max_length=4000)
    depends_on: tuple[Literal['cancel'], ...] = ()
    status: Literal['waiting', 'clarifying', 'awaiting_result', 'completed'] = 'waiting'
    proposal_id: ID | None = None

    @model_validator(mode='after')
    def issued_step_requires_proposal(self):
        if self.status in {'awaiting_result', 'completed'} and self.proposal_id is None:
            raise ValueError('Issued plan step requires its original proposal ID')
        if self.status in {'waiting', 'clarifying'} and self.proposal_id is not None:
            raise ValueError('Unissued plan step cannot have a proposal ID')
        return self


class PendingPlan(BaseModel):
    """A fixed two-node dependency graph, never authority to execute tools."""
    model_config = ConfigDict(extra='forbid', frozen=True)
    plan_id: ID
    original_message: str = Field(min_length=1, max_length=4000)
    source_account_id: ID
    steps: tuple[PlanStep, PlanStep]
    paused: bool = False

    @model_validator(mode='after')
    def ordered_dependencies_required(self):
        cancel, transfer = self.steps
        if cancel.step_id != 'cancel' or cancel.depends_on or transfer.step_id != 'transfer' or transfer.depends_on != ('cancel',):
            raise ValueError('Only cancellation followed by a dependent transfer is supported')
        if cancel.status != 'completed' and transfer.status != 'waiting':
            raise ValueError('Transfer cannot start before cancellation is completed')
        if transfer.status == 'completed':
            raise ValueError('Completed plans must be removed from pending state')
        return self


class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: ID
    pending_transfer: PendingTransfer | None = None
    pending_spending: PendingSpending | None = None
    pending_cancellation: PendingCancellation | None = None
    awaiting: Literal["amount", "recipient", "period", "subscription"] | None = None
    pending_tool_requests: tuple[PendingToolRequest, ...] = ()
    pending_plan: PendingPlan | None = None

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
        if self.pending_plan:
            step = next(s for s in self.pending_plan.steps if s.status != 'completed')
            if step.status == 'awaiting_result':
                expected_tool = 'request_subscription_cancel' if step.step_id == 'cancel' else 'request_transfer'
                if not any(r.proposal.proposal_id == step.proposal_id and r.proposal.tool.value == expected_tool
                           for r in self.pending_tool_requests):
                    raise ValueError('Active plan step requires its canonical pending proposal')
            expected_fields = {'subscription'} if step.step_id == 'cancel' else {'amount', 'recipient'}
            if step.status == 'clarifying' and self.awaiting not in expected_fields:
                raise ValueError('Plan clarification must match its current step')
            if step.status != 'clarifying' and self.awaiting is not None:
                raise ValueError('Waiting plan cannot carry an unrelated clarification draft')
        return self


class ConversationTurn(BaseModel):
    """Private P1 helper output; does not change the public AgentResult DTO."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: AgentResult
    state: ConversationState

"""Canonical shared DTOs. All modules import from here; no duplicate models."""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from .enums import ActionStatus, Cadence, Direction, Tier, ToolName

Money = Annotated[Decimal, Field(max_digits=16, decimal_places=2)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=2)]
NonnegativeMoney = Annotated[Decimal, Field(ge=0, max_digits=16, decimal_places=2)]
ID = Annotated[str, StringConstraints(min_length=1, max_length=128)]
Currency = Literal["CNY"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False, validate_assignment=True)


class User(StrictModel):
    user_id: ID
    display_name: str


class Account(StrictModel):
    account_id: ID
    user_id: ID
    currency: Currency = "CNY"
    balance: NonnegativeMoney
    locked: bool = False


class Recipient(StrictModel):
    recipient_id: ID
    user_id: ID
    display_name: str
    account_number_masked: str


class Transaction(StrictModel):
    transaction_id: ID
    account_id: ID
    timestamp: datetime
    amount: PositiveMoney
    direction: Direction
    merchant: str
    category: str
    note: str = ""

    @field_validator("timestamp")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must contain a timezone")
        return value


class Subscription(StrictModel):
    subscription_id: ID
    user_id: ID
    merchant: str
    estimated_amount: PositiveMoney
    cadence: Cadence
    status: Literal["active", "cancelled"]
    cancellation_supported: bool


class ChatInput(StrictModel):
    conversation_id: ID
    message: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class ActionProposal(StrictModel):
    proposal_id: ID
    tool: ToolName
    arguments: dict[str, object]
    rationale: str = ""


class AgentResult(StrictModel):
    reply: str
    proposals: list[ActionProposal] = Field(default_factory=list)
    needs_clarification: bool = False


class BankingContext(StrictModel):
    user_id: ID  # injected by authenticated backend, NEVER from LLM
    account_id: ID
    daily_transfer_total: NonnegativeMoney
    account_balance: NonnegativeMoney
    account_locked: bool = False


class PolicyDecision(StrictModel):
    tier: Tier
    allowed_to_proceed: bool
    requires_confirmation: bool
    requires_mfa: bool
    reason_code: str


class ChatOutput(StrictModel):
    conversation_id: ID
    reply: str
    actions: list[ActionProposal] = Field(default_factory=list)
    status: ActionStatus


class Anomaly(StrictModel):
    transaction_id: ID
    reason: str


class SpendingReport(StrictModel):
    period: Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
    currency: Currency = "CNY"
    total_spending: NonnegativeMoney
    category_totals: dict[str, NonnegativeMoney]
    anomalies: list[Anomaly] = Field(default_factory=list)


class SubscriptionCandidate(StrictModel):
    subscription_id: ID
    merchant: str
    estimated_amount: PositiveMoney
    cadence: Cadence
    confidence: Annotated[float, Field(ge=0, le=1)]
    evidence_transaction_ids: list[ID]
    cancellation_supported: bool


class SubscriptionReport(StrictModel):
    candidates: list[SubscriptionCandidate] = Field(default_factory=list)


class CancellationAssessment(StrictModel):
    eligible: bool
    requires_confirmation: Literal[True] = True
    reason_code: str


class ExecutionResult(StrictModel):
    action_id: ID  # server-issued; NOT proposal_id
    status: ActionStatus
    message: str
    audit_id: ID


class ErrorResponse(StrictModel):
    code: str
    message: str
    request_id: ID

"""Shared API request and response DTOs for approval flow."""
from datetime import datetime
from pydantic import field_validator
from .models import ID, StrictModel, ExecutionResult, Account, Transaction, SubscriptionReport


class HealthResponse(StrictModel):
    status: str = "ok"


class AccountsResponse(StrictModel):
    accounts: list[Account]


class TransactionsResponse(StrictModel):
    transactions: list[Transaction]


class ConfirmActionRequest(StrictModel):
    confirmation_id: ID
    action_digest: str
    idempotency_key: ID


class VerifyActionRequest(StrictModel):
    verification_code: str
    idempotency_key: ID


class PendingAction(StrictModel):
    action_id: ID
    proposal_id: ID
    action_digest: str
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value: datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at requires timezone")
        return value


class AuditEvent(StrictModel):
    audit_id: ID
    action_id: ID
    event_type: str
    timestamp: datetime
    reason_code: str


class AuditResponse(StrictModel):
    events: list[AuditEvent]

# backend/app/services/mfa.py
"""
P3: simulated OTP / MFA challenge lifecycle for RED-tier actions.

A challenge is bound to one ActionApprovalModel row (and therefore to its
owner and its current state). It has an issue time, an expiry, a
failed-attempt limit and a consumed marker. No SMS/email is sent: the code is
a fixed, clearly labelled simulated value.
"""
from datetime import datetime, timedelta, timezone
from enum import Enum
from sqlalchemy.orm import Session
from contracts.enums import ActionStatus
from app.db.models import ActionApprovalModel

SIMULATED_OTP_CODE = "123456"
MFA_CODE_TTL = timedelta(minutes=5)
MAX_FAILED_ATTEMPTS = 3


class ChallengeCheck(str, Enum):
    OK = "OK"
    WRONG_CODE = "WRONG_CODE"
    TOO_MANY_ATTEMPTS = "TOO_MANY_ATTEMPTS"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"
    NOT_ISSUED = "NOT_ISSUED"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def issue_challenge(record: ActionApprovalModel, now: datetime) -> None:
    """Move the action to PENDING_MFA with a fresh challenge. Caller commits."""
    record.status = ActionStatus.PENDING_MFA.value
    record.verification_code = SIMULATED_OTP_CODE
    record.failed_attempts = 0
    record.mfa_issued_at = now
    # The challenge can never outlive the action proposal itself.
    record.mfa_expires_at = min(now + MFA_CODE_TTL, as_utc(record.expires_at))
    record.mfa_consumed_at = None


def remaining_attempts(record: ActionApprovalModel) -> int:
    return max(MAX_FAILED_ATTEMPTS - int(record.failed_attempts or 0), 0)


def check_challenge(record: ActionApprovalModel, code: str, now: datetime) -> ChallengeCheck:
    """Pure check of the submitted code against the stored challenge. Does not mutate."""
    if record.verification_code is None or record.mfa_expires_at is None:
        return ChallengeCheck.NOT_ISSUED
    if record.mfa_consumed_at is not None:
        return ChallengeCheck.CONSUMED
    if remaining_attempts(record) <= 0:
        return ChallengeCheck.TOO_MANY_ATTEMPTS
    if as_utc(record.mfa_expires_at) <= now:
        return ChallengeCheck.EXPIRED
    if code != record.verification_code:
        return ChallengeCheck.WRONG_CODE
    return ChallengeCheck.OK


def record_failed_attempt(db: Session, record: ActionApprovalModel) -> int:
    """Atomically increment failed_attempts; returns attempts remaining. Caller commits."""
    db.query(ActionApprovalModel).filter(
        ActionApprovalModel.action_id == record.action_id
    ).update(
        {ActionApprovalModel.failed_attempts: ActionApprovalModel.failed_attempts + 1},
        synchronize_session=False,
    )
    db.flush()
    db.refresh(record)
    return remaining_attempts(record)


def claim_challenge(db: Session, record: ActionApprovalModel, now: datetime) -> bool:
    """
    Consume the challenge with a single conditional UPDATE so that only one
    request can ever move on to execution. Returns False if another request
    already consumed it or the action left PENDING_MFA. Caller commits.
    """
    claimed = db.query(ActionApprovalModel).filter(
        ActionApprovalModel.action_id == record.action_id,
        ActionApprovalModel.user_id == record.user_id,
        ActionApprovalModel.status == ActionStatus.PENDING_MFA.value,
        ActionApprovalModel.mfa_consumed_at.is_(None),
    ).update(
        {ActionApprovalModel.mfa_consumed_at: now},
        synchronize_session=False,
    )
    db.flush()
    db.refresh(record)
    return claimed == 1

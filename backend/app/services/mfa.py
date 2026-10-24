# backend/app/services/mfa.py
"""
P3: simulated OTP / MFA challenge lifecycle for RED-tier actions.

A challenge is bound to one ActionApprovalModel row (and therefore to its
owner and its current state). It has an issue time, an expiry, a
failed-attempt limit and a consumed marker.

Delivery is simulated (hackathon shortcut): no SMS/email is sent. Each code is
a random 6-digit value printed to the backend console and shown in the
owner's demo inbox (GET /api/v1/demo/otp-inbox).
"""
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from sqlalchemy.orm import Session
from contracts.enums import ActionStatus
from app.db.models import ActionApprovalModel

OTP_CODE_DIGITS = 6
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


def generate_code() -> str:
    return f"{secrets.randbelow(10 ** OTP_CODE_DIGITS):0{OTP_CODE_DIGITS}d}"


def deliver_to_demo_console(record: ActionApprovalModel) -> None:
    """Simulated delivery channel: print the code where the demo operator can see it."""
    print(
        f"[DEMO OTP] user={record.user_id} action={record.action_id} "
        f"code={record.verification_code} expires_at={as_utc(record.mfa_expires_at).isoformat()}",
        flush=True,
    )


def issue_challenge(record: ActionApprovalModel, now: datetime) -> None:
    """Move the action to PENDING_MFA with a fresh challenge. Caller commits."""
    record.status = ActionStatus.PENDING_MFA.value
    record.verification_code = generate_code()
    record.failed_attempts = 0
    record.mfa_issued_at = now
    # The challenge can never outlive the action proposal itself.
    record.mfa_expires_at = min(now + MFA_CODE_TTL, as_utc(record.expires_at))
    record.mfa_consumed_at = None
    deliver_to_demo_console(record)


def active_challenges(db: Session, user_id: str, now: datetime) -> list[ActionApprovalModel]:
    """The user's demo inbox: unexpired, unused challenges still awaiting verification."""
    pending = db.query(ActionApprovalModel).filter(
        ActionApprovalModel.user_id == user_id,
        ActionApprovalModel.status == ActionStatus.PENDING_MFA.value,
        ActionApprovalModel.mfa_consumed_at.is_(None),
    ).order_by(ActionApprovalModel.mfa_issued_at.desc()).all()
    return [r for r in pending if r.mfa_expires_at is not None and as_utc(r.mfa_expires_at) > now]


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
    if not secrets.compare_digest(str(code), record.verification_code):
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
    already consumed it or the action left PENDING_MFA.

    The caller must commit the claim in the SAME transaction as the execution
    and the COMPLETED status. The UPDATE holds the row's write lock until that
    commit, so a racing request waits and then matches zero rows; if execution
    fails, rolling back releases the claim and no half-finished state remains.
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


def is_stranded(record: ActionApprovalModel) -> bool:
    """
    Consumed challenge on an action that never completed. Only rows written by
    the old two-commit flow (claim committed before execution) can look like
    this; the execution never committed, so no money moved.
    """
    return (
        record.status == ActionStatus.PENDING_MFA.value
        and record.mfa_consumed_at is not None
        and record.audit_id is None
    )


def fail_after_rejected_execution(db: Session, record: ActionApprovalModel, now: datetime) -> None:
    """
    After an executor refusal (e.g. insufficient funds) has been rolled back,
    retire the action as FAILED with its challenge consumed so the same code
    cannot be replayed. Conditional so it never overwrites a concurrent
    COMPLETED. Caller commits.
    """
    db.query(ActionApprovalModel).filter(
        ActionApprovalModel.action_id == record.action_id,
        ActionApprovalModel.status == ActionStatus.PENDING_MFA.value,
    ).update(
        {
            ActionApprovalModel.status: ActionStatus.FAILED.value,
            ActionApprovalModel.mfa_consumed_at: now,
        },
        synchronize_session=False,
    )

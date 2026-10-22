# backend/app/api/approvals.py
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from contracts.enums import ActionStatus, Tier, ToolName
from contracts.models import ExecutionResult
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel, ActionApprovalModel, AuditLogModel
from app.services.executor import execute_transfer, execute_subscription_cancel
from app.services import mfa

router = APIRouter()

def _execute_action(db: Session, user: UserModel, record: ActionApprovalModel) -> tuple[str, str]:
    """Whitelisted dispatch: only known mutation tools reach an executor. Unknown tools fail closed."""
    if record.tool == ToolName.REQUEST_TRANSFER.value:
        return execute_transfer(db, user, record), "Action confirmed and executed successfully."
    if record.tool == ToolName.REQUEST_SUBSCRIPTION_CANCEL.value:
        return execute_subscription_cancel(db, user, record), "Subscription cancellation confirmed and executed successfully."
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported action tool '{record.tool}'. Refusing to execute."
    )

class ConfirmActionRequest(BaseModel):
    confirmation_id: str
    action_digest: str
    idempotency_key: str | None = None

class VerifyActionRequest(BaseModel):
    verification_code: str

@router.post("/actions/{action_id}/confirm", response_model=ExecutionResult)
def confirm_action(
    action_id: str,
    payload: ConfirmActionRequest,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    record = db.query(ActionApprovalModel).filter(
        ActionApprovalModel.action_id == action_id,
        ActionApprovalModel.user_id == user.user_id
    ).first()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Action '{action_id}' not found for current user"
        )

    # Anti-Tampering Check
    if payload.action_digest != record.action_digest:
        record.status = ActionStatus.REJECTED.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload digest mismatch. Tampering detected or invalid payload."
        )

    # Test Vector T06: Idempotent replay protection
    # If already COMPLETED, return success without moving money again!
    if record.status == ActionStatus.COMPLETED.value:
        return ExecutionResult(
            action_id=record.action_id,
            status=ActionStatus.COMPLETED,
            message="Action already confirmed and executed (idempotent replay).",
            audit_id=record.audit_id or "aud_replayed"
        )

    # Prevent confirming actions in any other terminal state
    if record.status != ActionStatus.PENDING_CONFIRMATION.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action cannot be confirmed (current status: {record.status})"
        )

    # Expiration check
    now = mfa.utc_now()
    if mfa.as_utc(record.expires_at) < now:
        record.status = ActionStatus.CANCELLED.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action proposal has expired"
        )

    # RED Tier: Issue MFA challenge (P3 lifecycle in app/services/mfa.py)
    if record.tier == Tier.RED.value:
        mfa.issue_challenge(record, now)
        audit_id = f"aud_{uuid.uuid4().hex[:10]}"
        db.add(AuditLogModel(
            audit_id=audit_id,
            action_id=record.action_id,
            user_id=user.user_id,
            action_type="MFA_CHALLENGE_ISSUED",
            payload_digest=record.action_digest,
            reason_code="RED_TIER_MFA_REQUIRED",
            details=f"Simulated OTP challenge issued; expires at {record.mfa_expires_at.isoformat()}."
        ))
        db.commit()

        ttl_minutes = int(mfa.MFA_CODE_TTL.total_seconds() // 60)
        return ExecutionResult(
            action_id=record.action_id,
            status=ActionStatus.PENDING_MFA,
            message=(
                f"Strong verification (MFA) required. A simulated verification code ('{mfa.SIMULATED_OTP_CODE}') "
                f"has been issued (no SMS/email is sent). It expires in {ttl_minutes} minutes; "
                f"{mfa.MAX_FAILED_ATTEMPTS} attempts allowed."
            ),
            audit_id=audit_id
        )

    # YELLOW Tier: Execute atomically and complete
    audit_id, message = _execute_action(db, user, record)

    record.status = ActionStatus.COMPLETED.value
    record.audit_id = audit_id
    db.commit()

    return ExecutionResult(
        action_id=record.action_id,
        status=ActionStatus.COMPLETED,
        message=message,
        audit_id=audit_id
    )

@router.post("/actions/{action_id}/verify", response_model=ExecutionResult)
def verify_action(
    action_id: str,
    payload: VerifyActionRequest,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    record = db.query(ActionApprovalModel).filter(
        ActionApprovalModel.action_id == action_id,
        ActionApprovalModel.user_id == user.user_id
    ).first()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Action '{action_id}' not found for current user"
        )

    # Idempotent replay for verify
    if record.status == ActionStatus.COMPLETED.value:
        return ExecutionResult(
            action_id=record.action_id,
            status=ActionStatus.COMPLETED,
            message="Action already verified and executed (idempotent replay).",
            audit_id=record.audit_id or "aud_replayed"
        )

    if record.status != ActionStatus.PENDING_MFA.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action is not awaiting MFA verification (current status: {record.status})"
        )

    # Re-check action expiry: a correct code cannot revive an expired proposal
    now = mfa.utc_now()
    if mfa.as_utc(record.expires_at) <= now:
        record.status = ActionStatus.CANCELLED.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action proposal has expired"
        )

    check = mfa.check_challenge(record, payload.verification_code, now)

    if check == mfa.ChallengeCheck.NOT_ISSUED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verification challenge has been issued for this action."
        )

    if check == mfa.ChallengeCheck.CONSUMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Verification code already used; this action is being processed."
        )

    if check == mfa.ChallengeCheck.EXPIRED:
        record.status = ActionStatus.CANCELLED.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired. Please start a new request."
        )

    # Anti-Brute Force (Max 3 failed attempts)
    if check in (mfa.ChallengeCheck.WRONG_CODE, mfa.ChallengeCheck.TOO_MANY_ATTEMPTS):
        remaining_attempts = (
            mfa.record_failed_attempt(db, record) if check == mfa.ChallengeCheck.WRONG_CODE else 0
        )

        if remaining_attempts <= 0:
            record.status = ActionStatus.FAILED.value
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Too many failed verification attempts. Action has been locked and marked FAILED."
            )

        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid verification code. {remaining_attempts} attempt(s) remaining."
        )

    # Execution-time controls: a correct code cannot override a newly locked account
    if user.is_locked:
        record.status = ActionStatus.REJECTED.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is locked. Mutations are blocked."
        )
    # TODO(P4): re-run security.policy.evaluate_action against the current
    # BankingContext here once the real policy bridge replaces the mock.

    # Consume the challenge atomically; only one request may execute
    if not mfa.claim_challenge(db, record, now):
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Verification code already used; this action is being processed."
        )
    db.commit()

    # MFA verified -> Execute atomically and complete
    try:
        audit_id, _ = _execute_action(db, user, record)
    except HTTPException:
        # Executors validate before mutating; the consumed challenge cannot be reused.
        record.status = ActionStatus.FAILED.value
        db.commit()
        raise
    record.status = ActionStatus.COMPLETED.value
    record.audit_id = audit_id
    db.commit()

    return ExecutionResult(
        action_id=record.action_id,
        status=ActionStatus.COMPLETED,
        message="MFA verification successful. Action executed.",
        audit_id=audit_id
    )
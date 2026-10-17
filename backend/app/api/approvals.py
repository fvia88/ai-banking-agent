# backend/app/api/approvals.py
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from contracts.enums import ActionStatus, Tier
from contracts.models import ExecutionResult
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel, ActionApprovalModel, AuditLogModel
from app.services.executor import execute_transfer

router = APIRouter()

class ConfirmActionRequest(BaseModel):
    confirmation_id: str
    action_digest: str

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
            audit_id="aud_replayed"
        )

    # Prevent confirming actions in any other terminal state
    if record.status != ActionStatus.PENDING_CONFIRMATION.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action cannot be confirmed (current status: {record.status})"
        )

    # Expiration check
    now = datetime.now(timezone.utc)
    expires_at = record.expires_at if record.expires_at.tzinfo else record.expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        record.status = ActionStatus.CANCELLED.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action proposal has expired"
        )

    # RED Tier: Issue MFA challenge
    if record.tier == Tier.RED.value:
        record.status = ActionStatus.PENDING_MFA.value
        record.verification_code = "123456"
        audit_id = f"aud_{uuid.uuid4().hex[:10]}"
        db.commit()

        return ExecutionResult(
            action_id=record.action_id,
            status=ActionStatus.PENDING_MFA,
            message="Strong verification (MFA) required. A simulated verification code ('123456') has been issued.",
            audit_id=audit_id
        )

    # YELLOW Tier: Execute transfer atomically and complete
    audit_id = execute_transfer(db, user, record)
    record.status = ActionStatus.COMPLETED.value
    db.commit()

    return ExecutionResult(
        action_id=record.action_id,
        status=ActionStatus.COMPLETED,
        message="Action confirmed and executed successfully.",
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
            audit_id="aud_replayed"
        )

    if record.status != ActionStatus.PENDING_MFA.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action is not awaiting MFA verification (current status: {record.status})"
        )

    # Anti-Brute Force (Max 3 failed attempts)
    if payload.verification_code != record.verification_code:
        record.failed_attempts = int(record.failed_attempts) + 1
        remaining_attempts = 3 - int(record.failed_attempts)

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

    # MFA verified -> Execute transfer atomically and complete
    audit_id = execute_transfer(db, user, record)
    record.status = ActionStatus.COMPLETED.value
    db.commit()

    return ExecutionResult(
        action_id=record.action_id,
        status=ActionStatus.COMPLETED,
        message="MFA verification successful. Action executed.",
        audit_id=audit_id
    )
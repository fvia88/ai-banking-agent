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

router = APIRouter()

class ConfirmActionRequest(BaseModel):
    confirmation_id: str
    action_digest: str

@router.post("/actions/{action_id}/confirm", response_model=ExecutionResult)
def confirm_action(
    action_id: str,
    payload: ConfirmActionRequest,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. Existence and ownership check
    record = db.query(ActionApprovalModel).filter(
        ActionApprovalModel.action_id == action_id,
        ActionApprovalModel.user_id == user.user_id
    ).first()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Action '{action_id}' not found for current user"
        )

    # 2. Status check (Prevent double-confirmations)
    if record.status != ActionStatus.PENDING_CONFIRMATION.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action is not pending confirmation (current status: {record.status})"
        )

    # 3. Expiration check
    now = datetime.now(timezone.utc)
    # Ensure record.expires_at is timezone-aware for comparison
    expires_at = record.expires_at if record.expires_at.tzinfo else record.expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        record.status = ActionStatus.CANCELLED.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action proposal has expired"
        )

    # 4. Anti-Tampering Check: digest comparison
    if payload.action_digest != record.action_digest:
        record.status = ActionStatus.REJECTED.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload digest mismatch. Tampering detected or invalid payload."
        )

    # Generate audit event ID
    audit_id = f"aud_{uuid.uuid4().hex[:10]}"

    # 5. Permission Tier Branching (Yellow vs. Red)
    if record.tier == Tier.RED.value:
        # RED Tier: Strong verification required -> Transition to PENDING_MFA
        # In demo mode, we generate a fixed or simple simulated code: '123456'
        record.status = ActionStatus.PENDING_MFA.value
        record.verification_code = "123456"

        audit_entry = AuditLogModel(
            audit_id=audit_id,
            user_id=user.user_id,
            action_type="ACTION_CONFIRMED_AWAITING_MFA",
            payload_digest=record.action_digest,
            details=f"Red tier action {action_id} confirmed. MFA challenge issued."
        )
        db.add(audit_entry)
        db.commit()

        return ExecutionResult(
            action_id=record.action_id,
            status=ActionStatus.PENDING_MFA,
            message="Strong verification (MFA) required. A simulated verification code ('123456') has been issued.",
            audit_id=audit_id
        )

    # YELLOW Tier: Direct approval -> Transition to COMPLETED
    record.status = ActionStatus.COMPLETED.value
    
    audit_entry = AuditLogModel(
        audit_id=audit_id,
        user_id=user.user_id,
        action_type="ACTION_CONFIRMED_AND_EXECUTED",
        payload_digest=record.action_digest,
        details=f"Yellow tier action {action_id} confirmed and executed."
    )
    db.add(audit_entry)
    db.commit()

    return ExecutionResult(
        action_id=record.action_id,
        status=ActionStatus.COMPLETED,
        message="Action confirmed and executed successfully.",
        audit_id=audit_id
    )

class VerifyActionRequest(BaseModel):
    verification_code: str

@router.post("/actions/{action_id}/verify", response_model=ExecutionResult)
def verify_action(
    action_id: str,
    payload: VerifyActionRequest,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. Existence and ownership check
    record = db.query(ActionApprovalModel).filter(
        ActionApprovalModel.action_id == action_id,
        ActionApprovalModel.user_id == user.user_id
    ).first()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Action '{action_id}' not found for current user"
        )

    # 2. Status check (Must be waiting for MFA)
    if record.status != ActionStatus.PENDING_MFA.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action is not awaiting MFA verification (current status: {record.status})"
        )

    # 3. Expiration check
    now = datetime.now(timezone.utc)
    expires_at = record.expires_at if record.expires_at.tzinfo else record.expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        record.status = ActionStatus.CANCELLED.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action proposal has expired"
        )

    # 4. Anti-Brute Force / Rate Limiting (Max 3 failed attempts)
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

    # 5. Success Path: Code is valid
    record.status = ActionStatus.COMPLETED.value
    audit_id = f"aud_{uuid.uuid4().hex[:10]}"

    audit_entry = AuditLogModel(
        audit_id=audit_id,
        user_id=user.user_id,
        action_type="ACTION_MFA_VERIFIED_AND_EXECUTED",
        payload_digest=record.action_digest,
        details=f"Red tier action {action_id} verified via simulated MFA and marked COMPLETED."
    )
    db.add(audit_entry)
    db.commit()

    return ExecutionResult(
        action_id=record.action_id,
        status=ActionStatus.COMPLETED,
        message="MFA verification successful. Action confirmed and executed.",
        audit_id=audit_id
    )
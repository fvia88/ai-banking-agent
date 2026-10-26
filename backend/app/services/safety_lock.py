"""P2 persistence around P4's existing locked-account decision; no policy algorithm changes."""
import json
from datetime import timedelta
from uuid import uuid4

from app.db.models import ActionApprovalModel, AuditLogModel, UserModel
from app.services import mfa

FAILURE_LIMIT = 3
FAILURE_WINDOW = timedelta(minutes=15)
LOCK_REASON = "REPEATED_VERIFICATION_FAILURES"
PENDING = ("PENDING_CONFIRMATION", "PENDING_MFA")


def audit_event(db, user, event, reason, details, record=None):
    row = AuditLogModel(
        audit_id="aud_" + uuid4().hex, user_id=user.user_id,
        action_id=record.action_id if record else None,
        action_type=event, payload_digest=record.action_digest if record else "security_operator",
        reason_code=reason, details=json.dumps(details, sort_keys=True),
    )
    db.add(row)
    return row.audit_id


def record_verification_failure(db, user, record, reason, now):
    """Caller holds the approval guard's user lock and owns commit/rollback.

    Count wrong OTPs and bad confirmation digests across actions/conversations.
    The observation window expires; an activated lock never expires automatically.
    """
    if user.is_locked:
        return False
    started = user.security_failure_window_at
    if started is None or now - mfa.as_utc(started) >= FAILURE_WINDOW:
        user.security_failure_window_at = now
        user.security_failure_count = 0
    user.security_failure_count = int(user.security_failure_count or 0) + 1
    audit_event(db, user, "VERIFICATION_FAILURE", reason,
                {"failure_count": user.security_failure_count}, record)
    if user.security_failure_count < FAILURE_LIMIT:
        return False
    user.is_locked = True
    user.safety_locked_at = now
    user.safety_lock_reason = LOCK_REASON
    # Retire other pending approvals so a manual unlock cannot revive old OTPs.
    pending = db.query(ActionApprovalModel).filter(
        ActionApprovalModel.user_id == user.user_id,
        ActionApprovalModel.action_id != record.action_id,
        ActionApprovalModel.status.in_(PENDING),
    ).all()
    for other in pending:
        other.status = "REJECTED"
        other.verification_code = None
        other.mfa_consumed_at = now
        audit_event(db, user, "ACTION_REJECTED_SAFETY_LOCK", LOCK_REASON,
                    {"status": "REJECTED"}, other)
    audit_event(db, user, "SAFETY_LOCK_TRIGGERED", LOCK_REASON,
                {"failure_count": user.security_failure_count, "manual_reset_required": True}, record)
    return True


def reset_safety_lock(db, user_id, reason):
    """Local demo-operator operation, never exposed as an agent tool or HTTP unlock."""
    if not reason.strip() or len(reason) > 200:
        raise ValueError("A review reason of 1-200 characters is required")
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
    # Same user-first write lock as approval execution, including on SQLite.
    found = db.query(UserModel).filter_by(user_id=user_id).update(
        {UserModel.is_locked: UserModel.is_locked}, synchronize_session=False)
    if found != 1:
        raise ValueError("User not found")
    user = db.query(UserModel).filter_by(user_id=user_id).populate_existing().one()
    if not user.is_locked or user.safety_lock_reason != LOCK_REASON:
        raise ValueError("User does not have an automatic safety lock; existing manual locks are preserved")
    user.is_locked = False
    user.security_failure_count = 0
    user.security_failure_window_at = None
    user.safety_locked_at = None
    user.safety_lock_reason = None
    return audit_event(db, user, "SAFETY_LOCK_RESET", "DEMO_OPERATOR_REVIEW",
                       {"review_reason": reason.strip(), "operator": "local_demo_operator"})

"""Database-backed approval serialization; shared by confirm and verify.

Acquire locks in user -> action -> account order. A no-op user UPDATE takes a
row lock on PostgreSQL and a writer reservation on SQLite. Serializing all
approvals for one user deliberately trades some parallelism for a simple lock
order, protecting current user-lock state as well as competing owned accounts.
No process-local mutex or new public action status is required.
"""
from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from contracts.enums import ActionStatus
from contracts.models import ExecutionResult
from app.db.models import ActionApprovalModel, UserModel


PENDING = (ActionStatus.PENDING_CONFIRMATION.value, ActionStatus.PENDING_MFA.value)


def claim_pending_action(db: Session, user_id: str, record: ActionApprovalModel, expected_status: str):
    """Hold the user and action write locks until this transaction ends.

    The conditional no-op UPDATE is the claim: no other approval for this user
    can evaluate financial state until we commit/roll back. Refresh the identity
    map after waiting so an earlier ORM snapshot cannot drive execution.
    """
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
    with db.no_autoflush:
        found = db.query(UserModel).filter(UserModel.user_id == user_id).update(
            {UserModel.is_locked: UserModel.is_locked}, synchronize_session=False,
        )
        if found != 1:
            raise HTTPException(status_code=404, detail="User not found")
        claimed = db.query(ActionApprovalModel).filter(
            ActionApprovalModel.action_id == record.action_id,
            ActionApprovalModel.user_id == user_id,
            ActionApprovalModel.status == expected_status,
        ).update({ActionApprovalModel.status: ActionApprovalModel.status}, synchronize_session=False)
        if claimed != 1:
            raise HTTPException(status_code=409, detail="Action state changed while another request was processing it. Retry to read its final result.")
        db.refresh(record)


def execute_claimed_action(
    db: Session, *, user_id: str, action_id: str,
    operation: Callable[[ActionApprovalModel, UserModel], ExecutionResult],
) -> ExecutionResult:
    """Run approval decisions and successful execution within one locked transaction.

    Authentication may already have opened the Session transaction. Reuse it;
    never commit between fresh policy evaluation and the financial execution.
    Completed/terminal actions are immutable replay/error paths, not new claims.
    """
    try:
        record = db.query(ActionApprovalModel).filter(
            ActionApprovalModel.action_id == action_id,
            ActionApprovalModel.user_id == user_id,
        ).populate_existing().first()
        if record is None:
            raise HTTPException(status_code=404, detail=f"Action '{action_id}' not found for current user")
        if record.status in PENDING:
            claim_pending_action(db, user_id, record, record.status)
        user = db.query(UserModel).filter(UserModel.user_id == user_id).populate_existing().one()
        result = operation(record, user)
        # Claim, fresh checks, MFA consumption, account/ledger/audit writes and
        # completion (or challenge issuance) become durable together.
        db.commit()
        return result
    except OperationalError as exc:
        db.rollback()
        code = getattr(exc.orig, "pgcode", None)
        sqlite_code = getattr(exc.orig, "sqlite_errorcode", None)
        if code in ("55P03", "40P01", "40001") or (
            sqlite_code is not None and (sqlite_code & 0xff) in (5, 6)
        ):
            raise HTTPException(status_code=409, detail="Another request is updating this action or account. Retry the same action.") from exc
        raise
    except Exception:
        db.rollback()
        raise

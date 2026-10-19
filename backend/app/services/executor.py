# backend/app/services/executor.py
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.db.models import UserModel, AccountModel, TransactionModel, ActionApprovalModel, AuditLogModel

def execute_transfer(
    db: Session,
    user: UserModel,
    record: ActionApprovalModel
) -> str:
    """
    Performs atomic transfer:
    1. Validates sufficient funds
    2. Deducts sender balance
    3. Increments daily_transfer_total
    4. Creates official Transaction entry
    5. Writes to immutable Audit log
    """
    payload = json.loads(record.payload_json)
    amount = Decimal(str(payload["amount"]))
    source_acc_id = payload.get("source_account_id")
    recipient_id = payload.get("recipient_id", "Unknown Recipient")

    # Fetch source account
    account = db.query(AccountModel).filter(
        AccountModel.account_id == source_acc_id,
        AccountModel.user_id == user.user_id
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source account '{source_acc_id}' not found."
        )

    # 1. Sufficient funds check (prevent overdraft)
    if account.balance < amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient funds. Account balance is {account.balance:.2f} CNY, but attempted transfer is {amount:.2f} CNY."
        )

    # 2. Atomic balance & daily total adjustment
    account.balance -= amount
    account.daily_transfer_total += amount

    # 3. Create official ledger transaction
    now_iso = datetime.now(timezone.utc).isoformat()
    tx_id = f"tx_{uuid.uuid4().hex[:10]}"
    tx_record = TransactionModel(
        transaction_id=tx_id,
        account_id=account.account_id,
        timestamp=now_iso,
        amount=amount,
        direction="debit",
        merchant=f"Transfer to {recipient_id}",
        category="Transfers"
    )
    db.add(tx_record)

    # 4. Create immutable audit entry
    audit_id = f"aud_{uuid.uuid4().hex[:10]}"
    audit_entry = AuditLogModel(
        audit_id=audit_id,
        action_id=record.action_id,
        user_id=user.user_id,
        action_type="TRANSFER_EXECUTED_ATOMIC",
        payload_digest=record.action_digest,
        reason_code="TRANSFER_SUCCESS",
        details=f"Transferred {amount:.2f} CNY to {recipient_id}. Remaining balance: {account.balance:.2f} CNY."
    )
    db.add(audit_entry)

    return audit_id
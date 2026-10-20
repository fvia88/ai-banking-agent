# backend/app/api/transactions.py
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from contracts.enums import Direction
from contracts.models import Transaction
from contracts.api_schemas import TransactionsResponse
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel, AccountModel, TransactionModel

router = APIRouter()

@router.get("/transactions", response_model=TransactionsResponse)
def get_transactions(
    period: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = (
        db.query(TransactionModel)
        .join(AccountModel, TransactionModel.account_id == AccountModel.account_id)
        .filter(AccountModel.user_id == user.user_id)
    )
    if period:
        query = query.filter(TransactionModel.timestamp.startswith(period))
        
    records = query.order_by(TransactionModel.timestamp.desc()).all()
    
    parsed_transactions = []
    for r in records:
        # 1. Parse timestamp and guarantee timezone is present
        ts = datetime.fromisoformat(r.timestamp)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # 2. Map direction string to Direction enum safely
        direction_val = Direction(r.direction.lower())

        parsed_transactions.append(
            Transaction(
                transaction_id=r.transaction_id,
                account_id=r.account_id,
                timestamp=ts,
                amount=Decimal(str(r.amount)),
                direction=direction_val,
                merchant=r.merchant,
                category=r.category,
                note=""
            )
        )

    return TransactionsResponse(transactions=parsed_transactions)
# backend/app/api/transactions.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from contracts.models import Transaction
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel, AccountModel, TransactionModel

router = APIRouter()

@router.get("/transactions", response_model=list[Transaction])
def get_transactions(
    period: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = (
        db.query(TransactionModel)
        .join(AccountModel, TransactionModel.account_id == AccountModel.account_id)
        .filter(AccountModel.user_id == user.user_id)
    )
    if period:
        # ISO timestamp string prefix match on "YYYY-MM"
        query = query.filter(TransactionModel.timestamp.startswith(period))
        
    records = query.order_by(TransactionModel.timestamp.desc()).all()
    
    return [
        Transaction(
            transaction_id=r.transaction_id,
            account_id=r.account_id,
            timestamp=r.timestamp,
            amount=f"{r.amount:.2f}",
            direction=r.direction,  # type: ignore[arg-type]
            merchant=r.merchant,
            category=r.category
        )
        for r in records
    ]
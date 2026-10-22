# backend/app/api/transactions.py
from datetime import datetime, timezone, timedelta
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

CST = timezone(timedelta(hours=8))

def get_month_boundaries_cst(period: str) -> tuple[datetime, datetime]:
    """Calculates start and end datetime in Asia/Shanghai (+08:00) for a given YYYY-MM."""
    year, month = map(int, period.split("-"))
    start_dt = datetime(year, month, 1, 0, 0, 0, tzinfo=CST)
    
    # Calculate start of next month
    if month == 12:
        end_dt = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=CST)
    else:
        end_dt = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=CST)
        
    return start_dt, end_dt

@router.get("/transactions", response_model=TransactionsResponse)
def get_transactions(
    period: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    records = (
        db.query(TransactionModel)
        .join(AccountModel, TransactionModel.account_id == AccountModel.account_id)
        .filter(AccountModel.user_id == user.user_id)
        .order_by(TransactionModel.timestamp.desc())
        .all()
    )
    
    start_dt, end_dt = get_month_boundaries_cst(period) if period else (None, None)
    parsed_transactions = []

    for r in records:
        ts = datetime.fromisoformat(r.timestamp)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # Precise timezone-aware month boundary filtering
        if start_dt and end_dt:
            if not (start_dt <= ts < end_dt):
                continue

        parsed_transactions.append(
            Transaction(
                transaction_id=r.transaction_id,
                account_id=r.account_id,
                timestamp=ts,
                amount=Decimal(str(r.amount)),
                direction=Direction(r.direction.lower()),
                merchant=r.merchant,
                category=r.category,
                note=""
            )
        )

    return TransactionsResponse(transactions=parsed_transactions)
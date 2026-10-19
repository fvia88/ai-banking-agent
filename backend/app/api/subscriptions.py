# backend/app/api/subscriptions.py
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from contracts.enums import Direction
from contracts.models import Transaction, SubscriptionReport
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel, AccountModel, TransactionModel
from app.services.adapters import subscriptions_service

router = APIRouter()

@router.get("/subscriptions", response_model=SubscriptionReport)
def list_subscriptions(
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. Fetch user's transaction history
    records = (
        db.query(TransactionModel)
        .join(AccountModel, TransactionModel.account_id == AccountModel.account_id)
        .filter(AccountModel.user_id == user.user_id)
        .order_by(TransactionModel.timestamp.desc())
        .all()
    )

    transactions = []
    for r in records:
        ts = datetime.fromisoformat(r.timestamp)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        transactions.append(
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

    # 2. Run detection via adapter
    return subscriptions_service.detect(transactions)
# backend/app/api/accounts.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel, AccountModel
from decimal import Decimal
from contracts.models import Account
from contracts.api_schemas import AccountsResponse

router = APIRouter()

@router.get("/accounts", response_model=AccountsResponse)
def list_accounts(
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    records = db.query(AccountModel).filter(AccountModel.user_id == user.user_id).all()
    
    return AccountsResponse(
        accounts=[
            Account(
                account_id=acc.account_id,
                user_id=acc.user_id,
                currency="CNY",
                balance=Decimal(str(acc.balance)),
                locked=user.is_locked
            )
            for acc in records
        ]
    )
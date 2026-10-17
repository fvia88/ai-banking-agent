# backend/app/api/accounts.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel, AccountModel

router = APIRouter()

class AccountResponse(BaseModel):
    account_id: str
    account_number: str
    currency: str
    balance: str
    daily_transfer_total: str

@router.get("/accounts", response_model=list[AccountResponse])
def list_accounts(
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    accounts = db.query(AccountModel).filter(AccountModel.user_id == user.user_id).all()
    return [
        AccountResponse(
            account_id=acc.account_id,
            account_number=acc.account_number,
            currency=acc.currency,
            balance=f"{acc.balance:.2f}",
            daily_transfer_total=f"{acc.daily_transfer_total:.2f}"
        )
        for acc in accounts
    ]
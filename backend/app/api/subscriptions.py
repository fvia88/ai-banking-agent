"""Recurring evidence and verified subscriptions are separate resources."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from contracts.models import Subscription, SubscriptionReport
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel
from app.services.subscriptions import selected_account, stored_records, subscription_report

router = APIRouter()


@router.get("/subscriptions", response_model=SubscriptionReport)
def list_subscriptions(
    account_id: str | None = Query(default=None),
    user: UserModel = Depends(get_current_user), db: Session = Depends(get_db),
):
    account = selected_account(db, user.user_id, account_id)
    return subscription_report(db, user.user_id, account.account_id if account else None)


@router.get("/subscriptions/records", response_model=list[Subscription])
def list_stored_subscriptions(
    account_id: str | None = Query(default=None),
    user: UserModel = Depends(get_current_user), db: Session = Depends(get_db),
):
    account = selected_account(db, user.user_id, account_id)
    return stored_records(db, user.user_id, account.account_id if account else None)

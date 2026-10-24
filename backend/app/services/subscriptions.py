"""P2 persistence and tenancy boundary around P5's pure functions."""
from datetime import datetime, timezone

from fastapi import HTTPException
from contracts.models import Subscription, SubscriptionCandidate, SubscriptionReport, Transaction
from app.db.models import AccountModel, SubscriptionModel, TransactionModel
from app.services.adapters import subscriptions_service


class SubscriptionUnavailable(ValueError):
    def __init__(self, reason_code):
        self.reason_code = reason_code
        super().__init__(reason_code)


def selected_account(db, user_id, account_id=None):
    query = db.query(AccountModel).filter(AccountModel.user_id == user_id)
    if account_id is not None:
        query = query.filter(AccountModel.account_id == account_id)
    account = query.order_by(AccountModel.account_id).first()
    if account is None and account_id is not None:
        raise HTTPException(status_code=404, detail="Account not found for current user")
    return account


def as_contract(row):
    return Subscription(
        subscription_id=row.subscription_id, user_id=row.user_id, merchant=row.merchant,
        estimated_amount=row.estimated_amount, cadence=row.cadence, status=row.status,
        cancellation_supported=row.cancellation_supported,
    )


def stored_records(db, user_id, account_id):
    if account_id is None:
        return []
    rows = db.query(SubscriptionModel).join(
        AccountModel, SubscriptionModel.account_id == AccountModel.account_id,
    ).filter(SubscriptionModel.user_id == user_id, AccountModel.user_id == user_id,
             SubscriptionModel.account_id == account_id).order_by(SubscriptionModel.subscription_id).all()
    return [as_contract(row) for row in rows]


def subscription_report(db, user_id, account_id):
    if account_id is None:
        return SubscriptionReport()
    selected_account(db, user_id, account_id)
    rows = db.query(TransactionModel).filter(TransactionModel.account_id == account_id).order_by(
        TransactionModel.timestamp, TransactionModel.transaction_id,
    ).all()
    transactions = []
    for row in rows:
        timestamp = datetime.fromisoformat(row.timestamp)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        transactions.append(Transaction(
            transaction_id=row.transaction_id, account_id=row.account_id, timestamp=timestamp,
            amount=row.amount, direction=row.direction.lower(), merchant=row.merchant,
            category=row.category,
        ))
    report = subscriptions_service.detect(transactions)
    return subscriptions_service.enrich(report, stored_records(db, user_id, account_id), user_id)


def cancellation_record(db, user_id, subscription_id, account_id=None):
    """Only exact stored IDs can authorize execution; never silently remap a payload."""
    row = db.query(SubscriptionModel).join(
        AccountModel, SubscriptionModel.account_id == AccountModel.account_id,
    ).filter(SubscriptionModel.subscription_id == subscription_id,
             SubscriptionModel.user_id == user_id, AccountModel.user_id == user_id).populate_existing().first()
    if row is None or (account_id is not None and row.account_id != account_id):
        raise SubscriptionUnavailable("SUBSCRIPTION_NOT_FOUND")
    stored = as_contract(row)
    # Confidence is recurrence evidence, not authorization. Verified records do
    # not require enough transaction history to qualify for detection.
    candidate = SubscriptionCandidate(
        subscription_id=stored.subscription_id, merchant=stored.merchant,
        estimated_amount=stored.estimated_amount, cadence=stored.cadence,
        confidence=0, evidence_transaction_ids=[], cancellation_supported=False,
    )
    decision = subscriptions_service.assess(candidate, [stored], user_id)
    if not decision.eligible:
        raise SubscriptionUnavailable(decision.reason_code)
    if decision.stored_subscription_id != subscription_id or not decision.requires_confirmation:
        raise SubscriptionUnavailable("INVALID_CANCELLATION_DECISION")
    return row

# backend/tests/test_finance_signoff.py
"""
P3 sign-off: expected spending outputs for the data the app actually serves.

Seeds a fresh database the way startup does, then loads one account's stored
transactions exactly as api/chat.py does for analyze_spending, so these
numbers are what the browser demo should show before any extra demo transfers.
"""
from datetime import datetime
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contracts.enums import Direction
from contracts.models import Transaction
from app.db import seed
from app.db.models import TransactionModel
from app.services.adapters import finance_service


@pytest.fixture
def seeded(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(seed, "engine", engine)
    monkeypatch.setattr(seed, "SessionLocal", sessions)
    seed.seed_database()
    with sessions() as db:
        yield db
    engine.dispose()


def _report(db, account_id: str, period: str):
    """Same selection and conversion as the analyze_spending read loop in api/chat.py."""
    rows = db.query(TransactionModel).filter(TransactionModel.account_id == account_id).all()
    txs = [
        Transaction(
            transaction_id=t.transaction_id,
            account_id=t.account_id,
            timestamp=datetime.fromisoformat(t.timestamp),
            amount=Decimal(str(t.amount)),
            direction=Direction(t.direction.lower()),
            merchant=t.merchant,
            category=t.category,
        )
        for t in rows
    ]
    return finance_service.analyze(txs, period)


def _add_debit(db, tx_id, timestamp, amount, merchant, category, account_id="acc_cny_001"):
    db.add(TransactionModel(transaction_id=tx_id, account_id=account_id, timestamp=timestamp,
                            amount=Decimal(amount), direction="debit", merchant=merchant, category=category))
    db.commit()


def test_finance_bridge_is_real_engine_not_mock():
    assert finance_service.use_mock is False


def test_alice_october_demo_report(seeded):
    report = _report(seeded, "acc_cny_001", "2026-10")
    assert report.total_spending == Decimal("80.00")
    assert report.category_totals == {"Dining": Decimal("35.00"), "Entertainment": Decimal("45.00")}
    assert report.anomalies == []  # payroll credit of 5000.00 is excluded, not netted


def test_alice_september_demo_report(seeded):
    report = _report(seeded, "acc_cny_001", "2026-09")
    assert report.total_spending == Decimal("45.00")
    assert report.category_totals == {"Entertainment": Decimal("45.00")}


def test_fixture_account_october_report(seeded):
    report = _report(seeded, "account_001", "2026-10")
    assert report.total_spending == Decimal("1843.00")
    assert report.anomalies == []
    assert report.category_totals["Shopping"] == Decimal("1200.00")  # gross: the 300.00 refund is not subtracted


def test_reports_are_scoped_to_the_selected_account(seeded):
    alice = _report(seeded, "acc_cny_001", "2026-10")
    fixture = _report(seeded, "account_001", "2026-10")
    assert "Shopping" not in alice.category_totals  # fixture account's purchases never leak in
    assert (alice.total_spending, fixture.total_spending) == (Decimal("80.00"), Decimal("1843.00"))


def test_executed_transfer_counts_as_spending_in_transfers_category(seeded):
    """Agreed rule (docs/finance/RULES.md): outbound transfers are debits and count as spending."""
    _add_debit(seeded, "tx_demo_transfer", "2026-10-21T10:00:00+08:00", "500.00", "Transfer to rcp_bob", "Transfers")
    report = _report(seeded, "acc_cny_001", "2026-10")
    assert report.total_spending == Decimal("580.00")
    assert report.category_totals["Transfers"] == Decimal("500.00")


def test_utc_executor_timestamp_is_bucketed_by_shanghai_month(seeded):
    """The executor stores UTC ISO timestamps; 2026-10-31 17:30 UTC is 2026-11-01 01:30 in Shanghai."""
    _add_debit(seeded, "tx_late_utc", "2026-10-31T17:30:00+00:00", "200.00", "Transfer to rcp_bob", "Transfers")
    assert _report(seeded, "acc_cny_001", "2026-10").total_spending == Decimal("80.00")
    assert _report(seeded, "acc_cny_001", "2026-11").total_spending == Decimal("200.00")

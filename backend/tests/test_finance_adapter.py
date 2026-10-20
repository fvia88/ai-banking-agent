# backend/tests/test_finance_adapter.py
from contracts.models import Transaction
from app.services.adapters import calculate_history_periods, finance_service
from decimal import Decimal

def test_calculate_history_periods_handles_year_boundary():
    # Test standard period
    p1 = calculate_history_periods("2026-10", extra_months=3)
    assert p1 == ["2026-07", "2026-08", "2026-09", "2026-10"]

    # Test year boundary (e.g. February roll back into previous year)
    p2 = calculate_history_periods("2026-02", extra_months=3)
    assert p2 == ["2025-11", "2025-12", "2026-01", "2026-02"]

def test_t12_spending_report_excludes_credits_and_sums_exact_decimals():
    """T12: Spending calculation only includes debits for the target period."""
    txs = [
        # Target period debits (Oct 2026)
        Transaction(
            transaction_id="tx_1", account_id="acc1", timestamp="2026-10-01T10:00:00+08:00",
            amount="35.00", direction="debit", merchant="Coffee", category="Dining"
        ),
        Transaction(
            transaction_id="tx_2", account_id="acc1", timestamp="2026-10-05T10:00:00+08:00",
            amount="45.00", direction="debit", merchant="Movies", category="Entertainment"
        ),
        # Credit inflow (Must be excluded per T12!)
        Transaction(
            transaction_id="tx_3", account_id="acc1", timestamp="2026-10-10T10:00:00+08:00",
            amount="5000.00", direction="credit", merchant="Salary", category="Income"
        ),
        # Previous month debit (Must be excluded from target period total)
        Transaction(
            transaction_id="tx_4", account_id="acc1", timestamp="2026-09-05T10:00:00+08:00",
            amount="45.00", direction="debit", merchant="Movies", category="Entertainment"
        )
    ]

    report = finance_service.analyze(txs, period="2026-10")
    
    # 35.00 + 45.00 = 80.00 (Salary credit excluded!)
    assert Decimal(str(report.total_spending)) == Decimal("80.00")
    assert Decimal(str(report.category_totals["Dining"])) == Decimal("35.00")
    assert Decimal(str(report.category_totals["Entertainment"])) == Decimal("45.00")
    assert "Income" not in report.category_totals
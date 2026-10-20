# backend/app/mocks/finance.py
from decimal import Decimal
from collections import defaultdict
from contracts.models import Transaction, SpendingReport

class MockFinanceAdapter:
    """
    Mock analytics engine fulfilling Person 3's module contract (finance/analytics.py).
    Enforces spending calculations and excludes credit inflows (Test Vector T12).
    """
    @staticmethod
    def analyze_spending(transactions: list[Transaction], period: str) -> SpendingReport:
        target_txs = []
        for tx in transactions:
            # Safely get timestamp as a string whether it's datetime or str
            ts_str = tx.timestamp.isoformat() if hasattr(tx.timestamp, "isoformat") else str(tx.timestamp)
            
            # Rule (Test Vector T12): Exclude credit inflows; only calculate debits for the requested period
            if tx.direction == "debit" and ts_str.startswith(period):
                target_txs.append(tx)

        total_spending = Decimal("0.00")
        category_totals = defaultdict(lambda: Decimal("0.00"))

        for tx in target_txs:
            amt = Decimal(str(tx.amount))
            total_spending += amt
            category_totals[tx.category] += amt

        # Format category totals as exact 2-decimal string Money
        formatted_category_totals = {
            cat: f"{amt:.2f}"
            for cat, amt in category_totals.items()
        }

        return SpendingReport(
            period=period,
            currency="CNY",
            total_spending=f"{total_spending:.2f}",
            category_totals=formatted_category_totals,
            anomalies=[]
        )
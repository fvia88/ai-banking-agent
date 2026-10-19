# backend/app/mocks/subscriptions.py
from collections import defaultdict
from decimal import Decimal
from contracts.enums import Cadence
from contracts.models import Transaction, SubscriptionCandidate, SubscriptionReport

class MockSubscriptionsAdapter:
    """
    Mock subscriptions engine fulfilling Person 5's module contract (subscriptions/detector.py).
    Detects recurring merchant charges across transaction history.
    """
    @staticmethod
    def detect_subscriptions(transactions: list[Transaction]) -> SubscriptionReport:
        # Group debit transactions by merchant
        merchant_groups = defaultdict(list)
        for tx in transactions:
            if tx.direction.value == "debit" if hasattr(tx.direction, "value") else str(tx.direction).lower() == "debit":
                merchant_groups[tx.merchant].append(tx)

        candidates = []
        for merchant, txs in merchant_groups.items():
            # If a merchant appears 2 or more times with the same charge, detect as recurring
            if len(txs) >= 2:
                latest_tx = txs[0]
                candidates.append(
                    SubscriptionCandidate(
                        subscription_id=f"sub_{latest_tx.transaction_id}",
                        merchant=merchant,
                        estimated_amount=Decimal(str(latest_tx.amount)),
                        cadence=Cadence.MONTHLY,
                        confidence=0.95,
                        evidence_transaction_ids=[tx.transaction_id for tx in txs],
                        cancellation_supported=True
                    )
                )

        return SubscriptionReport(candidates=candidates)
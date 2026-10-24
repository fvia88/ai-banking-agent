# backend/app/db/seed.py
import json
from pathlib import Path
from decimal import Decimal
from app.db.session import SessionLocal, Base, engine
from app.db.migrate import upgrade_database
from app.db.models import UserModel, AccountModel, TransactionModel

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = PROJECT_ROOT / "fixtures"

def load_fixture(filename: str):
    path = FIXTURES_DIR / filename
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []

def seed_database():
    """Initialize an empty demo DB without resetting existing user data."""
    upgrade_database(engine)
    
    db = SessionLocal()
    try:
        if db.query(UserModel.user_id).first() is not None:
            print("Database already contains users; existing data preserved.")
            return
        # --- 1. Seed Users from fixtures/users.json ---
        users_data = load_fixture("users.json")
        for u in users_data:
            db.add(UserModel(
                user_id=u["user_id"],
                username=u["display_name"],
                is_locked=False
            ))

        # Guarantee demo profile exists for frontend
        if not any(u["user_id"] == "usr_demo_01" for u in users_data):
            db.add(UserModel(user_id="usr_demo_01", username="Alice Wang", is_locked=False))

        # --- 2. Seed Accounts from fixtures/accounts.json ---
        accounts_data = load_fixture("accounts.json")
        for a in accounts_data:
            acc_id = a["account_id"]
            db.add(AccountModel(
                account_id=acc_id,
                user_id=a["user_id"],
                account_number=f"622202000000{acc_id[-4:] if len(acc_id) >= 4 else '0001'}",
                currency=a.get("currency", "CNY"),
                balance=Decimal(str(a["balance"])),
                daily_transfer_total=Decimal("0.00")
            ))

        # Guarantee demo account exists for frontend
        db.add(AccountModel(
            account_id="acc_cny_001",
            user_id="usr_demo_01",
            account_number="6222021001009988",
            currency="CNY",
            balance=Decimal("15250.00"),
            daily_transfer_total=Decimal("0.00")
        ))

        # --- 3. Seed Transactions from fixtures/transactions.json ---
        txs_data = load_fixture("transactions.json")
        for t in txs_data:
            db.add(TransactionModel(
                transaction_id=t["transaction_id"],
                account_id=t["account_id"],
                timestamp=t["timestamp"],
                amount=Decimal(str(t["amount"])),
                direction=t["direction"].lower(),
                merchant=t["merchant"],
                category=t["category"]
            ))

        # Add demo transactions for acc_cny_001 so frontend dashboard remains rich
        demo_txs = [
            TransactionModel(
                transaction_id="tx_demo_001",
                account_id="acc_cny_001",
                timestamp="2026-10-01T09:30:00+08:00",
                amount=Decimal("35.00"),
                direction="debit",
                merchant="Starbucks Reserve",
                category="Dining"
            ),
            TransactionModel(
                transaction_id="tx_demo_002",
                account_id="acc_cny_001",
                timestamp="2026-10-05T14:15:00+08:00",
                amount=Decimal("45.00"),
                direction="debit",
                merchant="iQIYI VIP Monthly",
                category="Entertainment"
            ),
            TransactionModel(
                transaction_id="tx_demo_003",
                account_id="acc_cny_001",
                timestamp="2026-09-05T14:15:00+08:00",
                amount=Decimal("45.00"),
                direction="debit",
                merchant="iQIYI VIP Monthly",
                category="Entertainment"
            ),
            TransactionModel(
                transaction_id="tx_demo_004",
                account_id="acc_cny_001",
                timestamp="2026-10-10T18:00:00+08:00",
                amount=Decimal("5000.00"),
                direction="credit",
                merchant="Payroll Inward",
                category="Income"
            )
        ]
        db.add_all(demo_txs)

        db.commit()
        print("Database successfully seeded from fixtures/ (user_001 / account_001) and demo profile.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()

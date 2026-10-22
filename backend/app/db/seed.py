# backend/app/db/seed.py
from decimal import Decimal
from app.db.session import SessionLocal, Base, engine
from app.db.models import UserModel, AccountModel, TransactionModel

def seed_database():
    """Initialize an empty demo DB without resetting existing user data."""
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        if db.query(UserModel.user_id).first() is not None:
            print("Database already contains users; existing data preserved.")
            return
        # Create standard demo user
        demo_user = UserModel(
            user_id="usr_demo_01",
            username="Alice Wang",
            is_locked=False
        )
        db.add(demo_user)
        
        # Primary checking account (CNY 15,250.00 balance)
        checking = AccountModel(
            account_id="acc_cny_001",
            user_id="usr_demo_01",
            account_number="6222021001009988",
            currency="CNY",
            balance=Decimal("15250.00"),
            daily_transfer_total=Decimal("0.00")
        )
        db.add(checking)
        
        # Transactions for spending analysis & subscription tests
        sample_txs = [
            TransactionModel(
                transaction_id="tx_001",
                account_id="acc_cny_001",
                timestamp="2026-10-01T09:30:00+08:00",
                amount=Decimal("35.00"),
                direction="debit",
                merchant="Starbucks Reserve",
                category="Dining"
            ),
            TransactionModel(
                transaction_id="tx_002",
                account_id="acc_cny_001",
                timestamp="2026-10-05T14:15:00+08:00",
                amount=Decimal("45.00"),
                direction="debit",
                merchant="iQIYI VIP Monthly",
                category="Entertainment"
            ),
            TransactionModel(
                transaction_id="tx_003",
                account_id="acc_cny_001",
                timestamp="2026-09-05T14:15:00+08:00",
                amount=Decimal("45.00"),
                direction="debit",
                merchant="iQIYI VIP Monthly",
                category="Entertainment"
            ),
            TransactionModel(
                transaction_id="tx_004",
                account_id="acc_cny_001",
                timestamp="2026-10-10T18:00:00+08:00",
                amount=Decimal("5000.00"),
                direction="credit",
                merchant="Payroll Inward",
                category="Income"
            )
        ]
        db.add_all(sample_txs)
        db.commit()
        print("Database successfully seeded with demo user 'usr_demo_01' and fixture transactions.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()

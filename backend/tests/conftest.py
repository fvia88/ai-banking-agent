# backend/tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.session import Base, get_db
from app.db.seed import seed_database

TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return engine

@pytest.fixture(scope="function")
def db_session(test_engine):
    connection = test_engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection)
    session = session_factory()
    
    # Import seed logic directly to populate the test session
    from app.db.models import UserModel, AccountModel, TransactionModel
    from decimal import Decimal
    
    demo_user = UserModel(user_id="usr_demo_01", username="Alice Wang", is_locked=False)
    session.add(demo_user)
    session.add(AccountModel(
        account_id="acc_cny_001",
        user_id="usr_demo_01",
        account_number="6222021001009988",
        currency="CNY",
        balance=Decimal("15250.00"),
        daily_transfer_total=Decimal("0.00")
    ))
    session.add(TransactionModel(
        transaction_id="tx_001",
        account_id="acc_cny_001",
        timestamp="2026-10-01T09:30:00+08:00",
        amount=Decimal("35.00"),
        direction="debit",
        merchant="Starbucks",
        category="Dining"
    ))
    session.commit()
    from app.db.subscription_seed import seed_subscriptions
    seed_subscriptions(session, [])
    session.commit()
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

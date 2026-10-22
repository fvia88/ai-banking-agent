# backend/tests/test_milestone1.py
from fastapi import status
from decimal import Decimal

def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


def test_startup_seed_preserves_balance_and_existing_data(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import seed
    from app.db.models import AccountModel, TransactionModel
    from decimal import Decimal
    engine = create_engine('sqlite:///:memory:')
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(seed, 'engine', engine)
    monkeypatch.setattr(seed, 'SessionLocal', sessions)
    try:
        seed.seed_database()
        with sessions() as db:
            seeded_count = db.query(TransactionModel).count()
            assert seeded_count > 0
            account = db.get(AccountModel, 'acc_cny_001')
            assert account.balance == Decimal('15250.00')
            account.balance = Decimal('14750.00')
            db.add(TransactionModel(transaction_id='retained_transfer', account_id=account.account_id,
                timestamp='2026-10-21T10:00:00+08:00', amount=Decimal('500.00'),
                direction='debit', merchant='Synthetic transfer', category='Transfers'))
            db.commit()
        seed.seed_database()
        with sessions() as db:
            assert db.get(AccountModel, 'acc_cny_001').balance == Decimal('14750.00')
            assert db.query(TransactionModel).count() == seeded_count + 1
            assert db.get(TransactionModel, 'retained_transfer') is not None
    finally:
        engine.dispose()


def test_startup_seed_does_not_inject_demo_user_into_existing_database(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import seed
    from app.db.models import UserModel
    engine = create_engine('sqlite:///:memory:')
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(seed, 'engine', engine)
    monkeypatch.setattr(seed, 'SessionLocal', sessions)
    try:
        seed.Base.metadata.create_all(engine)
        with sessions() as db:
            db.add(UserModel(user_id='existing_user', username='Existing synthetic user', is_locked=False))
            db.commit()
        seed.seed_database()
        with sessions() as db:
            assert db.query(UserModel).count() == 1
            assert db.get(UserModel, 'existing_user') is not None
            assert db.get(UserModel, 'usr_demo_01') is None
    finally:
        engine.dispose()

def test_list_accounts(client):
    response = client.get("/api/v1/accounts", headers={"X-Demo-User-Id": "usr_demo_01"})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "accounts" in data
    assert len(data["accounts"]) >= 1
    assert data["accounts"][0]["account_id"] == "acc_cny_001"
    assert Decimal(str(data["accounts"][0]["balance"])) == Decimal("15250.00")

def test_get_transactions_filtered(client):
    response = client.get("/api/v1/transactions?period=2026-10", headers={"X-Demo-User-Id": "usr_demo_01"})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "transactions" in data
    txs = data["transactions"]
    assert len(txs) == 1
    assert txs[0]["merchant"] == "Starbucks"

def test_chat_mock_proposal(client):
    payload = {
        "conversation_id": "conv_test_123",
        "message": "Please transfer 500 CNY to Bob"
    }
    response = client.post("/api/v1/chat", json=payload, headers={"X-Demo-User-Id": "usr_demo_01"})
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["conversation_id"] == "conv_test_123"
    assert len(body["actions"]) == 1
    assert body["actions"][0]["tool"] == "request_transfer"
    assert body["status"] == "PENDING_CONFIRMATION"

def test_chat_creates_server_action_record(client, db_session):
    payload = {
        "conversation_id": "conv_verify_01",
        "message": "Transfer 500 CNY to Bob"
    }
    response = client.post("/api/v1/chat", json=payload, headers={"X-Demo-User-Id": "usr_demo_01"})
    assert response.status_code == 200
    data = response.json()
    
    # Check that status is now PENDING_CONFIRMATION
    assert data["status"] == "PENDING_CONFIRMATION"
    assert len(data["actions"]) == 1
    
    action_args = data["actions"][0]["arguments"]
    assert "action_id" in action_args
    assert "action_digest" in action_args
    assert len(action_args["action_digest"]) == 64  # Valid SHA-256 length

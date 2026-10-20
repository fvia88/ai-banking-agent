# backend/tests/test_milestone1.py
from fastapi import status
from decimal import Decimal

def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}

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
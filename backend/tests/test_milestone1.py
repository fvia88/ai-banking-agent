# backend/tests/test_milestone1.py
from fastapi import status

def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}

def test_list_accounts(client):
    response = client.get("/api/v1/accounts", headers={"X-Demo-User-Id": "usr_demo_01"})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) >= 1
    assert data[0]["account_id"] == "acc_cny_001"
    assert data[0]["balance"] == "15250.00"

def test_get_transactions_filtered(client):
    # Match October 2026 transactions
    response = client.get("/api/v1/transactions?period=2026-10", headers={"X-Demo-User-Id": "usr_demo_01"})
    assert response.status_code == status.HTTP_200_OK
    txs = response.json()
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
    assert body["status"] == "PROPOSED"
# backend/tests/test_read_loop.py

def test_balance_inquiry_executes_read_double_hop(client):
    """
    Verifies that asking for balance triggers the backend read loop:
    1. Agent proposes get_balance
    2. Backend queries real AccountModel
    3. Agent replies with "Verified balance: CNY 15250.00."
    4. proposals is empty and status is COMPLETED.
    """
    response = client.post(
        "/api/v1/chat",
        json={"conversation_id": "c_read_balance", "message": "What is my balance?"},
        headers={"X-Demo-User-Id": "usr_demo_01"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "Verified balance: CNY 15250.00" in data["reply"]
    assert len(data["actions"]) == 0
    assert data["status"] == "COMPLETED"
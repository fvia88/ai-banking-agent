# backend/tests/test_subscriptions.py
from decimal import Decimal
from contracts.enums import Cadence, ActionStatus, ToolName
from app.db.models import TransactionModel

def test_get_subscriptions_detects_recurring_charges(client, db_session):
    """
    Verifies GET /api/v1/subscriptions identifies recurring charges.
    Requires at least 2 recurring transactions to establish cadence evidence.
    """
    # Add two monthly charges for iQIYI VIP (September and October)
    tx_sept = TransactionModel(
        transaction_id="tx_sub_01",
        account_id="acc_cny_001",
        timestamp="2026-09-05T14:15:00+08:00",
        amount=Decimal("45.00"),
        direction="debit",
        merchant="iQIYI VIP Monthly",
        category="Entertainment"
    )
    tx_oct = TransactionModel(
        transaction_id="tx_sub_02",
        account_id="acc_cny_001",
        timestamp="2026-10-05T14:15:00+08:00",
        amount=Decimal("45.00"),
        direction="debit",
        merchant="iQIYI VIP Monthly",
        category="Entertainment"
    )
    db_session.add_all([tx_sept, tx_oct])
    db_session.commit()

    response = client.get("/api/v1/subscriptions", headers={"X-Demo-User-Id": "usr_demo_01"})
    assert response.status_code == 200
    data = response.json()

    assert "candidates" in data
    assert len(data["candidates"]) >= 1

    sub = data["candidates"][0]
    assert sub["merchant"] == "iQIYI VIP Monthly"
    assert Decimal(str(sub["estimated_amount"])) == Decimal("45.00")
    assert sub["cadence"] == Cadence.MONTHLY.value
    assert sub["cancellation_supported"] is True
    assert sub["confidence"] == 0.4

def test_t07_cancel_subscription_yellow_tier_and_execution(client):
    """
    T07: Cancel subscription is YELLOW tier;
    Marks cancelled only upon user confirmation.
    """
    # 1. User says "Cancel my subscription"
    chat_resp = client.post("/api/v1/chat", json={
        "conversation_id": "c_cancel_01",
        "message": "Cancel my subscription"
    }, headers={"X-Demo-User-Id": "usr_demo_01"})
    
    assert chat_resp.status_code == 200
    chat_data = chat_resp.json()
    assert chat_data["status"] == ActionStatus.PENDING_CONFIRMATION.value
    
    action = chat_data["actions"][0]
    assert action["tool"] == ToolName.REQUEST_SUBSCRIPTION_CANCEL.value
    assert action["arguments"]["tier"] == "YELLOW"  # Must be YELLOW tier per spec
    
    action_id = action["arguments"]["action_id"]
    digest = action["arguments"]["action_digest"]

    # 2. Confirm the cancellation action
    confirm_resp = client.post(
        f"/api/v1/actions/{action_id}/confirm",
        json={
            "confirmation_id": "conf_cancel_01",
            "action_digest": digest,
            "idempotency_key": "idemp_cancel_01"
        },
        headers={"X-Demo-User-Id": "usr_demo_01"}
    )
    assert confirm_resp.status_code == 200
    confirm_data = confirm_resp.json()
    assert confirm_data["status"] == ActionStatus.COMPLETED.value
    assert "cancellation confirmed" in confirm_data["message"].lower()

    # 3. Check audit log records the cancellation
    audit_resp = client.get("/api/v1/audit", headers={"X-Demo-User-Id": "usr_demo_01"})
    assert audit_resp.status_code == 200
    events = audit_resp.json()["events"]
    assert any(ev["event_type"] == "SUBSCRIPTION_CANCELLED" for ev in events)

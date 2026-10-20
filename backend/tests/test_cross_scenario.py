# backend/tests/test_cross_scenario.py
from decimal import Decimal
from contracts.enums import ActionStatus, ToolName
from app.db.models import AccountModel

def test_cross_scenario_orchestration_cancel_and_transfer_savings(client, db_session):
    """
    Cross-Scenario Orchestration:
    1. Chat proposes BOTH subscription cancellation and transfer of savings.
    2. Backend creates server action tickets for both.
    3. User confirms cancellation -> COMPLETED.
    4. User confirms transfer -> COMPLETED & 45.00 CNY deducted from checking.
    5. Audit log reflects both operations in sequence.
    """
    # 1. User prompts the multi-step intent
    chat_resp = client.post("/api/v1/chat", json={
        "conversation_id": "c_orchestration_01",
        "message": "Cancel my subscription and transfer the savings to my vault"
    }, headers={"X-Demo-User-Id": "usr_demo_01"})
    
    assert chat_resp.status_code == 200
    chat_data = chat_resp.json()
    assert chat_data["status"] == ActionStatus.PENDING_CONFIRMATION.value
    assert len(chat_data["actions"]) == 2

    # Verify Action 1 is Cancellation
    action_cancel = chat_data["actions"][0]
    assert action_cancel["tool"] == ToolName.REQUEST_SUBSCRIPTION_CANCEL.value
    cancel_id = action_cancel["arguments"]["action_id"]
    cancel_digest = action_cancel["arguments"]["action_digest"]

    # Verify Action 2 is Transfer of Savings
    action_transfer = chat_data["actions"][1]
    assert action_transfer["tool"] == ToolName.REQUEST_TRANSFER.value
    assert action_transfer["arguments"]["amount"] == "45.00"
    transfer_id = action_transfer["arguments"]["action_id"]
    transfer_digest = action_transfer["arguments"]["action_digest"]

    # 2. Confirm Action 1 (Cancel Subscription)
    res_cancel = client.post(
        f"/api/v1/actions/{cancel_id}/confirm",
        json={
            "confirmation_id": "conf_orch_cancel",
            "action_digest": cancel_digest,
            "idempotency_key": "idemp_orch_cancel"
        },
        headers={"X-Demo-User-Id": "usr_demo_01"}
    )
    assert res_cancel.status_code == 200
    assert res_cancel.json()["status"] == ActionStatus.COMPLETED.value

    # 3. Confirm Action 2 (Transfer 45 CNY Savings)
    res_transfer = client.post(
        f"/api/v1/actions/{transfer_id}/confirm",
        json={
            "confirmation_id": "conf_orch_transfer",
            "action_digest": transfer_digest,
            "idempotency_key": "idemp_orch_transfer"
        },
        headers={"X-Demo-User-Id": "usr_demo_01"}
    )
    assert res_transfer.status_code == 200
    assert res_transfer.json()["status"] == ActionStatus.COMPLETED.value

    # 4. Check that balance was deducted by exactly 45.00 CNY (15,250.00 -> 15,205.00)
    acc = db_session.query(AccountModel).filter(AccountModel.account_id == "acc_cny_001").first()
    db_session.refresh(acc)
    assert acc.balance == Decimal("15205.00")

    # 5. Check Audit log reflects both events
    audit_resp = client.get("/api/v1/audit", headers={"X-Demo-User-Id": "usr_demo_01"})
    assert audit_resp.status_code == 200
    event_types = [ev["event_type"] for ev in audit_resp.json()["events"]]
    assert "SUBSCRIPTION_CANCELLED" in event_types
    assert "TRANSFER_EXECUTED_ATOMIC" in event_types
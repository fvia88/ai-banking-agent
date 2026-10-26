# backend/tests/test_execution.py
from decimal import Decimal
from contracts.enums import ActionStatus
from app.db.models import AccountModel, TransactionModel

def test_atomic_money_transfer_and_idempotency(client, db_session):
    """
    Tests real money movement + Test Vector T06 (Idempotency):
    1. Initial balance: 15,250.00 CNY
    2. Propose & confirm transfer of 500.00 CNY to Bob
    3. Balance must become exactly 14,750.00 CNY
    4. Repeat the SAME confirmation -> Balance MUST STAY 14,750.00 CNY (No double charge!)
    5. Audit log must record the event
    """
    # 1. Check initial balance
    acc = db_session.query(AccountModel).filter(AccountModel.account_id == "acc_cny_001").first()
    assert acc.balance == Decimal("15250.00")
    initial_tx_count = db_session.query(TransactionModel).count()

    # 2. Propose 500 CNY transfer
    chat_resp = client.post("/api/v1/chat", json={
        "conversation_id": "c_exec_01",
        "message": "Transfer 500 CNY to Bob"
    }, headers={"X-Demo-User-Id": "usr_demo_01"})
    
    action = chat_resp.json()["actions"][0]
    action_id = action["approval"]["action_id"]
    digest = action["approval"]["action_digest"]

    # 3. Confirm transfer
    confirm_resp = client.post(
        f"/api/v1/actions/{action_id}/confirm",
        json={"idempotency_key": "test_request", "confirmation_id": "conf_exec_01", "action_digest": digest},
        headers={"X-Demo-User-Id": "usr_demo_01"}
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == ActionStatus.COMPLETED.value

    # Check updated balance in DB
    db_session.refresh(acc)
    assert acc.balance == Decimal("14750.00")
    assert acc.daily_transfer_total == Decimal("500.00")
    
    # Check new transaction ledger record
    new_tx_count = db_session.query(TransactionModel).count()
    assert new_tx_count == initial_tx_count + 1

    # 4. T06 Idempotency Test: Repeat the SAME confirmation request
    replay_resp = client.post(
        f"/api/v1/actions/{action_id}/confirm",
        json={"idempotency_key": "test_request", "confirmation_id": "conf_exec_01", "action_digest": digest},
        headers={"X-Demo-User-Id": "usr_demo_01"}
    )
    assert replay_resp.status_code == 200
    assert replay_resp.json()["status"] == ActionStatus.COMPLETED.value

    # Balance MUST STILL be 14,750.00 CNY (NOT 14,250.00)
    db_session.refresh(acc)
    assert acc.balance == Decimal("14750.00")
    assert db_session.query(TransactionModel).count() == new_tx_count

    # 5. Check Audit log endpoint
    audit_resp = client.get("/api/v1/audit", headers={"X-Demo-User-Id": "usr_demo_01"})
    assert audit_resp.status_code == 200
    data = audit_resp.json()
    assert "events" in data
    events = data["events"]
    assert len(events) >= 1
    assert any("TRANSFER_EXECUTED" in ev["event_type"] for ev in events)
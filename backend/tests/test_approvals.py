# backend/tests/test_approvals.py
from contracts.enums import ActionStatus
from app.db.models import AccountModel
from decimal import Decimal

def test_confirm_yellow_action_completes_successfully(client):
    """T02 Yellow path: Propose <= 1000 CNY transfer, confirm, and verify COMPLETED."""
    # 1. Propose transfer via chat
    chat_resp = client.post("/api/v1/chat", json={
        "conversation_id": "c_yellow",
        "message": "Transfer 500 CNY to Bob"
    }, headers={"X-Demo-User-Id": "usr_demo_01"})
    
    action = chat_resp.json()["actions"][0]
    action_id = action["arguments"]["action_id"]
    digest = action["arguments"]["action_digest"]

    # 2. Confirm the action
    confirm_resp = client.post(
        f"/api/v1/actions/{action_id}/confirm",
        json={"confirmation_id": "conf_001", "action_digest": digest},
        headers={"X-Demo-User-Id": "usr_demo_01"}
    )
    assert confirm_resp.status_code == 200
    res_data = confirm_resp.json()
    assert res_data["status"] == ActionStatus.COMPLETED.value
    assert res_data["action_id"] == action_id
    assert "audit_id" in res_data

def test_confirm_with_tampered_digest_fails(client):
    """Anti-tampering test: Sending incorrect digest gets rejected."""
    chat_resp = client.post("/api/v1/chat", json={
        "conversation_id": "c_tamper",
        "message": "Transfer 500 CNY to Bob"
    }, headers={"X-Demo-User-Id": "usr_demo_01"})
    
    action_id = chat_resp.json()["actions"][0]["arguments"]["action_id"]

    # Attempt to confirm with a bogus digest
    confirm_resp = client.post(
        f"/api/v1/actions/{action_id}/confirm",
        json={"confirmation_id": "conf_002", "action_digest": "fake_tampered_hash_123"},
        headers={"X-Demo-User-Id": "usr_demo_01"}
    )
    assert confirm_resp.status_code == 400
    assert "mismatch" in confirm_resp.json()["detail"].lower()

def test_t03_red_tier_flow_requires_mfa_and_completes(client, db_session):
    """T03 Red path: Transfer that exceeds daily limit triggers PENDING_MFA, then COMPLETED on verify."""
    # 1. Update Alice's daily_transfer_total to 800 in the test DB
    acc = db_session.query(AccountModel).filter(AccountModel.account_id == "acc_cny_001").first()
    acc.daily_transfer_total = Decimal("800.00")
    db_session.commit()

    # 2. Propose another 500 CNY transfer (Total = 1300 CNY > 1000 limit -> RED)
    chat_resp = client.post("/api/v1/chat", json={
        "conversation_id": "c_red_flow",
        "message": "Transfer 500 CNY to Bob"
    }, headers={"X-Demo-User-Id": "usr_demo_01"})
    
    action = chat_resp.json()["actions"][0]
    action_id = action["arguments"]["action_id"]
    digest = action["arguments"]["action_digest"]
    assert action["arguments"]["tier"] == "RED"

    # 3. Confirm the action -> Expect PENDING_MFA
    confirm_resp = client.post(
        f"/api/v1/actions/{action_id}/confirm",
        json={"confirmation_id": "conf_red", "action_digest": digest},
        headers={"X-Demo-User-Id": "usr_demo_01"}
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == ActionStatus.PENDING_MFA.value

    # 4. Verify with the demo code '123456' -> Expect COMPLETED
    verify_resp = client.post(
        f"/api/v1/actions/{action_id}/verify",
        json={"verification_code": "123456"},
        headers={"X-Demo-User-Id": "usr_demo_01"}
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["status"] == ActionStatus.COMPLETED.value


def test_mfa_rate_limit_locks_after_three_failed_attempts(client, db_session):
    """Security test: Entering incorrect MFA code 3 times marks the action FAILED."""
    # Set daily total to 800 so proposal is RED
    acc = db_session.query(AccountModel).filter(AccountModel.account_id == "acc_cny_001").first()
    acc.daily_transfer_total = Decimal("800.00")
    db_session.commit()

    chat_resp = client.post("/api/v1/chat", json={
        "conversation_id": "c_rate_limit",
        "message": "Transfer 500 CNY to Bob"
    }, headers={"X-Demo-User-Id": "usr_demo_01"})
    
    action = chat_resp.json()["actions"][0]
    action_id = action["arguments"]["action_id"]
    digest = action["arguments"]["action_digest"]

    # Confirm to transition to PENDING_MFA
    client.post(
        f"/api/v1/actions/{action_id}/confirm",
        json={"confirmation_id": "conf_rate", "action_digest": digest},
        headers={"X-Demo-User-Id": "usr_demo_01"}
    )

    # Attempt 1: Wrong code
    resp1 = client.post(f"/api/v1/actions/{action_id}/verify", json={"verification_code": "000000"}, headers={"X-Demo-User-Id": "usr_demo_01"})
    assert resp1.status_code == 400
    assert "2 attempt(s) remaining" in resp1.json()["detail"]

    # Attempt 2: Wrong code
    resp2 = client.post(f"/api/v1/actions/{action_id}/verify", json={"verification_code": "111111"}, headers={"X-Demo-User-Id": "usr_demo_01"})
    assert resp2.status_code == 400
    assert "1 attempt(s) remaining" in resp2.json()["detail"]

    # Attempt 3: Wrong code -> Action should fail and lock
    resp3 = client.post(f"/api/v1/actions/{action_id}/verify", json={"verification_code": "222222"}, headers={"X-Demo-User-Id": "usr_demo_01"})
    assert resp3.status_code == 400
    assert "FAILED" in resp3.json()["detail"]
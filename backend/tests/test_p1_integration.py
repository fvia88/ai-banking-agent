import os
import pytest
from decimal import Decimal
from contracts.enums import ActionStatus, ToolName
from app.services.adapters import agent_service
from app.db.models import AccountModel

@pytest.fixture(autouse=True)
def enable_real_agent_mock_provider():
    """Switches adapter to call Person 1's real agent module in offline mock mode."""
    old_mock = agent_service.use_mock
    old_provider = os.environ.get("AGENT_PROVIDER")

    agent_service.use_mock = False
    os.environ["AGENT_PROVIDER"] = "mock"

    yield

    agent_service.use_mock = old_mock
    if old_provider is not None:
        os.environ["AGENT_PROVIDER"] = old_provider
    else:
        os.environ.pop("AGENT_PROVIDER", None)


def test_real_agent_balance_inquiry_read_loop(client):
    """
    End-to-End Test 1: Balance inquiry with Person 1's real agent.
    1. Agent emits get_balance proposal.
    2. Backend queries real AccountModel.
    3. Backend feeds tool_result back to Agent.
    4. Agent produces verified text.
    """
    res = client.post(
        "/api/v1/chat",
        json={"conversation_id": "c_real_bal", "message": "What is my balance?"},
        headers={"X-Demo-User-Id": "usr_demo_01"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "Verified balance: CNY 15250.00." in data["reply"]
    assert len(data["actions"]) == 0
    assert data["status"] == ActionStatus.COMPLETED.value


def test_real_agent_transfer_proposal_and_execution(client, db_session):
    """
    End-to-End Test 2: Transfer proposal with Person 1's real agent.
    1. Agent matches 'Bob' to 'Bob Li' (usr_bob_01).
    2. Agent generates canonical request_transfer proposal.
    3. Backend issues server action ticket and Yellow tier.
    4. Client confirms -> 500.00 CNY deducted atomically from DB!
    """
    chat_res = client.post(
        "/api/v1/chat",
        json={"conversation_id": "c_real_tx", "message": "Transfer 500 to Bob"},
        headers={"X-Demo-User-Id": "usr_demo_01"},
    )
    assert chat_res.status_code == 200
    chat_data = chat_res.json()
    assert chat_data["status"] == ActionStatus.PENDING_CONFIRMATION.value
    assert len(chat_data["actions"]) == 1

    action = chat_data["actions"][0]
    assert action["tool"] == ToolName.REQUEST_TRANSFER.value
    assert action["arguments"]["recipient_id"] == "usr_bob_01"
    assert action["arguments"]["amount"] == "500.00"

    action_id = action["arguments"]["action_id"]
    digest = action["arguments"]["action_digest"]

    # Confirm the transfer
    confirm_res = client.post(
        f"/api/v1/actions/{action_id}/confirm",
        json={
            "confirmation_id": "conf_real_01",
            "action_digest": digest,
            "idempotency_key": "idemp_real_01",
        },
        headers={"X-Demo-User-Id": "usr_demo_01"},
    )
    assert confirm_res.status_code == 200
    assert confirm_res.json()["status"] == ActionStatus.COMPLETED.value

    # Verify money was deducted in the database
    acc = db_session.query(AccountModel).filter(AccountModel.account_id == "acc_cny_001").first()
    db_session.refresh(acc)
    assert acc.balance == Decimal("14750.00")
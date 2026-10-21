import os
import json
import pytest
from decimal import Decimal
from contracts.enums import ActionStatus, ToolName
from app.services.adapters import agent_service
from app.db.models import AccountModel
from app.services.session_store import get_conversation_state


def saved_p1_state(conversation_id, user_id='usr_demo_01'):
    return get_conversation_state(json.dumps(['p1', user_id, conversation_id]))


def post_chat(client, conversation_id, message, user_id='usr_demo_01'):
    response = client.post('/api/v1/chat', json=dict(conversation_id=conversation_id, message=message),
                           headers={'X-Demo-User-Id': user_id})
    assert response.status_code == 200, response.text
    return response.json()


def test_real_balance_loop_consumes_saved_original_proposal(client):
    body = post_chat(client, 'p1_balance_consumption', 'What is my balance?')
    assert 'Verified balance: CNY 15250.00.' in body['reply']
    assert body['actions'] == []
    assert saved_p1_state('p1_balance_consumption')['pending_tool_requests'] == []


def test_real_spending_followup_uses_stored_month_draft(client, monkeypatch):
    from app.services.adapters import finance_service
    from finance.analytics import analyze_spending
    calls = []
    def actual_finance(transactions, period):
        calls.append((transactions, period))
        return analyze_spending(transactions, period)
    monkeypatch.setattr(finance_service, 'analyze', actual_finance)
    first = post_chat(client, 'p1_spending_http', 'Analyze my spending')
    assert 'Which month' in first['reply'] and first['actions'] == []
    before = saved_p1_state('p1_spending_http')
    invalid = post_chat(client, 'p1_spending_http', '2026-13')
    assert invalid['actions'] == [] and saved_p1_state('p1_spending_http') == before
    final = post_chat(client, 'p1_spending_http', '2026-10')
    assert 'Verified spending for 2026-10: CNY 35.00.' in final['reply']
    assert calls[0][1] == '2026-10'
    assert all(t.account_id == 'acc_cny_001' for t in calls[0][0])
    assert saved_p1_state('p1_spending_http')['pending_spending'] is None
    assert saved_p1_state('p1_spending_http')['pending_tool_requests'] == []


def test_real_transfer_invalid_answer_retains_bob_and_canonical_proposal(client):
    assert not post_chat(client, 'p1_transfer_memory', 'Transfer to Bob')['actions']
    invalid = post_chat(client, 'p1_transfer_memory', '0')
    assert invalid['actions'] == []
    assert saved_p1_state('p1_transfer_memory')['pending_transfer']['recipient_text'] == 'bob'
    final = post_chat(client, 'p1_transfer_memory', '500')
    assert len(final['actions']) == 1
    assert final['actions'][0]['arguments']['recipient_id'] == 'usr_bob_01'
    pending = saved_p1_state('p1_transfer_memory')['pending_tool_requests']
    assert len(pending) == 1
    assert pending[0]['proposal']['arguments'] == dict(source_account_id='acc_cny_001',
        recipient_id='usr_bob_01', amount='500.00', currency='CNY')
    # Current UI still receives metadata in a response copy. It must not pollute
    # the canonical original proposal used to validate later tool results.
    assert 'action_id' in final['actions'][0]['arguments']
    post_chat(client, 'p1_transfer_memory', 'Transfer to Bob')
    discarded = post_chat(client, 'p1_transfer_memory', 'Never mind!')
    assert discarded['reply'] == 'Unfinished request discarded.'
    state = saved_p1_state('p1_transfer_memory')
    assert state['pending_transfer'] is None and state['pending_tool_requests'] == pending


def test_real_cancellation_selection_uses_saved_draft(client):
    first = post_chat(client, 'p1_cancel_http', 'Cancel my subscription')
    assert not first['actions'] and saved_p1_state('p1_cancel_http')['awaiting'] == 'subscription'
    final = post_chat(client, 'p1_cancel_http', 'iQIYI VIP Monthly')
    assert len(final['actions']) == 1
    assert final['actions'][0]['tool'] == 'request_subscription_cancel'
    assert final['actions'][0]['arguments']['subscription_id'] == 'sub_iQIYI_01'
    assert saved_p1_state('p1_cancel_http')['pending_cancellation'] is None


def test_real_state_isolated_by_user_even_with_same_conversation_id(client, db_session):
    from app.db.models import UserModel
    db_session.add(UserModel(user_id='other_p1_user', username='Other synthetic user', is_locked=False))
    db_session.add(AccountModel(account_id='other_p1_account', user_id='other_p1_user',
        account_number='synthetic_other', currency='CNY', balance=Decimal('77.00'), daily_transfer_total=Decimal('0')))
    db_session.commit()
    post_chat(client, 'same_conversation', 'Analyze my spending')
    before = saved_p1_state('same_conversation')
    other = post_chat(client, 'same_conversation', 'What is my balance?', 'other_p1_user')
    assert 'CNY 77.00' in other['reply']
    assert saved_p1_state('same_conversation') == before
    assert saved_p1_state('same_conversation', 'other_p1_user')['pending_spending'] is None
    # Other users must not inherit the demo user's Bob recipient.
    blocked = post_chat(client, 'other_transfer', 'Transfer 5 to Bob', 'other_p1_user')
    assert blocked['actions'] == []

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

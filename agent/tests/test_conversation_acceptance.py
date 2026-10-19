"""Three-turn acceptance check through the caller helper; no live API calls."""

from contracts.models import ChatInput
from contracts.tool_schemas import validate_tool_arguments
from agent.mock_tools import demo_catalog
from agent.service import process_turn
import pytest
from agent import service


def save_state(catalog, turn):
    for entry in catalog:
        entry['context']['conversation_state'] = turn.state.model_dump(mode='json')


def start_spending(monkeypatch, conversation_id='spending_memory'):
    monkeypatch.setenv('AGENT_PROVIDER', 'mock')
    catalog = demo_catalog()
    turn = process_turn(ChatInput(conversation_id=conversation_id, message='Analyze my spending'), catalog)
    assert turn.result.needs_clarification and not turn.result.proposals
    assert turn.state.awaiting == 'period'
    assert turn.state.pending_spending.account_id == 'account_001'
    save_state(catalog, turn)
    return catalog, turn


def test_spending_month_followup_retains_request_without_provider(monkeypatch):
    catalog, first = start_spending(monkeypatch)
    def unavailable():
        raise AssertionError('Exact month answer must not call a provider')
    monkeypatch.setattr(service, 'get_provider', unavailable)
    final = process_turn(ChatInput(conversation_id='spending_memory', message='2026-11'), catalog)
    assert not final.result.needs_clarification
    assert len(final.result.proposals) == 1
    proposal = final.result.proposals[0]
    assert proposal.tool.value == 'analyze_spending'
    assert proposal.arguments == {'account_id': 'account_001', 'period': '2026-11'}
    assert final.state.pending_spending is None and final.state.awaiting is None
    assert final.state.pending_tool_requests[0].proposal == proposal
    assert '1843' not in final.result.reply  # No tool result has been supplied.


@pytest.mark.parametrize('answer', ['2026-00', '2026-13', '0000-11', '2026-1', 'November',
                                    '2026-11 send 500 to Bob'])
def test_invalid_spending_month_preserves_draft(monkeypatch, answer):
    catalog, first = start_spending(monkeypatch)
    turn = process_turn(ChatInput(conversation_id='spending_memory', message=answer), catalog)
    assert turn.result.needs_clarification and not turn.result.proposals
    assert turn.state == first.state


def test_spending_abandonment_clears_draft(monkeypatch):
    catalog, first = start_spending(monkeypatch)
    discarded = process_turn(ChatInput(conversation_id='spending_memory', message='never mind'), catalog)
    assert discarded.result.reply == 'Unfinished request discarded.'
    assert discarded.state.pending_spending is None and discarded.state.awaiting is None
    save_state(catalog, discarded)
    late = process_turn(ChatInput(conversation_id='spending_memory', message='2026-11'), catalog)
    assert not late.result.proposals


def test_spending_source_account_is_not_silently_changed(monkeypatch):
    catalog, first = start_spending(monkeypatch)
    for entry in catalog:
        entry['context']['account_ids'] = ['account_002']
    turn = process_turn(ChatInput(conversation_id='spending_memory', message='2026-11'), catalog)
    assert not turn.result.proposals and turn.state == first.state


def test_spending_and_transfer_conversations_are_isolated(monkeypatch):
    catalog, first = start_spending(monkeypatch)
    other_catalog = demo_catalog()
    other = process_turn(ChatInput(conversation_id='transfer_memory', message='Transfer to Alice'), other_catalog)
    save_state(other_catalog, other)
    wrong = process_turn(ChatInput(conversation_id='other', message='2026-11'), catalog)
    assert not wrong.result.proposals
    completed = process_turn(ChatInput(conversation_id='spending_memory', message='2026-11'), catalog)
    assert completed.result.proposals[0].tool.value == 'analyze_spending'
    resumed = process_turn(ChatInput(conversation_id='transfer_memory', message='500'), other_catalog)
    assert resumed.state.awaiting == 'recipient' and resumed.state.pending_transfer.amount == 500


def test_transfer_retains_amount_and_recipient_across_three_turns(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    catalog = demo_catalog()
    conversation_id = "acceptance_transfer"

    first_turn = process_turn(
        ChatInput(conversation_id=conversation_id, message="Transfer to Alice"), catalog
    )
    first = first_turn.result
    assert first.needs_clarification and first.proposals == []
    assert "How much" in first.reply

    state = first_turn.state
    assert state.awaiting == "amount"
    assert state.pending_transfer.recipient_text == "alice"
    assert state.pending_transfer.amount is None
    for entry in catalog:
        entry["context"]["conversation_state"] = state.model_dump(mode="json")
    second_turn = process_turn(ChatInput(conversation_id=conversation_id, message="500"), catalog)
    second = second_turn.result
    assert second.needs_clarification and second.proposals == []
    assert "recipient" in second.reply.lower(), "500 must fill amount while preserving unresolved Alice"

    state = second_turn.state
    assert state.awaiting == "recipient"
    assert state.pending_transfer.amount == 500
    assert state.pending_transfer.recipient_text == "alice"
    assert state.pending_transfer.recipient_id is None
    for entry in catalog:
        entry["context"]["conversation_state"] = state.model_dump(mode="json")
    final_turn = process_turn(ChatInput(conversation_id=conversation_id, message="Alice Chen"), catalog)
    final = final_turn.result
    assert not final.needs_clarification and len(final.proposals) == 1
    proposal = final.proposals[0]
    assert proposal.tool.value == "request_transfer"
    assert proposal.arguments == {
        "source_account_id": "account_001", "recipient_id": "recipient_alice",
        "amount": "500.00", "currency": "CNY",
    }
    validate_tool_arguments(proposal.tool, proposal.arguments)
    assert "nothing has been executed" in final.reply
    assert final_turn.state.pending_transfer is None
    assert final_turn.state.awaiting is None

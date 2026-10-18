"""Three-turn acceptance check through the caller helper; no live API calls."""

from contracts.models import ChatInput
from contracts.tool_schemas import validate_tool_arguments
from agent.mock_tools import demo_catalog
from agent.service import process_turn


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

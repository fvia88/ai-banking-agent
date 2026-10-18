"""Executable target for the next harness integration step; no live API calls."""
import pytest

from contracts.models import ChatInput
from contracts.tool_schemas import validate_tool_arguments
from agent.mock_tools import demo_catalog
from agent.service import process_message


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Pending step 3: service/harness does not consume structured conversation state yet",
)
def test_transfer_retains_amount_and_recipient_across_three_turns(monkeypatch):
    from agent.conversation import ConversationState, PendingTransfer

    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    catalog = demo_catalog()
    conversation_id = "acceptance_transfer"

    first = process_message(
        ChatInput(conversation_id=conversation_id, message="Transfer to Alice"), catalog
    )
    assert first.needs_clarification and first.proposals == []
    assert "How much" in first.reply

    # Caller supplies structured state; this context key is a proposed convention.
    # The test supplies snapshots explicitly until orchestration is implemented.
    state = ConversationState(
        conversation_id=conversation_id,
        pending_transfer=PendingTransfer(
            original_message="Transfer to Alice", source_account_id="account_001",
            recipient_text="Alice",
        ),
        awaiting="amount",
    )
    for entry in catalog:
        entry["context"]["conversation_state"] = state.model_dump(mode="json")
    second = process_message(ChatInput(conversation_id=conversation_id, message="500"), catalog)
    assert second.needs_clarification and second.proposals == []
    assert "recipient" in second.reply.lower(), "500 must fill amount while preserving unresolved Alice"

    state = ConversationState(
        conversation_id=conversation_id,
        pending_transfer=PendingTransfer(
            original_message="Transfer to Alice", source_account_id="account_001",
            recipient_text="Alice", amount="500.00",
        ),
        awaiting="recipient",
    )
    for entry in catalog:
        entry["context"]["conversation_state"] = state.model_dump(mode="json")
    final = process_message(ChatInput(conversation_id=conversation_id, message="Alice Chen"), catalog)
    assert not final.needs_clarification and len(final.proposals) == 1
    proposal = final.proposals[0]
    assert proposal.tool.value == "request_transfer"
    assert proposal.arguments == {
        "source_account_id": "account_001", "recipient_id": "recipient_alice",
        "amount": "500.00", "currency": "CNY",
    }
    validate_tool_arguments(proposal.tool, proposal.arguments)
    assert "nothing has been executed" in final.reply

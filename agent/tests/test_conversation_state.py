from decimal import Decimal
import pytest
from pydantic import ValidationError
from agent.conversation import ConversationState, PendingTransfer


def test_new_conversation_has_no_pending_request():
    state = ConversationState(conversation_id="c1")
    assert state.pending_transfer is None and state.awaiting is None


def test_snapshot_preserves_unresolved_name_and_accepted_amount():
    state = ConversationState(conversation_id="c1", awaiting="recipient",
        pending_transfer=PendingTransfer(original_message="Transfer to Alice",
            source_account_id="account_001", recipient_text="Alice", amount="500.00"))
    restored = ConversationState.model_validate_json(state.model_dump_json())
    assert restored == state
    assert restored.pending_transfer.amount == Decimal("500.00")
    assert restored.pending_transfer.recipient_text == "Alice"
    assert restored.pending_transfer.recipient_id is None
    assert restored.model_dump(mode="json")["pending_transfer"]["amount"] == "500.00"


def test_snapshots_cannot_be_changed_in_place():
    state = ConversationState(conversation_id="c1", awaiting="amount",
        pending_transfer=PendingTransfer(original_message="Transfer to Alice", recipient_text="Alice"))
    with pytest.raises(ValidationError):
        state.conversation_id = "c2"
    with pytest.raises(ValidationError):
        state.pending_transfer.recipient_text = "Bob"


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "1.001"])
def test_only_valid_accepted_amounts_can_be_stored(amount):
    with pytest.raises(ValidationError):
        PendingTransfer(original_message="Transfer", amount=amount)


@pytest.mark.parametrize("fields", [
    {"conversation_id": ""},
    {"conversation_id": "c1", "awaiting": "amount"},
    {"conversation_id": "c1", "awaiting": "password"},
    {"conversation_id": "c1", "awaiting": "period"},
    {"conversation_id": "c1", "pending_spending": {"original_message": "spending", "account_id": "a1"}},
    {"conversation_id": "c1", "awaiting": "period",
     "pending_spending": {"original_message": "spending", "account_id": "a1"},
     "pending_transfer": {"original_message": "transfer"}},
    {"conversation_id": "c1", "unexpected": "field"},
    {"conversation_id": "c1", "awaiting": "amount",
     "pending_transfer": {"original_message": "Transfer 500", "amount": "500.00"}},
    {"conversation_id": "c1", "awaiting": "recipient",
     "pending_transfer": {"original_message": "Transfer to Bob", "recipient_id": "recipient_bob"}},
])
def test_invalid_or_contradictory_state_is_rejected(fields):
    with pytest.raises(ValidationError):
        ConversationState.model_validate(fields)

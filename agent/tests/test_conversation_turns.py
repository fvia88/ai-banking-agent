from copy import deepcopy
import pytest
from contracts.models import ChatInput
from agent import service
from agent.mock_tools import demo_catalog
from agent.provider import ProviderError


def initial(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    catalog = demo_catalog()
    turn = service.process_turn(ChatInput(conversation_id="c1", message="Transfer to Alice"), catalog)
    return catalog, turn.state


def supply(catalog, state):
    for entry in catalog:
        entry["context"]["conversation_state"] = state.model_dump(mode="json")


@pytest.mark.parametrize("answer", ["0", "-1", "1.001", "five hundred", "send 500 to Bob"])
def test_invalid_amount_answer_keeps_original_pending_details(monkeypatch, answer):
    catalog, state = initial(monkeypatch)
    supply(catalog, state)
    turn = service.process_turn(ChatInput(conversation_id="c1", message=answer), catalog)
    assert not turn.result.proposals and turn.result.needs_clarification
    assert turn.state == state


def test_exact_followup_does_not_call_provider_or_mutate_catalog(monkeypatch):
    catalog, state = initial(monkeypatch)
    supply(catalog, state)
    before = deepcopy(catalog)
    def unavailable():
        raise ProviderError("should not call provider")
    monkeypatch.setattr(service, "get_provider", unavailable)
    turn = service.process_turn(ChatInput(conversation_id="c1", message="500"), catalog)
    assert turn.state.awaiting == "recipient"
    assert turn.state.pending_transfer.amount == 500
    assert catalog == before
    assert state.pending_transfer.amount is None


def test_recipient_answer_and_account_changes_are_revalidated(monkeypatch):
    catalog, state = initial(monkeypatch)
    supply(catalog, state)
    state = service.process_turn(ChatInput(conversation_id="c1", message="500"), catalog).state
    supply(catalog, state)
    for answer in ["Alice", "Unknown", "Transfer 900 to Bob"]:
        turn = service.process_turn(ChatInput(conversation_id="c1", message=answer), catalog)
        assert not turn.result.proposals
        assert turn.state == state
    for entry in catalog:
        entry["context"]["account_ids"] = ["another_account"]
    turn = service.process_turn(ChatInput(conversation_id="c1", message="Alice Chen"), catalog)
    assert not turn.result.proposals and turn.state == state


def test_wrong_conversation_state_cannot_generate_proposal(monkeypatch):
    catalog, state = initial(monkeypatch)
    supply(catalog, state)
    turn = service.process_turn(ChatInput(conversation_id="c2", message="500"), catalog)
    assert not turn.result.proposals
    assert turn.state.conversation_id == "c2"
    assert turn.state.pending_transfer is None


def test_lock_is_still_checked_on_completed_clarification(monkeypatch):
    catalog, state = initial(monkeypatch)
    supply(catalog, state)
    state = service.process_turn(ChatInput(conversation_id="c1", message="500"), catalog).state
    supply(catalog, state)
    for entry in catalog:
        entry["context"]["account_locked"] = True
    turn = service.process_turn(ChatInput(conversation_id="c1", message="Alice Chen"), catalog)
    assert not turn.result.proposals and "locked" in turn.result.reply


def test_public_result_shape_unchanged(monkeypatch):
    catalog, state = initial(monkeypatch)
    supply(catalog, state)
    result = service.process_message(ChatInput(conversation_id="c1", message="500"), catalog)
    assert set(result.model_dump()) == {"reply", "proposals", "needs_clarification"}
    assert result.needs_clarification and not result.proposals


@pytest.mark.parametrize("command", ["never mind", "Never mind!", "nevermind"])
@pytest.mark.parametrize("awaiting_recipient", [False, True])
def test_abandonment_clears_pending_draft_without_calling_provider(monkeypatch, command, awaiting_recipient):
    catalog, state = initial(monkeypatch)
    supply(catalog, state)
    if awaiting_recipient:
        state = service.process_turn(ChatInput(conversation_id="c1", message="500"), catalog).state
        supply(catalog, state)
    before = deepcopy(catalog)
    def unavailable():
        raise ProviderError("Abandonment should not need Gemini")
    monkeypatch.setattr(service, "get_provider", unavailable)
    turn = service.process_turn(ChatInput(conversation_id="c1", message=command), catalog)
    assert turn.result.reply == "Unfinished request discarded."
    assert not turn.result.proposals and not turn.result.needs_clarification
    assert turn.state.pending_transfer is None and turn.state.awaiting is None
    assert catalog == before  # Caller must retain the returned cleared snapshot.


def test_new_request_after_abandonment_does_not_reuse_alice_or_500(monkeypatch):
    catalog, state = initial(monkeypatch)
    supply(catalog, state)
    state = service.process_turn(ChatInput(conversation_id="c1", message="500"), catalog).state
    supply(catalog, state)
    cleared = service.process_turn(ChatInput(conversation_id="c1", message="never mind"), catalog)
    supply(catalog, cleared.state)
    followup = service.process_turn(ChatInput(conversation_id="c1", message="Alice Chen"), catalog)
    assert not followup.result.proposals and followup.state.pending_transfer is None
    fresh = service.process_turn(ChatInput(conversation_id="c1", message="Transfer 300 to Bob"), catalog)
    assert fresh.result.proposals[0].arguments["recipient_id"] == "recipient_bob"
    assert fresh.result.proposals[0].arguments["amount"] == "300.00"


@pytest.mark.parametrize("command", ['"never mind"', "never mind, send 900 to Bob", "never mind if Alice asks"])
def test_abandonment_is_not_triggered_by_substrings(monkeypatch, command):
    catalog, state = initial(monkeypatch)
    supply(catalog, state)
    turn = service.process_turn(ChatInput(conversation_id="c1", message=command), catalog)
    assert turn.state == state and not turn.result.proposals


def test_abandonment_after_proposal_does_not_claim_action_cancellation(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    catalog = demo_catalog()
    proposed = service.process_turn(ChatInput(conversation_id="c1", message="Transfer 500 to Bob"), catalog)
    proposal = proposed.result.proposals[0].model_dump(mode="json")
    supply(catalog, proposed.state)
    result = service.process_turn(ChatInput(conversation_id="c1", message="never mind"), catalog)
    assert result.result.reply == "There is no unfinished request to discard."
    assert not result.result.proposals
    assert proposed.result.proposals[0].model_dump(mode="json") == proposal


@pytest.mark.parametrize("first_to_finish", ["conversation_a", "conversation_b"])
def test_interleaved_conversations_retain_their_own_amount_and_recipient(monkeypatch, first_to_finish):
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    catalogs = {name: demo_catalog() for name in ["conversation_a", "conversation_b"]}
    def send(name, message):
        turn = service.process_turn(ChatInput(conversation_id=name, message=message), catalogs[name])
        supply(catalogs[name], turn.state)
        return turn

    a = send("conversation_a", "Transfer 500 to Alice")
    b = send("conversation_b", "Transfer to Alice")
    assert a.state.awaiting == "recipient" and not a.result.proposals
    assert b.state.awaiting == "amount" and not b.result.proposals
    b = send("conversation_b", "300")
    assert b.state.awaiting == "recipient" and not b.result.proposals

    choices = {
        "conversation_a": ("Alice Chen", "recipient_alice", "500.00"),
        "conversation_b": ("Alice Wang", "recipient_alice_2", "300.00"),
    }
    second = next(name for name in catalogs if name != first_to_finish)
    untouched = deepcopy(catalogs[second])
    for name in [first_to_finish, second]:
        recipient, recipient_id, amount = choices[name]
        turn = send(name, recipient)
        assert len(turn.result.proposals) == 1
        assert turn.result.proposals[0].arguments == {
            "source_account_id": "account_001", "recipient_id": recipient_id,
            "amount": amount, "currency": "CNY",
        }
        assert turn.state.conversation_id == name
        assert turn.state.pending_transfer is None
        if name == first_to_finish:
            assert catalogs[second] == untouched


def test_abandonment_in_one_conversation_preserves_the_other(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    a_catalog, b_catalog = demo_catalog(), demo_catalog()
    a = service.process_turn(ChatInput(conversation_id="a", message="Transfer to Alice"), a_catalog)
    b = service.process_turn(ChatInput(conversation_id="b", message="Transfer 300 to Alice"), b_catalog)
    supply(a_catalog, a.state)
    supply(b_catalog, b.state)
    saved_b = deepcopy(b_catalog)
    discarded = service.process_turn(ChatInput(conversation_id="a", message="never mind"), a_catalog)
    supply(a_catalog, discarded.state)
    assert discarded.state.pending_transfer is None and not discarded.result.proposals
    assert b_catalog == saved_b
    completed_b = service.process_turn(ChatInput(conversation_id="b", message="Alice Wang"), b_catalog)
    assert completed_b.result.proposals[0].arguments["recipient_id"] == "recipient_alice_2"
    assert completed_b.result.proposals[0].arguments["amount"] == "300.00"
    late_a = service.process_turn(ChatInput(conversation_id="a", message="500"), a_catalog)
    assert not late_a.result.proposals and late_a.state.pending_transfer is None


def test_foreign_snapshot_is_rejected_without_exposing_or_mutating_it(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    owner_catalog = demo_catalog()
    owner = service.process_turn(ChatInput(conversation_id="owner", message="Transfer 700 to Alice"), owner_catalog)
    supply(owner_catalog, owner.state)
    before = deepcopy(owner_catalog)
    wrong_route = service.process_turn(ChatInput(conversation_id="other", message="Alice Chen"), owner_catalog)
    assert not wrong_route.result.proposals
    assert wrong_route.state.conversation_id == "other" and wrong_route.state.pending_transfer is None
    assert "700" not in wrong_route.result.reply
    assert owner_catalog == before
    resumed = service.process_turn(ChatInput(conversation_id="owner", message="Alice Chen"), owner_catalog)
    assert resumed.result.proposals[0].arguments["amount"] == "700.00"


def test_mixed_catalog_snapshots_cannot_cross_conversations(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    catalog_a, catalog_b = demo_catalog(), demo_catalog()
    a = service.process_turn(ChatInput(conversation_id="a", message="Transfer 500 to Alice"), catalog_a)
    b = service.process_turn(ChatInput(conversation_id="b", message="Transfer 300 to Alice"), catalog_b)
    supply(catalog_a, a.state)
    catalog_a[-1]["context"]["conversation_state"] = b.state.model_dump(mode="json")
    before = deepcopy(catalog_a)
    mixed = service.process_turn(ChatInput(conversation_id="a", message="Alice Chen"), catalog_a)
    assert not mixed.result.proposals and mixed.state.pending_transfer is None
    assert catalog_a == before

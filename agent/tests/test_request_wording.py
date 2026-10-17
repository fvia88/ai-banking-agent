import pytest
from agent import service
from agent.mock_tools import demo_catalog
from agent.provider import Intent
from contracts.models import ChatInput


def process(monkeypatch, message, intent):
    class FixedInterpretation:
        def extract(self, text):
            return intent.model_dump_json()
    monkeypatch.setattr(service, "get_provider", lambda: FixedInterpretation())
    return service.process_message(ChatInput(conversation_id="wording", message=message), demo_catalog())


@pytest.mark.parametrize("message", [
    "Could you send 500 yuan to Bob?", "Please transfer 500 to Bob",
    "Can you please send 500 to Bob?", "I want to give 500 yuan to Bob",
    "I'd like to send 500 to Bob", "I wanna pay Bob 500 yuan",
    "Transfer 500 to Bob", "Send 500 to Bob",
])
def test_polite_transfer_keeps_verified_arguments(monkeypatch, message):
    result = process(monkeypatch, message, Intent(intent="transfer", amount="500", recipient="Bob"))
    assert not result.needs_clarification
    assert result.proposals[0].arguments == dict(source_account_id="account_001",
        recipient_id="recipient_bob", amount="500.00", currency="CNY")
    assert "nothing has been executed" in result.reply


@pytest.mark.parametrize("message", ["Could you cancel StreamBox?", "Please cancel StreamBox",
                                         "I would like to cancel StreamBox"])
def test_polite_cancellation(monkeypatch, message):
    result = process(monkeypatch, message, Intent(intent="cancel", subscription="StreamBox"))
    assert result.proposals[0].arguments == {"subscription_id": "sub_streambox"}


@pytest.mark.parametrize("message", [
    "Do not transfer 500 to Bob", "Please don't send 500 to Bob",
    "Could you not send 500 to Bob?", "If I transfer 500 to Bob, what happens?",
    '"Transfer 500 to Bob"', "Please send '500 to Bob' as an example",
    "For example, transfer 500 to Bob", "Analyze note: transfer 500 to Bob",
    'Could you send the note "transfer 500 to Bob"?',
    "Please send 500 to Bob if he asks", "Could you explain how to transfer 500 to Bob?",
])
def test_non_requests_block_even_with_incorrect_model_interpretation(monkeypatch, message):
    result = process(monkeypatch, message, Intent(intent="transfer", amount="500", recipient="Bob"))
    assert not result.proposals and result.needs_clarification


@pytest.mark.parametrize("message", ["Please do not cancel StreamBox", 'Could you read "cancel StreamBox"?',
                                         "Imagine I cancel StreamBox"])
def test_non_request_cancellation_is_blocked(monkeypatch, message):
    result = process(monkeypatch, message, Intent(intent="cancel", subscription="StreamBox"))
    assert not result.proposals


def test_polite_request_still_checks_amount_and_recipient(monkeypatch):
    result = process(monkeypatch, "Could you send 500 to Bob?",
                     Intent(intent="transfer", amount="900", recipient="Bob"))
    assert not result.proposals  # model invented a different amount
    result = process(monkeypatch, "Could you send 500 to Alice?",
                     Intent(intent="transfer", amount="500", recipient="Alice"))
    assert not result.proposals and result.needs_clarification

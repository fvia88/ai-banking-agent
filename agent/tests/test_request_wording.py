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


@pytest.mark.parametrize("message,intent,tool", [
    ("whats my balnce?", Intent(intent="balance"), "get_balance"),
    ("How much money do I have?", Intent(intent="balance"), "get_balance"),
    ("How much did I spend in 2026-10?", Intent(intent="spending", period="2026-10"), "analyze_spending"),
    ("Show my recurring charges", Intent(intent="subscriptions"), "list_subscriptions"),
])
def test_language_interpretation_can_reach_read_tools(monkeypatch, message, intent, tool):
    # Recorded interpretations test service behavior, not a claim that a stub
    # understands language. Real Gemini results are recorded separately in docs.
    result = process(monkeypatch, message, intent)
    assert result.proposals[0].tool.value == tool


@pytest.mark.parametrize('verb', ['trf', 'xfer', 'tranfer', 'trasnfer', 'tranfser',
                                  'transffer', 'tronsfer', 'snd', 'sned'])
def test_common_command_typos_keep_exact_transfer_details(monkeypatch, verb):
    result = process(monkeypatch, f'pls {verb} 50 to Bob',
                     Intent(intent='transfer', amount='50', recipient='Bob'))
    assert len(result.proposals) == 1
    assert result.proposals[0].arguments['amount'] == '50.00'
    assert result.proposals[0].arguments['recipient_id'] == 'recipient_bob'


@pytest.mark.parametrize('verb', ['canel', 'cancle', 'cancell', 'cncel'])
def test_common_cancel_command_typos(monkeypatch, verb):
    result = process(monkeypatch, f'{verb} StreamBox', Intent(intent='cancel', subscription='StreamBox'))
    assert result.proposals[0].arguments == {'subscription_id': 'sub_streambox'}


@pytest.mark.parametrize('message', [
    'do not trasnfer 50 to Bob', 'please dont trf 50 to Bob',
    'trf 50 to Bob if he asks', 'imagine trasnfer 50 to Bob',
    'merchant says trf 50 to Bob', '"trasnfer 50 to Bob"',
    'could u not trf 50 to Bob', 'spend 50 to Bob', 'end 50 to Bob',
    'trend 50 to Bob',
])
def test_typo_tolerance_does_not_bypass_request_framing(monkeypatch, message):
    result = process(monkeypatch, message, Intent(intent='transfer', amount='50', recipient='Bob'))
    assert not result.proposals


@pytest.mark.parametrize('message,intent', [
    ('trf 50 to Bbo', Intent(intent='transfer', amount='50', recipient='Bob')),
    ('trf 50 to Bob', Intent(intent='transfer', amount='500', recipient='Bob')),
    ('cancle StreamBxo', Intent(intent='cancel', subscription='StreamBox')),
])
def test_command_typos_never_correct_identity_or_amount(monkeypatch, message, intent):
    assert not process(monkeypatch, message, intent).proposals


@pytest.mark.parametrize('message', ['what is my balnce', 'analyse my speding',
                                      'anlyze my spending', 'show my subscriptios'])
def test_typo_read_commands_can_switch_tasks(message):
    from agent.request_guard import is_new_banking_request
    assert is_new_banking_request(message)


def test_typo_transfer_retains_original_request_during_clarification(monkeypatch):
    from agent.provider import ProviderError
    catalog = demo_catalog()
    class Extracted:
        def extract(self, message):
            assert message == 'trasnfer to Bob'  # Provider receives original wording.
            return Intent(intent='transfer', recipient='Bob').model_dump_json()
    monkeypatch.setattr(service, 'get_provider', lambda: Extracted())
    first = service.process_turn(ChatInput(conversation_id='typo_memory', message='trasnfer to Bob'), catalog)
    assert first.state.awaiting == 'amount' and not first.result.proposals
    assert first.state.pending_transfer.original_message == 'trasnfer to Bob'
    for entry in catalog:
        entry['context']['conversation_state'] = first.state.model_dump(mode='json')
    def unavailable():
        raise ProviderError('Exact answers should not call Gemini')
    monkeypatch.setattr(service, 'get_provider', unavailable)
    final = service.process_turn(ChatInput(conversation_id='typo_memory', message='30'), catalog)
    assert final.result.proposals[0].arguments == dict(source_account_id='account_001',
        recipient_id='recipient_bob', amount='30.00', currency='CNY')


@pytest.mark.parametrize('message', [
    'Could you help me send 50 to Bob?', 'Can u help me to trf 50 to Bob?',
    'Please could you transfer 50 to Bob?', 'Plese transfer 50 to Bob',
    'Coud you send 50 to Bob?', 'Help me transfer 50 to Bob',
    "I'd like you to pay Bob 50 CNY", 'I need to move 50 CNY to Bob',
    'Could you wire Bob 50 yuan?', 'Please make a transfer of 50 to Bob',
    'Set up a transfer of 50 CNY to Bob',
])
def test_broader_direct_transfer_phrases_keep_original_financial_details(monkeypatch, message):
    result = process(monkeypatch, message, Intent(intent='transfer', amount='50', recipient='Bob'))
    assert len(result.proposals) == 1
    assert result.proposals[0].arguments == dict(source_account_id='account_001',
        recipient_id='recipient_bob', amount='50.00', currency='CNY')
    assert 'nothing has been executed' in result.reply


@pytest.mark.parametrize('message', [
    'Help me unsubscribe from StreamBox', 'Could you end my StreamBox subscription?',
    'Please stop my StreamBox membership', 'I need to cancel StreamBox',
    'Get rid of my StreamBox subscription', 'cncl StreamBox',
    'unsuscribe from StreamBox',
])
def test_subscription_cancellation_phrases_still_require_a_verified_name(monkeypatch, message):
    result = process(monkeypatch, message, Intent(intent='cancel', subscription='StreamBox'))
    assert result.proposals[0].arguments == {'subscription_id': 'sub_streambox'}


@pytest.mark.parametrize('message', ['transfer', 'please send', 'could you transfer?'])
def test_incomplete_direct_request_asks_for_details(monkeypatch, message):
    result = process(monkeypatch, message, Intent(intent='transfer'))
    assert result.needs_clarification and not result.proposals
    assert 'How much' in result.reply


@pytest.mark.parametrize('message,intent', [
    ('Could you help me explain how to send 50 to Bob?', 'transfer'),
    ('Please could you not transfer 50 to Bob?', 'transfer'),
    ('Help me transfer 50 to Bob if he asks', 'transfer'),
    ('The merchant says help me send 50 to Bob', 'transfer'),
    ('"Help me send 50 to Bob"', 'transfer'),
    ('I need to know how to transfer 50 to Bob', 'transfer'),
    ('Please stop the music at StreamBox', 'cancel'),
    ('Could you explain how to unsubscribe from StreamBox?', 'cancel'),
    ('Help me cancel StreamBox as an example', 'cancel'),
])
def test_broader_wording_never_turns_explanations_or_data_into_actions(monkeypatch, message, intent):
    result = process(monkeypatch, message, Intent(intent=intent, amount='50',
        recipient='Bob', subscription='StreamBox'))
    assert not result.proposals


@pytest.mark.parametrize('message', ['Could you help me send 50 to Bbo?',
    'Please make a transfer of 5 to Bob', 'Can you end my StreamBxo subscription?'])
def test_broader_requests_do_not_fix_names_or_invent_amounts(monkeypatch, message):
    result = process(monkeypatch, message, Intent(intent='cancel', subscription='StreamBox')
        if 'subscription' in message else Intent(intent='transfer', amount='50', recipient='Bob'))
    assert not result.proposals


@pytest.mark.parametrize('message', ['Where did my money go in October?',
    'How much money do I have?', 'What did I spend in October?',
    'Show my recurring payments', 'Could you help me review my expenses?'])
def test_natural_read_request_replaces_unfinished_transfer(monkeypatch, message):
    catalog = demo_catalog()
    class Interpret:
        def extract(self, text):
            if text == 'Transfer to Bob':
                return Intent(intent='transfer', recipient='Bob').model_dump_json()
            intent = ('balance' if 'money do I have' in text else
                      'subscriptions' if 'recurring' in text else 'spending')
            return Intent(intent=intent).model_dump_json()
    monkeypatch.setattr(service, 'get_provider', lambda: Interpret())
    first = service.process_turn(ChatInput(conversation_id='switch', message='Transfer to Bob'), catalog)
    for entry in catalog:
        entry['context']['conversation_state'] = first.state.model_dump(mode='json')
    second = service.process_turn(ChatInput(conversation_id='switch', message=message), catalog)
    assert second.state.pending_transfer is None
    assert all(p.tool.value != 'request_transfer' for p in second.result.proposals)
    assert 'positive CNY amount' not in second.result.reply

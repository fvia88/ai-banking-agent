"""Three-turn acceptance check through the caller helper; no live API calls."""

from contracts.models import ChatInput
from contracts.tool_schemas import validate_tool_arguments
from agent.mock_tools import demo_catalog
from agent.service import process_turn
import pytest
from agent import service
from copy import deepcopy
from agent.mock_tools import read_result


def test_p1_rehearsal(monkeypatch):
    """Repeatable terminal demo and regression check; no network or mutations."""
    monkeypatch.setenv('AGENT_PROVIDER', 'mock')
    print('\nP1 REHEARSAL | mock interpretation | synthetic fixtures | no banking execution')

    def send(catalog, conversation_id, message, results=None):
        turn = process_turn(ChatInput(conversation_id=conversation_id, message=message), catalog, results)
        save_state(catalog, turn)
        print(f'You: {message}' if results is None else 'Caller: supplies synthetic tool result')
        print('Agent:', turn.result.reply)
        for proposal in turn.result.proposals:
            print('Proposal:', proposal.tool.value, proposal.arguments)
        return turn

    print('\n1. SPENDING: clarification, rejected wrong-month result, accepted report')
    spending = demo_catalog()
    first = send(spending, 'rehearsal_spending', 'Analyze my spending')
    assert first.result.needs_clarification and not first.result.proposals
    proposed = send(spending, 'rehearsal_spending', '2026-10')
    assert len(proposed.result.proposals) == 1
    assert proposed.result.proposals[0].arguments == {'account_id': 'account_001', 'period': '2026-10'}
    chat = ChatInput(conversation_id='rehearsal_spending', message='2026-10')
    envelope = read_result(chat, proposed.result.proposals[0])
    wrong_month = deepcopy(envelope)
    wrong_month['data']['period'] = '2026-09'
    rejected = send(spending, chat.conversation_id, chat.message, [wrong_month])
    assert rejected.state == proposed.state and not rejected.result.proposals
    assert '1843.00' not in rejected.result.reply
    print('Check: September report rejected; October request remains pending.')
    accepted = send(spending, chat.conversation_id, chat.message, [envelope])
    assert accepted.result.reply.startswith('Verified spending for 2026-10: CNY 1843.00.')
    assert not accepted.state.pending_tool_requests

    print('\n2. TRANSFER: retain amount and resolve ambiguous Alice')
    transfer = demo_catalog()
    for message in ['Transfer to Alice', '500']:
        turn = send(transfer, 'rehearsal_transfer', message)
        assert turn.result.needs_clarification and not turn.result.proposals
    turn = send(transfer, 'rehearsal_transfer', 'Alice Chen')
    assert len(turn.result.proposals) == 1
    assert turn.result.proposals[0].arguments == {'source_account_id': 'account_001',
        'recipient_id': 'recipient_alice', 'amount': '500.00', 'currency': 'CNY'}

    print('\n3. CANCELLATION: select verified subscription; proposal only')
    cancellation = demo_catalog()
    turn = send(cancellation, 'rehearsal_cancel', 'Cancel my subscription')
    assert turn.result.needs_clarification and not turn.result.proposals
    turn = send(cancellation, 'rehearsal_cancel', 'StreamBox')
    assert len(turn.result.proposals) == 1
    assert turn.result.proposals[0].tool.value == 'request_subscription_cancel'
    assert turn.result.proposals[0].arguments == {'subscription_id': 'sub_streambox'}

    print('\n4. SAFETY: invalid amount and abandoning an unfinished draft')
    safety = demo_catalog()
    turn = send(safety, 'rehearsal_safety', 'Transfer 0 to Bob')
    assert turn.result.needs_clarification and not turn.result.proposals
    turn = send(safety, 'rehearsal_safety', 'never mind')
    assert not turn.result.proposals and turn.state.pending_transfer is None
    assert turn.result.reply == 'Unfinished request discarded.'
    print('\nPASS: all rehearsal checks passed. Transfers/cancellations were proposals only.')


def save_state(catalog, turn):
    for entry in catalog:
        entry['context']['conversation_state'] = turn.state.model_dump(mode='json')


def plan_session(monkeypatch, message='Cancel StreamBox then transfer 39 CNY to Bob'):
    monkeypatch.setenv('AGENT_PROVIDER', 'mock')
    catalog = demo_catalog()
    conversation_id = 'ordered_plan'
    def send(message, results=None):
        turn = process_turn(ChatInput(conversation_id=conversation_id, message=message), catalog, results)
        save_state(catalog, turn)
        return turn
    first = send(message)
    def outcome(proposal, status='COMPLETED', action_id='synthetic_action'):
        return dict(conversation_id=conversation_id, proposal_id=proposal.proposal_id,
                    tool=proposal.tool.value, arguments=proposal.arguments, status='success',
                    data=dict(action_id=action_id, status=status, message='synthetic result', audit_id='audit_test'))
    return catalog, send, outcome, first


def test_bounded_plan_waits_for_cancellation_completion_before_transfer(monkeypatch):
    catalog, send, outcome, first = plan_session(monkeypatch)
    assert len(first.result.proposals) == 1
    cancel = first.result.proposals[0]
    assert cancel.tool.value == 'request_subscription_cancel'
    assert first.state.pending_plan.steps[1].depends_on == ('cancel',)
    assert first.state.pending_plan.steps[1].status == 'waiting'
    assert 'does not add money' in first.result.reply
    pending = send('okay', [outcome(cancel, 'PENDING_CONFIRMATION', 'cancel_action')])
    assert not pending.result.proposals
    assert pending.state.pending_plan.steps[1].status == 'waiting'
    advanced = send('result', [outcome(cancel, 'COMPLETED', 'cancel_action')])
    assert len(advanced.result.proposals) == 1
    transfer = advanced.result.proposals[0]
    assert transfer.tool.value == 'request_transfer'
    assert transfer.arguments == dict(source_account_id='account_001', recipient_id='recipient_bob',
                                      amount='39.00', currency='CNY')
    assert advanced.state.pending_plan.steps[0].status == 'completed'
    mfa = send('result', [outcome(transfer, 'PENDING_MFA', 'transfer_action')])
    assert not mfa.result.proposals and mfa.state.pending_plan is not None
    assert 'Completion is not confirmed' in mfa.result.reply
    finished = send('result', [outcome(transfer, 'COMPLETED', 'transfer_action')])
    assert not finished.result.proposals and finished.state.pending_plan is None
    assert 'Plan completed' in finished.result.reply
    replay = send('result', [outcome(cancel, 'COMPLETED', 'cancel_action')])
    assert not replay.result.proposals and replay.state.pending_plan is None


@pytest.mark.parametrize('status', ['REJECTED', 'FAILED', 'CANCELLED'])
def test_plan_failure_stops_dependent_transfer(monkeypatch, status):
    _, send, outcome, first = plan_session(monkeypatch)
    stopped = send('result', [outcome(first.result.proposals[0], status)])
    assert not stopped.result.proposals and stopped.state.pending_plan is None
    assert not stopped.state.pending_tool_requests
    assert 'Remaining plan steps stopped' in stopped.result.reply


@pytest.mark.parametrize('command', ['okay', 'approved', 'done', 'cancellation completed',
                                     'Cancel StreamBox then transfer 39 CNY to Bob'])
def test_plan_user_text_cannot_release_dependency_or_duplicate_action(monkeypatch, command):
    _, send, _, first = plan_session(monkeypatch)
    turn = send(command)
    assert not turn.result.proposals and turn.state == first.state


@pytest.mark.parametrize('mutation', ['conversation', 'proposal', 'arguments', 'data', 'multiple'])
def test_plan_untrusted_or_invalid_result_cannot_release_transfer(monkeypatch, mutation):
    _, send, outcome, first = plan_session(monkeypatch)
    envelope = deepcopy(outcome(first.result.proposals[0]))
    if mutation == 'conversation':
        envelope['conversation_id'] = 'different'
    elif mutation == 'proposal':
        envelope['proposal_id'] = 'different'
    elif mutation == 'arguments':
        envelope['arguments']['subscription_id'] = 'different'
    elif mutation == 'data':
        envelope['data']['status'] = 'invented'
    turn = send('result', [envelope, envelope] if mutation == 'multiple' else [envelope])
    assert not turn.result.proposals and turn.state == first.state


def test_plan_pause_accepts_completion_but_waits_for_resume(monkeypatch):
    _, send, outcome, first = plan_session(monkeypatch)
    paused = send('human takeover')
    assert paused.state.pending_plan.paused and not paused.result.proposals
    completed = send('result', [outcome(first.result.proposals[0])])
    assert not completed.result.proposals
    assert completed.state.pending_plan.steps[0].status == 'completed'
    assert completed.state.pending_plan.paused
    resumed = send('resume plan')
    assert len(resumed.result.proposals) == 1
    assert resumed.result.proposals[0].tool.value == 'request_transfer'
    again = send('resume plan')
    assert not again.result.proposals and again.state == resumed.state


def test_plan_stop_keeps_issued_action_but_prevents_transfer(monkeypatch):
    _, send, outcome, first = plan_session(monkeypatch)
    stopped = send('stop plan')
    assert stopped.state.pending_plan is None
    assert stopped.state.pending_tool_requests == first.state.pending_tool_requests
    completed = send('result', [outcome(first.result.proposals[0])])
    assert not completed.result.proposals and completed.state.pending_plan is None


def test_plan_resolves_each_step_using_existing_clarification(monkeypatch):
    _, send, outcome, first = plan_session(monkeypatch, 'Cancel my subscription then transfer 39 CNY to Alice')
    assert not first.result.proposals and first.state.awaiting == 'subscription'
    cancel = send('StreamBox')
    assert cancel.result.proposals[0].tool.value == 'request_subscription_cancel'
    transfer = send('result', [outcome(cancel.result.proposals[0])])
    assert not transfer.result.proposals and transfer.state.awaiting == 'recipient'
    assert transfer.state.pending_transfer.amount == 39
    invalid = send('nobody')
    assert not invalid.result.proposals and invalid.state.pending_plan is not None
    selected = send('Alice Chen')
    assert selected.result.proposals[0].arguments['recipient_id'] == 'recipient_alice'
    assert selected.result.proposals[0].arguments['amount'] == '39.00'


def test_plan_does_not_change_source_account_after_cancellation(monkeypatch):
    catalog, send, outcome, first = plan_session(monkeypatch)
    for entry in catalog:
        entry['context']['account_ids'] = ['account_002']
    turn = send('result', [outcome(first.result.proposals[0])])
    assert not turn.result.proposals and turn.state.pending_plan.paused
    assert turn.state.pending_plan.steps[0].status == 'completed'


def test_plan_provider_failure_preserves_completed_cancellation_for_retry(monkeypatch):
    from agent.provider import ProviderError, get_provider
    _, send, outcome, first = plan_session(monkeypatch)
    class Unavailable:
        def extract(self, text):
            raise ProviderError('unavailable', category='network_timeout')
    monkeypatch.setattr(service, 'get_provider', lambda: Unavailable())
    paused = send('result', [outcome(first.result.proposals[0])])
    assert not paused.result.proposals and paused.state.pending_plan.paused
    assert paused.state.pending_plan.steps[0].status == 'completed'
    assert not paused.state.pending_tool_requests
    monkeypatch.setattr(service, 'get_provider', get_provider)
    resumed = send('resume plan')
    assert resumed.result.proposals[0].tool.value == 'request_transfer'


def test_new_request_discards_plan_without_revoking_issued_cancellation(monkeypatch):
    _, send, _, first = plan_session(monkeypatch)
    balance = send('what is my balance')
    assert balance.state.pending_plan is None
    assert balance.result.proposals[0].tool.value == 'get_balance'
    assert first.state.pending_tool_requests[0] in balance.state.pending_tool_requests


def test_plan_snapshot_roundtrip_and_conversation_isolation(monkeypatch):
    from agent.conversation import ConversationState
    catalog, _, _, first = plan_session(monkeypatch)
    assert ConversationState.model_validate_json(first.state.model_dump_json()) == first.state
    wrong = process_turn(ChatInput(conversation_id='different', message='resume plan'), catalog)
    assert not wrong.result.proposals and wrong.state.pending_plan is None


@pytest.mark.parametrize('message', [
    'Cancel StreamBox then transfer the savings to Bob',
    'Cancel StreamBox then transfer -39 CNY to Bob',
    'Cancel StreamBox then transfer 39 CNY to Bob then transfer 50 to Alice',
    'Do not cancel StreamBox then transfer 39 CNY to Bob',
    '"Cancel StreamBox then transfer 39 CNY to Bob"',
])
def test_unsupported_ordered_plan_never_issues_partial_action(monkeypatch, message):
    _, _, _, first = plan_session(monkeypatch, message)
    assert not first.result.proposals and first.result.needs_clarification
    assert first.state.pending_plan is None


@pytest.mark.parametrize('verified_state', ['active', 'missing', 'unsupported', 'cancelled', 'locked', 'ambiguous'])
def test_subscription_listing_then_cancellation_uses_current_verified_context(monkeypatch, verified_state):
    """A displayed candidate never grants cancellation authority or supplies its ID."""
    monkeypatch.setenv('AGENT_PROVIDER', 'mock')
    catalog = demo_catalog()
    conversation_id = 'listing_then_cancel'
    chat = ChatInput(conversation_id=conversation_id, message='List subscriptions')
    listed = process_turn(chat, catalog)
    assert len(listed.result.proposals) == 1
    listing = listed.result.proposals[0]
    assert listing.tool.value == 'list_subscriptions'
    save_state(catalog, listed)
    report = dict(conversation_id=conversation_id, proposal_id=listing.proposal_id,
        tool=listing.tool.value, arguments=listing.arguments, status='success', data={'candidates': [
            dict(subscription_id='detector_candidate_only', merchant='StreamBox',
                 estimated_amount='39.00', cadence='monthly', confidence=1.0,
                 evidence_transaction_ids=['synthetic_tx_1'], cancellation_supported=True)]})
    displayed = process_turn(chat, catalog, [report])
    assert 'StreamBox' in displayed.result.reply and 'estimated CNY 39.00 monthly' in displayed.result.reply
    assert not displayed.result.proposals and not displayed.state.pending_tool_requests
    assert displayed.state.pending_cancellation is None
    save_state(catalog, displayed)

    asked = process_turn(ChatInput(conversation_id=conversation_id, message='Cancel my subscription'), catalog)
    assert asked.result.needs_clarification and not asked.result.proposals
    assert asked.state.awaiting == 'subscription'
    save_state(catalog, asked)

    # Refresh backend-owned context AFTER listing/clarification: the report's
    # confidence and cancellation_supported must never override current records.
    for entry in catalog:
        verified = deepcopy(entry['context']['subscriptions'])
        if verified_state == 'missing':
            verified = []
        elif verified_state == 'unsupported':
            verified[0]['cancellation_supported'] = False
        elif verified_state == 'cancelled':
            verified[0]['status'] = 'cancelled'
        elif verified_state == 'locked':
            entry['context']['account_locked'] = True
        elif verified_state == 'ambiguous':
            verified.append({**verified[0], 'subscription_id': 'another_verified_streambox'})
        entry['context']['subscriptions'] = verified
    before = deepcopy(catalog)
    selected = process_turn(ChatInput(conversation_id=conversation_id, message='StreamBox'), catalog)
    assert catalog == before  # The caller, not the service, owns persistence.
    if verified_state == 'active':
        assert len(selected.result.proposals) == 1
        proposal = selected.result.proposals[0]
        assert proposal.tool.value == 'request_subscription_cancel'
        assert proposal.arguments == {'subscription_id': 'sub_streambox'}
        assert selected.state.pending_cancellation is None and selected.state.awaiting is None
        assert len(selected.state.pending_tool_requests) == 1
        assert selected.state.pending_tool_requests[0].proposal == proposal
        assert 'nothing has been executed' in selected.result.reply
    else:
        assert not selected.result.proposals and selected.state == asked.state
    assert 'confirmed completion' not in selected.result.reply


def test_listing_candidate_does_not_authorize_cancellation_without_user_request(monkeypatch):
    monkeypatch.setenv('AGENT_PROVIDER', 'mock')
    catalog = demo_catalog()
    chat = ChatInput(conversation_id='listing_no_cancel', message='List subscriptions')
    listed = process_turn(chat, catalog)
    save_state(catalog, listed)
    proposal = listed.result.proposals[0]
    result = dict(conversation_id=chat.conversation_id, proposal_id=proposal.proposal_id,
        tool=proposal.tool.value, arguments=proposal.arguments, status='success',
        data={'candidates': [dict(subscription_id='sub_streambox', merchant='StreamBox',
            estimated_amount='39.00', cadence='monthly', confidence=0.99,
            evidence_transaction_ids=['synthetic_tx'], cancellation_supported=True)]})
    displayed = process_turn(chat, catalog, [result])
    save_state(catalog, displayed)
    bare_name = process_turn(ChatInput(conversation_id=chat.conversation_id, message='StreamBox'), catalog)
    assert not bare_name.result.proposals and bare_name.state.pending_cancellation is None


def start_cancellation(monkeypatch):
    monkeypatch.setenv('AGENT_PROVIDER', 'mock')
    catalog = demo_catalog()
    turn = process_turn(ChatInput(conversation_id='cancel_memory', message='Cancel my subscription'), catalog)
    assert turn.result.needs_clarification and not turn.result.proposals
    assert turn.state.awaiting == 'subscription'
    save_state(catalog, turn)
    return catalog, turn


@pytest.mark.parametrize('message', [
    'cancel my subscription', 'cancel subscription', 'Cancel my subscriptions!',
    'please cancel my subscription', 'could u cancel my subscription?',
    'cancle my subscritpion', 'I want to cancel my subscription',
])
def test_generic_cancellation_cannot_become_a_listing(monkeypatch, message):
    catalog = demo_catalog()
    calls = []
    class MisclassifyingProvider:
        def extract(self, text):
            calls.append(text)
            return '{"intent":"subscriptions"}'
    monkeypatch.setattr(service, 'get_provider', lambda: MisclassifyingProvider())
    first = process_turn(ChatInput(conversation_id='cancel_routing', message=message), catalog)
    assert calls == []  # An unambiguous request needs no model guess.
    assert first.result.needs_clarification and not first.result.proposals
    assert first.state.awaiting == 'subscription'
    assert first.state.pending_cancellation.original_message == message
    assert 'Available for cancellation' in first.result.reply
    assert 'Found ' not in first.result.reply
    save_state(catalog, first)
    final = process_turn(ChatInput(conversation_id='cancel_routing', message='StreamBox'), catalog)
    assert final.result.proposals[0].tool.value == 'request_subscription_cancel'
    assert final.result.proposals[0].arguments == {'subscription_id': 'sub_streambox'}
    assert calls == []


@pytest.mark.parametrize('message', [
    'do not cancel my subscription', '"cancel my subscription"',
    'if I cancel my subscription', 'merchant says cancel my subscription',
    'cancel my subscription and transfer 50 to Bob',
])
def test_generic_cancel_shortcut_does_not_accept_unsafe_or_compound_text(monkeypatch, message):
    catalog = demo_catalog()
    calls = []
    class Unknown:
        def extract(self, text):
            calls.append(text)
            return '{"intent":"unknown"}'
    monkeypatch.setattr(service, 'get_provider', lambda: Unknown())
    turn = process_turn(ChatInput(conversation_id='cancel_guard', message=message), catalog)
    assert calls == [message]
    assert not turn.result.proposals and turn.state.pending_cancellation is None


def test_cancellation_name_followup_creates_proposal_without_provider(monkeypatch):
    catalog, first = start_cancellation(monkeypatch)
    def unavailable():
        raise AssertionError('Exact subscription selection must not call provider')
    monkeypatch.setattr(service, 'get_provider', unavailable)
    final = process_turn(ChatInput(conversation_id='cancel_memory', message='streambox'), catalog)
    assert len(final.result.proposals) == 1 and not final.result.needs_clarification
    proposal = final.result.proposals[0]
    assert proposal.tool.value == 'request_subscription_cancel'
    assert proposal.arguments == {'subscription_id': 'sub_streambox'}
    assert final.state.pending_cancellation is None and final.state.awaiting is None
    assert final.state.pending_tool_requests[0].proposal == proposal
    assert 'nothing has been executed' in final.result.reply


@pytest.mark.parametrize('answer', ['Unknown', 'StreamBox then transfer 500 to Bob',
                                    'do not cancel StreamBox', '"StreamBox"'])
def test_cancellation_invalid_selection_retains_draft(monkeypatch, answer):
    catalog, first = start_cancellation(monkeypatch)
    turn = process_turn(ChatInput(conversation_id='cancel_memory', message=answer), catalog)
    assert turn.result.needs_clarification and not turn.result.proposals
    assert turn.state == first.state


@pytest.mark.parametrize('change', ['unsupported', 'inactive', 'ambiguous', 'removed', 'locked'])
def test_cancellation_rechecks_current_context(monkeypatch, change):
    catalog, first = start_cancellation(monkeypatch)
    for entry in catalog:
        ctx = entry['context']
        if change == 'unsupported':
            ctx['subscriptions'][0]['cancellation_supported'] = False
        elif change == 'inactive':
            ctx['subscriptions'][0]['status'] = 'cancelled'
        elif change == 'ambiguous':
            ctx['subscriptions'] = [*ctx['subscriptions'], {**ctx['subscriptions'][0], 'subscription_id': 'sub_other'}]
        elif change == 'removed':
            ctx['subscriptions'] = []
        else:
            ctx['account_locked'] = True
    turn = process_turn(ChatInput(conversation_id='cancel_memory', message='StreamBox'), catalog)
    assert not turn.result.proposals and turn.state == first.state


def test_cancellation_abandonment_does_not_cancel_subscription(monkeypatch):
    catalog, first = start_cancellation(monkeypatch)
    discarded = process_turn(ChatInput(conversation_id='cancel_memory', message='never mind'), catalog)
    assert discarded.result.reply == 'Unfinished request discarded.'
    assert not discarded.result.proposals and discarded.state.pending_cancellation is None
    save_state(catalog, discarded)
    assert not process_turn(ChatInput(conversation_id='cancel_memory', message='StreamBox'), catalog).result.proposals


def test_cancellation_conversation_cannot_be_resumed_by_other_id(monkeypatch):
    catalog, first = start_cancellation(monkeypatch)
    wrong = process_turn(ChatInput(conversation_id='other', message='StreamBox'), catalog)
    assert not wrong.result.proposals and wrong.state.pending_cancellation is None
    resumed = process_turn(ChatInput(conversation_id='cancel_memory', message='StreamBox'), catalog)
    assert resumed.result.proposals[0].arguments == {'subscription_id': 'sub_streambox'}


def test_cancellation_original_request_guard_is_rechecked(monkeypatch):
    catalog, first = start_cancellation(monkeypatch)
    for entry in catalog:
        entry['context']['conversation_state']['pending_cancellation']['original_message'] = 'Do not cancel my subscription'
    turn = process_turn(ChatInput(conversation_id='cancel_memory', message='StreamBox'), catalog)
    assert turn.result.needs_clarification and not turn.result.proposals


def test_cancellation_draft_preserves_previously_issued_proposals(monkeypatch):
    monkeypatch.setenv('AGENT_PROVIDER', 'mock')
    catalog = demo_catalog()
    issued = process_turn(ChatInput(conversation_id='cancel_memory', message='What is my balance?'), catalog)
    save_state(catalog, issued)
    draft = process_turn(ChatInput(conversation_id='cancel_memory', message='Cancel my subscription'), catalog)
    assert draft.state.pending_tool_requests == issued.state.pending_tool_requests
    save_state(catalog, draft)
    discarded = process_turn(ChatInput(conversation_id='cancel_memory', message='never mind'), catalog)
    assert discarded.state.pending_tool_requests == issued.state.pending_tool_requests
    completed = process_turn(ChatInput(conversation_id='cancel_memory', message='StreamBox'), catalog)
    assert len(completed.state.pending_tool_requests) == 2


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

"""Bounded caller-owned planning: cancel, then transfer an explicit amount.

The backend still owns approvals and execution. Only correlated trusted results
accepted by the ordinary agent path can release the dependent step.
"""
from copy import deepcopy
from uuid import uuid4
import re
from pydantic import TypeAdapter, ValidationError
from contracts.models import ChatInput, AgentResult, ExecutionResult, PositiveMoney
from .conversation import ConversationState, ConversationTurn, PendingPlan, PlanStep
from .request_guard import is_direct_request, is_abandonment, is_new_banking_request


def _base(state):
    return ConversationState.model_validate({**state.model_dump(), 'pending_plan': None})


def _fresh(state):
    return ConversationState(conversation_id=state.conversation_id,
                             pending_tool_requests=state.pending_tool_requests)


def _attach(turn, plan):
    state = ConversationState.model_validate({**turn.state.model_dump(), 'pending_plan': plan})
    return ConversationTurn(result=turn.result, state=state)


def _reply(state, text, plan=None):
    return _attach(ConversationTurn(result=AgentResult(reply=text), state=_base(state)), plan)


def _call(single_turn, chat, catalog, state, results=None):
    copied = deepcopy(catalog)
    for entry in copied:
        entry.setdefault('context', {})['conversation_state'] = _base(state).model_dump(mode='json')
    return single_turn(chat, copied, results)


def _change(plan, index, **updates):
    steps = list(plan.steps)
    steps[index] = PlanStep.model_validate({**steps[index].model_dump(), **updates})
    return PendingPlan.model_validate({**plan.model_dump(), 'steps': steps})


def _start_step(single_turn, chat, catalog, state, plan, answer=None):
    index = 0 if plan.steps[0].status != 'completed' else 1
    if index == 1:
        accounts = catalog[0].get('context', {}).get('account_ids', []) if catalog else []
        if accounts != [plan.source_account_id]:
            paused = plan.model_copy(update={'paused': True})
            return _reply(state, 'Plan paused: the original source account is no longer selected. Stop this plan before choosing another account.', paused)
    message = answer if answer is not None else plan.steps[index].request
    child = _call(single_turn, ChatInput(conversation_id=chat.conversation_id, message=message), catalog, state)
    expected = 'request_subscription_cancel' if index == 0 else 'request_transfer'
    if child.result.proposals:
        if len(child.result.proposals) != 1 or child.result.proposals[0].tool.value != expected:
            raise ValueError('Plan step returned an unexpected proposal')
        plan = _change(plan, index, status='awaiting_result', proposal_id=child.result.proposals[0].proposal_id)
    elif child.result.needs_clarification:
        plan = _change(plan, index, status='clarifying')
    else:
        # A provider failure or blocked operation must not advance the graph.
        plan = _change(plan, index, status='clarifying' if child.state.awaiting else 'waiting')
        plan = plan.model_copy(update={'paused': True})
        child = ConversationTurn(result=AgentResult(reply=child.result.reply + ' Plan paused; say resume plan to retry or stop plan to discard remaining steps.'), state=child.state)
    return _attach(child, plan)


def _parse(message):
    parts = re.split(r'\s*,?\s*\bthen\b\s+', message.strip(), flags=re.I)
    if len(parts) != 2:
        return None
    cancel, transfer = parts
    if not is_direct_request(cancel, 'cancel') or not is_direct_request(transfer, 'transfer'):
        return None
    if re.search(r'\b(and|then|after)\b', cancel + ' ' + transfer, re.I):
        return None
    # Never infer projected savings, a recipient or an amount for a plan.
    # General wording remains supported by the ordinary single-step agent.
    match = re.fullmatch(r'(?:transfer|send)\s+([+-]?\d+(?:\.\d+)?)(?:\s+(?:CNY|yuan))?\s+to\s+(.+?)[.!?]?', transfer, re.I)
    if not match:
        return None
    try:
        TypeAdapter(PositiveMoney).validate_python(match[1])
    except ValidationError:
        return None
    return cancel, transfer


def maybe_process_plan(chat, catalog, results, state, single_turn):
    """Return a plan turn, or None to leave ordinary conversations untouched."""
    plan = state.pending_plan
    command = ' '.join(chat.message.strip().casefold().split()).rstrip('.!?').strip()
    if plan is None:
        if results or not re.search(r'\bthen\b', chat.message, re.I):
            return None
        parsed = _parse(chat.message)
        if parsed is None:
            return ConversationTurn(result=AgentResult(
                reply='For an ordered plan, request cancellation then an explicit transfer amount and recipient, for example: Cancel StreamBox then transfer 39 CNY to Bob. Otherwise request one step at a time.',
                needs_clarification=True), state=state)
        if any(entry.get('context', {}).get('clarification_request') for entry in catalog):
            raise ValueError('Plans cannot mix structured state with legacy replay')
        accounts = catalog[0].get('context', {}).get('account_ids', []) if catalog else []
        if len(accounts) != 1:
            return ConversationTurn(result=AgentResult(reply='Please select a source account through the app before starting the plan.', needs_clarification=True), state=state)
        plan = PendingPlan(plan_id=uuid4().hex, original_message=chat.message,
                           source_account_id=accounts[0], steps=(
                               PlanStep(step_id='cancel', request=parsed[0]),
                               PlanStep(step_id='transfer', request=parsed[1], depends_on=('cancel',))))
        turn = _start_step(single_turn, chat, catalog, _fresh(state), plan)
        return ConversationTurn(result=turn.result.model_copy(update={'reply':
            'Plan: cancellation first, then the specified transfer only after trusted cancellation completion. Each action needs separate approval. Cancelling a subscription does not add money to your balance. ' + turn.result.reply}), state=turn.state)

    index = 0 if plan.steps[0].status != 'completed' else 1
    step = plan.steps[index]
    if results:
        # Ordinary agent validation authenticates correlation/arguments/data and
        # consumes only accepted terminal results. Never advance on raw text.
        child = _call(single_turn, chat, catalog, state, results)
        consumed = (step.proposal_id is not None
                    and not any(r.proposal.proposal_id == step.proposal_id for r in child.state.pending_tool_requests))
        if not consumed:
            return _attach(child, plan)
        result = results[0]  # A multi-result input is rejected by ordinary validation.
        if result['proposal_id'] != step.proposal_id:
            raise ValueError('A different result cannot advance the plan')
        completed = result['status'] == 'success' and ExecutionResult.model_validate(result['data']).status.value == 'COMPLETED'
        if not completed:
            return ConversationTurn(result=AgentResult(reply=child.result.reply + ' Remaining plan steps stopped; no completed action was reversed.'), state=child.state)
        if index == 1:
            return ConversationTurn(result=AgentResult(reply=child.result.reply + ' Plan completed.'), state=child.state)
        plan = _change(plan, 0, status='completed')
        if plan.paused:
            return _reply(child.state, child.result.reply + ' Plan remains paused; no transfer was proposed.', plan)
        following = _start_step(single_turn, chat, catalog, child.state, plan)
        return ConversationTurn(result=following.result.model_copy(update={'reply': child.result.reply + ' Next plan step: ' + following.result.reply}), state=following.state)

    if is_abandonment(chat.message) or command in {'stop', 'stop plan', 'cancel plan', 'discard plan'}:
        return _reply(_fresh(state), 'Unfinished plan discarded. Already-issued actions were not cancelled and completed actions were not reversed.')
    if command in {'pause', 'pause plan', 'human takeover', 'hand off'}:
        plan = plan.model_copy(update={'paused': True})
        return _reply(state, 'Plan paused. No new action was proposed. Say resume plan to continue, or stop plan to discard remaining steps. Use the app team for human review; no person has been contacted automatically.', plan)
    if command in {'resume', 'resume plan'}:
        plan = plan.model_copy(update={'paused': False})
        if step.status == 'waiting':
            return _start_step(single_turn, chat, catalog, state, plan)
        if step.status == 'clarifying':
            return _reply(state, 'Plan resumed. Please answer the pending clarification, or stop plan.', plan)
        return _reply(state, 'Plan resumed. Waiting for a trusted backend result; no action was reissued.', plan)
    if chat.message.strip().casefold() == plan.original_message.strip().casefold():
        return _reply(state, 'This plan is already pending. No duplicate action was proposed.', plan)
    if is_new_banking_request(chat.message):
        child = _call(single_turn, chat, catalog, _fresh(state))
        return ConversationTurn(result=child.result.model_copy(update={'reply': 'Previous unfinished plan discarded; issued actions are unchanged. ' + child.result.reply}), state=child.state)
    if plan.paused:
        return _reply(state, 'Plan is paused. Say resume plan or stop plan. No new action was proposed.', plan)
    if step.status == 'clarifying':
        return _start_step(single_turn, chat, catalog, state, plan, answer=chat.message)
    return _reply(state, 'Waiting for a trusted backend result for the current plan step. Approval must use the backend controls; no new action was proposed.', plan)

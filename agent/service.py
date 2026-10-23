"""Stateless proposal generation. Contains no execution or persistence code."""
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from uuid import uuid4
import logging
from pydantic import ValidationError, TypeAdapter
from contracts.models import (ChatInput, AgentResult, ActionProposal, Account,
                              Recipient, Subscription, SubscriptionReport, SpendingReport, ExecutionResult, PositiveMoney)
from contracts.tool_schemas import validate_tool_arguments
from .provider import Intent, ProviderError, get_provider
from .request_guard import (is_direct_request, stated_word_amounts, is_new_banking_request,
                            is_abandonment, is_generic_cancellation_request)
from .conversation import (ConversationState, PendingTransfer, PendingSpending,
                           PendingCancellation, ConversationTurn, PendingToolRequest)
from .planning import maybe_process_plan

logger = logging.getLogger(__name__)

# Exact whole-message shortcuts only. These select a read tool, never an answer;
# all context/argument validation and trusted-result grounding still run below.
_EXACT_READ_INTENTS = {
    'what is my balance': 'balance', "what's my balance": 'balance',
    'whats my balance': 'balance', 'show my balance': 'balance',
    'show my subscriptions': 'subscriptions', 'list my subscriptions': 'subscriptions',
    'list subscriptions': 'subscriptions',
}


@dataclass
class _Progress:
    state: ConversationState
    stage: str = "input_state_validation"


def _transfer_question(progress, draft, field, reply):
    progress.state = ConversationState(conversation_id=progress.state.conversation_id,
                                       pending_transfer=draft, awaiting=field,
                                       pending_tool_requests=progress.state.pending_tool_requests)
    return clarify(reply)


def clarify(reply):
    return AgentResult(reply=reply, needs_clarification=True)


def _subscription_reply(report: SubscriptionReport) -> str:
    """Display report candidates as data, never as verified subscription state."""
    import json
    import re
    if not report.candidates:
        return ("No recurring-charge candidates were reported. This does not prove "
                "that you have no active subscriptions. No cancellation has been requested.")
    lines = [f"Found {len(report.candidates)} recurring-charge candidates:"]
    cadences = {"weekly": "weekly", "monthly": "monthly", "annual": "annually",
                "unknown": "(cadence unknown)"}
    for index, candidate in enumerate(report.candidates[:5], 1):
        merchant = candidate.merchant
        ordinary_name = (len(merchant) <= 64 and re.fullmatch(r"[\w &/().'-]+", merchant)
            and not re.search(r"\b(ignore|instructions?|system|assistant|execute|cancel|send|pay|transfer)\b", merchant, re.I))
        name = json.dumps(merchant, ensure_ascii=False) if ordinary_name else f"Candidate {index} (name withheld)"
        lines.append(f"- {name}: estimated CNY {candidate.estimated_amount:.2f} {cadences[candidate.cadence.value]}.")
    if len(report.candidates) > 5:
        lines.append(f"{len(report.candidates) - 5} more candidates are in the report.")
    lines.append("These are not proof of active subscriptions. No cancellation has been requested.")
    return "\n".join(lines)


def _spending_reply(report: SpendingReport) -> str:
    """Explain validated figures with fixed templates; report text is never code.

    Only recognized P3 reason codes are paraphrased. Free-text reasons may carry
    merchant/category data, so they are not forwarded to a model or repeated.
    """
    import json
    import re
    reasons = {
        "LARGE_VS_CATEGORY_HISTORY": "a debit unusually large compared with category history",
        "LARGE_TRANSACTION": "a large transaction with insufficient history for a personal baseline",
        "CATEGORY_MONTH_SPIKE": "category spending above its historical monthly baseline",
        "POSSIBLE_DUPLICATE_CHARGE": "a possible duplicate charge; this is not a confirmed duplicate",
        "DUPLICATE_TRANSACTION_ID": "duplicate transaction records counted once",
        "CONFLICTING_DUPLICATE_ID": "conflicting transaction records excluded from totals",
        "INVALID_TIMESTAMP": "an invalid timestamp excluded from totals",
        "INVALID_AMOUNT": "an invalid amount or direction excluded from totals",
    }
    lines = [f"Verified spending for {report.period}: CNY {report.total_spending:.2f}."]
    categories = sorted(report.category_totals.items(), key=lambda item: (-item[1], item[0]))
    if categories:
        labels = []
        for index, (label, amount) in enumerate(categories[:3], 1):
            ordinary_label = (len(label) <= 64 and re.fullmatch(r"[\w &/().'-]+", label)
                and not re.search(r"\b(ignore|instructions?|system|assistant|execute|cancel|send|pay|transfer)\b", label, re.I))
            display = json.dumps(label, ensure_ascii=False) if ordinary_label else f"Category {index} (label withheld)"
            labels.append(f"{display}: CNY {amount:.2f}")
        lines.append("Largest reported categories: " + "; ".join(labels) + ".")
        if len(categories) > 3:
            lines.append(f"{len(categories) - 3} more categories are in the report.")
        if sum(report.category_totals.values(), Decimal(0)) != report.total_spending:
            lines.append("The supplied category totals do not match the reported total; please review the source report.")
    else:
        lines.append("No category breakdown was supplied.")
    if report.anomalies:
        lines.append("Report flags (not proof of fraud):")
        for anomaly in report.anomalies[:3]:
            transaction_id = (anomaly.transaction_id if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", anomaly.transaction_id)
                              else "[transaction ID withheld]")
            code = anomaly.reason.partition(":")[0].strip()
            explanation = reasons.get(code, "flagged by the report; details need review")
            lines.append(f"- {transaction_id}: {explanation}.")
        if len(report.anomalies) > 3:
            lines.append(f"{len(report.anomalies) - 3} more flags are in the report.")
    else:
        lines.append("No anomalies were reported.")
    lines.append("Under the team's default spending rules: Credits are excluded, refunds do not reduce spending, and outbound transfers count as spending.")
    return "\n".join(lines)


def process_message(chat: ChatInput, tool_catalog: list[dict],
                    tool_results: list[dict] | None = None) -> AgentResult:
    """Backend-only inputs; see docs/agent/integration.md for local envelopes."""
    return process_turn(chat, tool_catalog, tool_results).result


def process_turn(chat: ChatInput, tool_catalog: list[dict],
                 tool_results: list[dict] | None = None) -> ConversationTurn:
    """P1 caller helper: return structured progress without changing shared DTOs.

    The caller supplies context.conversation_state and retains the returned state.
    No state is stored in this module or inferred from English reply templates.
    """
    original = ConversationState(conversation_id=chat.conversation_id)
    progress = _Progress(original)
    try:
        chat = ChatInput.model_validate(chat)
        snapshots = [entry.get("context", {}).get("conversation_state") for entry in tool_catalog]
        if snapshots and any(snapshot != snapshots[0] for snapshot in snapshots):
            raise ValueError("Inconsistent conversation state")
        if snapshots and snapshots[0] is not None:
            supplied = ConversationState.model_validate(snapshots[0])
            if supplied.conversation_id != chat.conversation_id:
                raise ValueError("Conversation state belongs to a different conversation")
            original = supplied
        planned = maybe_process_plan(chat, tool_catalog, tool_results or [], original, process_turn)
        if planned is not None:
            return planned
        # A standalone abandonment command concerns the local unfinished draft,
        # not approval, execution, or subscription cancellation. Do not swallow
        # an execution result if this call is actually processing tool results.
        if not tool_results and is_abandonment(chat.message):
            reply = ("Unfinished request discarded." if any(draft is not None for draft in
                     (original.pending_transfer, original.pending_spending, original.pending_cancellation))
                     else "There is no unfinished request to discard.")
            return ConversationTurn(result=AgentResult(reply=reply),
                                    state=ConversationState(conversation_id=chat.conversation_id,
                                        pending_tool_requests=original.pending_tool_requests))
        # Standalone social/help messages need no remote interpretation. Match
        # the whole message only, after state validation, and never intercept a
        # field answer or a trusted tool-result continuation.
        if not tool_results and original.awaiting is None:
            social = " ".join(chat.message.strip().casefold().split()).rstrip('.!?').strip()
            help_reply = "I can help with balances, spending, subscriptions, transfers, or cancellations. What would you like to do?"
            reply = None
            if social in {'hi', 'hello', 'hey', 'hi there', 'hello there', 'hey there',
                          'good morning', 'good afternoon', 'good evening', 'nihao', '你好'}:
                reply = "Hello! " + help_reply
            elif social in {'help', 'what can you do', 'what can you help me with'}:
                reply = help_reply
            elif social in {'ok', 'okay', 'oki', 'thanks', 'thank you', 'thankyou', 'ty', 'got it', 'understood'}:
                reply = ("Acknowledged. This does not confirm or execute any proposed action."
                         if original.pending_tool_requests else "You're welcome. What would you like help with next?")
            if reply is not None:
                return ConversationTurn(result=AgentResult(reply=reply), state=original)
        progress = _Progress(original)
        progress.stage = "request_processing"
        result = _process(chat, tool_catalog, tool_results or [], progress)
        progress.stage = "output_validation"
        if result.proposals:
            progress.state = ConversationState(conversation_id=chat.conversation_id,
                pending_tool_requests=(*progress.state.pending_tool_requests,
                    *(PendingToolRequest(proposal=p.model_copy(deep=True)) for p in result.proposals)))
        return ConversationTurn(result=result, state=progress.state)
    except (ProviderError, ValidationError, ValueError, TypeError, KeyError,
            AttributeError, InvalidOperation) as exc:
        # Never log exception text, tracebacks, validation inputs, identifiers,
        # provider payloads, or banking data. The random event ID identifies only
        # this failure; it is not derived from the user or conversation.
        category = "processing_error"
        http_code = None
        if isinstance(exc, ProviderError):
            allowed = {"provider_error", "missing_key", "invalid_request", "authentication",
                       "access_denied", "model_not_found", "quota_or_rate_limit",
                       "provider_server_error", "gateway_error", "provider_unavailable",
                       "gateway_timeout", "sdk_or_network_error", "network_timeout",
                       "proxy_error", "network_protocol_error", "network_connection_error",
                       "unsupported_location", "empty_response"}
            category = exc.category if exc.category in allowed else "provider_error"
            http_code = exc.http_code if type(exc.http_code) is int else None
        elif isinstance(exc, ValidationError):
            category = "validation_error"
        logger.warning("agent_failure event_id=%s stage=%s category=%s http_code=%s",
                       uuid4().hex, progress.stage, category, http_code)
        reply = "I could not safely process this request because of an internal processing or validation error. Please retry."
        if isinstance(exc, ProviderError):
            if category in {"network_connection_error", "network_protocol_error", "proxy_error"}:
                reply = "I could not connect to the AI service or the connection was interrupted. Please check your connection and retry."
            elif category == "network_timeout":
                reply = "The AI service request timed out. Please retry."
            elif category in {"provider_unavailable", "provider_server_error", "gateway_error", "gateway_timeout"}:
                reply = "The AI service is temporarily unavailable. Please retry shortly."
            elif category == "quota_or_rate_limit":
                reply = "The AI service usage limit has been reached. Please try again later."
            elif category in {"missing_key", "authentication", "access_denied", "unsupported_location", "model_not_found", "invalid_request"}:
                reply = "The AI service rejected access or its configuration needs attention. Please contact the app team."
            elif category == "empty_response":
                reply = "The AI service returned an empty response. Please retry."
            else:
                reply = "The AI service request failed. Please retry; the app team can check the diagnostic logs."
        elif progress.stage == "intent_validation":
            reply = "The AI service returned a response that did not pass validation. Please retry or rephrase your request."
        elif progress.stage == "tool_result_validation":
            reply = "I could not verify the backend result, so I cannot confirm its outcome. Please contact the app team."
        return ConversationTurn(
            result=AgentResult(reply=reply + " No new action was proposed."),
            state=original,
        )


def _process(chat, catalog, results, progress):
    progress.stage = "catalog_validation"
    entries = {e["name"]: e for e in catalog}
    if len(entries) != len(catalog):
        raise ValueError("Duplicate tools")
    # Only a backend-correlated result for this conversation may ground a reply.
    if results:
        progress.stage = "tool_result_validation"
        if len(results) != 1:
            raise ValueError("One result per continuation")
        result = results[0]
        tool = result["tool"]
        entry = entries[tool]
        context = entry.get("context", {})
        pending = next((request for request in progress.state.pending_tool_requests
                        if request.proposal.proposal_id == result["proposal_id"]), None)
        if result["conversation_id"] != chat.conversation_id or pending is None:
            raise ValueError("Uncorrelated result")
        if tool != pending.proposal.tool.value:
            raise ValueError("Result tool does not match original proposal")
        expected = validate_tool_arguments(tool, pending.proposal.arguments)
        echoed = validate_tool_arguments(tool, result["arguments"])
        if expected.model_dump() != echoed.model_dump():
            raise ValueError("Result arguments do not match original proposal")
        account_id = getattr(expected, "account_id", getattr(expected, "source_account_id", None))
        if account_id is not None and account_id not in context.get("account_ids", []):
            raise ValueError("Requested account no longer available")
        if result["status"] not in {"success", "error"}:
            raise ValueError("Unknown tool result status")
        def accept(reply):
            # Caller must retain this returned state to make consumption effective.
            progress.state = ConversationState.model_validate({**progress.state.model_dump(),
                "pending_tool_requests": [request.model_dump() for request in progress.state.pending_tool_requests
                                          if request.proposal.proposal_id != result["proposal_id"]]})
            return AgentResult(reply=reply)
        if result["status"] != "success":
            return accept("The tool did not complete successfully. No success is confirmed.")
        data = result["data"]
        if tool == "get_balance":
            account = Account.model_validate(data)
            if account.account_id != expected.account_id:
                raise ValueError("Result account differs from requested account")
            return accept(f"Verified balance: CNY {account.balance:.2f}.")
        if tool == "analyze_spending":
            report = SpendingReport.model_validate(data)
            if report.period != expected.period:
                raise ValueError("Result month differs from requested month")
            return accept(_spending_reply(report))
        if tool == "list_subscriptions":
            report = SubscriptionReport.model_validate(data)
            return accept(_subscription_reply(report))
        execution = ExecutionResult.model_validate(data)
        if execution.status.value == "COMPLETED":
            return accept(f"The backend confirmed completion. Action ID: {execution.action_id}.")
        # Nonterminal execution outcomes must remain pending for a later update.
        if execution.status.value in {"REJECTED", "FAILED", "CANCELLED"}:
            return accept(f"Backend action status: {execution.status.value}. Completion is not confirmed.")
        return AgentResult(reply=f"Backend action status: {execution.status.value}. Completion is not confirmed.")

    # Context is supplied by the backend, never inferred from fixture/global state.
    progress.stage = "clarification_processing"
    context = catalog[0].get("context", {}) if catalog else {}
    message = chat.message
    previous = context.get("clarification_request")
    if progress.state.awaiting is not None and is_new_banking_request(message):
        # Replace only the unfinished draft. Already-issued proposals retain
        # their canonical snapshots and still require backend approval.
        # On an exception process_turn returns the original supplied state.
        if previous:
            raise ValueError("Do not mix structured state with legacy replay")
        progress.state = ConversationState(
            conversation_id=chat.conversation_id,
            pending_tool_requests=progress.state.pending_tool_requests)
    pending = progress.state.pending_transfer
    spending = progress.state.pending_spending
    cancellation = progress.state.pending_cancellation
    continuing_cancellation = cancellation is not None
    continuing_spending = spending is not None
    continuing = pending is not None and progress.state.awaiting is not None
    if continuing_cancellation:
        if previous:
            raise ValueError("Do not mix structured state with legacy replay")
        extracted = Intent(intent="cancel", subscription=chat.message.strip())
    elif continuing_spending:
        if previous:
            raise ValueError("Do not mix structured state with legacy replay")
        import re
        from datetime import date
        period = chat.message.strip()
        try:
            if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", period):
                raise ValueError("Invalid month format")
            date(int(period[:4]), int(period[5:]), 1)
        except ValueError:
            return clarify("Please enter a valid month using YYYY-MM, for example 2026-11.")
        extracted = Intent(intent="spending", period=period)
    elif continuing:
        if previous:
            raise ValueError("Do not mix structured state with legacy replay")
        if not is_direct_request(pending.original_message, "transfer"):
            raise ValueError("Pending request is not an explicit transfer")
        if progress.state.awaiting == "amount":
            import re
            if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", chat.message.strip()):
                return clarify("Please answer with a positive CNY amount using digits.")
            try:
                accepted_amount = TypeAdapter(PositiveMoney).validate_python(chat.message.strip())
            except ValidationError:
                return clarify("Please enter a CNY amount greater than zero with at most two decimal places.")
            pending = PendingTransfer.model_validate({**pending.model_dump(), "amount": accepted_amount})
        else:
            transfer_context = entries.get("request_transfer", {}).get("context", {})
            choices = [Recipient.model_validate(r) for r in transfer_context.get("recipients", [])]
            name = chat.message.strip().casefold()
            matches = [r for r in choices if name in (r.display_name.casefold(), r.display_name.split()[0].casefold())]
            if len(matches) != 1:
                return clarify("Please specify the recipient's full name using the app's verified recipient list.")
            pending = PendingTransfer.model_validate({**pending.model_dump(),
                "recipient_text": chat.message.strip(), "recipient_id": matches[0].recipient_id})
        # Exact field answers are handled deterministically; no LLM is needed to
        # reinterpret the entire request or guess which details should be retained.
        amount_text = f"{pending.amount:.2f}" if pending.amount is not None else None
        extracted = Intent(intent="transfer", amount=amount_text, recipient=pending.recipient_text)
        message = f"Transfer {amount_text or ''} to {pending.recipient_text or ''}"
    elif previous:
        message = previous + " " + message
        # CLI/backend replays only the pending request, not arbitrary tool prose.
        import re
        if previous.lower().startswith(("transfer", "send")):
            if not re.search(r"\d", chat.message):
                message = re.sub(r"\bto\b.*$", "", previous).strip() + " to " + chat.message
            elif re.fullmatch(r"[+-]?\d+(?:\.\d+)?", chat.message.strip()):
                message = re.sub(r"^(transfer|send)\b", r"\1 " + chat.message, previous, flags=re.I)
    if not continuing and not continuing_spending and not continuing_cancellation:
        exact_message = " ".join(message.strip().casefold().replace("’", "'").split()).rstrip('.!?').strip()
        local_intent = _EXACT_READ_INTENTS.get(exact_message) if not previous else None
        if not previous and is_generic_cancellation_request(message):
            # Never let a model turn this explicit mutation request into a read.
            # The ordinary cancellation branch below asks for a verified name;
            # it still checks locks/support and requires backend approval later.
            extracted = Intent(intent='cancel')
        elif local_intent is not None:
            extracted = Intent(intent=local_intent)
        else:
            progress.stage = "provider_request"
            payload = get_provider().extract(message)
            progress.stage = "intent_validation"
            extracted = Intent.model_validate_json(payload)
    progress.stage = "proposal_validation"
    mapping = {"balance": "get_balance", "spending": "analyze_spending",
               "subscriptions": "list_subscriptions", "transfer": "request_transfer",
               "cancel": "request_subscription_cancel"}
    tool = mapping.get(extracted.intent)
    # State-changing intent must be explicit in the original pending/current request.
    request_text = (cancellation.original_message if continuing_cancellation else
                    pending.original_message if continuing else (previous or chat.message))
    if extracted.intent == "transfer" and not is_direct_request(request_text, "transfer"):
        return clarify("Please explicitly request the transfer and its exact amount and recipient.")
    if extracted.intent == "cancel" and not is_direct_request(request_text, "cancel"):
        return clarify("Please explicitly request cancellation of a verified subscription.")
    if not tool:
        return clarify("I'm not sure what you mean. I can help with balances, spending, subscriptions, transfers, or cancellations. Please ask for one step at a time.")
    if tool not in entries:
        return AgentResult(reply="That tool is unavailable. No action was executed.")
    context = entries[tool].get("context", {})
    args = {}
    if extracted.intent != "cancel":
        accounts = context.get("account_ids", [])
        if len(accounts) != 1:
            return clarify("Please select a source account through the app.")
        args["source_account_id" if extracted.intent == "transfer" else "account_id"] = accounts[0]
        if continuing and pending.source_account_id != accounts[0]:
            raise ValueError("Selected source account changed during clarification")
        if continuing_spending and spending.account_id != accounts[0]:
            raise ValueError("Selected spending account changed during clarification")
    if extracted.intent in ("transfer", "cancel") and context.get("account_locked", False):
        return AgentResult(reply="This account is locked. No state-changing proposal was created.")
    if extracted.intent == "spending":
        if not extracted.period:
            progress.state = ConversationState(conversation_id=chat.conversation_id,
                pending_spending=PendingSpending(original_message=chat.message, account_id=args['account_id']),
                awaiting="period", pending_tool_requests=progress.state.pending_tool_requests)
            return clarify("Which month? Please use YYYY-MM.")
        args["period"] = extracted.period
    if extracted.intent == "transfer":
        recipient_text = extracted.recipient
        if recipient_text and recipient_text.casefold() not in message.casefold():
            raise ValueError("Ungrounded recipient")
        draft = PendingTransfer(
            original_message=request_text, source_account_id=args["source_account_id"],
            recipient_text=recipient_text,
        )
        if not extracted.amount:
            return _transfer_question(progress, draft, "amount", "How much CNY would you like to transfer?")
        try:
            amount = Decimal(extracted.amount)
        except InvalidOperation:
            return _transfer_question(progress, draft, "amount", "Please enter a valid CNY transfer amount greater than zero.")
        if not amount.is_finite() or amount <= 0:
            return _transfer_question(progress, draft, "amount", "The transfer amount must be greater than zero. How much CNY would you like to transfer?")
        # Fail closed if the model invents an amount absent from the user request.
        import re
        amounts = re.findall(r"(?<!\w)[+-]?\d+(?:\.\d+)?", message)
        if amount not in [Decimal(a) for a in amounts] + stated_word_amounts(message):
            return _transfer_question(progress, draft, "amount",
                                      "Please confirm the CNY amount using digits, for example 500.")
        amount = TypeAdapter(PositiveMoney).validate_python(amount)
        draft = PendingTransfer.model_validate({**draft.model_dump(), "amount": amount})
        if not extracted.recipient:
            return _transfer_question(progress, draft, "recipient", "Who should receive the transfer?")
        recipients = [Recipient.model_validate(r) for r in context.get("recipients", [])]
        name = extracted.recipient.casefold()
        matches = [r for r in recipients if name == r.display_name.casefold() or
                   name == r.display_name.split()[0].casefold()]
        if len(matches) != 1:
            return _transfer_question(progress, draft, "recipient", "Please specify the recipient's full name using the app's verified recipient list.")
        if name not in message.casefold():
            raise ValueError("Ungrounded recipient")
        args.update(recipient_id=matches[0].recipient_id, amount=extracted.amount, currency="CNY")
    if extracted.intent == "cancel":
        subscriptions = [Subscription.model_validate(s) for s in context.get("subscriptions", [])]
        matches = [s for s in subscriptions if extracted.subscription and
                   s.merchant.casefold() == extracted.subscription.casefold() and
                   s.merchant.casefold() in message.casefold()]
        if len(matches) != 1:
            progress.state = ConversationState(conversation_id=chat.conversation_id,
                pending_cancellation=PendingCancellation(original_message=request_text),
                awaiting="subscription", pending_tool_requests=progress.state.pending_tool_requests)
            import json
            import re
            choices = [s.merchant for s in subscriptions
                       if s.status == "active" and s.cancellation_supported]
            safe_choices = [name for name in choices if len(name) <= 64
                            and re.fullmatch(r"[\w &/().'-]+", name)
                            and not re.search(r"\b(ignore|instructions?|system|assistant|execute|cancel|send|pay|transfer)\b", name, re.I)]
            question = ("I couldn't find a matching subscription in your verified list. "
                        if continuing_cancellation or extracted.subscription else "")
            if not subscriptions:
                question += "No verified subscriptions were supplied by the app. You can say never mind to discard this request."
            elif safe_choices:
                question += ("Available for cancellation: "
                             + "; ".join(json.dumps(name, ensure_ascii=False) for name in safe_choices[:5])
                             + ". Please enter the full subscription name, or say never mind.")
                if len(choices) > len(safe_choices[:5]):
                    question += " Check the app's verified subscription list for additional entries."
            else:
                question += "Please check the app's verified subscription list for an eligible subscription, or say never mind."
            return clarify(question)
        if not matches[0].cancellation_supported or matches[0].status != "active":
            if continuing_cancellation:
                return clarify("Cancellation is unavailable for this subscription. Please choose another verified subscription or say never mind.")
            return AgentResult(reply="Cancellation is unavailable for this subscription.")
        args["subscription_id"] = matches[0].subscription_id
    validated = validate_tool_arguments(tool, args)
    args = validated.model_dump(mode="json")
    if "amount" in args:
        args["amount"] = f"{validated.amount:.2f}"
    proposal = ActionProposal(proposal_id=str(uuid4()), tool=tool, arguments=args,
                              rationale="User requested this step; backend validation is required.")
    reply = ("Request proposed. Backend approval and policy checks are required; nothing has been executed."
             if extracted.intent in ("transfer", "cancel") else
             "I have proposed a read-only lookup. A verified tool result is needed before reporting figures.")
    return AgentResult.model_validate(dict(reply=reply, proposals=[proposal]))

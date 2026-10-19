"""Stateless proposal generation. Contains no execution or persistence code."""
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from uuid import uuid4
from pydantic import ValidationError, TypeAdapter
from contracts.models import (ChatInput, AgentResult, ActionProposal, Account,
                              Recipient, Subscription, SpendingReport, ExecutionResult, PositiveMoney)
from contracts.tool_schemas import validate_tool_arguments
from .provider import Intent, ProviderError, get_provider
from .request_guard import is_direct_request, stated_word_amounts
from .conversation import (ConversationState, PendingTransfer, PendingSpending,
                           PendingCancellation, ConversationTurn, PendingToolRequest)


@dataclass
class _Progress:
    state: ConversationState


def _transfer_question(progress, draft, field, reply):
    progress.state = ConversationState(conversation_id=progress.state.conversation_id,
                                       pending_transfer=draft, awaiting=field,
                                       pending_tool_requests=progress.state.pending_tool_requests)
    return clarify(reply)


def clarify(reply):
    return AgentResult(reply=reply, needs_clarification=True)


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
        # A standalone abandonment command concerns the local unfinished draft,
        # not approval, execution, or subscription cancellation. Do not swallow
        # an execution result if this call is actually processing tool results.
        command = chat.message.strip().casefold().rstrip(".!?").strip()
        if not tool_results and command in {"never mind", "nevermind"}:
            reply = ("Unfinished request discarded." if any(draft is not None for draft in
                     (original.pending_transfer, original.pending_spending, original.pending_cancellation))
                     else "There is no unfinished request to discard.")
            return ConversationTurn(result=AgentResult(reply=reply),
                                    state=ConversationState(conversation_id=chat.conversation_id,
                                        pending_tool_requests=original.pending_tool_requests))
        progress = _Progress(original)
        result = _process(chat, tool_catalog, tool_results or [], progress)
        if result.proposals:
            progress.state = ConversationState(conversation_id=chat.conversation_id,
                pending_tool_requests=(*progress.state.pending_tool_requests,
                    *(PendingToolRequest(proposal=p.model_copy(deep=True)) for p in result.proposals)))
        return ConversationTurn(result=result, state=progress.state)
    except (ProviderError, ValidationError, ValueError, TypeError, KeyError,
            AttributeError, InvalidOperation):
        return ConversationTurn(
            result=AgentResult(reply="I could not safely process this request. No action was executed. Please retry."),
            state=original,
        )


def _process(chat, catalog, results, progress):
    entries = {e["name"]: e for e in catalog}
    if len(entries) != len(catalog):
        raise ValueError("Duplicate tools")
    # Only a backend-correlated result for this conversation may ground a reply.
    if results:
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
            return accept(f"Verified spending for {report.period}: CNY {report.total_spending:.2f}.")
        if tool == "list_subscriptions":
            from contracts.models import SubscriptionReport
            report = SubscriptionReport.model_validate(data)
            return accept(f"Found {len(report.candidates)} recurring-charge candidates. These are not proof of active subscriptions.")
        execution = ExecutionResult.model_validate(data)
        if execution.status.value == "COMPLETED":
            return accept(f"The backend confirmed completion. Action ID: {execution.action_id}.")
        # Nonterminal execution outcomes must remain pending for a later update.
        if execution.status.value in {"REJECTED", "FAILED", "CANCELLED"}:
            return accept(f"Backend action status: {execution.status.value}. Completion is not confirmed.")
        return AgentResult(reply=f"Backend action status: {execution.status.value}. Completion is not confirmed.")

    # Context is supplied by the backend, never inferred from fixture/global state.
    context = catalog[0].get("context", {}) if catalog else {}
    message = chat.message
    previous = context.get("clarification_request")
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
        extracted = Intent.model_validate_json(get_provider().extract(message))
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
        return clarify("Please request one balance, spending, subscription, transfer, or cancellation step at a time.")
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
            return clarify("Which verified subscription should be cancelled?")
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

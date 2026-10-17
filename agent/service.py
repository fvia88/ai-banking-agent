"""Stateless proposal generation. Contains no execution or persistence code."""
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from pydantic import ValidationError
from contracts.models import (ChatInput, AgentResult, ActionProposal, Account,
                              Recipient, Subscription, SpendingReport, ExecutionResult)
from contracts.tool_schemas import validate_tool_arguments
from .provider import Intent, ProviderError, get_provider
from .request_guard import is_direct_request


def clarify(reply):
    return AgentResult(reply=reply, needs_clarification=True)


def process_message(chat: ChatInput, tool_catalog: list[dict],
                    tool_results: list[dict] | None = None) -> AgentResult:
    """Backend-only inputs; see docs/agent/integration.md for local envelopes."""
    try:
        return _process(ChatInput.model_validate(chat), tool_catalog, tool_results or [])
    except (ProviderError, ValidationError, ValueError, TypeError, KeyError,
            AttributeError, InvalidOperation):
        return AgentResult(reply="I could not safely process this request. No action was executed. Please retry.")


def _process(chat, catalog, results):
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
        if (result["conversation_id"] != chat.conversation_id or
                result["proposal_id"] not in context.get("pending_proposal_ids", [])):
            raise ValueError("Uncorrelated result")
        if result["status"] != "success":
            return AgentResult(reply="The tool did not complete successfully. No success is confirmed.")
        data = result["data"]
        if tool == "get_balance":
            account = Account.model_validate(data)
            if account.account_id not in context.get("account_ids", []):
                raise ValueError("Unknown account")
            return AgentResult(reply=f"Verified balance: CNY {account.balance:.2f}.")
        if tool == "analyze_spending":
            report = SpendingReport.model_validate(data)
            return AgentResult(reply=f"Verified spending for {report.period}: CNY {report.total_spending:.2f}.")
        if tool == "list_subscriptions":
            from contracts.models import SubscriptionReport
            report = SubscriptionReport.model_validate(data)
            return AgentResult(reply=f"Found {len(report.candidates)} recurring-charge candidates. These are not proof of active subscriptions.")
        execution = ExecutionResult.model_validate(data)
        if execution.status.value == "COMPLETED":
            return AgentResult(reply=f"The backend confirmed completion. Action ID: {execution.action_id}.")
        return AgentResult(reply=f"Backend action status: {execution.status.value}. Completion is not confirmed.")

    # Context is supplied by the backend, never inferred from fixture/global state.
    context = catalog[0].get("context", {}) if catalog else {}
    message = chat.message
    previous = context.get("clarification_request")
    if previous:
        message = previous + " " + message
        # CLI/backend replays only the pending request, not arbitrary tool prose.
        import re
        if previous.lower().startswith(("transfer", "send")):
            if not re.search(r"\d", chat.message):
                message = re.sub(r"\bto\b.*$", "", previous).strip() + " to " + chat.message
            elif re.fullmatch(r"[+-]?\d+(?:\.\d+)?", chat.message.strip()):
                message = re.sub(r"^(transfer|send)\b", r"\1 " + chat.message, previous, flags=re.I)
    extracted = Intent.model_validate_json(get_provider().extract(message))
    mapping = {"balance": "get_balance", "spending": "analyze_spending",
               "subscriptions": "list_subscriptions", "transfer": "request_transfer",
               "cancel": "request_subscription_cancel"}
    tool = mapping.get(extracted.intent)
    # State-changing intent must be explicit in the original pending/current request.
    request_text = previous or chat.message
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
    if extracted.intent in ("transfer", "cancel") and context.get("account_locked", False):
        return AgentResult(reply="This account is locked. No state-changing proposal was created.")
    if extracted.intent == "spending":
        if not extracted.period:
            return clarify("Which month? Please use YYYY-MM.")
        args["period"] = extracted.period
    if extracted.intent == "transfer":
        if not extracted.amount:
            return clarify("How much CNY would you like to transfer?")
        try:
            amount = Decimal(extracted.amount)
        except InvalidOperation:
            return clarify("Please enter a valid CNY transfer amount greater than zero.")
        if not amount.is_finite() or amount <= 0:
            return clarify("The transfer amount must be greater than zero. How much CNY would you like to transfer?")
        if not extracted.recipient:
            return clarify("Who should receive the transfer?")
        # Fail closed if the model invents an amount absent from the user request.
        import re
        amounts = re.findall(r"(?<!\w)[+-]?\d+(?:\.\d+)?", message)
        if amount not in [Decimal(a) for a in amounts]:
            raise ValueError("Ungrounded amount")
        recipients = [Recipient.model_validate(r) for r in context.get("recipients", [])]
        name = extracted.recipient.casefold()
        matches = [r for r in recipients if name == r.display_name.casefold() or
                   name == r.display_name.split()[0].casefold()]
        if len(matches) != 1:
            return clarify("Please specify the recipient's full name using the app's verified recipient list.")
        if name not in message.casefold():
            raise ValueError("Ungrounded recipient")
        args.update(recipient_id=matches[0].recipient_id, amount=extracted.amount, currency="CNY")
    if extracted.intent == "cancel":
        subscriptions = [Subscription.model_validate(s) for s in context.get("subscriptions", [])]
        matches = [s for s in subscriptions if extracted.subscription and
                   s.merchant.casefold() == extracted.subscription.casefold() and
                   s.merchant.casefold() in message.casefold()]
        if len(matches) != 1:
            return clarify("Which verified subscription should be cancelled?")
        if not matches[0].cancellation_supported or matches[0].status != "active":
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

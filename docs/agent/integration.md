# Agent integration conventions for milestone one

These are local adapter conventions, not changes to frozen v1.0.0 contracts.
P2 can translate its persistence representation at the call boundary. The agent
does not require other teammates' implementations to run.

## Conflicts inspected before implementation

The Word draft defines string money/timestamps and a dictionary cancellation
assessment. The checked-out package defines Decimal money, timezone-aware
datetime, and CancellationAssessment and explicitly supersedes the older draft.
The agent imports the executable models without changing them. Generated JSON
schemas permit broader money input than the documented two-decimal JSON rule;
the agent emits transfer amounts as two-decimal strings.

The frozen signature leaves catalog/result/history shapes unspecified. It has
no recipient lookup tool, dependency graph, or conversation-history field.
The local conventions below support independent development; they do not claim
to be a newly agreed team contract. Dependent cancellation/savings workflows
are deferred; compound requests ask for one step at a time in this milestone.

## Catalog

Each entry has name (one of the five ToolName values), parameters (the shared
argument model JSON schema), and context. Use the same context on each entry.
The parameters field is informational; validation always uses the shared Python
models. Never forward client-supplied catalog/context directly to the agent.

```json
{
  "name": "request_transfer",
  "parameters": {},
  "context": {
    "account_ids": ["account_001"],
    "account_locked": false,
    "recipients": [],
    "subscriptions": [],
    "pending_proposal_ids": [],
    "clarification_request": "Transfer 500 to Alice"
  }
}
```

recipients and subscriptions contain canonical Recipient/Subscription JSON
objects filtered to the authenticated customer. account_ids must also be
ownership-filtered. Omit clarification_request unless replaying a pending
clarification. Backend owns this state and must clear it on new intents or
completion. The mock supports full-name and amount clarification continuations;
broader conversational memory is not implemented. Multiple source accounts ask
for selection through the app; the backend must then narrow account_ids.

## Tool result

Pass one result at a time, from trusted backend orchestration only:

```json
{
  "conversation_id": "demo",
  "proposal_id": "the-original-proposal-id",
  "tool": "get_balance",
  "status": "success",
  "data": {
    "account_id": "account_001", "user_id": "user_001",
    "currency": "CNY", "balance": "5000.00", "locked": false
  }
}
```

The corresponding catalog context must contain that proposal ID in
pending_proposal_ids. Other statuses produce a failure reply. Data models are
Account, SpendingReport, SubscriptionReport, or ExecutionResult respectively.
The backend must verify correlation to the original exact tool/arguments,
authenticated owner, and current conversation before providing the envelope.
The agent's membership checks are not authentication or execution authorization.
Remove consumed pending IDs in backend state. A COMPLETED ExecutionResult is
the only mutation result that produces a completion statement. Raw returned
messages, merchant names, notes, anomaly prose, and provider replies are not
used as instructions or echoed into completion claims.

P2 still revalidates proposals, resolves ownership, applies P4 policy, obtains
payload-bound approval/MFA, and executes idempotently with audit records.
proposal_id is not a server action_id. The agent never performs these steps.

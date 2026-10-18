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
  "arguments": {"account_id": "account_001"},
  "status": "success",
  "data": {
    "account_id": "account_001", "user_id": "user_001",
    "currency": "CNY", "balance": "5000.00", "locked": false
  }
}
```

The corresponding context.conversation_state.pending_tool_requests must contain
the full original canonical proposal. A pending ID list alone is no longer
accepted. The result must echo the original typed arguments, conversation and
tool. Envelope status is success or error. Data models for successful results are
Account, SpendingReport, SubscriptionReport, or ExecutionResult respectively.
The backend must authenticate the owner and obtain the result from the correct
actual tool execution. Echoed arguments do not authenticate a result or prove
which data was queried. P1 checks the recorded request and the returned
account/month where the shared data model carries those fields. Save the returned
state to remove consumed requests; retaining stale snapshots permits replay.
A COMPLETED ExecutionResult is
the only mutation result that produces a completion statement. Raw returned
messages, merchant names, notes, anomaly prose, and provider replies are not
used as instructions or echoed into completion claims.

P2 still revalidates proposals, resolves ownership, applies P4 policy, obtains
payload-bound approval/MFA, and executes idempotently with audit records.
proposal_id is not a server action_id. The agent never performs these steps.

## Task one baseline and P2 handoff examples

Prepared 18 October 2026. These examples describe the current P1 implementation;
they do not mean P2's adapter is already connected or that new shared fields are
approved. The next conversation-harness task may propose a stronger state/result
format, to be agreed before production integration.

### Baseline before further implementation

- Branch: feature/agent. Reviewed commit: 4b0dd75 (add milestone plan (temp)).
- Working tree was clean before this documentation change.
- Shared contract version: 1.0.0.
- Combined offline baseline: 149 passed, one existing Gemini SDK/Pydantic warning.
- No Gemini requests, seed resets, runtime changes, or backend edits in this task.

Exact PowerShell command from repository root:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = (Get-Location).Path + ';' + (Join-Path (Get-Location) 'backend')
$env:DATABASE_URL = 'sqlite:///:memory:'
agent/.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_contracts.py agent/tests backend/tests finance/tests subscriptions/tests -q
```

These environment settings apply to this terminal process. The in-memory database
keeps this check separate from a persistent demo database.

### Frozen models versus proposed conventions

| Item | Status |
| --- | --- |
| ChatInput, AgentResult, ActionProposal and typed tool arguments | Frozen shared v1.0.0 models |
| Tool entry with name, parameters and context | Proposed P1-to-P2 convention |
| account_ids, recipients, subscriptions and conversation_state context fields | Proposed convention, supplied by trusted caller |
| conversation_id/proposal_id/tool/arguments/status/data tool-result envelope | Proposed convention |
| clarification_request string | Existing limited replay convention, not complete multi-turn state |

The catalog is not an OpenAI-style type/function wrapper and is not sent directly
to Gemini. The provider extracts Intent; P1 resolves verified IDs and validates
canonical arguments. Generate parameters from TOOL_ARGUMENT_MODELS, not by copying
hand-written schemas. Keep common conversation context consistent across entries.

### Example A - backend supplies catalog and context

The runnable example below generates all five entries with their exact schemas.
For illustration, this is the context attached to each entry:

```json
{
  "account_ids": ["account_001"],
  "account_locked": false,
  "recipients": [
    {
      "recipient_id": "recipient_bob",
      "user_id": "user_001",
      "display_name": "Bob Li",
      "account_number_masked": "**** 5678"
    }
  ],
  "subscriptions": [],
  "conversation_state": {
    "conversation_id": "handoff_balance",
    "pending_transfer": null,
    "awaiting": null,
    "pending_tool_requests": []
  }
}
```

These IDs are synthetic shared-fixture examples, not IDs to hard-code in P2.
P2's existing seed uses usr_demo_01 and acc_cny_001; integration must use the actual
authenticated database IDs consistently in context, proposals and results. Filter
recipients/subscriptions/accounts to that authenticated customer. Empty subscriptions
above means none supplied in this example, not proof the customer has none.

### Example B - balance proposal and returned result

Input ChatInput:

```json
{"conversation_id": "handoff_balance", "message": "What is my balance?"}
```

P1 returns an AgentResult containing a proposal shaped like this (proposal ID is
illustrative; runtime generates a UUID):

```json
{
  "proposal_id": "example_balance_proposal",
  "tool": "get_balance",
  "arguments": {"account_id": "account_001"},
  "rationale": "User requested this step; backend validation is required."
}
```

P2 checks ownership, performs the read, and retains process_turn's returned state
including the original proposal in pending_tool_requests in caller-owned context.
Then P2 calls process_message(chat, catalog, [result]) with:

```json
{
  "conversation_id": "handoff_balance",
  "proposal_id": "example_balance_proposal",
  "tool": "get_balance",
  "arguments": {"account_id": "account_001"},
  "status": "success",
  "data": {
    "account_id": "account_001",
    "user_id": "user_001",
    "currency": "CNY",
    "balance": "5000.00",
    "locked": false
  }
}
```

Expected reply: "Verified balance: CNY 5000.00." with proposals=[] and
needs_clarification=false. The original request, echoed arguments and returned
account must match. Save process_turn's returned state to consume the accepted
result. Do not require transfer confirmation for this read-only tool.

### Example C - canonical transfer proposal

For "Transfer 500 to Bob", P1 returns a proposal shaped like:

```json
{
  "proposal_id": "example_transfer_proposal",
  "tool": "request_transfer",
  "arguments": {
    "source_account_id": "account_001",
    "recipient_id": "recipient_bob",
    "amount": "500.00",
    "currency": "CNY"
  },
  "rationale": "User requested this step; backend validation is required."
}
```

P2 must retain recipient_id (not recipient or a fallback Bob), validate the
selected source account, and apply policy/approval. This is not an executed
transfer. Keep server action IDs, digests and tiers outside strict tool arguments
through a team-approved API shape. That API-shape decision remains open.

For a later mutation result, data is ExecutionResult. Only its COMPLETED status
permits a completion claim. Envelope status=success means a result was returned;
it does not by itself mean the banking operation completed. No mutation is
performed by the runnable balance example below.

### Runnable offline handoff example

Run this Python block from the repository root using the agent virtual environment.
It calls the real public service interface with the mock provider; it does not
import P2, call Gemini, or execute mutations. Fixture helpers are demo-only.

```python
import os
from contracts.models import ChatInput
from contracts.tool_schemas import validate_tool_arguments
from agent.mock_tools import demo_catalog, read_result
from agent.service import process_message, process_turn

os.environ["AGENT_PROVIDER"] = "mock"
catalog = demo_catalog()  # Generates all five schemas and synthetic context.
chat = ChatInput(conversation_id="handoff_balance", message="What is my balance?")
initial_turn = process_turn(chat, catalog)
initial = initial_turn.result
assert len(initial.proposals) == 1
proposal = initial.proposals[0]
assert proposal.tool.value == "get_balance"
validate_tool_arguments(proposal.tool, proposal.arguments)
for entry in catalog:
    entry["context"]["conversation_state"] = initial_turn.state.model_dump(mode="json")
result = read_result(chat, proposal)  # Synthetic Account data, not a DB call.
final_turn = process_turn(chat, catalog, [result])
final = final_turn.result
for entry in catalog:
    entry["context"]["conversation_state"] = final_turn.state.model_dump(mode="json")
assert final.reply == "Verified balance: CNY 5000.00."
assert not final.proposals

transfer = process_message(
    ChatInput(conversation_id="handoff_transfer", message="Transfer 500 to Bob"),
    demo_catalog(),
)
assert len(transfer.proposals) == 1
args = validate_tool_arguments(transfer.proposals[0].tool, transfer.proposals[0].arguments)
assert args.recipient_id == "recipient_bob"
assert transfer.proposals[0].arguments["amount"] == "500.00"
print("PASS: balance round trip and canonical transfer proposal; no mutations executed")
```

### Confirm with Marvel when available

1. Accept or revise these catalog/context and tool-result conventions.
2. Confirm backend-owned conversation/pending-action state and authenticated IDs.
3. Agree approval metadata/API shape without modifying strict tool arguments.
4. Wire P2's mock/real switch; current backend still calls its own mock agent.

P1 can proceed with a local harness without waiting. Mark unapproved handoff
choices explicitly and leave all backend changes to P2.

## Task two structured clarification progress

Added 19 October 2026. State storage and the structured clarification connection
are implemented. The three-turn acceptance test now passes. The CLI now exposes
this loop through --interactive. No backend, database, global service state, or
public DTO changes were made.

Acceptance sequence (existing amount-first order):

| Input | Expected response | State to retain |
| --- | --- | --- |
| Transfer to Alice | Ask for amount; no proposal | recipient_text=Alice, awaiting=amount |
| 500 | Ask which recipient; no proposal | amount=500.00, recipient_text=Alice, awaiting=recipient |
| Alice Chen | One request_transfer proposal | account_001, recipient_alice, 500.00 CNY |

agent/conversation.py defines private immutable PendingTransfer and
ConversationState snapshots. The future caller/harness owns their lifetime.
Fields include conversation_id, original_message, source_account_id, unresolved
recipient_text, resolved recipient_id, accepted amount, and awaiting. A pending
name is not a verified recipient ID. Amounts use the shared PositiveMoney type;
invalid amounts are not accepted into state. The models reject extra fields and
contradictory clarification states.

The caller supplies snapshots in the proposed context.conversation_state key,
consistently on all catalog entries. P1's local process_turn helper returns
ConversationTurn(result=AgentResult, state=ConversationState). The next awaited
field comes from state.awaiting, not from parsing English replies. P2 may adapt
this local helper; it is not a new frozen module signature. Canonical
process_message keeps its original signature and returns only turn.result.

The acceptance test now passes each returned state into the next call rather
than constructing the expected updated state itself. Initial interpretation uses
the selected provider. Exact digit amounts and verified recipient-name answers
are then handled locally for this bounded transfer flow. Invalid answers retain
the previous accepted state. Account selection/lock, recipient context, money
constraints and argument schemas are rechecked before producing a proposal.
The helper returns idle state after producing a proposal so the caller can avoid
replaying the pending draft. It does not persist proposal/execution records.

Run the state and conversation checks offline:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
agent/.venv/Scripts/python.exe -m pytest -p no:cacheprovider agent/tests/test_conversation_state.py agent/tests/test_conversation_acceptance.py agent/tests/test_conversation_turns.py -q
```

Caller pattern (trusted context only):

```python
from contracts.models import ChatInput
from agent.mock_tools import demo_catalog
from agent.service import process_turn

catalog = demo_catalog()  # Synthetic harness only; production supplies DB context.
for message in ["Transfer to Alice", "500", "Alice Chen"]:
    turn = process_turn(ChatInput(conversation_id="demo", message=message), catalog)
    print(turn.result.model_dump_json())
    for entry in catalog:
        entry["context"]["conversation_state"] = turn.state.model_dump(mode="json")
```

Do not mix this state with the legacy clarification_request replay string.
Mismatched conversation IDs, inconsistent catalog snapshots or a changed source
account cannot generate a transfer proposal. Only exact numeric amount answers
and verified names are supported here; general answer paraphrases, corrections,
request switching and expiry are not implemented. Standalone never mind/nevermind
now returns a cleared state and no proposals, without a provider call. This only
discards an unfinished local draft; it is not execution/action cancellation.
The caller must save the returned cleared snapshot before the next message.
Commands embedded in longer text or quotes are not recognized as abandonment,
and an incoming tool result is never swallowed by an abandonment command.
The interactive
caller loop now runs with python -m agent.cli --interactive (mock by default).
It prints replies/proposals and state, persists the returned snapshot only in
its in-memory catalog, and exits cleanly on quit, Ctrl+C or end-of-input.
Existing single-message CLI commands are preserved. Interactive mode does not
execute lookups or mutations and does not interpret ok as approval.
Backend integration still requires P2 agreement. Next is the separate task
for final regression/live checks and meeting preparation.

### Conversation-isolation verification

Task four passed with no runtime changes required. Interleaved tests cover
500.00 to Alice Chen versus 300.00 to Alice Wang, both completion orders,
abandonment in only one conversation, foreign snapshot rejection and inconsistent
catalog snapshots. The tests assert that caller-owned context is not mutated.
See testing_memory_trial1.md for the terminal command and expected outcomes.
P2 remains responsible for authenticated user/conversation ownership; matching
conversation IDs alone is not an authorization boundary.

## Task five - original proposal matching and consumption

This strengthens the local proposed handoff convention; shared contracts remain
v1.0.0. P2 must explicitly adopt it when integrating. The local caller uses
process_turn to retain both public AgentResult and returned ConversationState.
The public process_message signature and AgentResult fields remain unchanged.

- Each new proposal is copied into state.pending_tool_requests as
  PendingToolRequest(proposal=the_original_ActionProposal). Arguments are checked
  against the shared tool model before they are retained.
- read_result in mock_tools now echoes validated arguments in its envelope.
- P1 requires matching conversation, saved proposal ID, tool and canonical
  arguments. Missing original proposal or missing echoed arguments is rejected.
- Account data must identify the exact requested account, not merely any account
  in the user's allowed list. SpendingReport.period must equal the requested month.
- SubscriptionReport and SpendingReport do not carry account IDs themselves.
  P1 checks the saved/echoed account; the trusted backend must ensure actual data
  was queried only for that account and authenticated user.
- Accepted read results and error outcomes consume only their own request.
  Terminal execution outcomes consume it too; pending confirmation/MFA outcomes
  retain it. Backend must bind mutation execution records to their original
  proposal and action ID; this local stub does not execute or authorize mutations.
- Validation rejection does not consume the request, allowing a corrected result.
  Already-consumed results are rejected after the caller saves returned state.
- Unfinished-draft abandonment preserves issued pending proposals. It is not
  revocation of a backend action or permission to ignore later execution outcomes.

CLI --resolve-read uses this round trip with fixtures. Interactive mode remains
proposal-only; it does not execute tools. No backend imports or database writes
were added. Replay protection here is sequential, in-memory caller bookkeeping,
not an atomic production idempotency mechanism.

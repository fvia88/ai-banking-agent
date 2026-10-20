# P1 / P2 integration compatibility review

Reviewed: 2026-10-19 (Asia/Shanghai). Local checkout:
`7d35328216fbc201bccdbe93692e940acf2b897c`.

Audience: Marvel (P2/backend) and P1/agent. This is a review of the code currently
in this branch, not Marvel's unmerged work. No backend changes were made. The
earlier experimental adapter change has been undone.

## Main conclusion

Both sides were intentionally developed with stubs. P1 now supports the five
intents, transfer/spending/cancellation clarification, caller-owned state and
matched tool results. P2 has chat/read endpoints and transfer approval/execution,
but the chat path still calls its own mock agent and security mock.

Connect these pieces incrementally. Do not replace P1's canonical tool arguments
with backend-specific shapes. Frozen `contracts/` remains the source of truth;
the context/state/result envelope below is a **proposed integration convention**
that P1 and P2 must agree to adopt.

## 1. Compatibility by tool

Examples use synthetic IDs. Real IDs must come from backend-owned user context;
there is no requirement to rename database IDs to match P1 fixtures.

| Tool | Canonical arguments P1 returns | Current backend gap | Needed integration |
| --- | --- | --- | --- |
| `get_balance` | `{"account_id":"account_001"}` | Backend mock uses `currency` instead of `account_id`, reports a fixed balance, and chat creates a confirmation record even for Green reads. | Query the exact owned account; return shared `Account` data automatically, without a confirmation request. |
| `analyze_spending` | `{"account_id":"account_001","period":"2026-11"}` | No spending dispatch in chat. `/transactions` returns transactions for all the user's accounts and filters month by timestamp prefix. | Select transactions for the requested owned account and call P3 `finance.analytics.analyze_spending`. Preserve its Asia/Shanghai month semantics; do not prefilter with an incompatible timestamp-prefix rule. |
| `list_subscriptions` | `{"account_id":"account_001"}` | No subscription chat dispatch or detector implementation found in the reviewed subscription package. | Wire a real detector/report provider when available, or explicitly label a synthetic stub. Return shared `SubscriptionReport`; do not present P1's empty demo report as a real lookup. |
| `request_transfer` | `{"source_account_id":"account_001","recipient_id":"recipient_bob","amount":"500.00","currency":"CNY"}` | Backend already reads `recipient_id` (this earlier mismatch is fixed). However, record creation replaces the proposed source account with the route's first account. | Preserve and authorize the requested source; verify recipient ownership/allowlisting. Use shared argument validation before policy/record creation. |
| `request_subscription_cancel` | `{"subscription_id":"sub_streambox"}` | Policy mock recognizes cancellation, but confirmation always invokes the transfer executor. | Resolve/authorize the subscription, check current eligibility and status, obtain confirmation, then dispatch a cancellation executor/stub explicitly. Never send it to transfer execution. |

Sources: `contracts/tool_schemas.py`, `backend/app/mocks/agent.py`,
`backend/app/api/chat.py`, `backend/app/api/transactions.py`,
`backend/app/services/actions.py`, `backend/app/api/approvals.py`.

## 2. Integration blockers and owners

| Priority | Finding in current code | Required change / decision | Owner |
| --- | --- | --- | --- |
| First | `AgentAdapterService.process` always calls `MockAgentAdapter`; `use_mock` has no effect. | Add an explicit P1 path, preserving a deliberate stub mode. Switching the provider to Gemini is separate from switching this backend adapter. | P2 |
| First | `/chat` passes only `ChatInput`; no catalog/state reaches P1. | Build trusted tool catalog/context from the resolved user before calling P1. | P2, with P1 checking format |
| First | No conversation state persistence/ownership binding exists in this chat path. | Load/save the latest state per user + conversation. For a local trial, in-memory storage is acceptable; define process-restart limits. Serialize state updates to avoid stale snapshots. | P2 |
| First | `process_message` returns only `AgentResult`; memory state is available through P1's additional `process_turn` helper. | Agree to use `process_turn` inside the backend adapter, or an equivalent wrapper. Do not change the frozen public function signature. | P1 + P2 |
| First | `/chat` maps all no-proposal results to `COMPLETED` and does not expose `needs_clarification`. `ChatOutput` has no such field. | Agree how UI represents clarification and errors. Backend can retain the internal flag immediately; adding a public field requires coordinated contract versioning. Do not silently add fields or invent an enum value. | P1 + P2; app/UI owner for presentation |
| Before read integration | All proposals become confirmation records, even Green tools. | Dispatch reads automatically after authorization/policy. Honor `allowed_to_proceed`, `requires_confirmation` and `requires_mfa`, not just tier labels. | P2 + P4 |
| Before result integration | Route adds `action_id`, `action_digest`, `tier` inside `proposal.arguments`. | Keep canonical argument dictionaries unchanged; retain original proposals and separate backend metadata. Agree on a public metadata representation before changing frozen response models. | P2 + P1 |
| Before result integration | No result envelope/callback to P1 exists. | Persist original proposal mapping, wrap typed results with the correlation fields below, and feed them back with saved state. | P2, with P1 checking round trip |
| Before mutation integration | Transfer source is silently replaced; cancellation has no execution dispatch. | Reject source/context mismatches rather than rewriting requests; whitelist executor by tool. | P2 |

### Important metadata detail

`ActionProposal.arguments` is a generic dictionary at DTO level, but each tool's
canonical argument model forbids extra keys. Adding action metadata therefore
breaks subsequent P1/P4 argument validation.

For non-transfer tools, `create_action_record` also aliases `proposal.arguments`
as its payload. The route then mutates that dictionary after computing its digest.
The returned dictionary consequently differs from the payload that was hashed.
Keep immutable/copy-separated canonical payloads and backend action records.

## 3. Exact P1 caller conventions to agree on

Public frozen entry point:

```python
process_message(chat: ChatInput, tool_catalog: list[dict],
                tool_results: list[dict] | None = None) -> AgentResult
```

Additional existing P1 helper for memory:

```python
turn = process_turn(chat, tool_catalog, tool_results=None)
# turn.result: shared AgentResult
# turn.state: private ConversationState; serialize with model_dump(mode="json")
```

`process_message` alone discards the returned state, so simply importing it does
not implement persistent clarification. P1 stores no global conversation memory.

Catalog entry shape is P1's local format, **not** nested OpenAI function calling:

```python
{
    "name": "analyze_spending",
    "parameters": TOOL_ARGUMENT_MODELS[ToolName.ANALYZE_SPENDING].model_json_schema(),
    "context": {
        "account_ids": ["account_001"],
        "account_locked": False,
        "recipients": verified_recipient_dicts,
        "subscriptions": verified_subscription_dicts,
        "conversation_state": saved_state_dict,
    },
}
```

Build all allowed entries from `contracts.tool_schemas.TOOL_ARGUMENT_MODELS`.
Context uses shared `Recipient` and `Subscription` shapes for their lists.
Supply the same state snapshot on every catalog entry; first turn may omit it.
Never take ownership lists, lock flags, state or tool results from user prose.
Current P1 asks for account selection unless context contains exactly one account.
P2 should supply the app-selected owned account; multi-account conversation
selection is not yet implemented by P1.

State contains mutually exclusive unfinished drafts:

- `pending_transfer`, with `awaiting="amount"` or `"recipient"`.
- `pending_spending`, with `awaiting="period"`.
- `pending_cancellation`, with `awaiting="subscription"`.
- `pending_tool_requests`, holding original proposals already issued.

Save returned state after **every** turn, including invalid answers, abandonment,
proposal generation and result processing. Never mind discards the unfinished
draft; it does not revoke an already-issued action. Older snapshots without the
new draft fields remain valid through their null defaults.

## 4. Tool-result format and data conversion

P1 currently accepts **one result per continuation call**:

```json
{
  "conversation_id": "conversation_001",
  "proposal_id": "original_p1_proposal_id",
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

| Tool | `data` model |
| --- | --- |
| `get_balance` | `contracts.models.Account` |
| `analyze_spending` | `contracts.models.SpendingReport` |
| `list_subscriptions` | `contracts.models.SubscriptionReport` |
| Transfer / cancellation | `contracts.models.ExecutionResult` |

`GET /accounts` currently returns `AccountResponse`, not shared `Account`:
it omits `user_id` and adds `account_number` / `daily_transfer_total`. Construct
the shared DTO from database fields rather than passing that HTTP response
directly to P1. Existing endpoint models need not be replaced just for this.

Mutation result example: `data` contains backend `action_id`, `status`, `message`
and `audit_id`. Store the mapping from user + conversation + original proposal ID
to backend action ID; these IDs are different. `status="success"` in the outer
envelope means a valid tool response arrived, not that execution completed.
P1 only claims completion for inner `ExecutionResult.status="COMPLETED"`.

Tool failure uses outer `status="error"`; do not forward raw exceptions/secrets.
P1 consumes reported tool failures and accepted read/terminal mutation results.
Nonterminal execution results remain pending. Validation rejection retains the
request so a corrected response can be supplied.

P1 checks conversation, saved proposal ID, tool, canonical echoed arguments,
requested account availability, returned Account ID and SpendingReport month.
Subscription/Spending reports have no account field: P2 must ensure the actual
query was scoped correctly. Echoing fields does not authenticate data. P2 must
also verify action-ID correlation and prevent duplicate concurrent execution.

## 5. Use the already-merged teammate modules

- **P3:** `finance.analytics.analyze_spending(transactions, period)` already
  returns shared `SpendingReport`. Scope transactions to the selected owned
  account before calling it. Keep finance aggregation in P3, not in the adapter.
- **P4:** `security.policy.evaluate_action(proposal, context)` exists and validates
  shared arguments/account matching. The backend adapter still calls its mock.
  Review wiring with P4; its default permits locked-account reads, whereas the
  current chat route blocks all locked-user chat before policy runs.
- **P5:** reviewed package provides cancellation eligibility via
  `subscriptions.eligibility.assess_cancellation(SubscriptionCandidate)`, not
  subscription detection or execution. Clarification context needs verified
  `Subscription` records; detector candidates are a different DTO and are not
  proof of active subscriptions. Agree on the trusted source with P5.
- **P1:** Gemini is selected by `AGENT_PROVIDER=gemini`, with `GEMINI_API_KEY`
  and optional `GEMINI_MODEL` (default `gemini-3.1-flash-lite`). Mock provider is
  default. Settings reading `.env` does not itself populate `os.environ` for P1.

P1 limitations: exact numeric/name transfer follow-ups, YYYY-MM spending answers,
and whole merchant-name cancellation answers. General corrections/request switching
and duplicate-merchant selection are deferred. Replies currently summarize totals
or candidate counts rather than detailed finance explanations. Keep these visible
as P1 scope items rather than asking P2 to implement language understanding.

## 6. Recommended implementation order and acceptance checks

1. **Adapter connection, with mock provider:** pass trusted catalog/context to
   P1; prove the P2 mock is not called. Missing context must never fall back to
   hardcoded balances or recipients.
2. **Stateful chat:** spend request -> month -> exact proposal; cancellation
   request -> StreamBox -> exact proposal; transfer to Alice -> 500 -> Alice Chen.
   Invalid answers and never mind must work; two users/conversations must remain
   isolated. Save state server-side before handling the next turn.
3. **First read round trip:** query an account with a deliberately different
   balance from fixtures; P1 must report the database value. No confirmation or
   transfer executor should run. Wrong account/month/result correlation must fail.
4. **Finance and subscription reads:** wire P3 and agreed P5 report source, one
   tool at a time. Keep provider/network failure separate from application errors.
5. **Mutation dispatch:** preserve selected source/recipient IDs; validate with
   shared schemas; keep metadata separate; obtain confirmation/MFA as required;
   return correlated execution results. Test cancellation never calls transfer.
6. **Gemini smoke checks:** after the same flow passes offline, switch provider
   and repeat a few wording examples without changing backend orchestration.

Before treating mutations as integration-complete, additionally verify account
lock and current policy again at execution, MFA expiry, concurrent replay and
audit linkage. Static review found no expiry recheck in `verify_action` and no
lock recheck in either approval execution path. Existing sequential replay tests
do not establish concurrent idempotency. These are backend/security follow-ups,
not reasons to delay the first read-only integration slice.

## 7. Evidence and review limits

- Full existing suites: **314 passed, 1 existing Google SDK Pydantic warning**.
  Includes contracts, agent, backend, finance, subscriptions and security.
- Earlier isolated HTTP checks against this backend snapshot: spending and
  cancellation clarification returned mock greetings; balance used a hardcoded
  value rather than the seeded review account; locked balance was blocked.
- This pass's synthetic direct probes confirmed: selected transfer source
  overwritten, metadata-enriched arguments rejected by shared validation, Green
  reads recorded as PENDING_CONFIRMATION, and non-transfer payload mutation after
  digest computation. No banking actions or live Gemini requests were executed.
- Executor dispatch gaps, missing state/callback wiring and execution rechecks
  are source-code findings. This is not an exhaustive concurrency/security audit.
- Passing module tests do not prove P1/P2 end-to-end compatibility. Repeat the
  acceptance checks after Marvel's next merge; this document may then be stale.

Reproduce the existing-suite check from repository root:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = (Get-Location).Path + ';' + (Join-Path (Get-Location) 'backend')
$env:DATABASE_URL = 'sqlite:///:memory:'
agent/.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_contracts.py agent/tests backend/tests finance/tests subscriptions/tests security/tests -q
```

Further examples: [integration.md](integration.md) and
[testing_memory_trial1.md](testing_memory_trial1.md).

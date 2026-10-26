# Trusted agent continuation

P2 now returns persisted mutation outcomes to P1 using P1's existing
`process_turn(..., tool_results=[...])` interface. P1 code and the shared DTOs
are unchanged. This applies when `USE_MOCK_AGENT=false`; `AGENT_PROVIDER=mock`
can still select P1's deterministic offline provider for testing.

## Delivery and correlation

`POST /api/v1/actions/{action_id}/continue` accepts no result payload. The backend
resolves the demo session owner, loads the action, verifies the stored proposal
ID/tool/canonical arguments/digest against the original pending P1 request, and
builds an `ExecutionResult` from the database. Completed actions require their
persisted execution audit. Other statuses get an `ACTION_STATUS_OBSERVED` audit;
this records observation rather than claiming execution. OTPs and arbitrary
exception messages are not sent to P1.

The P2-specific response contains `{execution: ExecutionResult, chat: ChatOutput}`.
Existing `/confirm` and `/verify` contracts remain unchanged. The frontend calls
continuation after either succeeds or returns an error, updates the original
card from the database status, and displays P1's reply/follow-up proposals.

Pending confirmation and pending MFA retain P1's pending request. Completed,
failed, rejected, and cancelled outcomes consume it. Wrong OTPs that leave an
action pending do not imply a terminal failure. Provider or delivery failures
leave the bank transaction intact; the card offers **Retry conversation update**.
A later chat turn also recovers previously undelivered MFA/terminal outcomes.
If recovery generates a new approval, the response explicitly tells the user
their latest message was not processed and should be resent after reviewing it.

## Persistence, concurrency, and retries

Alembic revision `0005_agent_continuation` adds owner/conversation keyed
`agent_conversations` state and nullable action correlation/cache fields.
Existing balances, transactions, approvals, and audits are preserved. Legacy
actions without a conversation link continue to confirm/verify normally; no
conversation association is guessed for them. Current mock tickets likewise
retain ordinary approval UI behavior without P1 continuation.

Real chat turns and continuations serialize through the same database
conversation row. PostgreSQL uses a row lock; SQLite's conflict-safe insert
reserves the writer. The Python lock is an additional single-process guard.
Returned P1 state, newly validated follow-up approval tickets, and the response
cache commit together. Repeated continuation for the same persisted status
returns the cached response without another P1 call or duplicate ticket.
A conditional status update discards results if action status changed during
processing. Financial execution never waits for P1 or takes conversation locks.
Restarted workers load conversation state from the database, not memory.

P1's bounded cancellation-then-transfer plan now receives its missing result
handoff. Cancellation completion may create a new transfer proposal, which
passes through the usual P2/P4 validation and requires its own confirmation/MFA.
Cancellation never credits the balance. Paused plans do not advance automatically.
If policy refuses a dependent proposal, P1 receives that refusal and stops the
remaining plan; no unticketed proposal is left waiting for an impossible approval.
General planning, external merchant cancellation and broader takeover requirements
remain outside this change. Frontend approval metadata now uses a separate
`approval` object; see `frontend_metadata_transport.md`, including old-cache handling.

## Manual checks

Rebuild both updated services with your existing provider environment settings:

```powershell
docker compose up -d --build backend frontend
```

Startup applies migration 0005 automatically. For local backend development,
use `python backend/start.py --reload` and rebuild/restart the frontend as usual.

1. With a fresh daily total, ask **Transfer 20 CNY to Bob**, then confirm.
   The card completes and a new agent message confirms backend completion.
2. Request enough to exceed the 1,000 CNY cumulative daily threshold while
   staying within the available balance. Confirm: the agent reports
   `PENDING_MFA` and no completion. Submit the demo inbox OTP: the card and
   agent then report completion. A wrong OTP leaves MFA pending until attempts
   are exhausted.
3. With the seeded subscription active, ask **Cancel iQIYI VIP Monthly then
   transfer 45 CNY to Bob**. Confirm cancellation. A separate transfer approval
   appears; the balance stays unchanged until that transfer is approved.
4. Start that plan in an active subscription state, say **pause plan**, then
   approve cancellation: P1 reports completion but proposes no transfer.

Automated coverage includes original/canonical proposal matching, owner and
conversation isolation, terminal refusals, MFA lifecycle without secret transport,
memory loss, missed browser callbacks, provider outage/retry, cached replay,
continuation commit rollback/retry, refused and paused/dependent plans, and concurrent continuation using separate connections
with Python locks disabled on SQLite and disposable PostgreSQL.

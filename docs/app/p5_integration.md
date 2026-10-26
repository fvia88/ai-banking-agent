# Subscription integration and cancellation

The backend calls P5's real recurring-charge detector, stored-record mapping,
enrichment and cancellation assessment. P5 code and shared contracts are unchanged.
The stored Subscription contract already exists; the new database table and
additional records endpoint are P2 implementation details.

## Startup and migration

From the repository root, Docker users run:

```powershell
docker compose up -d --build
```

Alembic revision `0003_subscriptions` adds the subscriptions table. Startup then
inserts missing known synthetic records only when their existing owned account
is present. It does not reset balances, daily totals, transaction history or
existing subscription state. The seed includes Alice's iQIYI demo record and
the shared StreamBox/CloudMusic records for the fixture account when present.
It never creates active subscriptions from detector confidence.

Completed cancellation actions created before this table existed are respected
when inserting a missing known record: its initial status is cancelled. Its
cancelled_at stays unknown (NULL); an execution timestamp is not fabricated.
Existing records are never reactivated by startup. Older nonempty databases
still do not receive missing fixture users, accounts or transaction history.

Local users use `python backend/start.py --reload` after installing requirements.
`USE_MOCK_SUBSCRIPTIONS=false` selects real detection and is the default locally
and in Compose. Explicit true selects only the mock detector; verified mapping,
eligibility and persistent cancellation checks still apply. There is no automatic
fallback to mocks on real-module failures.

## Read APIs and account scope

* `GET /api/v1/subscriptions` remains the canonical SubscriptionReport.
* `GET /api/v1/subscriptions/records` returns a list of canonical Subscription
  objects from storage, including active/cancelled status.
* Both accept optional `account_id`. Without it they choose the first owned
  account ordered by account_id, matching chat's default account. Explicit
  foreign or unknown accounts return 404. Accounts are never combined for
  recurrence detection.

The detector receives the selected account's full history, including enough data
for annual recurrence when available. P5 owns deduplication, cadence, price bands,
confidence, evidence IDs and merchant matching. P5 enrichment handles differing
candidate and stored IDs; mutation payloads always name the exact stored ID.

## Evidence versus verified state

The dashboard separates recurring-charge evidence from verified demo records.
Confidence below 0.70 is labelled possible recurrence; 0.70 and above is labelled
a recurring pattern. Neither label establishes active status or permission.
Alice's two seeded iQIYI charges produce confidence 0.40, while her separate
verified demo record supplies active status and cancellation support.

Raw detection never grants cancellation. Verified records may exist with little
or no recurring history and remain cancellable when active and supported. The
UI requests cancellation only from active supported stored records. Cancelled
and unsupported records have disabled controls. Ambiguous names are clarified
by P1 rather than silently picking a subscription.

## Execution

P1 receives current owned stored records on every chat turn. P2 checks P5
eligibility before storing a cancellation action, then rechecks current
ownership/status/support together with P4 policy during confirmation. The
executor checks again and conditionally updates active supported state to
cancelled. That update, the cancellation audit and the completed approval are
committed together by the confirmation route. Replaying a completed action
returns the original audit ID; a separate pending cancellation cannot execute
after the record is cancelled.

Cancellation never creates a refund, increases balance or automatically transfers
projected savings. Historical charges remain evidence after cancellation.
All merchant cancellation is simulated; no merchant service is contacted.

## Manual walkthrough after rebuilding

1. Refresh the dashboard. Inspect recurring evidence and verified records.
2. Ask `List my subscriptions` in chat.
3. For an active supported iQIYI record, use its cancellation button or type
   `Cancel iQIYI VIP Monthly subscription`. This wording also works with P1's
   deterministic mock provider. If asked to clarify, enter `iQIYI VIP Monthly`.
4. Before confirmation, the stored record stays active and balance is unchanged.
5. Confirm the Yellow proposal. The refreshed record shows Cancelled (simulated),
   the balance stays unchanged, and the audit panel shows SUBSCRIPTION_CANCELLED.
6. Refresh/restart and ask to cancel again. Cancelled state persists and no new
   executable cancellation should be issued. Historical evidence can remain.

If a prior demo already cancelled iQIYI, the upgrade preserves that outcome.
Do not reactivate records just to make the walkthrough appear fresh. Use a
disposable demo database for another full cancellation rehearsal.

## Verification and limits

Integration tests reach P5's actual detector/mapping/eligibility through HTTP,
verify the P1 result loop, weak and strong candidates, differing IDs, unknown and
foreign records/accounts, full annual history, state changes between proposal
and confirmation, no balance credit and safe repeated cancellation. Migration
tests exercise fresh and older SQLite/PostgreSQL databases and startup using
new sessions, preserving cancelled state and existing financial data.

This does not add renewal reminders, real merchant cancellation, a general task
planner or a correlated mutation-result continuation back into P1. Approval
concurrency now uses the guard described in `execution_safety.md`. Daily totals
now use `daily_transfer_lifecycle.md`; broader safety-lock behavior remains separate work. The current frontend
still uses its existing approval metadata transport.

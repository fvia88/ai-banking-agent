# Approval execution protection

Step two adds a shared `execute_claimed_action` guard for both `/confirm` and
`/verify`. It uses database locks rather than process-local mutexes, so the
protection is shared across backend workers. No schema migration, shared-contract
change or new public action status is introduced.

## Transaction and lock order

For a pending action, the guard acquires locks in this order:

1. A no-op UPDATE on the authenticated user's row serializes that user's
   approvals and protects the current user-lock state. PostgreSQL takes a row
   lock; SQLite reserves its single writer. This deliberately serializes separate
   accounts belonging to one user as a conservative demo tradeoff.
2. A conditional no-op UPDATE claims the action only if its owner and previously
   observed pending status still match. The action is refreshed after waiting.
3. Policy evaluation selects the owned source account with FOR UPDATE and
   populate_existing. The executor also refreshes the account under that lock.
   This avoids using an earlier SQLAlchemy identity-map snapshot for funds or
   cumulative policy calculations.

The locks stay in the same transaction through fresh policy evaluation, MFA
consumption when applicable, account changes, ledger/audit writes and COMPLETED
status. A successful challenge issuance instead commits PENDING_MFA plus its
challenge audit without a debit. The former commit between Red policy checking
and execution has been removed. No LLM request runs inside the critical section.

The Session may already have a transaction from authentication; the guard reuses
it. Database access outside these guarded mutation routes must follow a compatible
locking protocol. This is not a claim that arbitrary direct database edits or
future mutation endpoints are automatically safe.

## Replies, refusal and retry

An overlapping request whose pending state changed returns HTTP 409. A later
request that initially sees COMPLETED returns its original execution/audit result
without executing. A bad digest cannot rewrite an already completed action.
PostgreSQL lock acquisition is limited to five seconds; recognized lock/deadlock/
serialization failures, and SQLite busy/locked errors, roll back and return 409.
Retry the same action rather than creating another transfer to recover a conflict.
Replay protection here is tied to the server action ID; this does not introduce
cross-action deduplication using the currently optional idempotency_key field.

Expected Yellow executor refusals now roll back partial financial writes and
conditionally record FAILED, matching Red's existing rollback-before-failure
behavior. Conditional failure transitions cannot overwrite a concurrent completion.
Policy denials remain REJECTED and expiry remains CANCELLED.

Unexpected failures roll back; an uncommitted action remains retryable within its
authorization/expiry limits. If a commit succeeds but its acknowledgement is lost,
the next request rereads the durable COMPLETED state and replays its result.
P3 OTP generation, attempt limits, expiry, legacy stranded-challenge handling and
conditional MFA consumption are preserved.

## Verification

The original three failing safety assertions now pass on SQLite and PostgreSQL:
duplicate Yellow confirmation creates one debit/audit; competing 600 CNY actions
cannot bypass MFA; competing 400 CNY transfers cannot spend more than a 500 CNY
balance. Two additional race cases cover mixed Yellow/Red execution and separate
Red verifications competing for insufficient funds. Both databases pass all five
cases (10 tests). PostgreSQL tests used a separate disposable PostgreSQL 16
container and uniquely named databases, not banking_db or the app volume.

The older same-action Red race test now synchronizes before entering the lock,
not inside OTP checking. Otherwise a correct serializer would deadlock the test's
barrier. The Yellow tests retain a bounded pre-flush rendezvous that lets a
correctly blocked second worker wait safely while the first finishes.

Additional tests cover Yellow partial-write refusal, unexpected executor crashes,
commit failure before durability, acknowledgement loss after durability and bad
digest replay against a completed action. These supplement existing P3 recovery,
P4 policy and P5 cancellation checks.

At the execution-safety checkpoint the offline run produced 731 passes and one
pre-existing security-default test failure. That disagreement is now resolved:
local code and Compose default to real P4. The later full suite passed all 756
tests; see `security_defaults_and_audit.md` for current evidence.

To run race checks, use the commands in `concurrency_reproduction.md`. Set
MIGRATION_TEST_POSTGRES_ADMIN_URL to a disposable PostgreSQL server's admin URL
to enable PostgreSQL tests; otherwise those parametrizations are skipped. That
test user needs permission to create/drop uniquely named test databases.

The SQLAlchemy refresh/locking behavior is documented at:
https://docs.sqlalchemy.org/en/20/orm/session_api.html

## Deployment and remaining scope

Rebuild the backend image using the same intended provider environment settings:

```powershell
docker compose up -d --build backend
```

Local development uses the existing backend startup script. No database reset or
new migration is needed. No app container was rebuilt during verification.

Calendar-based daily-total lifecycle is now implemented; see
`daily_transfer_lifecycle.md` for its migration, locking and boundary tests.
Explicit ESCALATED_TO_RED auditing and security-mode defaults are now completed;
see `security_defaults_and_audit.md`. Still separate work: frontend conflict/retry and
metadata transport, and trusted mutation-result continuation to P1. Broader failure
and recovery acceptance should include deployment/network fault scenarios, beyond
the simulated commit and executor failures covered here.

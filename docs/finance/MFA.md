# P3 Simulated OTP / MFA: Design, Demo Steps and Limits

Applies to Red-tier actions: transfers where today's cumulative total after the transfer
exceeds CNY 1000. Code: `backend/app/services/mfa.py`, `backend/app/api/approvals.py`
(`/confirm`, `/verify`), `backend/app/api/demo_inbox.py`. Both routes run inside P2's
shared execution guard (`backend/app/services/action_execution.py`).

Last checked against `main` at `d0581e7` (2026-10-27).

## Lifecycle

```
chat proposes Red transfer ──> PENDING_CONFIRMATION     (no debit)
POST /confirm (digest ok)  ──> PENDING_MFA + challenge   (no debit)
POST /verify  correct code ──> COMPLETED                 (exactly one debit + audit ID)
              wrong code   ──> stays PENDING_MFA, attempts - 1
              3rd wrong    ──> FAILED
              code expired ──> CANCELLED
              action expired ──> CANCELLED
              policy now denies (e.g. account locked) ──> REJECTED (HTTP 403, audited)
              executor refusal (e.g. insufficient funds) ──> FAILED, no debit
```

A Yellow action can also be escalated to Red at `/confirm` when the fresh policy check
sees a higher cumulative total (audited as `ESCALATED_TO_RED`). It then follows this flow.

| Property | Implementation |
|---|---|
| Code | Random 6 digits (`secrets.randbelow`), compared in constant time |
| Expiry | 5 minutes, and never later than the action's own expiry |
| Attempts | 3 failed attempts on one challenge, then the action is `FAILED`. A correct code cannot revive it |
| Fresh policy | Real P4 policy is re-evaluated at `/confirm` and again at `/verify` before the debit (`_current_policy`). A correct OTP cannot override a new lock, a changed daily tier or another policy denial |
| Locking | Each request locks in the order user row, then action (conditional claim), then source account (`FOR UPDATE`). Competing approvals for the same user wait or get HTTP 409. On PostgreSQL the lock wait is limited to 5 seconds |
| Single use | A conditional UPDATE claims the challenge (`mfa_consumed_at`). The claim, the policy recheck, the debit, ledger/audit writes and `COMPLETED` commit in **one** transaction |
| Failure recovery | Executor refusal (e.g. insufficient funds): rolled back, action `FAILED`, code retired. Unexpected crash: nothing commits, so the code is still valid and a retry gives exactly one debit. If the commit landed but the response was lost, a retry returns the original audit ID |
| Replay | Verifying a `COMPLETED` action returns the original audit ID and never debits again |
| Safety lock (P2/P4) | Three wrong OTPs or confirmation digest mismatches within 15 minutes, across all of a user's actions, lock the user. Other pending approvals become `REJECTED` and their codes are retired. The lock does not expire; it needs a manual operator reset (`docs/app/safety_lock.md`) |
| Ownership | Actions and the inbox are scoped to the authenticated demo user. Another user gets 404, and this does not count towards the victim's safety lock |
| Delivery | Simulated: printed to the backend console and shown in the owner's demo inbox (`GET /api/v1/demo/otp-inbox`), labelled "[Simulated]" |
| Daily total | Counted per Asia/Shanghai day (`docs/app/daily_transfer_lifecycle.md`). An action verified after midnight counts against the new day; a Red action is never downgraded because midnight passed |
| API shape | Approval metadata (`action_id`, `action_digest`, `tier`) is in `action.approval`, not in the tool arguments. `/confirm` and `/verify` bodies require an `idempotency_key` |
| Old databases | Alembic migrations add the MFA, daily-date and safety-lock columns at startup without touching existing data (see `docs/app/database_migrations.md`) |

## Demo steps (fresh database, Alice)

Run with P1's real agent: `USE_MOCK_AGENT=false`. Docker already sets this. For a
deterministic run, add `AGENT_PROVIDER=mock`. Real P4 security is the default for both
Docker and local startup.

1. Chat: **"Transfer 1200 CNY to Bob"**. A Red action card appears, and the balance is still 15250.00.
2. Click **Confirm**. The status becomes MFA-pending, and the balance is still 15250.00.
3. Optional: enter a wrong code **once** to show "2 attempt(s) remaining".
4. Read the code from the **Demo inbox (simulated)** panel, or from the backend console.
5. Enter the code. The status is `COMPLETED`, the balance is 14050.00 and an audit ID is shown.
6. Optional: submit again to show the same audit ID and no second debit.

**Warning for rehearsals:** wrong codes count towards the owner-wide safety lock. Three
wrong codes within 15 minutes, even on different actions, lock Alice. Transfers and
cancellations are then refused until someone runs:

```powershell
docker compose exec backend python -m app.db.reset_safety_lock --user-id usr_demo_01 --reason "Reviewed synthetic MFA demo failures" --confirm-demo-reset
```

Rehearse on a disposable database, and show at most one wrong code in the recording.

Note: this transfer also adds `Transfers 1200.00` to Alice's October spending report
(see `SIGNOFF.md`).

## Known limits (state these honestly)

- No real SMS or email delivery. The code is visible in the console and the demo inbox by design.
- Identity is the `X-Demo-User-Id` header, not real authentication.
- Not production MFA: no device binding and no authenticated staff console. The safety-lock
  reset is a local operator command, not a bank process.
- Concurrency evidence: the MFA race test (`test_truly_concurrent_verifies_debit_once`) runs
  on SQLite with real threads only. P2 reports that the shared race tests in
  `test_security_concurrency.py` and `test_safety_lock.py` pass on both SQLite and a
  disposable PostgreSQL 16 (`docs/app/execution_safety.md`). On 2026-10-27 those PostgreSQL
  cases were skipped locally because no PostgreSQL server was available; they were not re-run by P3.

## Test evidence

Run on `main` at `d0581e7`, 2026-10-27, SQLite in-memory, `AGENT_PROVIDER=mock`: full Python
suite 815 passed, 22 skipped (all skips are PostgreSQL cases that need
`MIGRATION_TEST_POSTGRES_ADMIN_URL`).

`backend/tests/test_mfa.py` (P3):
- `test_red_transfer_debits_once_only_after_valid_mfa`
- `test_code_is_random_printed_to_console_and_not_in_confirm_response`
- `test_demo_inbox_is_owner_scoped_and_drops_used_codes`
- `test_demo_inbox_hides_expired_codes`
- `test_duplicate_verify_does_not_debit_twice_and_returns_same_audit_id`
- `test_concurrent_verify_loser_is_rejected_without_debit`
- `test_expired_challenge_rejects_correct_code`
- `test_expired_action_rejects_correct_code`
- `test_challenge_never_outlives_action`
- `test_third_wrong_code_fails_and_correct_code_cannot_recover`
- `test_wrong_user_cannot_verify`
- `test_account_locked_after_confirm_blocks_execution`
- `test_unknown_tool_fails_closed_at_verify`
- `test_executor_failure_consumes_challenge_without_retry_debit`
- `test_unexpected_executor_crash_leaves_no_debit_and_code_still_usable`
- `test_executor_refusal_rolls_back_partial_writes`
- `test_legacy_stranded_challenge_is_retired_not_stuck`
- `test_truly_concurrent_verifies_debit_once` (two real threads, shared file DB, SQLite only)

Related P2/P4 tests that cover the MFA path:
- `backend/tests/test_security_concurrency.py`: competing Red verifications cannot overspend,
  mixed confirm/verify reconcile, competing Yellow actions cannot bypass MFA
  (SQLite and PostgreSQL)
- `backend/tests/test_safety_lock.py`: three wrong codes lock the user and retire other
  tickets, wrong-user and expired codes do not count, concurrent wrong codes share one counter
- `backend/tests/test_daily_transfers.py`: MFA verified across midnight, Red not downgraded
- `backend/tests/test_action_execution.py`: commit failure and lost acknowledgement recovery

Database upgrades (P2): `backend/tests/test_migrations.py`.

# P3 Simulated OTP / MFA: Design, Demo Steps and Limits

Applies to Red-tier actions: transfers where today's cumulative total after the transfer
exceeds CNY 1000. Code: `backend/app/services/mfa.py`, `backend/app/api/approvals.py`
(`/confirm`, `/verify`), `backend/app/api/demo_inbox.py`.

## Lifecycle

```
chat proposes Red transfer ──> PENDING_CONFIRMATION     (no debit)
POST /confirm (digest ok)  ──> PENDING_MFA + challenge   (no debit)
POST /verify  correct code ──> COMPLETED                 (exactly one debit + audit ID)
              wrong code   ──> stays PENDING_MFA, attempts - 1
              3rd wrong    ──> FAILED
              code expired ──> CANCELLED
              action expired / account locked / executor refusal ──> CANCELLED / REJECTED / FAILED
```

| Property | Implementation |
|---|---|
| Code | Random 6 digits (`secrets.randbelow`), compared in constant time |
| Expiry | 5 minutes, and never later than the action's own expiry |
| Attempts | 3 failed attempts, then the action is `FAILED`. A correct code cannot revive it |
| Single use | A conditional UPDATE claims the challenge (`mfa_consumed_at`). The claim, the debit and `COMPLETED` commit in **one** transaction, so a racing request either waits and gets 409, or nothing commits at all |
| Failure recovery | Executor refusal (e.g. insufficient funds): rolled back, action `FAILED`, code retired. Unexpected crash: nothing commits, so the code is still valid and a retry gives exactly one debit. If the commit landed but the response was lost, a retry returns the original audit ID |
| Replay | Verifying a `COMPLETED` action returns the original audit ID and never debits again |
| Ownership | Actions and the inbox are scoped to the authenticated demo user. Another user gets 404 |
| Delivery | Simulated: printed to the backend console and shown in the owner's demo inbox (`GET /api/v1/demo/otp-inbox`), labelled "[Simulated]" |
| Old databases | P2's Alembic migration `0002_mfa_lifecycle` adds the MFA columns at startup without touching existing data (see `docs/app/database_migrations.md`) |

## Demo steps (fresh database, Alice)

Run with P1's real agent: `USE_MOCK_AGENT=false`. Docker already sets this. For a
deterministic run, add `AGENT_PROVIDER=mock`. The backend's default `USE_MOCK_AGENT=true`
mock ignores the amount and always drafts 500 CNY (Yellow), so it cannot show this flow.
These steps were verified over HTTP on 2026-10-24 with `USE_MOCK_AGENT=false AGENT_PROVIDER=mock`.

1. Chat: **"Transfer 1200 CNY to Bob"**. A Red action card appears, and the balance is still 15250.00.
2. Click **Confirm**. The status becomes MFA-pending, and the balance is still 15250.00.
3. Optional: enter a wrong code once to show "2 attempt(s) remaining".
4. Read the code from the **Demo inbox (simulated)** panel, or from the backend console.
5. Enter the code. The status is `COMPLETED`, the balance is 14050.00 and an audit ID is shown.
6. Optional: submit again to show the same audit ID and no second debit.

Note: this transfer also adds `Transfers 1200.00` to Alice's October spending report
(see `SIGNOFF.md`).

## Known limits (state these honestly)

- No real SMS or email delivery. The code is visible in the console and the demo inbox by design.
- Identity is the `X-Demo-User-Id` header, not real authentication.
- Not production MFA: no device binding, no rate limiting across actions, and no user-level
  lockout after repeated failures. That safety lock is P4's Day 2 item.
- The real P4 policy is not yet re-run at verify time (TODO in `approvals.py`). Only the
  account lock and expiry are rechecked.
- Concurrency is proven on SQLite with real threads. PostgreSQL behaviour relies on its row
  lock and is still to be tested (Day 2).

## Test evidence

`backend/tests/test_mfa.py`:
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
- `test_truly_concurrent_verifies_debit_once` (two real threads, shared file DB)

Database upgrades (P2): `backend/tests/test_migrations.py`.

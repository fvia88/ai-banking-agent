# Persistent demo safety lock

P2 now records repeated verification failures and activates P4's existing
locked-account rule. The user chose persistent recovery: an automatic lock
requires a manual demo-operator reset. It never expires automatically.

## Behavior

- Three wrong MFA codes and/or confirmation digest mismatches in one 15-minute
  observation window activate the lock. The counter is owner-wide, including
  different actions and conversations; creating another action cannot reset it.
- A pending action with a bad confirmation digest is rejected immediately, as
  before. Retrying an already terminal ticket does not add another failure.
- The threshold-triggering MFA action becomes `FAILED`. Other owned pending
  approvals become `REJECTED`, and their OTPs are retired. Completed actions are
  preserved. Old tickets never become executable after a reset.
- Transfers and subscription cancellations are blocked by real P4 policy while
  locked. Balance, transaction, spending, subscription, and audit reads remain
  available under the existing read policy. The dashboard shows the locked state.
- Wrong-owner, malformed request, expired-code, and ordinary insufficient-funds
  refusals are not counted as credential verification failures.
- Failure count/window, lock state, sibling retirement, and audit entries commit
  together under the existing database user lock. Separate processes share this
  protection. A commit failure rolls all these changes back.

The 15-minute window resets an inactive counter, not an activated lock. This is
a fixed observation window beginning at the first failure, rather than a rolling
event-history window. A correct OTP does not erase earlier failures in the window.
The existing three-attempt limit per challenge also remains in force. The two
limits are independent: per-challenge failure can retire a ticket without reaching
the owner threshold when failures are sufficiently far apart.

Audit events are `VERIFICATION_FAILURE`, `SAFETY_LOCK_TRIGGERED`,
`ACTION_REJECTED_SAFETY_LOCK`, and `SAFETY_LOCK_RESET`. They use fixed reason
codes and failure counts; they do not include submitted OTPs or rejected digest
values. The existing synthetic demo inbox/console remains the simulated OTP
delivery channel, not production MFA.

## Upgrade and manual reset

Alembic `0006_safety_lock` adds failure-window and automatic-lock provenance
fields to `users`. It preserves existing `is_locked` values, balances, ledger,
approvals, and audits. Normal backend startup applies it. Rebuild both services
to include the dashboard indicator:

```powershell
docker compose up -d --build backend frontend
```

After reviewing the demo user's failures, a local demo operator can run:

```powershell
docker compose exec backend python -m app.db.reset_safety_lock --user-id usr_demo_01 --reason "Reviewed synthetic MFA demo failures" --confirm-demo-reset
```

For a locally started backend, keep the same database environment and run:

```powershell
$env:PYTHONPATH = 'backend;.'
python -m app.db.reset_safety_lock --user-id usr_demo_01 --reason "Reviewed synthetic MFA demo failures" --confirm-demo-reset
```

This audited command clears only a recognized automatic safety lock and its
failure counter. It refuses to clear an unrelated manually applied lock. It
does not reset balances, delete transactions, revive approvals, or clear daily
transfer totals. Start a fresh action after the reset. Do not put secrets in
the review reason. There is no HTTP unlock endpoint or agent unlock tool.

This command is a local prototype operator mechanism, not an authenticated bank
staff console. Existing demo-header identity is not production authentication.

## Verification

Tests cover single- and multi-action failures, digest tampering, expired-window
reset, persistent lock after time passes, unaffected owners, read access, old
ticket retirement, manual reset/audit, preservation of unrelated manual locks,
commit failure recovery, SQLite/PostgreSQL concurrent failures, and startup
preservation. No app database is used by these tests.

To check in the frontend, first obtain a Red action with an amount that crosses
the cumulative daily threshold but is within the available balance. Confirm,
then submit a six-digit code different from the actual demo inbox code three
times. The action fails, the account displays locked, and new transfers and
cancellations are refused. A balance request still succeeds. Run the reviewed
operator reset command above, refresh the dashboard, and create a new action.

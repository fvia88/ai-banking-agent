# Yellow confirmation concurrency reproductions

Step one of the execution-safety work recreates the three reported races without
changing application runtime files. The new tests are in
`backend/tests/test_security_concurrency.py`. They assert the desired safe
behavior and failed at the initial test-only checkpoint. Step two subsequently
added the execution guard; these assertions now pass. See `execution_safety.md`
for current transaction guarantees, PostgreSQL verification and remaining scope.

## Method

Each case creates its own disposable, file-backed SQLite database and seeds a
synthetic user/account plus canonical Yellow actions evaluated by real P4.
Two workers call the actual confirmation route function, each with its own
SQLAlchemy session and connection. This exercises the route, policy and executor
but does not test HTTP middleware or authentication dependencies.

A test-only SQLAlchemy before_flush listener pauses both workers after they
calculate financial updates and before database writes. It does not replace
policy, execution results or money calculations. This exposes an allowed race
schedule that a manual double-click may not reliably hit. The rendezvous has a
bounded wait: if future locking correctly serializes before this point, the first
worker can continue without waiting forever for a blocked second worker.

Tests check worker termination, unexpected exceptions, returned results, stored
action states, action/audit linkage, ledger counts and amounts, balance and daily
total reconciliation. No live LLM, Docker app database or personal demo account
is used. The original reproduction used SQLite. The test harness now additionally
supports a disposable PostgreSQL server when its test admin URL is supplied.

## Observed vulnerable behavior

| Case | Desired behavior | Observed current behavior |
|---|---|---|
| Two confirmations of one 100 CNY action; balance 2000 | One ledger debit and audit; duplicate conflicts or replays original result | Both complete with different audit IDs; two debits and execution audits; balance 1900 and daily total 100 reflect only one debit |
| Two different 600 CNY actions; balance 2000, daily total 0 | One completes; the other moves to PENDING_MFA without a second debit | Both complete as Yellow; ledger debits total 1200 but balance is 1400 and daily total 600 |
| Two different 400 CNY actions; balance 500 | Only one completes; the other is refused without another debit | Both complete; ledger debits total 800 but balance is 100 and daily total 400 |

In all three cases the first run confirmed that both workers reached the
pre-flush race window. A nonnegative displayed balance is not evidence of safety:
lost updates hide the ledger/account inconsistency.

Five additional runs reproduced all three failures each time, with both workers
reaching the intended window in every case (15 repeated race reproductions).

## Reproduce

From the repository root, with the project virtual environment active:

```powershell
$env:PYTHONPATH = 'backend;.'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:DATABASE_URL = 'sqlite:///:memory:'
$env:AGENT_PROVIDER = 'mock'
$env:USE_MOCK_SECURITY = 'false'
python -m pytest backend/tests/test_security_concurrency.py -q -p no:cacheprovider --tb=short
```

Expected on the original vulnerable runtime: three assertion failures with captured
financial and action/audit evidence. A database-lock exception or stuck worker
is a harness/runtime error, not the successful reproduction of these three cases.
With the execution guard, the safety assertions should pass. PostgreSQL
parametrizations are skipped unless MIGRATION_TEST_POSTGRES_ADMIN_URL is set.
Use a separate terminal for testing: do not leave the test DATABASE_URL set when
starting the real app.

## Next milestone

Action/account protection and transaction boundaries are now implemented and
verified on both SQLite and PostgreSQL while preserving P4 checks and P3 recovery.
Daily-total reset and broader failure/retry acceptance remain follow-up work.

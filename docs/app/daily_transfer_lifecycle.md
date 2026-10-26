# Daily transfer totals

Daily transfer totals now belong to a persisted Asia/Shanghai calendar date,
stored in `accounts.daily_transfer_date`. Counters remain per account, matching
the existing BankingContext and policy integration; this change does not create
a combined limit across multiple accounts owned by one user.

## Day boundary and reads

The banking day changes at 00:00 Asia/Shanghai (16:00 UTC). The implementation
uses an explicit UTC+08:00 offset, independent of the host/container timezone.
Account creation sets the current banking date alongside its initial total.

Chat policy contexts use a read-only effective total: an older date counts as
zero today. Read requests and proposal generation do not write a reset or change
balances. No scheduled task or midnight background worker is required.

## Locked rollover and execution

At transfer confirmation or successful OTP verification, the shared execution
guard first claims the user/action and locks the account. The fresh policy check
then rolls an older counter forward to zero and the current banking date. That
bookkeeping is flushed within the same transaction, not independently committed.
The normal policy calculation then uses the new-day amount.

A persisted rollover writes a DAILY_TRANSFER_TOTAL_RESET audit event, linked to
the action/user/digest, with reason SHANGHAI_DAY_CHANGED and previous/new dates
and previous total. Concurrent requests reset once; the next request sees the
first completed new-day debit instead of erasing it. A confirmation that issues
MFA can commit the reset without making a debit. A policy denial may also commit
this maintenance reset alongside its rejection audit; that is not execution of
the transfer.

Policy checking captures one authoritative instant after the account lock. The
executor uses that same instant for the UTC ledger timestamp, so midnight between
validation and execution cannot place a debit in a different day from its counter.
The following operation uses its own fresh instant and rolls forward if needed.
The timestamp is removed from Session.info when the guarded request ends.

Red actions are never downgraded just because midnight passed. A pending MFA
action verified after midnight counts against the new day after its current
authorization and expiry checks pass. Expired actions cannot be revived by a
rollover. A clock earlier than the stored transfer date causes a conflict with no
financial changes, rather than resetting the counter backwards.

Unexpected execution failures roll back the reset, its audit and all partial
financial writes together. The next valid attempt can perform the reset safely.
Expected executor refusals retain the existing conditional FAILED handling after
rollback. Balances and historical transactions are never replenished or deleted
by daily rollover.

## Upgrade existing databases

Alembic revision `0004_transfer_day` adds the date column and initializes unknown
dates to the Shanghai date of the upgrade. Existing totals and balances are
preserved. This is deliberately conservative: an old undated total may include
historical transfers, but the migration does not guess which amounts happened
today. That retained total expires at the next Shanghai day boundary. Previously
dated rows retain their dates and amounts. Compatible ORM-created installations
are accepted; an incompatible existing column type stops the upgrade.

Rebuild with your intended provider environment settings:

```powershell
docker compose up -d --build backend
```

The existing startup script applies the migration automatically. Local users
restart `python backend/start.py --reload`. Keep older backend instances stopped
during schema upgrades, as described in database_migrations.md. No database reset
or manual counter update is required.

## Evidence

Fourteen focused tests cover UTC/Shanghai boundaries, month/year/leap-day changes,
same-day accumulation, old-day proposal contexts, pending Yellow/Red actions,
MFA across midnight, a policy/executor midnight crossing, rollback and a backwards
clock. The concurrency suite adds a first-transfer-of-day race on both SQLite and
PostgreSQL: only one 600 CNY transfer completes before MFA and only one reset audit
is stored. Migration tests verify legacy totals/balances are preserved and repeat
upgrades are safe on both databases.

The combined offline run recorded 749 passed and the pre-existing security-mode
default test failure. PostgreSQL used disposable databases in a separate test
container; the running banking_db and its volume were not modified.

The real frontend cannot simulate tomorrow without changing the server clock.
Use these controlled tests instead of changing your computer clock or manually
editing the live counter to claim a midnight test passed. After an actual day
boundary, new proposals should use only today's transfers, while prior Red
approval requirements and transaction history remain intact.

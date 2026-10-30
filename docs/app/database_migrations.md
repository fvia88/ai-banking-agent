# Database upgrades and backend startup

Backend startup now runs Alembic migrations, seeds only an empty database, and
then starts FastAPI. A failed upgrade prevents the server from starting.
Existing balances, transactions, approvals and audit records are preserved.

## Docker

From the repository root, keep your existing provider environment variables and run:

```powershell
git pull
docker compose up -d --build
docker compose logs --tail 50 backend
```

The rebuild is needed because the image contains a copy of the source code and
dependencies. The database volume remains in place. Do not use `down -v` to
upgrade. The frontend remains available at http://localhost:3000.

## Local development without Docker

Activate the project virtual environment and run from the repository root:

```powershell
python -m pip install -r backend/requirements.txt -r agent/requirements.txt
python backend/start.py --reload
```

Use your existing DATABASE_URL and provider settings. Without DATABASE_URL the
backend uses the existing default `sqlite:///./backend_demo.db`, relative to the
current working directory. Run from the repo root to select the expected file.
Start the Vite frontend separately as before. Node.js does not migrate PostgreSQL.

Use this startup script instead of invoking Uvicorn directly. Uvicorn alone does
not apply migrations. Restart the script after pulling new migration files.

## Existing and fresh databases

`0001_legacy_schema` creates the original tables on an empty database or adopts
existing create_all tables without resetting their data. It rejects legacy tables
missing required baseline columns rather than silently marking them current.
`0002_mfa_lifecycle` adds nullable mfa_issued_at, mfa_expires_at, mfa_consumed_at
and audit_id columns. Compatible columns already added by the manual SQL repair
are accepted. Alembic records the applied revision in `alembic_version`.

`0003_subscriptions` adds durable verified subscription records. Startup backfills
missing known records only for existing owned demo/fixture accounts, preserving
cancelled state and financial data. See `p5_integration.md` for scope and APIs.

`0004_transfer_day` dates account-level daily transfer counters in Asia/Shanghai.

`0005_agent_continuation` persists owner-scoped P1 conversation state and adds
nullable action-to-conversation links plus cached status delivery. Existing
financial data and unlinked approvals are preserved. See `agent_continuation.md`.

`0006_safety_lock` adds owner-wide verification-failure counters and automatic-lock
provenance to users. Existing lock values and financial data are preserved.
Activated locks survive restart until a reviewed local reset; see `safety_lock.md`.
It preserves legacy amounts and initializes missing dates to the upgrade day;
those totals expire at the next Shanghai day boundary. See
`daily_transfer_lifecycle.md` for lazy rollover, atomic accounting and tests.

`0007_chat_history` adds owner-scoped conversation summaries and visible chat
messages. Transcript storage is separate from P1 working memory; existing
financial records are preserved. The frontend loads saved messages and refreshes
approval status without authorizing execution.

The older `001_add_mfa_lifecycle.sql` is retained as a manual repair reference;
automatic startup uses the Python revisions, not that SQL file. No manual stamp
or database reset is required for the supported existing schemas.

Old actions retain their statuses and NULL lifecycle values. Do not invent MFA
timestamps or reset completed actions. Start a new request for an old pending
MFA action without lifecycle timestamps. Missing historical audit linkage is not
backfilled. Existing seed behavior preserves nonempty databases and does not
insert missing fixture users, accounts or transactions into them. Known missing
subscription records are backfilled as described above.

## Safety and future changes

Back up a valued database before upgrading. PostgreSQL startup upgrades share
one transaction and acquire an advisory lock to serialize migration runners;
lock acquisition times out after 30 seconds. This does not lock out an already
running older app. For this local demo, stop older backend instances before
upgrading, especially before future incompatible schema changes. Run only one
local SQLite startup at a time.

Downgrades are deliberately disabled to avoid deleting application data. Review
and restore a backup if recovery is required. Never edit a deployed revision:
add a new reviewed revision for each subsequent schema change. New revisions
must use frozen schema definitions, not import live ORM models. Merely editing
models.py will not create a migration.

For manual Alembic inspection from the repository root:

```powershell
python -m alembic -c backend/alembic.ini current
python -m alembic -c backend/alembic.ini history
```

Startup uses Alembic's documented shared-connection upgrade pattern:
https://alembic.sqlalchemy.org/en/latest/cookbook.html#sharing-a-connection-across-one-or-more-programmatic-migration-commands

Backups such as `banking_before_mfa.dump` are local files, not source code;
do not commit them. Commit migrations, startup changes and these instructions.

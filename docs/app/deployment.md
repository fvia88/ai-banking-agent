# Deployment and local development

This guide describes the checked-in local prototype. Commands use Windows
PowerShell unless stated otherwise. Keep all existing application data when
upgrading; a fresh demo is a separate, deliberate operation.

## Prerequisites

| Path | Requirements |
|---|---|
| Complete Docker demo | Git; Docker Desktop with Linux containers running; Docker Compose v2 |
| Local backend/frontend | Python 3.11+ and a virtual environment; Node.js 24/npm; PostgreSQL, or SQLite for a lightweight local run |
| Live Gemini interpretation | A backend API key and a model accessible to that key; optional for the deterministic demo |

Docker builds use Python 3.11, PostgreSQL 16, a Node 20 frontend builder, and
Nginx. The locked Vite requires Node 20.19+ or 22.12+; the locked ESLint requires
20.19+, 22.13+, or 24+. Node 24 was used for local frontend checks. The build
definitions remain authoritative; image tags and Python dependency ranges are
not a fully pinned release environment.

## Docker startup

From the repository root, copy `.env.example` to `.env` if you do not already
have a local environment file:

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
docker version
docker compose version
docker compose --env-file .env config --quiet
docker compose up -d --build
docker compose ps
Invoke-RestMethod http://localhost:8000/api/v1/health
```

On macOS/Linux, use `test -f .env || cp .env.example .env` for the copy step and use
`curl` for the health request. Initial image pulls/builds require network access.
If `.env` already exists, review it instead of overwriting credentials/settings.
Existing shell variables take precedence over Compose's `.env`; use a fresh
terminal or explicitly set the intended mode if an older session has overrides.

Wait for PostgreSQL to become healthy and for the backend to finish migrations
and seeding. Open http://localhost:3000. Backend docs are at
http://localhost:8000/docs. A failed startup is visible in:

```powershell
docker compose logs --tail 80 postgres backend frontend
```

The published ports are 3000 (Nginx/frontend), 8000 (FastAPI), and 5432
(PostgreSQL). Container-to-container traffic uses `backend:8000` and
`postgres:5432`. Browser API calls go through Nginx's `/api/` proxy.
The service/container names and ports are fixed in the current Compose file;
another copy cannot run alongside it unchanged.

## Modes and environment

| Setting | Checked-in Compose default | Meaning |
|---|---|---|
| `USE_MOCK_AGENT` | `false` | Real P1 orchestration; `true` selects P2's simpler mock adapter |
| `AGENT_PROVIDER` | `mock` | Offline deterministic interpretation; `gemini` calls the live provider |
| `USE_MOCK_SECURITY` | `false` | Actual P4 policy; keep false for the integrated demo |
| `USE_MOCK_SUBSCRIPTIONS` | `false` | Actual P5 detection/eligibility; keep false for the integrated demo |
| `GEMINI_API_KEY` | empty | Required only for `AGENT_PROVIDER=gemini` |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | Current code default, not a guarantee of availability to your key |
| `AGENT_TIMEOUT_SECONDS` | `20` | Provider timeout; accepted range 1-60 seconds |
| `DATABASE_URL` | supplied by Compose | PostgreSQL URL with the `postgres` service hostname |

Finance uses the real P3 implementation by default. `USE_MOCK_FINANCE` exists
for local/testing use but is not forwarded by the current Compose environment.
Do not assume adding arbitrary variables to `.env` injects them into a container.

The offline recommended setup is real P1 + `AGENT_PROVIDER=mock`, with real
P3/P4/P5. It demonstrates integration deterministically without an LLM key.
`USE_MOCK_AGENT=true` is a different, simpler fallback and is not the full
planning/continuation demo.

For live Gemini, edit `.env` locally: set `USE_MOCK_AGENT=false`,
`AGENT_PROVIDER=gemini`, a nonempty `GEMINI_API_KEY`, and a model enabled for that
key. Recreate the backend so the changed environment is loaded:

```powershell
docker compose up -d --force-recreate backend
```

`docker compose restart` does not apply new environment settings. Source changes
require a rebuild (`docker compose up -d --build backend frontend`). Keep secrets
out of screenshots, source code, frontend variables, and Git. Unfiltered
`docker compose config` can print resolved secrets; use `config --quiet` to validate.

### Local environment loading differs

Backend `Settings` reads configuration such as `DATABASE_URL` from the process
environment or root `.env`. Agent/provider mode switches use `os.getenv`, so they
must be exported into the local Python process. Merely copying the Compose
`.env` file does not export these switches for `python backend/start.py`.

## Local backend and frontend

Use two terminals. Commands below start a host backend against Docker PostgreSQL;
stop the Docker application services first to avoid serving mixed versions:

```powershell
docker compose stop backend frontend
docker compose up -d postgres
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt -r agent/requirements.txt
$env:DATABASE_URL = 'postgresql+psycopg2://banking_user:banking_password@127.0.0.1:5432/banking_db'
$env:USE_MOCK_AGENT = 'false'
$env:USE_MOCK_SECURITY = 'false'
$env:USE_MOCK_FINANCE = 'false'
$env:USE_MOCK_SUBSCRIPTIONS = 'false'
$env:AGENT_PROVIDER = 'mock'
python backend/start.py --reload
```

Reuse an existing virtual environment rather than recreating it unnecessarily.
If activation is restricted, use `.venv\Scripts\python.exe` directly for Python
and pip commands. Startup sets Python import paths, applies migrations, preserves
nonempty databases, and then starts FastAPI on 127.0.0.1:8000. Direct Uvicorn
startup skips that preparation; use the provided startup script.

For a separate lightweight SQLite run, replace `DATABASE_URL` above with
`sqlite:///./backend_demo.db`. This is separate data from Docker PostgreSQL.
Run one local SQLite startup at a time. PostgreSQL is the reference backend for
the concurrency/release checks.

In terminal two:

```powershell
cd frontend
npm ci --legacy-peer-deps
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to the host backend at
127.0.0.1:8000. Its configured port is 5173; check the terminal if Vite selects a
different free port. No frontend API key is needed.

For a live local provider, export these before starting the backend:

```powershell
$env:AGENT_PROVIDER = 'gemini'
$env:GEMINI_MODEL = 'gemini-3.1-flash-lite' # Change to a model available to your key.
$env:AGENT_TIMEOUT_SECONDS = '20'
$geminiKey = Read-Host 'Gemini API key' -AsSecureString
$env:GEMINI_API_KEY = ([System.Net.NetworkCredential]::new('', $geminiKey)).Password.Trim()
Remove-Variable geminiKey
```

The provider variable is a process environment string after entry; secure input
only avoids echoing it while typing. Restart the local backend after changes.

## Upgrades, persistence, and backups

All six Alembic revisions are applied automatically by startup, including MFA
lifecycle, subscription storage, daily totals, conversation state, and safety-lock
tracking. Do not edit old migrations, reset tables, or use `create_all` to repair
an existing schema. See [database migrations](database_migrations.md).

Before upgrading valued demo data, stop application writers and back up PostgreSQL:

```powershell
docker compose stop backend frontend
$backupTag = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupName = "banking-before-upgrade-$backupTag.dump"
docker compose exec -T postgres pg_dump -U banking_user -d banking_db -Fc -f "/tmp/$backupName"
docker compose cp "postgres:/tmp/$backupName" ".\$backupName"
Get-Item -LiteralPath ".\$backupName" | Select-Object Name, Length
docker compose exec -T postgres pg_restore --list "/tmp/$backupName"
```

Confirm each command succeeded before continuing. A dump listing checks readability,
not a successful restore; rehearse restoration into a separate disposable database
if recovery evidence is needed. Dump files are local artifacts and ignored by Git.
This container-file-plus-copy method avoids binary redirection problems in older
Windows PowerShell.

After reviewing the code update:

```powershell
docker compose up -d --build
```

Startup does not reset existing balances, ledger, cancelled subscriptions,
real P1 conversation memory, or safety locks. Missing fixture users/accounts/transactions
are not generally backfilled into a nonempty database. A fresh seed includes both
the fixture account and Alice's separate demo profile.

Use `docker compose stop` / `start`, or `down` without `-v`, to preserve the
volume. Automatic destructive schema downgrades are disabled. After migration
failure, preserve the database and inspect logs; do not erase the volume as the
default recovery step.

### Separate rehearsal data without deleting your current volume

The current Compose file has fixed container names and ports, so stop/remove the
normal stack's containers before using another project. `down` without `-v`
preserves its database:

```powershell
docker compose down
$rehearsalProject = 'banking_rehearsal_' + (Get-Date -Format 'yyyyMMddHHmmss')
docker compose -p $rehearsalProject --env-file .env up -d --build
```

The unique project gets a separate named PostgreSQL volume and a fresh seed.
Keep the project name in that terminal. When rehearsal is finished:

```powershell
docker compose -p $rehearsalProject down
docker compose up -d
```

The normal project reconnects to its original volume. Rehearsal data also remains
in its separate volume unless deliberately removed. This is not shared hosting.

## Safety-lock reset

Three wrong MFA codes or tampered confirmations in a fixed 15-minute observation
window trigger a persistent user lock and retire pending approvals. Reads remain
available. Rebuilding or restarting does not unlock the user.

After reviewing the synthetic failures, a local demo operator can run:

```powershell
docker compose exec backend python -m app.db.reset_safety_lock --user-id usr_demo_01 --reason "Reviewed synthetic demo failures" --confirm-demo-reset
```

For a host backend, use its database environment, set `PYTHONPATH=backend;.` in
PowerShell, and run the same `python -m app.db.reset_safety_lock ...` command.
The reset is audited, clears only a recognized automatic safety lock, preserves
financial data and unrelated manual locks, and does not revive old tickets.
Create a new action after reset. See [safety locks](safety_lock.md).

## Verification

Record the candidate commit (`git rev-parse HEAD`) and whether the working tree is
clean (`git status --short`). Do not publish a test count from an older commit as
evidence for the final candidate.

### Python checks with isolated SQLite

Run in a separate terminal with project dependencies installed. The explicit
test database prevents the test process from using your application database:

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = 'backend;.'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:DATABASE_URL = 'sqlite:///:memory:'
$env:USE_MOCK_AGENT = 'true'
$env:USE_MOCK_SECURITY = 'false'
$env:USE_MOCK_FINANCE = 'false'
$env:USE_MOCK_SUBSCRIPTIONS = 'false'
$env:AGENT_PROVIDER = 'mock'
Remove-Item Env:MIGRATION_TEST_POSTGRES_ADMIN_URL -ErrorAction SilentlyContinue
python -m pytest tests/test_contracts.py agent/tests backend/tests finance/tests subscriptions/tests security/tests -q -p no:cacheprovider --tb=short
```

Individual tests switch to real P1 with offline interpretation as needed.
PostgreSQL cases are skipped unless the disposable admin URL is configured.
Close this test terminal afterward; do not start the real app with the test
`DATABASE_URL` still active.

### Optional disposable PostgreSQL verification

Keep the test environment above and start an independent test server. Use an
unused name/port if these are already occupied; do not stop another person's
container to claim them:

```powershell
docker run --detach --rm --name banking-verify-postgres --publish 127.0.0.1:55432:5432 --env POSTGRES_USER=banking_test --env POSTGRES_PASSWORD=banking_test --env POSTGRES_DB=postgres postgres:16-alpine
docker exec banking-verify-postgres pg_isready -U banking_test -d postgres
```

Wait until `pg_isready` reports accepting connections. Then:

```powershell
$env:MIGRATION_TEST_POSTGRES_ADMIN_URL = 'postgresql+psycopg2://banking_test:banking_test@127.0.0.1:55432/postgres'
python -m pytest tests/test_contracts.py agent/tests backend/tests finance/tests subscriptions/tests security/tests -q -p no:cacheprovider --tb=short
Remove-Item Env:MIGRATION_TEST_POSTGRES_ADMIN_URL
docker stop banking-verify-postgres
```

Fixtures create uniquely named test databases and drop them afterward. The role
needs permission to create/drop databases. Never point this URL at a shared,
valued, or production database server. The `--rm` test container is removed when
stopped; its data is disposable. If tests fail, still stop your test container
after collecting the relevant output.

### Frontend checks

```powershell
cd frontend
npm ci --legacy-peer-deps
npm test
npm run build
```

`npm run lint` is an additional check. `npm run preview` is only a static preview;
it does not configure the Nginx production API proxy. The current frontend Docker
builder still uses `npm install --legacy-peer-deps`; clean build verification must
confirm installation/build from the committed manifests. A successful build from
an already populated local `node_modules` is not proof of a clean Docker startup.

## Runtime API map

All paths below start with `/api/v1`; bodies and responses are described in `/docs`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Backend process health; not a complete provider/database readiness test |
| GET | `/accounts` | Owned synthetic account balances/lock state |
| GET | `/transactions?period=YYYY-MM` | Owned history using Shanghai month boundaries |
| POST | `/chat` | Proposals and grounded read replies; no direct money movement |
| GET | `/actions/{action_id}` | Owned approval metadata/status |
| POST | `/actions/{action_id}/confirm` | Confirm the exact digest; execute Yellow or issue Red MFA |
| POST | `/actions/{action_id}/verify` | Verify simulated OTP and execute once |
| POST | `/actions/{action_id}/cancel` | Withdraw a pending ticket, not reverse an executed operation |
| POST | `/actions/{action_id}/continue` | Return trusted bank outcomes to P1 |
| GET | `/demo/otp-inbox` | Owner-scoped, synthetic pending OTPs |
| GET | `/subscriptions` | Recurring-charge evidence/candidates |
| GET | `/subscriptions/records` | Verified stored subscription status |
| GET | `/audit` | Owned, redacted audit events |

The browser uses `usr_demo_01`; `X-Demo-User-Id` is only a prototype session
mechanism. Confirmation, verification, and cancellation requests require
`idempotency_key`; execution replay protection is tied to the server action ID.
Approval IDs/digests/tier/status live separately from canonical tool arguments.

## Troubleshooting

| Symptom | Check/action |
|---|---|
| Docker named-pipe/daemon connection error | Open Docker Desktop, select Linux containers, wait for the engine, then retry `docker version`. |
| Port or container name already in use | Check the existing Compose stack or local PostgreSQL/backend. Current fixed names/ports prevent two unchanged copies running together. |
| Dashboard opens but API calls fail | Check backend logs, PostgreSQL health, and that the chosen frontend URL is 3000 for Docker or the Vite URL for local development. |
| App uses the wrong provider after editing `.env` | Check shell overrides, keep `USE_MOCK_AGENT=false`, and recreate the backend; restart alone does not reload environment. |
| Local app remains on the simple mock | Export local `USE_MOCK_AGENT=false` and provider variables before startup. Agent flags are not loaded by Settings from `.env`. |
| Gemini key/model/quota/timeout failure | Check key access, provider/model settings and connectivity without exposing the key. Use the labelled offline provider for deterministic integration rehearsal. |
| Missing database columns | Use `backend/start.py` or the Docker startup path, which runs Alembic. Keep old instances stopped during upgrades; inspect migration errors rather than deleting data. |
| Unexpected spending total | Confirm account and month; demo transfers count as debits. Fresh Alice is 80.00 for 2026-10; the separate fixture account is 1843.00. |
| Transfer/cancellation blocked after wrong OTPs | Inspect the audit and lock state; use the reviewed operator reset, then issue a new action. |
| Approval no longer executable | Cancelled/failed/rejected/expired tickets cannot be revived. Start a new request if appropriate. |
| Blank chat history after browser refresh | Banking/real P1 state persists, but full browser transcript/card restoration is still incomplete. Do not assume refreshing resets financial data. |

The unchanged Compose stack has demo credentials, published database/API ports,
and prototype authentication. It is intended for a controlled local demonstration,
not direct public deployment. No live provider availability, clean-checkout build,
or final demo rehearsal is implied by these instructions; those are separate
release verification tasks on the final candidate commit.

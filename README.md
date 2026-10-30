# Banking AI Agent

A fintechathon prototype for natural-language banking with synthetic data.
The app connects a React dashboard to FastAPI, PostgreSQL, the P1 agent, P3
spending analytics, P4 security policy, and P5 subscription detection.

**No real bank connection, real money movement, or external merchant cancellation.**
The default demo runs without an API key. Live Groq interpretation is optional.

## Start with Docker

Install Docker Desktop with the Linux-container engine running and Docker Compose
v2 available. Ports **3000**, **8000**, and **5432** must be free. No host Python or
Node installation is needed for this path.

For the current submission candidate, use the shared `version/v30-clean` branch
and record its commit. The branch must be pushed before others can clone it.

```powershell
git clone --branch version/v30-clean https://github.com/fvia88/ai-banking-agent.git
cd ai-banking-agent
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
docker compose up -d --build
docker compose ps
Invoke-RestMethod http://localhost:8000/api/v1/health
```

On macOS/Linux, use `test -f .env || cp .env.example .env` and
`curl http://localhost:8000/api/v1/health` instead of the two PowerShell commands.
If `.env` already exists, retain your settings rather than overwriting it.

Open:

| Service | Address |
|---|---|
| Banking dashboard | http://localhost:3000 |
| FastAPI/OpenAPI documentation | http://localhost:8000/docs |
| Backend health | http://localhost:8000/api/v1/health |

The backend applies Alembic migrations before serving requests and seeds an empty
database. Restarting preserves balances, transactions, subscription status,
real P1 conversation state, visible chat history, and safety locks. PostgreSQL data lives in a Docker volume.

```powershell
docker compose logs --tail 80 backend
docker compose stop
docker compose start
```

`docker compose down` also preserves the database volume. **Do not add `-v` unless
you deliberately intend to erase that Compose project's demo database.**

See the [deployment guide](docs/app/deployment.md) for upgrades, local development,
provider settings, backups, troubleshooting, and verification commands.

## Optional shared judging website

For the single-service Render + Neon + Groq setup, see the
[shared deployment guide](docs/app/free_shared_deployment.md). Keep `render.yaml`,
`infra/Dockerfile.shared`, the gateway, and the root Neon configuration when
deploying this way. The root Node dependencies are deployment tooling; the
application frontend has its own dependencies in `frontend/`.

This path uses a shared synthetic account behind a demo password, with secrets
configured privately on the host. Its public deployment and live provider must
be verified before sharing a judging URL. Local Docker uses a separate database.

## Choose the interpretation mode

The supplied `.env.example` uses:

```dotenv
USE_MOCK_AGENT=false
AGENT_PROVIDER=mock
USE_MOCK_SECURITY=false
USE_MOCK_SUBSCRIPTIONS=false
```

This runs **real P1 orchestration with a deterministic offline intent provider**,
plus real finance, security, and subscription modules. It is not a live LLM call.
`USE_MOCK_AGENT=true` instead selects P2's simpler mock adapter, which does not
provide the full P1 plan/continuation demonstration.

For live interpretation, edit your local `.env`: set `AGENT_PROVIDER=groq`,
provide `GROQ_API_KEY`, and choose a `GROQ_MODEL` available to that key. Keep
`USE_MOCK_AGENT=false`, then recreate the backend:

```powershell
docker compose up -d --force-recreate backend
```

Do not commit `.env` or place keys in frontend code. Local Python development
requires explicit shell environment variables; see the deployment guide.

## Supported demo flows

The browser uses synthetic Alice (`usr_demo_01`, account `acc_cny_001`). On a
fresh database, her balance is **CNY 15,250.00** and October 2026 spending is
**CNY 80.00**. The separate frozen fixture account has October spending of
**CNY 1,843.00**; it is not Alice's dashboard dataset. Executed transfers count
as spending and change later reports.

| Scenario | Example | Expected behavior |
|---|---|---|
| Balance | `What is my balance?` | Grounded database result, no approval |
| Bill analysis | `Analyze my spending for 2026-10` | Exact totals/categories and descriptive anomaly flags |
| Transfers | `Transfer 20 CNY to Bob` | Proposal first; money changes only after approval |
| Subscriptions | `List my subscriptions` | Recurring evidence stays distinct from verified stored records |
| Simulated cancellation | `Cancel iQIYI VIP Monthly` | Approval required; stored cancellation persists |
| Ordered plan | `Cancel iQIYI VIP Monthly then transfer 45 CNY to Bob` | Cancellation first, then a separately approved transfer |

Yellow mutations require confirmation. Transfers crossing the **CNY 1,000
cumulative daily threshold** require Red confirmation plus a simulated six-digit
OTP, shown in the demo inbox. Daily totals use Asia/Shanghai dates. Cancellation
does not refund or credit money. The ordered example requires an active supported
subscription and sufficient balance.

**Cancel approval** withdraws a pending ticket, including one awaiting MFA.
P1's `pause plan`, `resume plan`, and `stop plan` control plan progression; they
do not themselves revoke already-issued tickets or reverse completed operations.

Three verification failures within the fixed 15-minute observation window trigger
a persistent safety lock. Reads remain available; a reviewed manual reset is
required. See [safety-lock instructions](docs/app/safety_lock.md).

## Conversation history

The sidebar supports new chats and saved conversations. Messages and proposal
cards are stored server-side; refreshing restores the selected conversation
and its current action statuses. Loading history never executes an action.
Browser storage retains only the selected conversation ID. On the hosted demo,
authorized visitors share the same synthetic identity and history.

## Source layout

```text
agent/             P1 intent interpretation and bounded planning
backend/           P2 FastAPI, persistence, approvals, adapters, migrations, tests
frontend/          P2 React/Vite/TypeScript interface and frontend tests
finance/           P3 deterministic spending analytics
security/          P4 pure permission-tier policy
subscriptions/     P5 recurring-charge detection and eligibility
contracts/         Shared executable models, tool schemas, and generated schemas
fixtures/          Frozen synthetic test datasets
infra/             Local Docker, Nginx, and shared-host gateway/entry point
docs/              Module documentation; current app guides are in docs/app/
tests/             Shared contract tests
```

Each teammate owns their module and corresponding documentation folder. P2 owns
the application/integration paths and Compose configuration. Shared contract and
fixture changes require coordination with the contract maintainer. Executable
`contracts/` definitions supersede conflicting details in the preliminary Word
draft; Python money is `Decimal`, JSON money is serialized as strings, and
transaction timestamps are timezone-aware.

## Verification and limits

Run the [verification commands](docs/app/deployment.md#verification) against the
exact candidate commit. Python tests cover the agent, contracts, analytics,
subscriptions, migrations, approvals/MFA, cancellation and concurrency. PostgreSQL
tests require a separate disposable database; otherwise those cases are skipped.
Frontend checks are `npm test` and `npm run build` inside `frontend/`.

This remains a local prototype: demo-header identity is not production login,
recipient context is synthetic, MFA/merchant cancellation are simulated, and
planning supports a bounded two-step chain. The `human takeover` phrase only
pauses an active plan and directs the user to the team; there is no staff handoff
workflow. Completed operations are not automatically reversed. Full decision/control
auditing, malformed stored-transaction handling, and extreme
year validation remain documented limitations, not implemented guarantees.

Current deployment, behavior, and module documentation:

- [Deployment and local development](docs/app/deployment.md)
- [Database upgrades and preservation](docs/app/database_migrations.md)
- [Execution safety and concurrency](docs/app/execution_safety.md)
- [Safety locks and operator reset](docs/app/safety_lock.md)
- [Approval cancellation](docs/app/approval_cancellation.md)
- [Trusted agent continuation](docs/app/agent_continuation.md)
- [Frontend metadata contract](docs/app/frontend_metadata_transport.md)
- [Broader requirement coverage and limits](docs/app/broader_requirements_review.md)
- [Agent integration contract](docs/agent/integration.md)
- [Finance calculation rules](docs/finance/RULES.md)
- [Simulated MFA behavior and demo](docs/finance/MFA.md)
- [Security threat model](docs/security/threat_model.md)
- [Subscription detection and eligibility](docs/subscriptions/README.md)

- [Shared hosted deployment](docs/app/free_shared_deployment.md)
- [Technical documentation](docs/agent/technical_documentation.md)

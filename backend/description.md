# Description of /backend

Here is a straightforward breakdown of how each file works, how they connect together.

---

### 1. Folder & File Breakdown and How They Connect

The backend follows a standard layered architecture: **API Layer (HTTP) $\rightarrow$ Service/Adapter Layer $\rightarrow$ Data & Mock Layer**.

```
HTTP Request (Client)
       │
       ▼
[main.py]  (FastAPI app & global error handling)
       │
       ├─► [api/deps.py]        ── Resolves authenticated demo user & DB session
       │
       ├─► [api/health.py]      ── Health checks (/api/v1/health)
       ├─► [api/accounts.py]    ── Queries [db/models.py] via [db/session.py]
       ├─► [api/transactions.py]── Queries [db/models.py] via [db/session.py]
       └─► [api/chat.py]        ── Calls [services/adapters.py]
                                         │
                                         ▼
                                  [mocks/agent.py] (Simulates P1 Agent)
```

---

#### **Folder: `backend/app/` (Core Application)**
* **`config.py`**:
  * **What it does:** Reads environment variables (or `.env`) using Pydantic Settings. Holds app configurations like `DATABASE_URL`, API prefix (`/api/v1`), and the default demo user ID (`usr_demo_01`).
  * **Connections:** Imported by `session.py`, `deps.py`, and `main.py`.

* **`main.py`**:
  * **What it does:** The **application entrypoint and composition root**. It initializes the FastAPI app, adds CORS middleware, sets up global error handling (returning canonical `ErrorResponse`), and registers all sub-routers (`/health`, `/accounts`, `/transactions`, `/chat`).
  * **Connections:** Glues the API routers together into one runnable web server.

---

#### **Folder: `backend/app/api/` (Presentation / HTTP Endpoints)**
* **`deps.py`**:
  * **What it does:** FastAPI dependencies for authentication and database sessions. It extracts `X-Demo-User-Id` from the request header (defaulting to `usr_demo_01`) and queries the database to ensure the user exists. 
  * **Why it matters:** Per spec, `ChatInput` does not pass `user_id`. Identity is resolved strictly server-side.
  * **Connections:** Injected via `Depends(get_current_user)` into `accounts.py`, `transactions.py`, and `chat.py`.

* **`health.py`**:
  * **What it does:** Implements `GET /api/v1/health` $\rightarrow$ `{"status": "ok"}`.
  * **Connections:** Used by health checks, Docker container probes, and monitoring.

* **`accounts.py`**:
  * **What it does:** Implements `GET /api/v1/accounts`. Queries the user's bank accounts and returns balances formatted as string decimals (`Decimal`).
  * **Connections:** Uses `deps.py` for user context and `db/models.py` to query the database.

* **`transactions.py`**:
  * **What it does:** Implements `GET /api/v1/transactions?period=YYYY-MM`. Queries transaction history for the user and filters by year-month.
  * **Connections:** Uses `deps.py`, queries `TransactionModel`, and formats output into `contracts.models.Transaction`.

* **`chat.py`**:
  * **What it does:** Implements `POST /api/v1/chat`. Accepts user messages (`ChatInput`), delegates processing to `agent_service`, and returns proposed actions (`ChatOutput`).
  * **Crucial constraint:** Chat generates *proposals only* (`PROPOSED`), never executing money movement.

---

#### **Folder: `backend/app/db/` (Persistence & Database)**
* **`session.py`**:
  * **What it does:** Creates the SQLAlchemy 2.0 database engine and `SessionLocal` factory. Provides the `get_db()` dependency generator.
  * **Connections:** Used by `deps.py`, `seed.py`, and API route handlers.

* **`models.py`**:
  * **What it does:** Defines database tables (`UserModel`, `AccountModel`, `TransactionModel`, `AuditLogModel`). Money values use `Numeric(18, 2)` to prevent binary floating-point errors.
  * **Connections:** Used by `seed.py` to populate data, and queried by `accounts.py` and `transactions.py`.

* **`seed.py`**:
  * **What it does:** Standalone script that resets tables and seeds deterministic synthetic data (demo user `usr_demo_01`, account `acc_cny_001` with `15250.00 CNY`, and sample transactions for dining, income, and recurring subscriptions).
  * **Connections:** Populates the tables defined in `models.py`.

---

#### **Folder: `backend/app/mocks/` & `services/` (Swappable Team Stubs)**
* **`mocks/agent.py`**:
  * **What it does:** A mock implementation of Person 1's Agent. Instead of calling real LLMs, it inspects keywords (like `"transfer"` or `"balance"`) and deterministically returns a contract-compliant `AgentResult` with proposals.
  * **Connections:** Called exclusively by `adapters.py`.

* **`services/adapters.py`**:
  * **What it does:** The **integration bridge**. Right now it points to `MockAgentAdapter`. Later, when Person 1 finishes `agent/service.py`, you flip `use_mock = False` in this single file without touching any API route code.

---

#### **Folder: `backend/tests/` (Verification)**
* **`conftest.py`**:
  * **What it does:** Pytest configuration. Spins up an isolated, temporary in-memory SQLite database, seeds it, and overrides FastAPI's `get_db` dependency to use test data.
  * **Connections:** Injected automatically into tests.

* **`test_milestone1.py`**:
  * **What it does:** Executes 4 test cases verifying:
    1. `/health` responds with `{"status": "ok"}`.
    2. `/accounts` returns the correct seeded balance (`15250.00`).
    3. `/transactions?period=2026-10` properly filters October transactions.
    4. `/chat` returns a `PROPOSED` status for transfer intent.
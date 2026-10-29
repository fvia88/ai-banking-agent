# P4 Security Self-Assessment & Integration Readiness (Milestone 07 / Phase B4 — Final Readiness)

**Owner**: Person 4 (Finance Risk & Security Engineering)
**Branch**: `feature/security`
**Shared Contracts Version**: 1.0.0
**Related Documents**:
- [README.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/README.md) — Module overview (84 unit tests, 27 bridge tests, 16 integration tests, 6/6 concurrency tests)
- [threat_model.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/threat_model.md) — STRIDE & OWASP LLM threat analysis, code sandbox boundaries, and audit trail
- [security_assessment.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/security_assessment.md) — Pure policy engine assessment
- [integration_guide.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/integration_guide.md) — Recommended backend integration guide
- [integration_test_matrix.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/integration_test_matrix.md) — Detailed scenario-by-scenario policy vs. runtime test matrix

---

## 1. P4 Scope and Security Architecture

Person 4 owns the deterministic authorization boundary between untrusted AI-generated tool proposals (`ActionProposal`) and state-changing banking operations:

1. **Core Policy Engine** (`security/policy.py`, `security/rules.py`, `security/__init__.py`):
   - Exports `evaluate_action(proposal: ActionProposal, context: BankingContext, config: PolicyConfig = DEFAULT_CONFIG) -> PolicyDecision`.
   - Designed as a **pure, side-effect-free, fail-closed** function that never mutates inputs, performs no I/O, and never raises unhandled exceptions to callers.
2. **Backend Security Adapter Bridge** (`backend/app/services/adapters.py:143-166`):
   - Connects `SecurityAdapterService` (`policy_service`) to `security.policy.evaluate_action` by default (`USE_MOCK_SECURITY` defaults to `"false"` when unset at `backend/app/services/adapters.py:151`), while preserving `MockSecurityAdapter` only when `use_mock=True` or `USE_MOCK_SECURITY=true` is explicitly configured.
   - `MockAgentAdapter` (`backend/app/mocks/agent.py:70,133,164`) supplies `source_account_id`, enabling the real P4 security policy engine to run by default across both mock-agent and real-agent workflows.
3. **Security Test Suites & Regression Evidence**:
   - `security/tests/test_policy.py` — **84 passed** in 0.79s covering all fixture cases, exact boundary limits, and adversarial vectors.
   - `backend/tests/test_security_bridge.py` — **27 passed** in 0.50s covering default real mode (`USE_MOCK_SECURITY=false`), strict env/constructor validation, service-level reason codes, differential HTTP spoofing rejection, and end-to-end HTTP integration with P1's real agent.
   - `backend/tests/test_security_integration.py` — **16 passed** in 0.89s covering sequential HTTP policy enforcement at `/chat`, `/confirm`, and `/verify`, sequential Yellow-to-Red escalation, post-proposal account locking, stored payload tampering rejection, and locked balance reads.
   - `backend/tests/test_security_concurrency.py` — **6 passed, 6 skipped** in 13.31s covering duplicate execution prevention, cumulative daily threshold escalation, account overspending prevention, mixed confirm/verify reconciliation, and Shanghai banking day rollover on file-backed SQLite. (PostgreSQL tests skip cleanly when `MIGRATION_TEST_POSTGRES_ADMIN_URL` is unset).
   - `backend/tests/test_mfa.py` — **18 passed** in 1.36s covering OTP challenge lifecycle, brute-force lockout, post-confirm lock enforcement, and single-action `/verify` race protection.
   - `tests/test_contracts.py` — **14 passed** in 0.34s verifying schema constraints and fixtures.
   - Broader backend suite (`backend/tests`) — **238 passed, 22 skipped** in 28.58s.

> [!NOTE]
> **Environment Verification Caveat**: All concurrency and row-locking tests have been executed and verified against file-backed SQLite databases (`sqlite:///` under `pytest` `tmp_path`). PostgreSQL concurrency has **not been verified** due to the absence of a configured PostgreSQL test service (`MIGRATION_TEST_POSTGRES_ADMIN_URL`).

---

## 2. Permission Tiers and Fail-Closed Behavior

`evaluate_action` (`security/policy.py:28-161`) executes a strict 6-step evaluation pipeline:

| Step | Check Performed | Failure Outcome (`PolicyDecision`) | Code Reference |
| :---: | :--- | :--- | :--- |
| **1** | Input object type validation (`isinstance(proposal, ActionProposal)`, `isinstance(context, BankingContext)`) | `Tier.RED`, `allowed_to_proceed=False`, `INVALID_PROPOSAL` or `INVALID_CONTEXT` | `policy.py:58-63` |
| **2** | Tool whitelist check against `contracts.enums.ToolName` | `Tier.RED`, `allowed_to_proceed=False`, `UNKNOWN_TOOL` | `policy.py:65-71` |
| **3** | Canonical schema validation via `validate_tool_arguments(tool, proposal.arguments)` | `Tier.RED`, `allowed_to_proceed=False`, `INVALID_TOOL_ARGUMENTS` | `policy.py:73-83` |
| **4** | Account lock check (`context.account_locked` on mutation tools, or read-only tools if `config.lock_denies_read_only=True`) | `Tier.RED`, `allowed_to_proceed=False`, `ACCOUNT_LOCKED` | `policy.py:85-89` |
| **5** | Account ownership check (`source_account_id == context.account_id` or `account_id == context.account_id`) | `Tier.RED`, `allowed_to_proceed=False`, `SOURCE_ACCOUNT_MISMATCH` or `ACCOUNT_MISMATCH` | `policy.py:91-103` |
| **6** | Risk tier classification (`GREEN`, `YELLOW`, `RED`) using `Decimal` arithmetic (`context.daily_transfer_total + amount <= 1000.00`) | Deterministic `PolicyDecision`; any unhandled tool returns `UNKNOWN_TOOL` | `policy.py:105-156` |
| **Guard** | Top-level `except Exception` catch-all | `Tier.RED`, `allowed_to_proceed=False`, `INTERNAL_POLICY_ERROR` | `policy.py:158-161` |

### Tier Taxonomy
- **`Tier.GREEN`** (`allowed_to_proceed=True, requires_confirmation=False, requires_mfa=False, reason_code="READ_ONLY_ACCESS"`): `get_balance`, `analyze_spending`, `list_subscriptions`.
- **`Tier.YELLOW`** (`allowed_to_proceed=True, requires_confirmation=True, requires_mfa=False`):
  - `request_transfer` where `context.daily_transfer_total + amount <= Decimal("1000.00")` (`TRANSFER_WITHIN_DAILY_LIMIT`).
  - `request_subscription_cancel` (`SUBSCRIPTION_CANCEL_CONFIRMATION_REQUIRED`).
- **`Tier.RED` (Approval + MFA Required)** (`allowed_to_proceed=True, requires_confirmation=True, requires_mfa=True, reason_code="TRANSFER_EXCEEDS_DAILY_LIMIT"`):
  - `request_transfer` where `context.daily_transfer_total + amount > Decimal("1000.00")`.
- **`Tier.RED` (Fail-Closed Rejection)** (`allowed_to_proceed=False, requires_confirmation=False, requires_mfa=False`):
  - Returned on any policy violation, schema failure, account lock, ownership mismatch, or internal error.

---

## 3. Strict Argument Validation and Account Ownership Checks

### A. Canonical Schema Validation (`contracts/tool_schemas.py`)
All 5 whitelisted tools are validated via Pydantic models inheriting from `StrictModel` (`ConfigDict(extra="forbid", use_enum_values=False, validate_assignment=True)` in `contracts/models.py:15-16`):
- **Monetary bounds**: `PositiveMoney` enforces `Decimal` with `gt=0, max_digits=16, decimal_places=2`. Rejects negative amounts (`-1.00`), zero (`0.00`, `-0.00`), sub-cent precision (`100.999`), $>16$ digits (`999999999999999.00`), and non-finite strings (`NaN`, `Inf`, `-Inf`).
- **Currency**: `Literal["CNY"] = "CNY"`. Rejects `"USD"`, lowercase `"cny"`, and whitespace-padded `"CNY "`.
- **Identifier bounds**: `ID` enforces `min_length=1, max_length=128` across `account_id`, `source_account_id`, `recipient_id`, and `subscription_id`. Rejects `None`, `""`, and strings of length $\ge 129$.
- **Extra field rejection (`extra="forbid"`)**: Rejects adversarial flags (`bypass_mfa`, `mfa_verified`, `admin`, `force_immediate`, `user_id`) as well as server approval metadata (`action_id`, `action_digest`, `tier`) if injected into `proposal.arguments`.
- **Prompt injection immunity**: `proposal.rationale` is never consulted for tier classification or authorization (`test_t09_prompt_injection_in_rationale_ignored`).

### B. Account Ownership & Runtime Enforcement
- **Transfers (`request_transfer`)**: `TransferArgs` requires `source_account_id: ID`. Step 5 of `evaluate_action` checks `validated_args.source_account_id != context.account_id` and rejects mismatches with `SOURCE_ACCOUNT_MISMATCH`. In `backend/app/services/actions.py:36-59`, `create_action_record` validates tool arguments, evaluates `policy_service.evaluate(canonical, context)`, and persists only canonical arguments in `ActionApprovalModel.payload_json`.
- **Read-only queries (`get_balance`, `analyze_spending`, `list_subscriptions`)**: All three schemas require `account_id: ID`. Step 5 checks `validated_args.account_id != context.account_id` and rejects mismatches with `ACCOUNT_MISMATCH`. In `backend/app/api/chat.py:109-129`, read tools validate arguments and invoke `policy_service.evaluate(proposal, read_context)` before querying data, while allowing locked users to read balances under the default policy (`test_locked_balance_read_still_calls_real_p4`).
- **Execution-Time Re-Evaluation (`_current_policy`)**: In `backend/app/api/approvals.py:80-164`, both `confirm_action` and `verify_action` reconstruct the proposal from stored `payload_json`, verify `action_digest` (`test_stored_payload_tampering_blocks_execution`), refresh user/account rows, and re-invoke `policy_service.evaluate(proposal, context)` (`test_confirm_rechecks_real_policy_and_replays_without_new_debit`, `test_new_lock_blocks_yellow_confirm`, `test_two_pending_yellow_actions_escalate_after_first_executes`, `test_policy_rejection_at_verify_cannot_be_overridden_by_correct_otp`).

---

## 4. Adapter Bridge and Verified Test Evidence

### A. Phase A Adapter Bridge (`backend/app/services/adapters.py`)
`SecurityAdapterService` (`adapters.py:143-166`) implements hardened configuration parsing:
- Explicit `use_mock` must be a `bool` (`isinstance(use_mock, bool)`) or `None`; non-boolean values raise `ValueError`.
- When `use_mock is None`, `USE_MOCK_SECURITY` is read from the environment and **defaults to `"false"` when unset**, selecting the real security policy engine by default. Only case-insensitive `"true"` and `"false"` are accepted; any other value raises `ValueError`.
- When `self.use_mock is False`, `evaluate()` imports and delegates directly to `security.policy.evaluate_action(proposal, context)`.

### B. Verified Test Suite Results (Step 2 Audit)
All test suites were executed sequentially from the repository root with `$env:PYTHONPATH="backend;.;contracts"`:

| Test Suite | Command | Exit Code | Verified Pytest Result |
| :--- | :--- | :---: | :--- |
| **P4 Security Policy Unit & Fixture Tests** | `.\.venv\Scripts\python.exe -m pytest security/tests/test_policy.py -v` | `0` | **84 passed** in 0.79s |
| **P4 Security Adapter & HTTP Bridge Tests** | `.\.venv\Scripts\python.exe -m pytest backend/tests/test_security_bridge.py -v` | `0` | **27 passed** in 0.50s |
| **P2/P4 HTTP Security Integration Tests** | `.\.venv\Scripts\python.exe -m pytest backend/tests/test_security_integration.py -v` | `0` | **16 passed** in 0.89s |
| **P4 Concurrency Regression Tests** | `.\.venv\Scripts\python.exe -m pytest backend/tests/test_security_concurrency.py -v` | `0` | **6 passed, 6 skipped** in 13.31s (SQLite verified; PostgreSQL skipped) |
| **P3 MFA Lifecycle & Same-Action Race Tests** | `.\.venv\Scripts\python.exe -m pytest backend/tests/test_mfa.py -v` | `0` | **18 passed** in 1.36s |
| **Shared Contracts Tests** | `.\.venv\Scripts\python.exe -m pytest tests/test_contracts.py -v` | `0` | **14 passed** in 0.34s |
| **Full Combined Backend Suite** | `.\.venv\Scripts\python.exe -m pytest backend/tests -q` | `0` | **238 passed, 22 skipped** in 28.58s |

---

## 5. Reconciliation of Concurrency Implementations and Execution Safety

Earlier revisions of this document recorded `3 failed` for an older version of the concurrency regression tests on file-backed SQLite (historical result, not re-run here). Since then, P2 landed the execution guard (`execute_claimed_action` in `backend/app/services/action_execution.py`), exclusive row locks (`with_for_update()`), and Shanghai midnight day rollover (`backend/app/services/daily_transfers.py`).

Fresh execution of the current `backend/tests/test_security_concurrency.py` on HEAD (since commit `4ab698a` / current HEAD `0fbc25d`) shows that the 3 previously reported defect scenarios are **not reproduced on file-backed SQLite**:

1. **Duplicate Concurrent Yellow Confirmations (Previously Defect 1 / RR-01)**:
   - *Status*: **NOT REPRODUCED (SQLite)** (`test_same_yellow_action_cannot_execute_twice[sqlite]` **PASSED**).
   - *Mechanism*: `execute_claimed_action` claims the action record under an exclusive row lock before calling `_execute_action`. Two simultaneous confirmations result in exactly 1 transfer ledger record (`tx_count=1`) and 1 execution audit (`audit_count=1`). The racing request either receives an idempotent replay with identical `audit_id` or an HTTP `409 Conflict`.
2. **Concurrent Transfers Competing for Daily Threshold (Previously Defect 2 / RR-02)**:
   - *Status*: **NOT REPRODUCED (SQLite)** (`test_competing_yellow_actions_cannot_bypass_cumulative_mfa[sqlite]` **PASSED**).
   - *Mechanism*: `execute_claimed_action` serializes account access with `with_for_update()`. The second 600 CNY transfer evaluates `_current_policy` against the fresh committed `daily_transfer_total = 600.00`, detects `600 + 600 = 1200 > 1000`, escalates to `Tier.RED` (`PENDING_MFA`), logs `ESCALATED_TO_RED` and `MFA_CHALLENGE_ISSUED`, and transfers zero funds without MFA.
3. **Concurrent Transfers Exceeding Account Balance (Previously Defect 3 / RR-03)**:
   - *Status*: **NOT REPRODUCED (SQLite)** (`test_competing_yellow_actions_cannot_overspend_account[sqlite]` and `test_competing_red_verifications_cannot_overspend_account[sqlite]` **PASSED**).
   - *Mechanism*: Row locking ensures only affordable transfers execute. When available balance is insufficient, `execute_transfer` raises `HTTPException 400`, rolls back all partial writes, and retires the action to `FAILED` without debits.
4. **Shanghai Banking Day Rollover Under Concurrency**:
   - *Status*: **VERIFIED (SQLite)** (`test_first_concurrent_transfers_of_new_day_reset_once[sqlite]` **PASSED**).
   - *Mechanism*: `daily_transfers.prepare_day` detects calendar day changes in GMT+8, emits exactly 1 `DAILY_TRANSFER_TOTAL_RESET` audit log, and correctly tracks the new day's initial total.

> [!WARNING]
> **PostgreSQL Concurrency Remains Unverified**: All 6 PostgreSQL test variants in `backend/tests/test_security_concurrency.py` skip cleanly (`SKIPPED: Set MIGRATION_TEST_POSTGRES_ADMIN_URL for disposable PostgreSQL race tests`). PostgreSQL concurrency and row locking under load have not been verified in this environment.

---

## 6. Decision and Control Audit Event Coverage

The backend implementation follows an application-level append-only logging pattern through `AuditLogModel` (database-level or cryptographic immutability is not enforced) and emits 12 explicit action types:

1. `TRANSFER_EXECUTED_ATOMIC`: Atomic database execution of transfers.
2. `SUBSCRIPTION_CANCELLED`: Confirmed cancellation of recurring subscriptions.
3. `ACTION_POLICY_REJECTED`: Execution-time policy refusal during confirmation or verification.
4. `ESCALATED_TO_RED`: Dynamic escalation when cumulative daily transfers cross CNY 1,000.00.
5. `MFA_CHALLENGE_ISSUED`: Generation and issuance of OTP challenge for Red actions.
6. `APPROVAL_CANCELLED_BY_USER`: Explicit cancellation of pending actions by user.
7. `VERIFICATION_FAILURE`: Wrong OTP code or confirmation digest mismatch attempts.
8. `SAFETY_LOCK_TRIGGERED`: Automatic account safety lockout after 3 verification failures.
9. `SAFETY_LOCK_RESET`: Authorized demo-operator reset of an account safety lock.
10. `ACTION_REJECTED_SAFETY_LOCK`: Automatic retirement of pending approvals when safety lock trips.
11. `DAILY_TRANSFER_TOTAL_RESET`: Shanghai midnight banking-day daily total rollover.
12. `ACTION_STATUS_OBSERVED`: Agent continuation observation of terminal action state.

### Identified Audit Gaps
- **Initial Proposal Generation**: Action proposals generated during `POST /api/v1/chat` insert rows into `ActionApprovalModel`, but do not create records in `AuditLogModel`.
- **Read-Only Authorizations**: Query actions (`get_balance`, `analyze_spending`, `list_subscriptions`) are authorized and executed without `AuditLogModel` entries.
- **Plan Lifecycle Events**: Plan pause, stop, or operator handoff events do not exist and are not audited.

---

## 7. Human Takeover and Generated-Code Sandbox Scope Exclusions

> [!NOTE]
> The team has formally confirmed that **Human Takeover and additional feature development are out of scope for now**. The sections below document the architectural boundaries of the current implementation.

### 7.1 Human Takeover Status
Bank.ly does NOT implement a general human takeover queue, operator-assigned review workflow, or ticket routing system; this capability has been formally confirmed as out of scope for the current release. The sole human intervention mechanism is `reset_safety_lock` in `backend/app/services/safety_lock.py`, which permits a local demo operator to reset an automatic lockout with a mandatory review reason (1-200 chars). This is an administrative lock-clear function and must not be characterized as a general human takeover queue.

### 7.2 Arbitrary Generated-Code Sandboxing
The Bank.ly AI Banking Agent does NOT execute arbitrary generated code (no Python `eval`/`exec`, no shell commands, no script interpreter). The LLM's agency is strictly confined to generating structured tool proposals (`ActionProposal`) matching a frozen whitelist of five tools (`ToolName`). Arguments are strictly validated by Pydantic models with `extra="forbid"`.

> [!IMPORTANT]
> **Typed tool whitelisting is NOT an arbitrary generated-code sandbox.**
> No operating-system-level sandbox (such as gVisor, Firecracker, or container isolation per invocation) is implemented in Bank.ly. Runtime OS sandboxing is out of scope; the architecture prevents unauthorized actions via schema validation and pure policy evaluation, not via runtime execution sandboxing of untrusted code.

---

## 8. Residual Risks, Mitigations, and Owners

| Risk ID | Residual Risk Description | Current Mitigation & Verification | Owner | Status |
| :--- | :--- | :--- | :---: | :---: |
| **RR-01** | Duplicate concurrent Yellow `/confirm` requests on the same `action_id` execute twice | Exclusive row locking in `execute_claimed_action` ensures at most 1 execution (`test_same_yellow_action_cannot_execute_twice[sqlite]`). | P2 (Runtime) / P4 (Test) | **PASS (SQLite)** / **NOT VERIFIED (PostgreSQL)** |
| **RR-02** | Concurrent Yellow transfers bypass cumulative daily threshold without MFA | Account locking in `execute_claimed_action` serializes `_current_policy`, escalating to `PENDING_MFA` with audit logs (`test_competing_yellow_actions_cannot_bypass_cumulative_mfa[sqlite]`). | P2 (Runtime) / P4 (Test) | **PASS (SQLite)** / **NOT VERIFIED (PostgreSQL)** |
| **RR-03** | Concurrent transfers exceeding balance overdraw account or lose ORM updates | Account serialization in `execute_claimed_action` and conditional debit in `execute_transfer` (`test_competing_yellow_actions_cannot_overspend_account[sqlite]`). | P2 (Runtime) / P4 (Test) | **PASS (SQLite)** / **NOT VERIFIED (PostgreSQL)** |
| **RR-04** | Concurrency behavior has only been tested on file-backed SQLite, not PostgreSQL | Disposable PostgreSQL tests are implemented in `test_security_concurrency.py`, but skipped due to missing environment (`MIGRATION_TEST_POSTGRES_ADMIN_URL`). | P2 / P4 | **NOT VERIFIED** |
| **RR-05** | Cross-account read-only rejection (`ACCOUNT_MISMATCH`) not separately parameterized over HTTP in `test_security_integration.py` | Enforced in `security/policy.py` unit tests and wired in `chat.py:114-129`; `GET_BALANCE` locked read tested over HTTP. | P2 / P4 | **PARTIAL** |

---

## 9. Clear Separation of Work Status and Acceptance Recommendation

### Implemented and Verified by Passing Automated Tests
- **Pure, fail-closed policy evaluation (`security/policy.py`, `security/rules.py`)**: Implemented by P4 and verified by **84 passed** tests in `security/tests/test_policy.py`.
- **Strict contract schema validation (`contracts/tool_schemas.py`, `contracts/models.py`)**: Verified by **14 passed** tests in `tests/test_contracts.py` and **84 passed** tests in `security/tests/test_policy.py`.
- **Default-real `SecurityAdapterService` bridge (`backend/app/services/adapters.py`)**: `USE_MOCK_SECURITY` defaults to `"false"` when unset; verified by **27 passed** tests in `backend/tests/test_security_bridge.py`, **16 passed** tests in `backend/tests/test_security_integration.py`, and **238 passed** tests across `backend/tests`.
- **Sequential execution-time policy re-evaluation, sequential Yellow-to-Red escalation, post-proposal account-lock enforcement, stored payload digest verification, and locked balance read access**: Verified by **16 passed** tests in `backend/tests/test_security_integration.py` and **18 passed** tests in `backend/tests/test_mfa.py`.
- **Concurrency safety on file-backed SQLite**: Verified by **6 passed** tests in `backend/tests/test_security_concurrency.py`.
- **Single-action Red MFA challenge lifecycle and same-action `/verify` atomic claim**: Verified by **18 passed** tests in `backend/tests/test_mfa.py`.
- **Shanghai banking day rollover lifecycle**: Verified by `test_first_concurrent_transfers_of_new_day_reset_once[sqlite]`.

### Unverified or Out-of-Scope Areas (Clear Boundary Demarcation)
- **PostgreSQL Concurrency Verification**: Skipped in automated test runs due to absent PostgreSQL test environment (`MIGRATION_TEST_POSTGRES_ADMIN_URL`). Remains **NOT VERIFIED**.
- **Initial Proposal & Read Authorization Auditing**: Proposals and read actions are not recorded in `AuditLogModel` (owned by P2 in `backend/app/api/chat.py`).
- **Database-Level Audit Immutability**: The application follows an append-only logging pattern; database-level or cryptographic immutability is not enforced.
- **Human Takeover Queue**: Not implemented; formally confirmed by the team as out of scope for the current release.
- **Arbitrary Generated-Code Sandboxing**: Not implemented (typed tool whitelisting is used instead); runtime OS sandboxing is out of scope.

### Final P4 Acceptance Recommendation

#### A. Competition Submission & Demo Readiness: READY
- All P4-owned deliverables (`security/policy.py`, `security/rules.py`, `security/tests/test_policy.py`, `backend/tests/test_security_bridge.py`, `backend/tests/test_security_concurrency.py`, and `docs/security/*`) are implemented, conform to frozen contracts v1.0.0, and pass in all runnable automated suites in the test environment (336 unique passing test items repository-wide = 84 + 14 + 238; the bridge, integration, and concurrency suites are subsets of the 238 backend tests; 22 backend tests skipped, all PostgreSQL-only).
- The core security policy engine, risk tiers, daily transfer limits, execution guard, and MFA challenge lifecycle are verified on file-backed SQLite, satisfying all functional requirements for competition submission and demonstration.
- Team-confirmed scope exclusions (Human Takeover Queue and runtime OS sandboxing) are documented as current scope boundaries.

#### B. Production Deployment Readiness: CONDITIONALLY READY (Pre-Production Prerequisites Outstanding)
Production deployment cannot be declared based on passing SQLite test suites alone. The following prerequisites remain outstanding before any production release:
1. **PostgreSQL Concurrency Under Load**: Multi-session concurrency, transaction serialization, and row-locking under real PostgreSQL must be verified by running the 6 skipped concurrency tests in a staging environment with `MIGRATION_TEST_POSTGRES_ADMIN_URL` configured.
2. **Audit Logging Enhancements**: Team acceptance or remediation of the documented audit coverage boundaries (initial proposal creation in `POST /api/v1/chat` and read-only query authorizations do not emit `AuditLogModel` records; database-level tamper-proofing/immutability is not enforced).

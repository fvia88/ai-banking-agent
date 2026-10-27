# P4 Security Self-Assessment & Integration Readiness (Milestone 07 / Phase B4)

**Owner**: Person 4 (Finance Risk & Security Engineering)  
**Branch**: `feature/security`  
**Shared Contracts Version**: 1.0.0  
**Related Documents**:
- [README.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/README.md) — Module overview (Milestone 03 baseline; reports the earlier 39-test count prior to Phase B3 expansion to 84 tests)
- [threat_model.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/threat_model.md) — STRIDE & OWASP LLM threat analysis
- [security_assessment.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/security_assessment.md) — Pure policy engine assessment (Milestone 03 baseline; reports 39 tests prior to Phase B3 expansion to 84 tests)
- [integration_guide.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/integration_guide.md) — Recommended backend integration guide
- [integration_test_matrix.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/integration_test_matrix.md) — Scenario-by-scenario policy vs. runtime test matrix

---

## 1. P4 Scope and Security Architecture

Person 4 owns the deterministic authorization boundary between untrusted AI-generated tool proposals (`ActionProposal`) and state-changing banking operations:

1. **Core Policy Engine** ([security/policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/policy.py), [security/rules.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/rules.py), [security/__init__.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/__init__.py)):
   - Exports `evaluate_action(proposal: ActionProposal, context: BankingContext, config: PolicyConfig = DEFAULT_CONFIG) -> PolicyDecision`.
   - Designed as a **pure, side-effect-free, fail-closed** function that never mutates inputs, performs no I/O, and never raises unhandled exceptions to callers.
2. **Backend Security Adapter Bridge** ([backend/app/services/adapters.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/adapters.py#L143-L166)):
   - Connects `SecurityAdapterService` (`policy_service`) to `security.policy.evaluate_action` by default (`USE_MOCK_SECURITY` defaults to `"false"` when unset at [backend/app/services/adapters.py:151](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/adapters.py#L151)), while preserving `MockSecurityAdapter` only when `use_mock=True` or `USE_MOCK_SECURITY=true` is explicitly configured.
   - `MockAgentAdapter` ([backend/app/mocks/agent.py:70,133,164](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/mocks/agent.py#L70)) supplies `source_account_id`, enabling the real P4 security policy engine to run by default across both mock-agent and real-agent workflows.
3. **Security Test Suites & Regression Evidence**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py) — **84 passed** (expanded from the Milestone 03 baseline of 39 tests).
   - [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py) — **27 passed** covering default real mode (`USE_MOCK_SECURITY=false`), strict env/constructor validation, service-level reason codes, differential HTTP spoofing rejection, and end-to-end HTTP integration with P1's real agent.
   - [backend/tests/test_security_integration.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py) — **16 passed** covering sequential HTTP policy enforcement at `/chat`, `/confirm`, and `/verify`, sequential Yellow-to-Red escalation, post-proposal account locking, stored payload tampering rejection, and locked balance reads.
   - [backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py) — **18 passed** covering OTP challenge lifecycle, brute-force lockout, post-confirm lock enforcement, and single-action `/verify` race protection on file-backed SQLite.
   - [backend/tests/test_security_concurrency.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_concurrency.py) — **3 failed**, deterministically reproducing three unresolved execution-time concurrency vulnerabilities in P2-owned runtime code on file-backed SQLite.

> [!IMPORTANT]
> **Integration Status Caveat**: While sequential policy enforcement and default real-policy selection (`USE_MOCK_SECURITY=false`) are active and verified by passing tests, **the overall security integration is NOT complete for concurrent production workloads** while the execution-time concurrency vulnerabilities documented in Section 5 remain unresolved in P2-owned runtime code (`backend/app/api/approvals.py` and `backend/app/services/executor.py`). Furthermore, **PostgreSQL concurrency behavior has not been verified.**

---

## 2. Permission Tiers and Fail-Closed Behavior

`evaluate_action` ([security/policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/policy.py#L28-L161)) executes a strict 6-step evaluation pipeline:

| Step | Check Performed | Failure Outcome (`PolicyDecision`) | Code Reference |
| :---: | :--- | :--- | :--- |
| **1** | Input object type validation (`isinstance(proposal, ActionProposal)`, `isinstance(context, BankingContext)`) | `Tier.RED`, `allowed_to_proceed=False`, `INVALID_PROPOSAL` or `INVALID_CONTEXT` | [policy.py:58-63](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/policy.py#L58-L63) |
| **2** | Tool whitelist check against `contracts.enums.ToolName` | `Tier.RED`, `allowed_to_proceed=False`, `UNKNOWN_TOOL` | [policy.py:65-71](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/policy.py#L65-L71) |
| **3** | Canonical schema validation via `validate_tool_arguments(tool, proposal.arguments)` | `Tier.RED`, `allowed_to_proceed=False`, `INVALID_TOOL_ARGUMENTS` | [policy.py:73-83](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/policy.py#L73-L83) |
| **4** | Account lock check (`context.account_locked` on mutation tools, or read-only tools if `config.lock_denies_read_only=True`) | `Tier.RED`, `allowed_to_proceed=False`, `ACCOUNT_LOCKED` | [policy.py:85-89](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/policy.py#L85-L89) |
| **5** | Account ownership check (`source_account_id == context.account_id` or `account_id == context.account_id`) | `Tier.RED`, `allowed_to_proceed=False`, `SOURCE_ACCOUNT_MISMATCH` or `ACCOUNT_MISMATCH` | [policy.py:91-103](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/policy.py#L91-L103) |
| **6** | Risk tier classification (`GREEN`, `YELLOW`, `RED`) using `Decimal` arithmetic (`context.daily_transfer_total + amount <= 1000.00`) | Deterministic `PolicyDecision`; any unhandled tool returns `UNKNOWN_TOOL` | [policy.py:105-156](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/policy.py#L105-L156) |
| **Guard** | Top-level `except Exception` catch-all | `Tier.RED`, `allowed_to_proceed=False`, `INTERNAL_POLICY_ERROR` | [policy.py:158-161](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/policy.py#L158-L161) |

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
All 5 whitelisted tools are validated via Pydantic models inheriting from `StrictModel` (`ConfigDict(extra="forbid", use_enum_values=False, validate_assignment=True)` in [contracts/models.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/contracts/models.py#L15-L16)):
- **Monetary bounds**: `PositiveMoney` enforces `Decimal` with `gt=0, max_digits=16, decimal_places=2`. Rejects negative amounts (`-1.00`), zero (`0.00`, `-0.00`), sub-cent precision (`100.999`), $>16$ digits (`999999999999999.00`), and non-finite strings (`NaN`, `Inf`, `-Inf`).
- **Currency**: `Literal["CNY"] = "CNY"`. Rejects `"USD"`, lowercase `"cny"`, and whitespace-padded `"CNY "`.
- **Identifier bounds**: `ID` enforces `min_length=1, max_length=128` across `account_id`, `source_account_id`, `recipient_id`, and `subscription_id`. Rejects `None`, `""`, and strings of length $\ge 129$.
- **Extra field rejection (`extra="forbid"`)**: Rejects adversarial flags (`bypass_mfa`, `mfa_verified`, `admin`, `force_immediate`, `user_id`) as well as server approval metadata (`action_id`, `action_digest`, `tier`) if injected into `proposal.arguments`.
- **Prompt injection immunity**: `proposal.rationale` is never consulted for tier classification or authorization (`test_t09_prompt_injection_in_rationale_ignored`).

### B. Account Ownership & Sequential Runtime Enforcement
- **Transfers (`request_transfer`)**: `TransferArgs` requires `source_account_id: ID`. Step 5 of `evaluate_action` checks `validated_args.source_account_id != context.account_id` and rejects mismatches with `SOURCE_ACCOUNT_MISMATCH`. In [backend/app/services/actions.py:36-59](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/actions.py#L36-L59), `create_action_record` validates tool arguments, evaluates `policy_service.evaluate(canonical, context)`, and persists only canonical arguments in `ActionApprovalModel.payload_json`.
- **Read-only queries (`get_balance`, `analyze_spending`, `list_subscriptions`)**: All three schemas require `account_id: ID`. Step 5 checks `validated_args.account_id != context.account_id` and rejects mismatches with `ACCOUNT_MISMATCH`. In [backend/app/api/chat.py:109-129](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/chat.py#L109-L129), read tools validate arguments and invoke `policy_service.evaluate(proposal, read_context)` before querying data, while allowing locked users to read balances under the default policy (`test_locked_balance_read_still_calls_real_p4`).
- **Execution-Time Re-Evaluation (`_current_policy`)**: In [backend/app/api/approvals.py:22-89](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L22-L89), both `confirm_action` and `verify_action` reconstruct the proposal from stored `payload_json`, verify `action_digest` (`test_stored_payload_tampering_blocks_execution`), refresh user/account rows, and re-invoke `policy_service.evaluate(proposal, context)` (`test_confirm_rechecks_real_policy_and_replays_without_new_debit`, `test_new_lock_blocks_yellow_confirm`, `test_two_pending_yellow_actions_escalate_after_first_executes`, `test_policy_rejection_at_verify_cannot_be_overridden_by_correct_otp`).

---

## 4. Adapter Bridge and Verified Test Evidence

### A. Phase A Adapter Bridge (`backend/app/services/adapters.py`)
`SecurityAdapterService` ([adapters.py:143-166](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/adapters.py#L143-L166)) implements hardened configuration parsing:
- Explicit `use_mock` must be a `bool` (`isinstance(use_mock, bool)`) or `None`; non-boolean values (`"true"`, `"false"`, `1`, `0`, `""`, lists, dicts) raise `ValueError`.
- When `use_mock is None`, `USE_MOCK_SECURITY` is read from the environment and **defaults to `"false"` when unset**, selecting the real security policy engine by default. Only case-insensitive `"true"` and `"false"` (with no leading/trailing whitespace) are accepted; any other value (`"treu"`, `"1"`, `"0"`, `"yes"`, `""`, `" true"`) raises `ValueError`.
- When `self.use_mock is False`, `evaluate()` imports and delegates directly to `security.policy.evaluate_action(proposal, context)`.

### B. Verified Test Suite Results (Step 2 Audit)
All test suites were executed sequentially from the repository root with `$env:PYTHONPATH="backend;."`:

| Test Suite | Command | Exit Code | Verified Pytest Result |
| :--- | :--- | :---: | :--- |
| **P4 Security Policy Unit & Fixture Tests** | `.\.venv\Scripts\python.exe -m pytest security/tests/test_policy.py -v` | `0` | **84 passed** in 0.80s |
| **P4 Security Adapter & HTTP Bridge Tests** | `.\.venv\Scripts\python.exe -m pytest backend/tests/test_security_bridge.py -v` | `0` | **27 passed** in 0.24s |
| **P2/P4 HTTP Security Integration Tests** | `.\.venv\Scripts\python.exe -m pytest backend/tests/test_security_integration.py -v` | `0` | **16 passed** in 0.60s |
| **P3 MFA Lifecycle & Same-Action Race Tests** | `.\.venv\Scripts\python.exe -m pytest backend/tests/test_mfa.py -v` | `0` | **18 passed** in 1.36s |
| **Shared Contracts Tests** | `.\.venv\Scripts\python.exe -m pytest tests/test_contracts.py -v` | `0` | **14 passed** in 0.33s |
| **Broader Backend Suite (Excl. Concurrency)** | `.\.venv\Scripts\python.exe -m pytest backend/tests --ignore=backend/tests/test_security_concurrency.py -q` | `0` | **133 passed, 7 skipped** in 7.21s |
| **P4 Concurrency Regression Tests** | `.\.venv\Scripts\python.exe -m pytest backend/tests/test_security_concurrency.py -v` | `1` | **3 failed** in 0.53s (reproducing 3 concurrency defects on file-backed SQLite) |

---

## 5. Unresolved Concurrency Vulnerabilities and Remaining Security Risks

While the passing integration and MFA suites verify sequential policy enforcement, they do **not** prove concurrent correctness. All three multi-threaded tests in [backend/tests/test_security_concurrency.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_concurrency.py) currently **fail (`3 failed`)** on file-backed SQLite, demonstrating unresolved concurrency vulnerabilities in P2-owned runtime code ([backend/app/api/approvals.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py) and [backend/app/services/executor.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/executor.py)):

1. **Critical Concurrency Risk 1 (`FAIL / UNFIXED`) — Duplicate Concurrent Yellow `/confirm` Requests Execute Twice**:
   - **Location**: [backend/app/api/approvals.py:117-200](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L117-L200) (`confirm_action`) and [backend/app/services/executor.py:11-79](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/executor.py#L11-L79) (`execute_transfer`).
   - **Reproducing Test**: `backend/tests/test_security_concurrency.py::test_concurrent_duplicate_yellow_confirm_executes_at_most_once` (**FAILED** on file-backed SQLite).
   - **Observed Defect**: Unlike Red `/verify` (which calls `mfa.claim_challenge` before execution), Yellow `/confirm` checks `record.status != ActionStatus.PENDING_CONFIRMATION.value` in Python (`L148`), runs `_current_policy` (`L164`), executes `_execute_action` (`L195`), and only sets `record.status = ActionStatus.COMPLETED.value` (`L197`) at commit time. Two concurrent `/confirm` requests for the same action both execute `execute_transfer`, creating **two ledger transactions (`tx_count=2`)** and **two execution audit entries (`audit_count=2`)** with distinct `audit_id`s.
   - **Ownership**: **P2 (Primary Runtime Owner)** for atomic action claiming and execution serialization; **P4** for security policy invariants and regression test evidence.
2. **Critical Concurrency Risk 2 (`FAIL / UNFIXED`) — Concurrent Yellow Transfers Bypass Cumulative Daily Threshold Without MFA**:
   - **Location**: [backend/app/api/approvals.py:22-89, 164-200](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L22-L89) (`_current_policy`, `confirm_action`) and [backend/app/services/executor.py:29-50](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/executor.py#L29-L50).
   - **Reproducing Test**: `backend/tests/test_security_concurrency.py::test_concurrent_yellow_transfers_cannot_bypass_cumulative_daily_threshold` (**FAILED** on file-backed SQLite).
   - **Observed Defect**: Two concurrent `600.00 CNY` Yellow transfer confirmations on the same account (starting `daily_transfer_total = 0.00 CNY`, threshold = `1,000.00 CNY`) both read the same stale `daily_transfer_total == 0.00 CNY` in `_current_policy`. Both pass as `Tier.YELLOW` (`0.00 + 600.00 <= 1000.00`) and **both complete without MFA** (`statuses=(COMPLETED, COMPLETED)`, `tx_count=2`, `exec_audit_count=2`), bypassing Red-tier MFA enforcement and suffering lost ORM updates on `balance` (`14,650.00 CNY`) and `daily_transfer_total` (`600.00 CNY`).
   - **Ownership**: **P2 (Primary Runtime Owner)** for account-level serialization and atomic state updates (with **P3** if MFA challenge issuance is affected); **P4** for policy escalation semantics and regression test evidence.
3. **Critical Concurrency Risk 3 (`FAIL / UNFIXED`) — Concurrent Transfers Exceeding Available Balance Both Succeed / Lost ORM Updates**:
   - **Location**: [backend/app/services/executor.py:29-50](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/executor.py#L29-L50) (`execute_transfer`) and [backend/app/api/approvals.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py).
   - **Reproducing Test**: `backend/tests/test_security_concurrency.py::test_concurrent_transfers_exceeding_balance_cannot_both_succeed` (**FAILED** on file-backed SQLite).
   - **Observed Defect**: With starting balance `500.00 CNY`, two concurrent `400.00 CNY` transfers both read `account.balance == 500.00 >= 400.00` in `execute_transfer` and **both succeed (`statuses=(COMPLETED, COMPLETED)`, `tx_count=2`, `exec_audit_count=2`)**, causing an overdrawn aggregate transfer amount (`800.00 CNY` transferred from a `500.00 CNY` balance) and lost ORM updates (`balance=100.00`, `daily_total=400.00`).
   - **Cross-Action Red `/verify` Impact**: Because Red `/verify` also invokes `execute_transfer` after `mfa.claim_challenge`, concurrent `/verify` requests across two *different* Red `action_id`s on the same account also depend on P2's account-level serialization to prevent balance overdrafts and lost updates.
   - **Ownership**: **P2 (Primary Runtime Owner)** for account serialization and atomic conditional balance/daily-total updates; **P4** for security requirements and regression test evidence.
4. **Unverified Environment Risk 4 (`NOT VERIFIED`) — PostgreSQL Concurrency Behavior**:
   - All multi-threaded concurrency tests in `backend/tests/test_mfa.py` and `backend/tests/test_security_concurrency.py` were executed against file-backed SQLite. **PostgreSQL concurrency behavior has not been verified.**
5. **Additional Residual Backend / Domain Limitations (Noted in `docs/app/p4_integration.md`)**:
   - `daily_transfer_total` does not yet have an automated calendar-day reset job.
   - Recipient ownership relies on backend-supplied context records; P4's `source_account_id` matching validates sender ownership rather than recipient directory existence.
   - Repeated OTP failure marks the specific action `FAILED` (`test_third_wrong_code_fails_and_correct_code_cannot_recover`), but does not automatically set `UserModel.is_locked = True` across the user account.
   - UI response proposals still carry tracking keys (`action_id`, `action_digest`, `tier`) added after policy evaluation and DB persistence (`chat.py:235-238`).

---

## 6. Ownership Boundaries for Remaining Work

1. **Person 2 (Backend — Primary Owner for Runtime Atomicity & Account Serialization)**:
   - Owns runtime execution and database transaction boundaries in [backend/app/api/approvals.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py) and [backend/app/services/executor.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/executor.py).
   - Responsible for implementing:
     - Atomic action-status claiming in `confirm_action` so concurrent duplicate Yellow `/confirm` requests cannot execute `_execute_action` more than once.
     - Account-level serialization so concurrent `/confirm` (and cross-action `/verify`) requests on the same `AccountModel` evaluate `_current_policy` against fresh committed `daily_transfer_total` and `balance`, escalating to `PENDING_MFA` when `daily_transfer_total + amount > 1000.00 CNY` without debiting first.
     - Atomic balance and `daily_transfer_total` updates in `execute_transfer` (`AccountModel.balance >= amount`) so concurrent transfers cannot overdraw the account or lose updates.
2. **Person 3 (MFA — Owner for OTP Challenge Lifecycle)**:
   - Owns [backend/app/services/mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/mfa.py) and [backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py).
   - Coordinates with P2 if account serialization in `approvals.py` interacts with `mfa.issue_challenge` or `mfa.claim_challenge`.
3. **Person 4 (Security — Owner for Policy Semantics & Regression Evidence)**:
   - Owns [security/policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/policy.py), [security/rules.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/rules.py), [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py), `SecurityAdapterService` in [backend/app/services/adapters.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/adapters.py), [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py), [backend/tests/test_security_concurrency.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_concurrency.py), and `docs/security/*`.
   - Responsible for defining execution-time security invariants, maintaining the concurrency regression suite (`test_security_concurrency.py`), and re-verifying once P2 lands the runtime serialization fixes.

---

## 7. Residual Risks, Mitigations, and Owners

| Risk ID | Residual Risk Description | Proposed Mitigation | Owner | Status |
| :--- | :--- | :--- | :---: | :---: |
| **RR-01** | Concurrent Yellow `/confirm` requests on the same `action_id` execute the same transfer twice (`tx_count=2`, `audit_count=2`) | Atomically claim `ActionApprovalModel` (`PENDING_CONFIRMATION` transition) and serialize execution before calling `_execute_action`. | P2 (Runtime) / P4 (Test) | **FAIL / UNFIXED** (Reproduced in `test_security_concurrency.py`) |
| **RR-02** | Concurrent `600 CNY` Yellow transfers on the same account read stale `daily_transfer_total = 0.00` and both complete without MFA (`1,200 CNY > 1,000 CNY`) | Serialize same-account confirmations before `_current_policy` reads `daily_transfer_total` so the second action escalates to `Tier.RED` / `PENDING_MFA` (or returns `409 Conflict` for retry) without debiting. | P2 (Runtime) / P4 (Test) | **FAIL / UNFIXED** (Reproduced in `test_security_concurrency.py`) |
| **RR-03** | Concurrent `400 CNY` transfers against a `500 CNY` balance both succeed (`800 CNY` debited) and lose ORM updates on `AccountModel` | Serialize account access and enforce atomic conditional debit (`balance >= amount`) in `executor.py` (covering both Yellow `/confirm` and cross-action Red `/verify`). | P2 (Runtime) / P4 (Test) | **FAIL / UNFIXED** (Reproduced in `test_security_concurrency.py`) |
| **RR-04** | Concurrency behavior has only been tested on file-backed SQLite (`tmp_path`), not PostgreSQL | Execute concurrency regression tests against PostgreSQL once P2 lands database serialization. | P2 / P4 | **NOT VERIFIED** |
| **RR-05** | Cross-account read-only rejection (`ACCOUNT_MISMATCH`) is enforced in `security/policy.py` and wired in `chat.py:114-129`, but not separately parameterized over HTTP in `test_security_integration.py` | Add an HTTP test case for mismatched `account_id` on a read-only tool in backend integration tests. | P2 / P4 | **PARTIAL** |

---

## 8. Clear Separation of Work Status

### Implemented and Verified by Passing Automated Tests
- **Pure, fail-closed policy evaluation (`security/policy.py`, `security/rules.py`)**: Implemented by P4 and verified by **84 passed** tests in [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py).
- **Strict contract schema validation (`contracts/tool_schemas.py`, `contracts/models.py`)**: Verified by **14 passed** tests in [tests/test_contracts.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/tests/test_contracts.py) and **84 passed** tests in [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py).
- **Default-real `SecurityAdapterService` bridge (`backend/app/services/adapters.py`)**: `USE_MOCK_SECURITY` defaults to `"false"` when unset; verified by **27 passed** tests in [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py), **16 passed** tests in [backend/tests/test_security_integration.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py), **18 passed** tests in [backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py), and **133 passed, 7 skipped** across the broader `backend/tests` suite.
- **Sequential execution-time policy re-evaluation, sequential Yellow-to-Red escalation, post-proposal account-lock enforcement, stored payload digest verification, and locked balance read access (`backend/app/api/chat.py`, `backend/app/api/approvals.py`)**: Verified by **16 passed** tests in [backend/tests/test_security_integration.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py) and **18 passed** tests in [backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py).
- **Single-action Red MFA challenge lifecycle and same-action `/verify` atomic claim (`backend/app/services/mfa.py`)**: Verified on file-backed SQLite by **18 passed** tests in [backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py).

### Unresolved Runtime Concurrency Defects (`FAIL / UNFIXED` — Owned by P2, Regression Evidence by P4)
- **Duplicate concurrent Yellow `/confirm` execution on the same `action_id`**: Reproduced by `test_concurrent_duplicate_yellow_confirm_executes_at_most_once` (**FAILED** in [backend/tests/test_security_concurrency.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_concurrency.py)).
- **Concurrent Yellow transfers bypassing the `1,000.00 CNY` cumulative daily threshold without MFA**: Reproduced by `test_concurrent_yellow_transfers_cannot_bypass_cumulative_daily_threshold` (**FAILED** in [backend/tests/test_security_concurrency.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_concurrency.py)).
- **Concurrent transfers exceeding available balance and causing lost ORM updates on `AccountModel`**: Reproduced by `test_concurrent_transfers_exceeding_balance_cannot_both_succeed` (**FAILED** in [backend/tests/test_security_concurrency.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_concurrency.py)).
- **PostgreSQL concurrency verification**: **NOT VERIFIED** (all concurrency tests to date have been run against file-backed SQLite).

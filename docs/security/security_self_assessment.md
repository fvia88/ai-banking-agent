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
   - Connects `SecurityAdapterService` (`policy_service`) to `security.policy.evaluate_action` when `use_mock=False` or `USE_MOCK_SECURITY=false`, while preserving `MockSecurityAdapter` when `use_mock=True`.
   - **Important Runtime Default**: In [backend/app/services/adapters.py:151](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/adapters.py#L151), `USE_MOCK_SECURITY` currently defaults to `"true"` for compatibility with `MockAgentAdapter`. Therefore, real policy enforcement is **opt-in** at runtime (`USE_MOCK_SECURITY=false` or `use_mock=False`) until P2 updates `MockAgentAdapter` to supply `source_account_id`.
3. **Security Test Suites**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py) — **84 passing collected test items** (expanded from the Milestone 03 baseline of 39 tests).
   - [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py) — **27 passing collected test items** covering adapter configuration, service-level reason codes, differential HTTP spoofing rejection, and end-to-end HTTP integration with P1's real agent.

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
- **Extra field rejection (`extra="forbid"`)**: Rejects adversarial flags (`bypass_mfa`, `mfa_verified`, `admin`, `force_immediate`) as well as server approval metadata (`action_id`, `action_digest`, `tier`) if injected into `proposal.arguments`.
- **Prompt injection immunity**: `proposal.rationale` is never consulted for tier classification or authorization (`test_t09_prompt_injection_in_rationale_ignored`).

### B. Account Ownership & Tenancy Enforcement vs. Default Mock Policy Behavior
- **Transfers (`request_transfer`)**: `TransferArgs` requires `source_account_id: ID`. Step 5 of `evaluate_action` checks `validated_args.source_account_id != context.account_id` and rejects mismatches with `SOURCE_ACCOUNT_MISMATCH`.
- **Read-only queries (`get_balance`, `analyze_spending`, `list_subscriptions`)**: All three schemas require `account_id: ID`. Step 5 checks `validated_args.account_id != context.account_id` and rejects mismatches with `ACCOUNT_MISMATCH`.
- **Critical Contrast with Default Runtime (`USE_MOCK_SECURITY="true"`)**:
  - Because `USE_MOCK_SECURITY` defaults to `"true"` in [backend/app/services/adapters.py:151](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/adapters.py#L151), the default `MockSecurityAdapter` ([backend/app/mocks/security.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/mocks/security.py)) does **not** reject unknown tools (falling back to `Tier.GREEN` / `READ_ONLY_AUTOMATIC`), does **not** reject extra injected arguments, and does **not** check `source_account_id`.
  - Furthermore, [backend/app/services/actions.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/actions.py#L123-L134) overwrites `source_account_id` with the backend's `source_account_id` *after* calling `policy_service.evaluate(proposal, context)`. Consequently, in default mock mode (`USE_MOCK_SECURITY="true"`), a spoofed `source_account_id="acc_victim_999"` is silently accepted and rewritten into a pending transfer from the user's own account, whereas in opt-in real mode (`USE_MOCK_SECURITY="false"` / `use_mock=False`) it is rejected before `actions.py` can overwrite it (`test_http_chat_differential_proof_mock_allows_vs_real_policy_rejects` in [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py#L338-L408)).

---

## 4. Adapter Bridge and Current Test Evidence

### A. Phase A Adapter Bridge (`backend/app/services/adapters.py`)
`SecurityAdapterService` ([adapters.py:143-166](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/adapters.py#L143-L166)) implements hardened configuration parsing:
- Explicit `use_mock` must be a `bool` (`isinstance(use_mock, bool)`) or `None`; non-boolean values (`"true"`, `"false"`, `1`, `0`, `""`, lists, dicts) raise `ValueError`.
- When `use_mock is None`, `USE_MOCK_SECURITY` is read from the environment (defaulting to `"true"` when unset). Only case-insensitive `"true"` and `"false"` (with no leading/trailing whitespace) are accepted; any other value (`"treu"`, `"1"`, `"0"`, `"yes"`, `""`, `" true"`) raises `ValueError`.
- When `self.use_mock is False`, `evaluate()` imports and delegates directly to `security.policy.evaluate_action(proposal, context)`.

### B. Verified Test Suite Results (Phase B3.1 & B4.2)
All test suites were executed separately from the repository root with `$env:PYTHONPATH="backend;."`:

| Test Suite | Command | Exit Code | Verified Pytest Result |
| :--- | :--- | :---: | :--- |
| **P4 Security Policy Unit & Fixture Tests** | `.\.venv\Scripts\python.exe -m pytest security/tests/test_policy.py -q` | `0` | **84 passed** in 0.36s |
| **Shared Contracts Tests** | `.\.venv\Scripts\python.exe -m pytest tests/test_contracts.py -q` | `0` | **14 passed** in 0.25s |
| **P4 Security Adapter & HTTP Bridge Tests** | `.\.venv\Scripts\python.exe -m pytest backend/tests/test_security_bridge.py -v` | `0` | **27 passed** in 0.25s |
| **P3 MFA Lifecycle & Concurrency Tests** | `.\.venv\Scripts\python.exe -m pytest backend/tests/test_mfa.py -q` | `0` | **15 passed** in 0.96s |
| **Full Backend Test Suite** | `.\.venv\Scripts\python.exe -m pytest backend/tests -q` | `0` | **80 passed** in 2.04s |

---

## 5. Known Approval, MFA, and Concurrency Risks in Shared Backend Code

The Phase B1/B2 read-only audit of `backend/app/` identified the following unfixed runtime vulnerabilities outside P4's `security/` package:

1. **Critical Risk 1 (`FAIL / UNFIXED`) — Yellow Confirmation Executes After Account Lock (TOCTOU)**:
   - **Location**: [backend/app/api/approvals.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L35-L128) (`confirm_action`).
   - **Defect**: Unlike `verify_action` (which checks `if user.is_locked:` on `UserModel` at [approvals.py:216](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L216)), `confirm_action` never checks `user.is_locked` and never re-evaluates `policy_service.evaluate()` before calling `_execute_action` at line 117. If `UserModel.is_locked` becomes `True` while a Yellow transfer or subscription cancellation is in `PENDING_CONFIRMATION`, `/confirm` still executes it.
2. **Critical Risk 2 (`FAIL / UNFIXED`) — Missing Execution-Time Policy Re-Evaluation & Yellow-to-Red Escalation (TOCTOU)**:
   - **Location**: [backend/app/api/approvals.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L90-L128) (`confirm_action`) and [L223-L224](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L223-L224) (`verify_action`).
   - **Defect**: Neither `confirm_action` nor `verify_action` calls `policy_service.evaluate()` (lines 223–224 in `verify_action` are an unimplemented `# TODO(P4)` comment). In `confirm_action`, the route trusts the static `record.tier` computed when `/api/v1/chat` was called. If two `600.00 CNY` transfers are proposed while `daily_transfer_total == 0.00`, both are stored with `tier="YELLOW"`. After the first transfer executes (`daily_transfer_total` becomes `600.00 CNY`), confirming the second transfer executes immediately without MFA even though `600.00 + 600.00 = 1,200.00 > 1,000.00 CNY`.
3. **Critical Risk 3 (`FAIL / UNFIXED`; Concurrency Race `NOT TESTED`) — Concurrent Yellow Confirmations of the Same `action_id`**:
   - **Location**: [backend/app/api/approvals.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L42-L121).
   - **Defect**: While Red `/verify` uses `mfa.claim_challenge` ([backend/app/services/mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/mfa.py#L110-L127)) to atomically claim the action via a conditional `UPDATE` before `_execute_action`, Yellow `/confirm` reads `record.status` in Python (line 73), calls `_execute_action` (line 117), and only updates `record.status = ActionStatus.COMPLETED.value` at line 119. Two concurrent `/confirm` requests for the same `action_id` can both pass line 73 and debit the account twice. (Only sequential replay after completion is tested in `test_atomic_money_transfer_and_idempotency`; no automated multi-threaded test currently exercises concurrent `/confirm` calls.)
4. **High Risk 4 (`FAIL / UNFIXED`; Concurrency Race `NOT TESTED`) — Competing Transfers Against the Same Account Across Distinct `action_id`s**:
   - **Location**: [backend/app/services/executor.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/executor.py#L28-L50) (`execute_transfer`).
   - **Defect**: `execute_transfer` performs an in-memory read-modify-write on `AccountModel` (`if account.balance < amount: ... account.balance -= amount; account.daily_transfer_total += amount`) without a row lock or conditional SQL `UPDATE ... WHERE account_id = :id AND balance >= :amount`. Competing executions of two different `action_id`s on the same account can race on both `balance` and `daily_transfer_total`. (No automated concurrency test currently exercises competing `action_id`s against the same account.)
5. **Medium Risk 5 (`BLOCKED`) — Read-Only Tools Bypass `policy_service.evaluate()` in `POST /api/v1/chat`**:
   - **Location**: [backend/app/api/chat.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/chat.py#L104-L200).
   - **Defect**: Read-only tools (`get_balance`, `analyze_spending`, `list_subscriptions`) are executed in `chat.py` before reaching the `create_action_record` / `policy_service.evaluate()` block at line 203.
6. **Medium Risk 6 (`BLOCKED`) — In-Place Mutation of `proposal.arguments` in `chat.py`**:
   - **Location**: [backend/app/api/chat.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/chat.py#L227-L232).
   - **Defect**: `chat.py` injects `action_id`, `action_digest`, and `tier` directly into `proposal.arguments` after `create_action_record` returns. Although `ActionApprovalModel.payload_json` is saved before this mutation (and is therefore clean), re-evaluating the mutated in-memory `ActionProposal` would fail `extra="forbid"`.
7. **Low/Medium Risk 7 (`FAIL / UNFIXED`) — Masked Rejection Reason Codes and Missing Rejection Audit Entries in `chat.py`**:
   - **Location**: [backend/app/api/chat.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/chat.py#L234-L240).
   - **Defect**: When `create_action_record` raises `ValueError(f"Action blocked by policy: {decision.reason_code}")`, `chat.py` catches `ValueError`, writes no `AuditLogModel` record, and returns a hardcoded message claiming the account is locked regardless of the actual `decision.reason_code`.

---

## 6. Unresolved Cross-Team Decisions

1. **Enabling `USE_MOCK_SECURITY=false` by Default (Requires P2)**:
   - Currently, `USE_MOCK_AGENT` defaults to `"true"` ([adapters.py:91](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/adapters.py#L91)), and `MockAgentAdapter` ([backend/app/mocks/agent.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/mocks/agent.py)) constructs transfer proposals without `source_account_id` (`source_account_id=None`).
   - Because `security.policy.evaluate_action` strictly requires `source_account_id: ID` on `request_transfer`, flipping `USE_MOCK_SECURITY` default to `"false"` before `MockAgentAdapter` (or `actions.py` when `source_account_id is None`) supplies `source_account_id` would break existing mock-agent tests.
   - By contrast, P1's real agent (`agent/service.py`) already populates `source_account_id="acc_cny_001"`, as proven by `test_http_chat_real_p1_agent_with_real_p4_policy_end_to_end` in [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py#L410-L460).
2. **Execution-Time Policy Re-Evaluation & Yellow-to-Red Escalation Contract (Requires P2 & P3)**:
   - P2 and P3 must agree on executing `policy_service.evaluate(reconstructed_proposal, fresh_context)` inside both `confirm_action` ([approvals.py:89](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L89)) and `verify_action` (replacing the `TODO(P4)` at [approvals.py:223-224](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L223-L224)).
   - Specifically, when a Yellow action escalates to `Tier.RED` at `/confirm` due to intervening daily transfers, `/confirm` should update `record.tier = Tier.RED.value`, invoke `mfa.issue_challenge(record, now)`, and return `ExecutionResult(status=ActionStatus.PENDING_MFA, ...)` rather than executing immediately.
3. **Atomic Claim Pattern for Yellow `/confirm` and `execute_transfer` (Requires P2)**:
   - P2 must decide whether to mirror P3's conditional `UPDATE` pattern (`claim_challenge` in `mfa.py:110-127`) for Yellow `/confirm` transitions (`PENDING_CONFIRMATION` $\rightarrow$ `EXECUTING`/`COMPLETED`) on `ActionApprovalModel` and for atomic balance/daily-total deductions on `AccountModel` in `executor.py`.

---

## 7. Residual Risks, Mitigations, and Owners

| Risk ID | Residual Risk Description | Proposed Mitigation | Owner | Status |
| :--- | :--- | :--- | :---: | :---: |
| **RR-01** | `MockSecurityAdapter` remains default when `USE_MOCK_SECURITY` is unset (`"true"`), so unknown tools, extra fields, and `source_account_id` spoofing are not rejected by default | Populate `source_account_id` in `MockAgentAdapter` (or default only missing `source_account_id` in `actions.py`), then flip `SecurityAdapterService` default to `"false"`. | P2 / P4 | **BLOCKED on P2** |
| **RR-02** | Yellow `/confirm` does not check `UserModel.is_locked` and neither `/confirm` nor `/verify` re-evaluates `policy_service.evaluate()` against fresh `daily_transfer_total` | Reconstruct `ActionProposal` from `record.payload_json` and `BankingContext` from live DB models in `confirm_action` and `verify_action`; call `policy_service.evaluate()`. | P2 / P3 / P4 | **FAIL / UNFIXED (Remediation Planned in Phase B2)** |
| **RR-03** | Concurrent Yellow `/confirm` requests on the same `action_id` can execute the same action twice | Perform conditional `UPDATE ActionApprovalModel SET status = ... WHERE action_id = :id AND status = 'PENDING_CONFIRMATION'` and verify `rowcount == 1` before `_execute_action`. | P2 | **FAIL / UNFIXED (Concurrency Race NOT TESTED; Planned in Phase B2)** |
| **RR-04** | Competing transfers across distinct `action_id`s on the same account can race on `AccountModel.balance` and `daily_transfer_total` | Use conditional SQL `UPDATE AccountModel SET balance = balance - :amt, daily_transfer_total = daily_transfer_total + :amt WHERE account_id = :acc AND balance >= :amt` in `executor.py`. | P2 | **FAIL / UNFIXED (Concurrency Race NOT TESTED; Planned in Phase B2)** |
| **RR-05** | Read-only tools in `chat.py` bypass `policy_service.evaluate()` | Invoke `policy_service.evaluate(proposal, context)` in `chat.py` before executing `READ_TOOLS`. | P2 / P4 | **BLOCKED on P2** |
| **RR-06** | Policy rejections in `chat.py` return a static account-locked string and omit `AuditLogModel` | Map `decision.reason_code` to accurate user feedback and persist an `AuditLogModel` entry on rejection. | P2 | **FAIL / UNFIXED** |

---

## 8. Clear Separation of Work Status

### Implemented and Verified by Automated Tests
- **Pure, fail-closed policy evaluation (`security/policy.py`, `security/rules.py`)**: Implemented by P4 and verified by **84 passing collected test items** in [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py).
- **Strict contract schema validation (`contracts/tool_schemas.py`, `contracts/models.py`)**: Verified by **14 passing collected test items** in [tests/test_contracts.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/tests/test_contracts.py) and the argument/boundary test sections (Sections 8, 9, 14, 19, and 20) within the **84 passing collected test items** in [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py).
- **Hardened `SecurityAdapterService` opt-in bridge (`backend/app/services/adapters.py`)**: Implemented by P4 and verified by **27 passing collected test items** in [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py), including spy verification, service-level `create_action_record` tests, differential HTTP spoofing rejection on `POST /api/v1/chat`, and end-to-end HTTP `/api/v1/chat` + `/confirm` transfer execution with P1's real agent and P4's real policy (`use_mock=False`).
- **Red-tier MFA lifecycle, OTP brute-force lockout, direct `UserModel.is_locked` check at `/verify`, and concurrent `/verify` atomic challenge claim (`backend/app/services/mfa.py`, `backend/app/api/approvals.py:216-233`)**: Implemented by P3 and verified by **15 passing collected test items** in [backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py) (under the default `policy_service.use_mock=True` setting).

### Planned (Remediation Designed in Phase B2, Currently `FAIL / UNFIXED` in Runtime Code)
- Execution-time policy re-evaluation (`policy_service.evaluate`) in `backend/app/api/approvals.py` for both `/confirm` (Yellow lock check & Yellow-to-Red escalation) and `/verify` (resolving `TODO(P4)` at line 223).
- Atomic conditional status claim on `ActionApprovalModel` in `confirm_action` before `_execute_action` (to prevent same-action concurrent Yellow confirmations).
- Atomic conditional balance and `daily_transfer_total` update on `AccountModel` in `backend/app/services/executor.py` (to prevent cross-action same-account races).

### Blocked on Cross-Team Coordination (P2 / P3)
- Switching `USE_MOCK_SECURITY` default from `"true"` to `"false"` in `backend/app/services/adapters.py` (blocked until P2 updates `MockAgentAdapter` in `backend/app/mocks/agent.py` or `actions.py` to supply `source_account_id` when missing).
- Routing read-only tools through `policy_service.evaluate()` in `backend/app/api/chat.py`.
- Applying the Phase B2 remediation patches to `backend/app/api/approvals.py`, `backend/app/services/executor.py`, and `backend/app/api/chat.py`.

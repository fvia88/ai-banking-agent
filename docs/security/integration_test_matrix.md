# P4 Security Integration Test Matrix (Milestone 07 / Phase B4 — Final Readiness)

**Owner**: Person 4 (Finance Risk & Security Engineering)
**Branch**: `feature/security`
**Shared Contracts Version**: 1.0.0
**Related Documents**:
- [README.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/README.md) — Module overview (84 unit tests, 27 bridge tests, 16 integration tests, 6/6 concurrency tests)
- [threat_model.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/threat_model.md) — STRIDE and OWASP LLM threat model, code sandbox boundaries, and audit trail
- [security_assessment.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/security_assessment.md) — Baseline policy engine assessment
- [integration_guide.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/integration_guide.md) — Recommended orchestrator integration pattern
- [security_self_assessment.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/security_self_assessment.md) — Final P4 security self-assessment and release readiness evaluation

---

## 1. Purpose and Status Definitions

This matrix tracks security enforcement across both the **pure policy evaluation layer** (`security/policy.py`, `security/rules.py`, `contracts/tool_schemas.py`) and the **backend runtime / HTTP execution layer** (`backend/app/services/adapters.py`, `backend/app/services/actions.py`, `backend/app/api/chat.py`, `backend/app/api/approvals.py`, `backend/app/services/executor.py`, `backend/app/services/mfa.py`, `backend/app/services/action_execution.py`, `backend/app/services/daily_transfers.py`, `backend/app/services/safety_lock.py`).

Per strict security verification rules:
1. **A runtime scenario is never marked `PASS` merely because a unit test in `security/tests/test_policy.py` passes.**
2. **Default real-policy runtime vs. explicit mock mode**: In `backend/app/services/adapters.py:151`, `USE_MOCK_SECURITY` defaults to `"false"` when unset, selecting the real P4 security policy engine (`security.policy.evaluate_action`) by default. `MockSecurityAdapter` is used only when `USE_MOCK_SECURITY=true` or `use_mock=True` is explicitly configured.
3. **Reconciling Historical Concurrency Reports with Current Execution Guard**:
   - *Historical Report (earlier revisions of this matrix; older version of the test file; not re-run here)*: 3 multi-threaded concurrency regression tests failed on file-backed SQLite (`3 failed`), reproducing duplicate Yellow confirmations, daily threshold bypass, and account overdraft races.
   - *Current Implementation (HEAD `4ab698a`)*: Following P2's execution guard (`execute_claimed_action` with `with_for_update()` in `backend/app/services/action_execution.py`), atomic approval state updates in `backend/app/api/approvals.py`, and GMT+8 Shanghai day rollover (`backend/app/services/daily_transfers.py`), all 6 SQLite multi-threaded concurrency tests in `backend/tests/test_security_concurrency.py` **passed in two consecutive runs on HEAD `4ab698a` (`6 passed`)**.
   - *PostgreSQL Concurrency Limitation*: All 6 corresponding PostgreSQL test variants skip cleanly (`6 skipped`) when `MIGRATION_TEST_POSTGRES_ADMIN_URL` is unset. **PostgreSQL concurrency behavior has not been verified in this environment.**

### Status Legend
- **`PASS`**: Property is implemented and verified by reported passing automated tests at the specified layer and environment (including SQLite concurrency tests where noted).
- **`FAIL / UNFIXED`**: Inspected runtime code and automated tests confirm an unresolved vulnerability or defect.
- **`PARTIAL`**: Core path is verified by passing tests, while a sub-case or multi-action/cross-environment aspect remains unverified.
- **`NOT VERIFIED`**: Behavior (such as PostgreSQL concurrency and row locking under multi-threaded load) has not been executed or verified in this environment.

---

## 2. Summary Matrix

| ID | Scenario | Layer | Current Status | Owner |
| :--- | :--- | :--- | :---: | :---: |
| **M-01A** | Policy decisions: Tier GREEN (`get_balance`, `analyze_spending`, `list_subscriptions`) | Pure Policy & Default Real Adapter (`use_mock=False`) | **PASS** | P4 |
| **M-01B** | Tier GREEN routing & policy evaluation through `POST /api/v1/chat` | Runtime HTTP (`chat.py:109-129`) | **PASS** (`GET_BALANCE` verified over HTTP in `test_security_integration.py`) | P2 / P4 |
| **M-01C** | Policy decisions: Tier YELLOW (`request_transfer` cumulative $\le 1,000.00	ext{ CNY}$, `request_subscription_cancel`) | Pure Policy & Sequential/Concurrent Runtime HTTP (`USE_MOCK_SECURITY=false` default) | **PASS** (Sequential & Concurrent on SQLite; PostgreSQL **NOT VERIFIED**) | P4 / P2 |
| **M-01D** | Policy decisions: Tier RED (`request_transfer` cumulative $> 1,000.00	ext{ CNY}$, requires confirmation + MFA) | Pure Policy, Service `create_action_record`, & Sequential/Concurrent HTTP | **PASS** (Sequential & Concurrent on SQLite; PostgreSQL **NOT VERIFIED**) | P4 / P2 / P3 |
| **M-02A** | Unknown / unwhitelisted tools rejected fail-closed (`UNKNOWN_TOOL`) | Pure Policy, Default Real Adapter, `create_action_record`, & `/verify` dispatch | **PASS** (Default Real Runtime `USE_MOCK_SECURITY=false`) | P4 / P2 / P3 |
| **M-02B** | Malformed, negative, non-finite, over-precision, or extra injected arguments (`INVALID_TOOL_ARGUMENTS`) | Pure Policy, Default Real Adapter, & Runtime HTTP `POST /api/v1/chat` | **PASS** | P4 / P2 |
| **M-02C** | Clean `payload_json` persistence & stored-payload tampering rejection (`INVALID_STORED_ACTION`) | Runtime HTTP (`chat.py:226-238`, `approvals.py:80-97`) | **PASS** (Stored payload tampering blocked; UI tracking fields remain response-only) | P2 / P4 |
| **M-03A** | Cross-account transfer spoofing (`source_account_id != context.account_id` $
ightarrow$ `SOURCE_ACCOUNT_MISMATCH`) | Pure Policy & Default Real Runtime HTTP `POST /api/v1/chat` | **PASS** | P4 / P2 |
| **M-03B** | Cross-account read-only query (`account_id != context.account_id` $
ightarrow$ `ACCOUNT_MISMATCH`) | Pure Policy (**PASS**) & Runtime HTTP `chat.py:114-129` | **PASS** (Policy) / **PARTIAL** (Wired in `chat.py`; HTTP test covers `GET_BALANCE` locked read) | P2 / P4 |
| **M-03C** | Locked-account mutation rejection (`ACCOUNT_LOCKED`) & read-only balance access at proposal time | Pure Policy & Default Real Runtime HTTP `POST /api/v1/chat` | **PASS** | P4 / P2 |
| **M-04A** | Real policy evaluation through `SecurityAdapterService` (`USE_MOCK_SECURITY=false` default) | Adapter & HTTP Bridge (`adapters.py:143-166`) | **PASS** | P4 |
| **M-04B** | `USE_MOCK_SECURITY=false` enabled by default with `MockAgentAdapter` supplying `source_account_id` | Runtime Default Config (`adapters.py`, `app/mocks/agent.py`, `actions.py`) | **PASS** | P2 / P4 |
| **M-05** | Yellow confirmation after account lock (sequential TOCTOU between `/chat` and `/confirm`) | Runtime HTTP (`approvals.py:80-164`) | **PASS** (Sequential) | P2 / P4 |
| **M-06** | Yellow-to-Red escalation when cumulative daily transfers change before `/confirm` | Runtime HTTP (`approvals.py:230-266`) | **PASS** (Sequential & Concurrent on SQLite via execution guard; PostgreSQL **NOT VERIFIED**) | P2 / P3 / P4 |
| **M-07A** | Red MFA verification after account lock (`UserModel.is_locked` check at `/verify`) | Runtime HTTP (`approvals.py:333-334`) | **PASS** | P3 / P2 |
| **M-07B** | Execution-time policy re-evaluation (`_current_policy`) in `/confirm` and `/verify` | Runtime HTTP (`approvals.py:80-164`) | **PASS** (Sequential & Concurrent on SQLite; PostgreSQL **NOT VERIFIED**) | P2 / P3 / P4 |
| **M-08A** | Concurrent Red MFA verification of the **same** `action_id` (`POST /api/v1/actions/{id}/verify`) | Runtime HTTP & DB (`mfa.py`, `approvals.py:300-423`) | **PASS** (SQLite) / **NOT VERIFIED** (PostgreSQL) | P3 / P2 |
| **M-08B** | Concurrent Yellow confirmation of the **same** `action_id` (`POST /api/v1/actions/{id}/confirm`) | Runtime HTTP & DB (`action_execution.py`, `approvals.py:177-291`) | **PASS** (SQLite via `execute_claimed_action`; PostgreSQL **NOT VERIFIED**) | P2 (Runtime) / P4 (Test) |
| **M-09** | Concurrent transfers against the same account across **distinct** `action_id`s (daily limit & balance races) | Runtime HTTP & Executor (`action_execution.py`, `approvals.py`, `executor.py`) | **PASS** (SQLite via row-locked execution guard & daily rollover; PostgreSQL **NOT VERIFIED**) | P2 (Runtime) / P4 (Test) |
| **M-10A** | Canonical rejection reason codes returned by policy and `create_action_record` | Pure Policy & Service (`security/rules.py`, `actions.py:14-50`) | **PASS** | P4 / P2 |
| **M-10B** | Rejection reason code surfacing in `POST /api/v1/chat` and `ACTION_POLICY_REJECTED` audit logging in `/confirm` & `/verify` | Runtime HTTP (`chat.py:242-259`, `approvals.py:143-164`) | **PASS** (Execution-time rejections audited; `/chat` surfaces reason codes) | P2 / P3 |

---

## 3. Reconciliation of Concurrency Implementations and Test Results

> [!NOTE]
> **Progression from Initial Defect Reproduction to Current Execution Guard**:
> Earlier revisions of this matrix recorded three failing multi-threaded concurrency tests on file-backed SQLite (`3 failed`, older test version, prior to the execution guard; historical, not re-run). P2 subsequently implemented `execute_claimed_action` in `backend/app/services/action_execution.py` and wrapped `/confirm` and `/verify` in locked database transactions (`with_for_update()`), alongside GMT+8 Shanghai day rollover in `backend/app/services/daily_transfers.py`.
>
> Fresh execution of the expanded 12-test suite in `backend/tests/test_security_concurrency.py` against current HEAD produces:
> **6 passed, 6 skipped in 13.31s** (100% pass rate for executable SQLite tests).

### Defect 1 (Previously M-08B) — Duplicate Concurrent Yellow `/confirm` Requests
- **Test Name**: `backend/tests/test_security_concurrency.py::test_same_yellow_action_cannot_execute_twice[sqlite]`
- **Historical Failure**: Two concurrent `/confirm` requests on the same action both executed, resulting in `tx_count=2` and `audit_count=2`.
- **Current Verified Status**: **PASS (SQLite)**.
- **Resolution**: In `execute_claimed_action`, the action record is claimed under an exclusive database row lock. The first worker completes the transaction and updates `status=COMPLETED`. The second worker either returns the idempotent replay with the identical `audit_id` or receives an HTTP `409 Conflict`. Exactly 1 transfer debit and 1 execution audit are recorded (`tx_count=1`, `audit_count=1`).
- **PostgreSQL Status**: **NOT VERIFIED** (`test_same_yellow_action_cannot_execute_twice[postgresql]` skipped).

### Defect 2 (Previously M-06 / M-09) — Concurrent Yellow Transfers Competing for Daily Threshold
- **Test Name**: `backend/tests/test_security_concurrency.py::test_competing_yellow_actions_cannot_bypass_cumulative_mfa[sqlite]`
- **Historical Failure**: Two concurrent 600 CNY Yellow transfers both read stale `daily_transfer_total == 0.00` and both executed without MFA (`1,200 CNY > 1,000 CNY`).
- **Current Verified Status**: **PASS (SQLite)**.
- **Resolution**: Under `execute_claimed_action`, the account row is locked with `with_for_update()`. The first 600 CNY transfer executes and updates `daily_transfer_total = 600.00`. The second worker's `_current_policy` re-evaluation reads the fresh committed `daily_transfer_total = 600.00`, detects `600.00 + 600.00 = 1,200.00 > 1,000.00`, escalates the action to `Tier.RED` (`PENDING_MFA`), emits `ESCALATED_TO_RED` and `MFA_CHALLENGE_ISSUED` audit records, and moves no funds without MFA.
- **PostgreSQL Status**: **NOT VERIFIED** (`test_competing_yellow_actions_cannot_bypass_cumulative_mfa[postgresql]` skipped).

### Defect 3 (Previously M-09) — Concurrent Transfers Exceeding Available Balance
- **Test Name**: `backend/tests/test_security_concurrency.py::test_competing_yellow_actions_cannot_overspend_account[sqlite]` and `test_competing_red_verifications_cannot_overspend_account[sqlite]`
- **Historical Failure**: Two concurrent 400 CNY transfers against a 500 CNY balance both succeeded (`800 CNY` debited), causing an account overdraft and lost ORM updates.
- **Current Verified Status**: **PASS (SQLite)**.
- **Resolution**: Account locking in `execute_claimed_action` serializes balance checks. Only the first 400 CNY transfer completes (`balance = 100.00 CNY`). The second transfer fails the balance check in `execute_transfer` (`HTTPException 400`), cleanly rolls back, and retires the action to `FAILED` without debits.
- **PostgreSQL Status**: **NOT VERIFIED** (PostgreSQL variants skipped).

### Additional Verified Concurrency Scenarios
- **Mixed Confirm & Verify Reconciliation**: `test_mixed_confirm_and_verify_reconcile_account[sqlite]` **PASSED** (1200 CNY Red verification and 600 CNY Yellow confirm reconcile correctly).
- **Shanghai Banking Day Rollover Under Concurrency**: `test_first_concurrent_transfers_of_new_day_reset_once[sqlite]` **PASSED** (concurrent transfers at day boundary trigger exactly 1 `DAILY_TRANSFER_TOTAL_RESET` audit log and properly account the new day's total).

---

## 4. Detailed Scenario Analysis

### Scenario 1: Policy Decisions for Green, Yellow, and Red

#### M-01A — Pure Policy & Adapter Tier Classification (Green / Yellow / Red)
1. **Expected Security Property**:
   - Read-only tools (`get_balance`, `analyze_spending`, `list_subscriptions`) with matching `account_id` return `Tier.GREEN`, `allowed_to_proceed=True`, `requires_confirmation=False`, `requires_mfa=False`, `reason_code="READ_ONLY_ACCESS"`.
   - `request_subscription_cancel` and `request_transfer` with `context.daily_transfer_total + amount <= 1000.00` return `Tier.YELLOW`, `allowed_to_proceed=True`, `requires_confirmation=True`, `requires_mfa=False`.
   - `request_transfer` with `context.daily_transfer_total + amount > 1000.00` returns `Tier.RED`, `allowed_to_proceed=True`, `requires_confirmation=True`, `requires_mfa=True`, `reason_code="TRANSFER_EXCEEDS_DAILY_LIMIT"`.
2. **Existing Test / Evidence**:
   - `security/tests/test_policy.py` (**84 passed**): `test_t01_get_balance_green`, `test_analyze_spending_green`, `test_list_subscriptions_green`, `test_t02_transfer_within_daily_limit_yellow`, `test_transfer_with_existing_daily_total_within_limit`, `test_transfer_exact_boundary_1000_zero_prior`, `test_transfer_exact_boundary_1000_split`, `test_transfer_exact_boundary_plus_one_cent_zero_prior`, `test_transfer_exact_boundary_plus_one_cent_split`, `test_t03_transfer_exceeds_daily_limit_red`, `test_very_large_transfer_red`, `test_t07_cancel_subscription_yellow`, `test_fixture_driven_expected_cases_matrix`.
   - `backend/tests/test_security_bridge.py` (**27 passed**): `test_explicit_use_mock_true_and_false_behavior`, `test_real_mode_invokes_security_policy_evaluate_action_spy`, `test_create_action_record_with_real_policy_preserves_reason_codes`.
   - `backend/tests/test_security_integration.py` (**16 passed**): `test_http_proposals_call_actual_policy_at_threshold`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 (Security)
5. **Required Follow-Up**: None in `security/`.

#### M-01B — Runtime Green Tool Routing in `POST /api/v1/chat`
1. **Expected Security Property**:
   - Read-only proposals generated during `POST /api/v1/chat` pass through `validate_tool_arguments` and `policy_service.evaluate(proposal, read_context)` before executing database queries.
2. **Existing Test / Evidence**:
   - Implemented in `backend/app/api/chat.py:109-129`.
   - Verified over HTTP for `GET_BALANCE` by `test_locked_balance_read_still_calls_real_p4` in `backend/tests/test_security_integration.py:164-172`, confirming `POST /api/v1/chat` invokes `security.policy.evaluate_action` with `ToolName.GET_BALANCE` and `account_locked=True`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P2 (Backend) with P4 (Security)
5. **Required Follow-Up**: None for `GET_BALANCE` routing; see M-03B for cross-account read-only HTTP test parameterization.

#### M-01C — Runtime Yellow Action Creation & Execution (`request_transfer` and `request_subscription_cancel`)
1. **Expected Security Property**:
   - Yellow proposals persist an `ActionApprovalModel` in `PENDING_CONFIRMATION` and execute upon `POST /api/v1/actions/{action_id}/confirm` with matching `action_digest`.
2. **Existing Test / Evidence**:
   - Verified by `test_confirm_rechecks_real_policy_and_replays_without_new_debit` and `test_real_p1_and_real_p4_transfer_roundtrip` in `backend/tests/test_security_integration.py`, and `test_http_chat_real_p1_agent_with_real_p4_policy_end_to_end` in `backend/tests/test_security_bridge.py`.
   - Concurrent Yellow execution verified on SQLite by `test_same_yellow_action_cannot_execute_twice[sqlite]` in `backend/tests/test_security_concurrency.py`.
3. **Current Status**: **PASS** (Sequential & Concurrent on SQLite; PostgreSQL **NOT VERIFIED**).
4. **Responsible Owner**: P4 / P2
5. **Required Follow-Up**: PostgreSQL execution verification requires disposable PostgreSQL environment.

#### M-01D — Runtime Red Action Creation, MFA Challenge, & Execution (`request_transfer` $> 1,000.00	ext{ CNY}$)
1. **Expected Security Property**:
   - Red proposals persist an `ActionApprovalModel` in `PENDING_CONFIRMATION`, transition to `PENDING_MFA` upon `/confirm` (issuing a 6-digit OTP without debiting funds), and execute only upon `POST /api/v1/actions/{action_id}/verify` with a valid, unexpired OTP.
2. **Existing Test / Evidence**:
   - Verified with real P4 policy (`USE_MOCK_SECURITY=false` default) by `test_http_proposals_call_actual_policy_at_threshold`, `test_two_pending_yellow_actions_escalate_after_first_executes`, and `test_policy_rejection_at_verify_cannot_be_overridden_by_correct_otp` in `backend/tests/test_security_integration.py` (**16 passed**), and all **18 passed** tests in `backend/tests/test_mfa.py`.
   - Concurrent Red verifications verified on SQLite by `test_competing_red_verifications_cannot_overspend_account[sqlite]` in `backend/tests/test_security_concurrency.py`.
3. **Current Status**: **PASS** (Sequential & Concurrent on SQLite; PostgreSQL **NOT VERIFIED**).
4. **Responsible Owner**: P4 / P2 / P3
5. **Required Follow-Up**: PostgreSQL concurrency verification.

---

### Scenario 2: Unknown Tools and Malformed or Injected Arguments

#### M-02A — Unknown / Unwhitelisted Tools (`UNKNOWN_TOOL`)
1. **Expected Security Property**:
   - Any tool name outside `ToolName` (`get_balance`, `analyze_spending`, `list_subscriptions`, `request_transfer`, `request_subscription_cancel`) must be rejected fail-closed (`allowed_to_proceed=False`, `tier=Tier.RED`, `reason_code="UNKNOWN_TOOL"`).
   - At execution time (`/confirm` and `/verify`), `_current_policy` and `_execute_action` must refuse any tool other than `request_transfer` and `request_subscription_cancel`.
2. **Existing Test / Evidence**:
   - `security/tests/test_policy.py`: `test_unknown_tool_object_rejected`, `test_action_proposal_with_unrecognized_tool_string_returns_unknown_tool`.
   - `backend/tests/test_security_bridge.py`: `test_unknown_tool_rejected_in_real_mode`, `test_create_action_record_with_real_policy_preserves_reason_codes`.
   - `backend/tests/test_mfa.py`: `test_unknown_tool_fails_closed_at_verify`.
3. **Current Status**: **PASS** (Real P4 policy is active by default via `USE_MOCK_SECURITY=false`).
4. **Responsible Owner**: P4 / P2 / P3
5. **Required Follow-Up**: None.

#### M-02B — Malformed, Negative, Non-Finite, Overlong, or Injected Arguments (`INVALID_TOOL_ARGUMENTS`)
1. **Expected Security Property**:
   - All tool arguments are validated against `contracts/tool_schemas.py` (`StrictModel` with `extra="forbid"`, `PositiveMoney` with `gt=0, max_digits=16, decimal_places=2`, `ID` with `min_length=1, max_length=128`, `currency: Literal["CNY"] = "CNY"`, and `period` regex `^\d{4}-(0[1-9]|1[0-2])$`).
   - Negative, zero, `-0.00`, `NaN`, `Inf`, `-Inf`, $>2$ decimal places, $>16$ digits, lowercase `"cny"`, `"USD"`, missing/null/empty IDs, IDs $>128$ chars, and injected fields (`bypass_mfa`, `admin`, `mfa_verified`, `user_id`, `action_id`, `action_digest`, `tier`) must be rejected with `INVALID_TOOL_ARGUMENTS`.
2. **Existing Test / Evidence**:
   - `security/tests/test_policy.py` (**84 passed**) and `tests/test_contracts.py` (**14 passed**).
   - `backend/tests/test_security_bridge.py` (**27 passed**): `test_meaningful_distinction_between_mock_and_real_policy_decisions`, `test_create_action_record_with_real_policy_preserves_reason_codes`.
   - `backend/tests/test_security_integration.py` (**16 passed**): `test_invalid_agent_arguments_do_not_issue_tickets` (verifying over HTTP `/api/v1/chat` that `-1.00`, `1.001`, injected `user_id`, and injected `action_id` are rejected with `INVALID_TOOL_ARGUMENTS` and create `0` DB rows).
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 / P2
5. **Required Follow-Up**: None.

#### M-02C — Clean `payload_json` Persistence & Stored-Payload Tampering Rejection (`INVALID_STORED_ACTION`)
1. **Expected Security Property**:
   - Server approval metadata (`action_id`, `action_digest`, `tier`) is added to the HTTP response proposal only *after* `create_action_record` validates canonical arguments, evaluates policy, and persists clean `payload_json`.
   - At execution time (`/confirm` and `/verify`), `_current_policy` re-validates `record.payload_json` against `validate_tool_arguments` and verifies `compute_action_digest(record.tool, payload) == record.action_digest`, rejecting any stored-row tampering with HTTP `403` (`INVALID_STORED_ACTION`).
2. **Existing Test / Evidence**:
   - `backend/tests/test_security_integration.py:134-144`: `test_stored_payload_tampering_blocks_execution`.
   - `security/tests/test_policy.py:1561-1606`: `test_server_approval_metadata_injected_into_arguments_rejected`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P2 / P4
5. **Required Follow-Up**: None.

---

### Scenario 3: Account Ownership, Source-Account Mismatch, and Locked-Account Rejection

#### M-03A — Cross-Account Transfer Spoofing (`SOURCE_ACCOUNT_MISMATCH`)
1. **Expected Security Property**:
   - If `proposal.arguments["source_account_id"] != context.account_id`, the proposal must be rejected with `allowed_to_proceed=False`, `tier=Tier.RED`, and `reason_code="SOURCE_ACCOUNT_MISMATCH"`.
2. **Existing Test / Evidence**:
   - `security/tests/test_policy.py`: `test_transfer_source_account_mismatch_rejected`, `test_cross_tenant_transfer_source_account_mismatch`.
   - `backend/tests/test_security_bridge.py:338-408`: `test_http_chat_differential_proof_mock_allows_vs_real_policy_rejects`.
   - `backend/tests/test_security_integration.py:115-131`: `test_invalid_agent_arguments_do_not_issue_tickets[{"source_account_id": "foreign_account"}, "SOURCE_ACCOUNT_MISMATCH"]`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 / P2
5. **Required Follow-Up**: None.

#### M-03B — Cross-Account Read-Only Query (`ACCOUNT_MISMATCH`)
1. **Expected Security Property**:
   - Read-only tool calls (`get_balance`, `analyze_spending`, `list_subscriptions`) specifying `account_id != context.account_id` must be rejected with `ACCOUNT_MISMATCH`.
2. **Existing Test / Evidence**:
   - `security/tests/test_policy.py`: `test_get_balance_account_mismatch_rejected`, `test_cross_tenant_query_account_mismatch`, `test_analyze_spending_account_mismatch_rejected`, `test_list_subscriptions_account_mismatch_rejected`.
   - `backend/app/api/chat.py:114-129`: validates read tool arguments and invokes `policy_service.evaluate(proposal, read_context)`. `test_locked_balance_read_still_calls_real_p4` in `backend/tests/test_security_integration.py` confirms real P4 on `GET_BALANCE`.
3. **Current Status**: **PASS** (Policy Layer & `GET_BALANCE` HTTP policy invocation) / **PARTIAL** (Cross-account read rejection over HTTP is wired in `chat.py:114-129` but not separately parameterized in `test_security_integration.py`).
4. **Responsible Owner**: P2 / P4
5. **Required Follow-Up**: Optional HTTP test parameterization.

#### M-03C — Locked-Account Rejection at Proposal Time (`ACCOUNT_LOCKED`)
1. **Expected Security Property**:
   - When `context.account_locked=True` (populated from `UserModel.is_locked`), all state-changing proposals (`request_transfer`, `request_subscription_cancel`) are rejected with `ACCOUNT_LOCKED` (`allowed_to_proceed=False`, `tier=Tier.RED`). Read-only queries remain available by default (`READ_ONLY_ACCESS`) unless `PolicyConfig(lock_denies_read_only=True)` is configured.
2. **Existing Test / Evidence**:
   - `security/tests/test_policy.py`: `test_t11_locked_account_rejects_transfer`, `test_locked_account_rejects_subscription_cancellation`, `test_locked_account_allows_read_only_by_default`, `test_locked_account_denies_read_only_when_configured`, `test_locked_account_read_only_tools_analyze_and_subscriptions`, `test_locked_account_precedes_source_account_mismatch`.
   - `backend/tests/test_security_integration.py:164-172`: `test_locked_balance_read_still_calls_real_p4`.
   - `backend/tests/test_policy.py:86-109`: `test_locked_user_can_check_balance_but_cannot_transfer`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 / P2
5. **Required Follow-Up**: None.

---

### Scenario 4: Real Policy Evaluation Through the Backend Adapter

#### M-04A & M-04B — `SecurityAdapterService` Configuration & Default Real Policy Mode
1. **Expected Security Property**:
   - `SecurityAdapterService(use_mock: bool | None = None)` strictly validates `use_mock` (raising `ValueError` on non-booleans) and `USE_MOCK_SECURITY` (accepting only case-insensitive `"true"` or `"false"`, raising `ValueError` on any other string or whitespace-padded value).
   - When `USE_MOCK_SECURITY` is unset, `SecurityAdapterService` defaults to `use_mock=False` (`backend/app/services/adapters.py:151`), selecting the real P4 policy engine by default.
   - `MockAgentAdapter` (`backend/app/mocks/agent.py:70,133,164`) includes `source_account_id`, so default mock-agent tests and MFA suites run against the real P4 policy engine without regression.
2. **Existing Test / Evidence**:
   - `backend/tests/test_security_bridge.py`: **27 passed**.
   - `backend/tests/test_security_integration.py`: **16 passed**.
   - `backend/tests/test_mfa.py`: **18 passed**.
   - Broader backend suite: **238 passed, 22 skipped** under default `USE_MOCK_SECURITY=false`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 (Adapter Bridge) / P2 (`MockAgentAdapter` & `actions.py`)
5. **Required Follow-Up**: None.

---

### Scenario 5: Yellow Confirmation After Account Lock

#### M-05 — Account Lock Enforcement After Proposal Creation (`/chat` $
ightarrow$ `/confirm`)
1. **Expected Security Property**:
   - If `UserModel.is_locked` becomes `True` *after* a Yellow action is proposed (`PENDING_CONFIRMATION`) but *before* `POST /api/v1/actions/{action_id}/confirm` is called, `/confirm` re-evaluates policy via `_current_policy`, marks the action `ActionStatus.REJECTED`, writes an `ACTION_POLICY_REJECTED` audit log (`reason_code="ACCOUNT_LOCKED"`), returns HTTP `403`, and leaves account balance unchanged.
2. **Existing Test / Evidence**:
   - Implemented in `backend/app/api/approvals.py:80-164`.
   - Verified by `test_new_lock_blocks_yellow_confirm` in `backend/tests/test_security_integration.py:106-112`.
3. **Current Status**: **PASS** (Sequential)
4. **Responsible Owner**: P2 (Backend) with P4 (Security)
5. **Required Follow-Up**: None.

---

### Scenario 6: Yellow-to-Red Escalation When Cumulative Daily Transfers Change

#### M-06 — Cumulative Daily Limit Escalation Between Proposal and Confirmation (Sequential & Concurrent)
1. **Expected Security Property**:
   - When two Yellow transfers whose combined amount exceeds `1,000.00 CNY` are proposed while `daily_transfer_total` is low, confirming the second transfer after (or concurrently with) the first must not allow both to execute as Yellow without MFA. The second transfer must re-evaluate against the updated `daily_transfer_total`, escalate from `Tier.YELLOW` to `Tier.RED` (`ActionStatus.PENDING_MFA`), and issue an OTP challenge without debiting funds.
2. **Existing Test / Evidence**:
   - **Sequential Escalation (`PASS`)**: Verified by `test_two_pending_yellow_actions_escalate_after_first_executes` in `backend/tests/test_security_integration.py:87-104`.
   - **Concurrent Escalation (`PASS on SQLite`)**: Verified by `test_competing_yellow_actions_cannot_bypass_cumulative_mfa[sqlite]` in `backend/tests/test_security_concurrency.py`. Under `execute_claimed_action`, the second worker reads `daily_transfer_total = 600.00`, escalates to `Tier.RED` (`PENDING_MFA`), logs `ESCALATED_TO_RED` and `MFA_CHALLENGE_ISSUED`, and creates exactly 1 ledger debit.
3. **Current Status**: **PASS** (Sequential & Concurrent on SQLite; PostgreSQL **NOT VERIFIED**).
4. **Responsible Owner**: P2 (Runtime Serialization) & P3 (MFA) with P4 (Policy & Concurrency Test)
5. **Required Follow-Up**: PostgreSQL verification when database environment is available.

---

### Scenario 7: Red MFA Verification After Account Lock & Execution-Time Policy Re-Evaluation

#### M-07A — Account Lock Check at Red `/verify`
1. **Expected Security Property**:
   - If a Red action is in `PENDING_MFA` and `UserModel.is_locked` becomes `True` before `POST /api/v1/actions/{action_id}/verify` is called with the valid OTP code, `/verify` rejects execution (`403`), marks the action `REJECTED`, and leaves the account balance unchanged.
2. **Existing Test / Evidence**:
   - Implemented via `_current_policy(db, user, record)` at `backend/app/api/approvals.py:333-334`.
   - Verified by `test_account_locked_after_confirm_blocks_execution` in `backend/tests/test_mfa.py:227-237`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P3 / P2
5. **Required Follow-Up**: None.

#### M-07B — Execution-Time Policy Re-Evaluation (`_current_policy`) in `/confirm` and `/verify`
1. **Expected Security Property**:
   - Both `/confirm` and `/verify` reconstruct `ActionProposal` from `record.payload_json`, verify `action_digest`, refresh user/account state, and call `policy_service.evaluate(proposal, context)` prior to executing any state mutation. A valid OTP cannot override a policy rejection at `/verify`.
2. **Existing Test / Evidence**:
   - Implemented in `backend/app/api/approvals.py:80-164`.
   - Verified by `test_confirm_rechecks_real_policy_and_replays_without_new_debit` and `test_policy_rejection_at_verify_cannot_be_overridden_by_correct_otp` in `backend/tests/test_security_integration.py`.
   - Concurrent recheck verified under row locks in `backend/tests/test_security_concurrency.py`.
3. **Current Status**: **PASS** (Sequential & Concurrent on SQLite; PostgreSQL **NOT VERIFIED**).
4. **Responsible Owner**: P2 / P3 / P4
5. **Required Follow-Up**: PostgreSQL verification.

---

### Scenario 8: Concurrent Confirmation / Verification of the Same Action

#### M-08A — Concurrent Red MFA Verification (`POST /api/v1/actions/{action_id}/verify`)
1. **Expected Security Property**:
   - Two simultaneous `/verify` requests submitting the valid OTP for the **same `action_id`** must result in at most one execution (`COMPLETED`) and one `409 Conflict` rejection, debiting the account once.
2. **Existing Test / Evidence**:
   - Implemented via atomic conditional SQL update in `backend/app/services/mfa.py:110-132` (`claim_challenge`) and `execute_claimed_action`.
   - Verified on file-backed SQLite by `test_concurrent_verify_loser_is_rejected_without_debit` and multi-threaded `test_truly_concurrent_verifies_debit_once` in `backend/tests/test_mfa.py:150-163, 338-414`.
3. **Current Status**: **PASS (SQLite)** / **NOT VERIFIED (PostgreSQL)**.
4. **Responsible Owner**: P3 (MFA) / P2 (Executor)
5. **Required Follow-Up**: PostgreSQL verification.

#### M-08B — Concurrent Yellow Confirmation of the Same Action (`POST /api/v1/actions/{action_id}/confirm`)
1. **Expected Security Property**:
   - Two simultaneous `/confirm` requests for the **same `action_id`** in `PENDING_CONFIRMATION` must result in at most one transfer execution and debit (`tx_count == 1`, `audit_count == 1`), with the second request receiving `409 Conflict` or returning the idempotent `COMPLETED` result with the same `audit_id`.
2. **Existing Test / Evidence**:
   - Implemented via `execute_claimed_action` in `backend/app/services/action_execution.py`.
   - Verified on file-backed SQLite by `test_same_yellow_action_cannot_execute_twice[sqlite]` in `backend/tests/test_security_concurrency.py:193-208` (**PASSED**).
3. **Current Status**: **PASS (SQLite via `execute_claimed_action`)** / **NOT VERIFIED (PostgreSQL)**.
4. **Responsible Owner**: P2 (Backend Runtime) / P4 (Regression Test)
5. **Required Follow-Up**: PostgreSQL verification.

---

### Scenario 9: Concurrent Transfers Against the Same Account Across Distinct Action IDs

#### M-09 — Competing Transfers Across Different `action_id`s on the Same Account
1. **Expected Security Property**:
   - Concurrent confirmations/verifications of two **different transfer actions (`act_1` and `act_2`)** drawing from the same `account_id` must serialize policy re-evaluation, balance checks, and `daily_transfer_total` updates so that:
     1. Two concurrent Yellow transfers (`600 CNY + 600 CNY > 1,000 CNY`) cannot both pass `_current_policy` as Yellow and execute without MFA.
     2. Two concurrent transfers (`400 CNY + 400 CNY > 500 CNY` balance) cannot both pass `account.balance < amount` in `execute_transfer` and overdraw the account.
2. **Existing Test / Evidence**:
   - Verified on file-backed SQLite in `backend/tests/test_security_concurrency.py`:
     - `test_competing_yellow_actions_cannot_bypass_cumulative_mfa[sqlite]` (**PASSED**).
     - `test_competing_yellow_actions_cannot_overspend_account[sqlite]` (**PASSED**).
     - `test_competing_red_verifications_cannot_overspend_account[sqlite]` (**PASSED**).
     - `test_mixed_confirm_and_verify_reconcile_account[sqlite]` (**PASSED**).
     - `test_first_concurrent_transfers_of_new_day_reset_once[sqlite]` (**PASSED**).
3. **Current Status**: **PASS (SQLite via row-locked execution guard & daily rollover)** / **NOT VERIFIED (PostgreSQL)**.
4. **Responsible Owner**: P2 (Backend Runtime) / P4 (Regression Test)
5. **Required Follow-Up**: PostgreSQL verification.

---

### Scenario 10: Rejection Reason Codes and Audit Linkage

#### M-10A — Deterministic Policy Reason Codes & Successful Execution Audit Linkage
1. **Expected Security Property**:
   - Every policy decision returns an explicit `SecurityReasonCode` (`security/rules.py:15-40`).
   - Every executed transfer, subscription cancellation, and issued MFA challenge creates an `AuditLogModel` record linked by `action_id`, `user_id`, `payload_digest`, and `audit_id`.
2. **Existing Test / Evidence**:
   - Verified across **84 passed** tests in `security/tests/test_policy.py`, **27 passed** tests in `backend/tests/test_security_bridge.py`, and **18 passed** tests in `backend/tests/test_mfa.py`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 / P2 / P3
5. **Required Follow-Up**: None for execution audit logs.

#### M-10B — Rejection Reason Code Surfacing in `POST /api/v1/chat` and Execution-Time Rejection Auditing
1. **Expected Security Property**:
   - When `create_action_record` rejects a proposal with `PolicyRejected(reason_code)`, `POST /api/v1/chat` surfaces the specific `reason_code` and explanation in `ChatOutput.reply` with `status=ActionStatus.REJECTED`.
   - Execution-time policy rejections in `_current_policy` (`/confirm` and `/verify`) record an `AuditLogModel` entry (`action_type="ACTION_POLICY_REJECTED"`, `reason_code=reason`).
2. **Existing Test / Evidence**:
   - Implemented in `backend/app/api/chat.py:242-259` and `backend/app/api/approvals.py:143-164`.
   - Verified by `test_invalid_agent_arguments_do_not_issue_tickets` in `backend/tests/test_security_integration.py:115-131`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P2 / P3 / P4
5. **Required Follow-Up**: None.

---

## 5. Decision and Control Audit Event Coverage

The backend implementation records 12 explicit `AuditLogModel` event types across security-relevant control points:

| Event Type (`action_type`) | Trigger / Context | Emitting Module | Owner |
| :--- | :--- | :--- | :---: |
| `TRANSFER_EXECUTED_ATOMIC` | Atomic ledger debit and balance update | `backend/app/services/executor.py` | P2 |
| `SUBSCRIPTION_CANCELLED` | Confirmed cancellation of recurring subscription | `backend/app/services/executor.py` | P2 |
| `ACTION_POLICY_REJECTED` | Execution-time policy refusal in `/confirm` or `/verify` | `backend/app/api/approvals.py` | P2 |
| `ESCALATED_TO_RED` | Cumulative daily transfer threshold crossed at confirm | `backend/app/api/approvals.py` | P2 |
| `MFA_CHALLENGE_ISSUED` | Red tier OTP challenge generation | `backend/app/api/approvals.py` | P2 / P3 |
| `APPROVAL_CANCELLED_BY_USER` | Explicit cancellation of pending ticket by user | `backend/app/api/approvals.py` | P2 |
| `VERIFICATION_FAILURE` | Wrong OTP or bad confirmation digest | `backend/app/services/safety_lock.py` | P2 / P3 |
| `SAFETY_LOCK_TRIGGERED` | Persistent safety lockout triggered after 3 failures | `backend/app/services/safety_lock.py` | P2 |
| `SAFETY_LOCK_RESET` | Authorized demo operator review and lock clearance | `backend/app/services/safety_lock.py` | P2 |
| `ACTION_REJECTED_SAFETY_LOCK` | Automatic retirement of pending tickets when lockout trips | `backend/app/services/safety_lock.py` | P2 |
| `DAILY_TRANSFER_TOTAL_RESET` | Shanghai midnight banking-day rollover | `backend/app/api/approvals.py` | P2 |
| `ACTION_STATUS_OBSERVED` | Agent continuation observation of terminal action state | `backend/app/api/continuation.py` | P1 / P2 |

### Audit Coverage Boundaries & Identified Gaps
1. **Initial Proposal Creation**: Proposing an action in `POST /api/v1/chat` inserts a row into `ActionApprovalModel`, but does NOT create an immutable `AuditLogModel` entry.
2. **Read-Only Authorizations**: Authorized queries (`GET_BALANCE`, `ANALYZE_SPENDING`, `LIST_SUBSCRIPTIONS`) are executed without logging to `AuditLogModel`.
3. **Plan Lifecycle Events**: Plan pause, stop, or operator handoff events do not exist and are not audited, as general multi-step DAG planning is not implemented.

---

## 6. Human Takeover and Generated-Code Sandbox Boundaries

### 6.1 Human Takeover Status
Bank.ly does NOT implement a general human takeover workflow, operator review queue, or ticket dispatch system. The only human intervention point is `reset_safety_lock` in `backend/app/services/safety_lock.py`, which allows a local demo operator to reset an automatic lockout with a 1-200 character review reason. This is an administrative lock-clear function and must not be represented as a general human takeover queue.

### 6.2 Arbitrary Generated-Code Sandboxing
The Bank.ly agent architecture executes only whitelisted typed tools (`contracts.enums.ToolName`) with Pydantic argument validation (`contracts/tool_schemas.py`). The system never executes arbitrary generated code strings (no Python `eval`/`exec`, no shell commands, no bash scripts).
Crucially, **typed tool whitelisting is NOT an arbitrary generated-code sandbox**. No operating-system-level sandbox (such as gVisor, Firecracker, or Docker per-invocation isolation) is implemented. This distinction must be maintained accurately in all project communications.

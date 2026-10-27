# P4 Security Integration Test Matrix (Milestone 07 / Phase B4)

**Owner**: Person 4 (Finance Risk & Security Engineering)  
**Branch**: `feature/security`  
**Shared Contracts Version**: 1.0.0  
**Related Documents**:
- [README.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/README.md) — Module overview (Milestone 03 baseline; reports the earlier 39-test count prior to Phase B3 expansion to 84 tests)
- [threat_model.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/threat_model.md) — STRIDE and OWASP LLM threat model
- [security_assessment.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/security_assessment.md) — Baseline policy engine assessment (Milestone 03 baseline; reports 39 tests prior to Phase B3 expansion to 84 tests)
- [integration_guide.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/integration_guide.md) — Recommended orchestrator integration pattern
- [security_self_assessment.md](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/security/security_self_assessment.md) — Milestone 07 P4 security self-assessment and integration readiness

---

## 1. Purpose and Status Definitions

This matrix tracks security enforcement across both the **pure policy evaluation layer** (`security/policy.py`, `security/rules.py`, `contracts/tool_schemas.py`) and the **backend runtime / HTTP execution layer** (`backend/app/services/adapters.py`, `backend/app/services/actions.py`, `backend/app/api/chat.py`, `backend/app/api/approvals.py`, `backend/app/services/executor.py`, `backend/app/services/mfa.py`).

Per strict security verification rules:
1. **A runtime scenario is never marked `PASS` merely because a unit test in `security/tests/test_policy.py` passes.**
2. **Default real-policy runtime vs. explicit mock mode**: In [backend/app/services/adapters.py:151](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/adapters.py#L151), `USE_MOCK_SECURITY` defaults to `"false"` when unset, selecting the real P4 security policy engine (`security.policy.evaluate_action`) by default. `MockSecurityAdapter` is used only when `USE_MOCK_SECURITY=true` or `use_mock=True` is explicitly configured.
3. **Sequential integration coverage vs. concurrent execution guarantees**: Passing sequential HTTP integration tests ([backend/tests/test_security_integration.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py)) and MFA lifecycle tests ([backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py)) do **not** establish complete production security or prove concurrent correctness. Multi-threaded concurrency regression tests in [backend/tests/test_security_concurrency.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_concurrency.py) were run against file-backed SQLite and currently fail (`3 failed`), reproducing three unresolved concurrency vulnerabilities in P2-owned runtime code. **PostgreSQL concurrency behavior has not been verified.**

### Status Legend
- **`PASS`**: Property is implemented and verified by reported passing automated tests at the specified layer and mode (sequential or single-action SQLite scope as noted).
- **`FAIL / UNFIXED`**: Inspected runtime code and automated concurrency tests confirm an unresolved vulnerability or defect.
- **`PARTIAL`**: Core path is verified by passing tests, while a sub-case or multi-action/cross-environment aspect remains unverified.
- **`NOT VERIFIED`**: Behavior (such as PostgreSQL concurrency and row locking) has not been executed or verified in this environment.

---

## 2. Summary Matrix

| ID | Scenario | Layer | Current Status | Owner |
| :--- | :--- | :--- | :---: | :---: |
| **M-01A** | Policy decisions: Tier GREEN (`get_balance`, `analyze_spending`, `list_subscriptions`) | Pure Policy & Default Real Adapter (`use_mock=False`) | **PASS** | P4 |
| **M-01B** | Tier GREEN routing & policy evaluation through `POST /api/v1/chat` | Runtime HTTP (`chat.py:109-129`) | **PASS** (`GET_BALANCE` verified over HTTP in `test_security_integration.py`) | P2 / P4 |
| **M-01C** | Policy decisions: Tier YELLOW (`request_transfer` cumulative $\le 1,000.00\text{ CNY}$, `request_subscription_cancel`) | Pure Policy & Sequential Runtime HTTP (`USE_MOCK_SECURITY=false` default) | **PASS** (Sequential; see **M-08B / M-09** for concurrency failures) | P4 / P2 |
| **M-01D** | Policy decisions: Tier RED (`request_transfer` cumulative $> 1,000.00\text{ CNY}$, requires confirmation + MFA) | Pure Policy, Service `create_action_record`, & Sequential HTTP `/chat` $\rightarrow$ `/confirm` $\rightarrow$ `/verify` | **PASS** (Sequential; see **M-09** for cross-action concurrency) | P4 / P2 / P3 |
| **M-02A** | Unknown / unwhitelisted tools rejected fail-closed (`UNKNOWN_TOOL`) | Pure Policy, Default Real Adapter, `create_action_record`, & `/verify` dispatch | **PASS** (Default Real Runtime `USE_MOCK_SECURITY=false`) | P4 / P2 / P3 |
| **M-02B** | Malformed, negative, non-finite, over-precision, or extra injected arguments (`INVALID_TOOL_ARGUMENTS`) | Pure Policy, Default Real Adapter, & Runtime HTTP `POST /api/v1/chat` | **PASS** | P4 / P2 |
| **M-02C** | Clean `payload_json` persistence & stored-payload tampering rejection (`INVALID_STORED_ACTION`) | Runtime HTTP (`chat.py:226-238`, `approvals.py:29-38`) | **PASS** (Stored payload tampering blocked; UI tracking fields remain response-only) | P2 / P4 |
| **M-03A** | Cross-account transfer spoofing (`source_account_id != context.account_id` $\rightarrow$ `SOURCE_ACCOUNT_MISMATCH`) | Pure Policy & Default Real Runtime HTTP `POST /api/v1/chat` | **PASS** | P4 / P2 |
| **M-03B** | Cross-account read-only query (`account_id != context.account_id` $\rightarrow$ `ACCOUNT_MISMATCH`) | Pure Policy (**PASS**) & Runtime HTTP `chat.py:114-129` | **PASS** (Policy) / **PARTIAL** (Wired in `chat.py`; HTTP test covers `GET_BALANCE` locked read) | P2 / P4 |
| **M-03C** | Locked-account mutation rejection (`ACCOUNT_LOCKED`) & read-only balance access at proposal time | Pure Policy & Default Real Runtime HTTP `POST /api/v1/chat` | **PASS** | P4 / P2 |
| **M-04A** | Real policy evaluation through `SecurityAdapterService` (`USE_MOCK_SECURITY=false` default) | Adapter & HTTP Bridge (`adapters.py:143-166`) | **PASS** | P4 |
| **M-04B** | `USE_MOCK_SECURITY=false` enabled by default with `MockAgentAdapter` supplying `source_account_id` | Runtime Default Config (`adapters.py`, `app/mocks/agent.py`, `actions.py`) | **PASS** | P2 / P4 |
| **M-05** | Yellow confirmation after account lock (sequential TOCTOU between `/chat` and `/confirm`) | Runtime HTTP (`approvals.py:22-89, 164`) | **PASS** (Sequential) | P2 / P4 |
| **M-06** | Yellow-to-Red escalation when cumulative daily transfers change before `/confirm` | Runtime HTTP (`approvals.py:22-89, 164-192`) | **PASS** (Sequential) / **FAIL / UNFIXED** (Concurrent — see Section 3, **Defect 2**) | P2 / P3 / P4 |
| **M-07A** | Red MFA verification after account lock (`UserModel.is_locked` check at `/verify`) | Runtime HTTP (`approvals.py:302`) | **PASS** | P3 / P2 |
| **M-07B** | Execution-time policy re-evaluation (`_current_policy`) in `/confirm` and `/verify` | Runtime HTTP (`approvals.py:22-89, 164, 302`) | **PASS** (Sequential; does not serialize concurrent requests) | P2 / P3 / P4 |
| **M-08A** | Concurrent Red MFA verification of the **same** `action_id` (`POST /api/v1/actions/{id}/verify`) | Runtime HTTP & DB (`mfa.py:110-132`, `approvals.py:310`) | **PASS** (Same-Action SQLite) / **NOT VERIFIED** (PostgreSQL; Cross-Action Red Verify) | P3 / P2 |
| **M-08B** | Concurrent Yellow confirmation of the **same** `action_id` (`POST /api/v1/actions/{id}/confirm`) | Runtime HTTP & DB (`approvals.py:117-200`) | **FAIL / UNFIXED** (Reproduced on SQLite — see Section 3, **Defect 1**) | P2 (Runtime) / P4 (Test) |
| **M-09** | Concurrent transfers against the same account across **distinct** `action_id`s (daily limit & balance races) | Runtime HTTP & Executor (`approvals.py`, `executor.py:29-50`) | **FAIL / UNFIXED** (Reproduced on SQLite — see Section 3, **Defects 2 & 3**; PostgreSQL **NOT VERIFIED**) | P2 (Runtime) / P4 (Test) |
| **M-10A** | Canonical rejection reason codes returned by policy and `create_action_record` | Pure Policy & Service (`security/rules.py`, `actions.py:14-50`) | **PASS** | P4 / P2 |
| **M-10B** | Rejection reason code surfacing in `POST /api/v1/chat` and `ACTION_POLICY_REJECTED` audit logging in `/confirm` & `/verify` | Runtime HTTP (`chat.py:242-259`, `approvals.py:81-88`) | **PASS** (Execution-time rejections audited; `/chat` surfaces reason codes) | P2 / P3 |

---

## 3. Unresolved Concurrency Vulnerabilities in P2-Owned Runtime Code

> [!WARNING]
> **Sequential Integration Passing $\neq$ Concurrent Execution Safety**  
> Passing results in `backend/tests/test_security_integration.py` (16 passed), `backend/tests/test_mfa.py` (18 passed), and the broader backend suite (`backend/tests` excluding `test_security_concurrency.py`: 133 passed, 7 skipped) verify **sequential** execution-time policy re-evaluation (`_current_policy`) and **single-action** Red MFA challenge claims (`mfa.claim_challenge`). They do **not** establish complete production security or prove concurrent correctness.
>
> As documented in [`backend/app/api/approvals.py:25-26`](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L25-L26) and [`docs/app/p4_integration.md:46-48`](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/docs/app/p4_integration.md#L46-L48), `_current_policy` does not serialize concurrent action confirmations or competing account transfers. All 3 tests in [backend/tests/test_security_concurrency.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_concurrency.py) **currently fail (`3 failed`)**, each reproducing a concrete concurrency vulnerability.
> - **Test Environment**: File-backed SQLite databases (`sqlite:///` under `pytest` `tmp_path`) with one independent SQLAlchemy `Session` per worker thread and `threading.Barrier` synchronization at `_current_policy`.
> - **PostgreSQL Verification Status**: **PostgreSQL concurrency behavior has not been verified.**

### Defect 1 — Duplicate Concurrent Yellow `/confirm` Requests Execute Twice (M-08B)
- **Test Name**: `backend/tests/test_security_concurrency.py::test_concurrent_duplicate_yellow_confirm_executes_at_most_once`
- **Observed Failure**:
  ```text
  AssertionError: Expected 1 transfer ledger entry:
    outcomes=[('ok', <ActionStatus.COMPLETED: 'COMPLETED'>, 'aud_99b02aa85c'),
              ('ok', <ActionStatus.COMPLETED: 'COMPLETED'>, 'aud_1d812c8424')],
    tx_count=2, audit_count=2, audit_ids=['aud_99b02aa85c', 'aud_1d812c8424'],
    balance=14750.00, daily_total=500.00, action_status=COMPLETED,
    action_audit_id=aud_1d812c8424
  assert 2 == 1
  ```
- **Security Impact**:
  - In [`confirm_action`](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L117-L200), `ActionApprovalModel` is loaded with a non-locking `SELECT` (`L117`), `record.status != ActionStatus.PENDING_CONFIRMATION.value` is checked in Python (`L148`), `_current_policy` runs (`L164`), and `_execute_action` executes (`L195`) before `record.status = ActionStatus.COMPLETED.value` is set (`L197`).
  - Unlike Red `/verify` (`mfa.claim_challenge`), Yellow `/confirm` performs no atomic action-status claim prior to execution. Two concurrent `/confirm` requests for the same `action_id` (`act_dup_yellow`) both succeed (`COMPLETED`) with different `audit_id`s, creating **two ledger transactions (`tx_count=2`)** and **two execution audit entries (`audit_count=2`)** while overwriting `AccountModel` from stale ORM state.
- **Ownership**: **P2 (Primary Runtime Owner)** for atomic action claiming and execution serialization in `backend/app/api/approvals.py` and `backend/app/services/executor.py`; **P4** for security requirements and concurrency regression evidence.
- **Test Environment**: File-backed SQLite (`dup_yellow.db` under `pytest` `tmp_path`). **PostgreSQL concurrency has not been verified.**

### Defect 2 — Concurrent Yellow Transfers Bypass Cumulative Daily Threshold Without MFA (M-06 / M-09)
- **Test Name**: `backend/tests/test_security_concurrency.py::test_concurrent_yellow_transfers_cannot_bypass_cumulative_daily_threshold`
- **Observed Failure**:
  ```text
  AssertionError: Both 600 CNY Yellow transfers must not complete without MFA:
    outcomes=[('act_yellow_600_2', 'ok', <ActionStatus.COMPLETED: 'COMPLETED'>, 'aud_1458c4b581'),
              ('act_yellow_600_1', 'ok', <ActionStatus.COMPLETED: 'COMPLETED'>, 'aud_fa3b31b41b')],
    statuses=(COMPLETED, COMPLETED), tiers=(YELLOW, YELLOW),
    tx_count=2, exec_audit_count=2, balance=14650.00, daily_total=600.00
  assert 2 == 1
  ```
- **Security Impact**:
  - When `daily_transfer_total` starts at `0.00 CNY` and two separate `600.00 CNY` Yellow transfers (`act_yellow_600_1` and `act_yellow_600_2`, combined `1,200.00 CNY > 1,000.00 CNY` threshold) are confirmed concurrently, both worker threads read the same stale `daily_transfer_total == 0.00 CNY` in [`_current_policy`](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L50-L63).
  - Both transfers pass the `1,000.00 CNY` cumulative daily threshold check as `Tier.YELLOW` (`0.00 + 600.00 <= 1000.00`) and **both execute to `COMPLETED` without MFA** (`tx_count=2`, `exec_audit_count=2`), completely bypassing Red-tier MFA escalation. In addition, unserialized ORM writes lose one update on `AccountModel.balance` (`14,650.00 CNY` instead of `14,050.00 CNY`) and `daily_transfer_total` (`600.00 CNY` instead of `1,200.00 CNY`).
- **Ownership**: **P2 (Primary Runtime Owner)** for account-level serialization and atomic state updates in `backend/app/api/approvals.py` and `backend/app/services/executor.py` (with **P3** coordination if MFA challenge issuance is touched); **P4** for policy escalation semantics and concurrency regression evidence.
- **Test Environment**: File-backed SQLite (`threshold_race.db` under `pytest` `tmp_path`). **PostgreSQL concurrency has not been verified.**

### Defect 3 — Concurrent Transfers Exceeding Available Balance Both Succeed / Lost ORM Updates (M-09)
- **Test Name**: `backend/tests/test_security_concurrency.py::test_concurrent_transfers_exceeding_balance_cannot_both_succeed`
- **Observed Failure**:
  ```text
  AssertionError: Expected exactly 1 COMPLETED transfer:
    outcomes=[('act_bal_400_2', 'ok', <ActionStatus.COMPLETED: 'COMPLETED'>, 'aud_a33c97512e'),
              ('act_bal_400_1', 'ok', <ActionStatus.COMPLETED: 'COMPLETED'>, 'aud_fa0b03339a')],
    statuses=(COMPLETED, COMPLETED), tx_count=2, exec_audit_count=2,
    balance=100.00, daily_total=400.00
  assert 2 == 1
  ```
- **Security Impact**:
  - When `AccountModel.balance` starts at `500.00 CNY` and two `400.00 CNY` transfers (`act_bal_400_1` and `act_bal_400_2`, combined `800.00 CNY > 500.00 CNY` available balance) are confirmed concurrently, both requests read `account.balance == 500.00 >= 400.00` in [`execute_transfer`](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/executor.py#L29-L50).
  - **Both transfers succeed (`statuses=(COMPLETED, COMPLETED)`, `tx_count=2`, `exec_audit_count=2`)**, recording `800.00 CNY` in executed transfer ledger entries against a `500.00 CNY` balance (overdrawn aggregate transfer amount), while lost ORM updates leave `AccountModel.balance` at `100.00 CNY` and `daily_transfer_total` at `400.00 CNY`.
  - **Cross-Action Red `/verify` Impact**: Although P3's `mfa.claim_challenge` serializes duplicate `/verify` calls on a *single* `action_id`, two *different* Red `action_id`s verified concurrently for the same account also call `execute_transfer` and therefore depend on P2's account-level serialization to prevent the same balance overdraft and lost-update race.
- **Ownership**: **P2 (Primary Runtime Owner)** for account-level locking and conditional balance/daily-total updates in `backend/app/services/executor.py` and `backend/app/api/approvals.py`; **P4** for security requirements and concurrency regression evidence.
- **Test Environment**: File-backed SQLite (`insufficient_race.db` under `pytest` `tmp_path`). **PostgreSQL concurrency has not been verified.**

---

## 4. Detailed Scenario Analysis

### Scenario 1: Policy Decisions for Green, Yellow, and Red

#### M-01A — Pure Policy & Adapter Tier Classification (Green / Yellow / Red)
1. **Expected Security Property**:
   - Read-only tools (`get_balance`, `analyze_spending`, `list_subscriptions`) with matching `account_id` return `Tier.GREEN`, `allowed_to_proceed=True`, `requires_confirmation=False`, `requires_mfa=False`, `reason_code="READ_ONLY_ACCESS"`.
   - `request_subscription_cancel` and `request_transfer` with `context.daily_transfer_total + amount <= 1000.00` return `Tier.YELLOW`, `allowed_to_proceed=True`, `requires_confirmation=True`, `requires_mfa=False`.
   - `request_transfer` with `context.daily_transfer_total + amount > 1000.00` returns `Tier.RED`, `allowed_to_proceed=True`, `requires_confirmation=True`, `requires_mfa=True`, `reason_code="TRANSFER_EXCEEDS_DAILY_LIMIT"`.
2. **Existing Test / Evidence**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py) (**84 passed**): `test_t01_get_balance_green`, `test_analyze_spending_green`, `test_list_subscriptions_green`, `test_t02_transfer_within_daily_limit_yellow`, `test_transfer_with_existing_daily_total_within_limit`, `test_transfer_exact_boundary_1000_zero_prior`, `test_transfer_exact_boundary_1000_split`, `test_transfer_exact_boundary_plus_one_cent_zero_prior`, `test_transfer_exact_boundary_plus_one_cent_split`, `test_t03_transfer_exceeds_daily_limit_red`, `test_very_large_transfer_red`, `test_t07_cancel_subscription_yellow`, `test_fixture_driven_expected_cases_matrix`.
   - [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py) (**27 passed**): `test_explicit_use_mock_true_and_false_behavior`, `test_real_mode_invokes_security_policy_evaluate_action_spy`, `test_create_action_record_with_real_policy_preserves_reason_codes`.
   - [backend/tests/test_security_integration.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py) (**16 passed**): `test_http_proposals_call_actual_policy_at_threshold`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 (Security)
5. **Required Follow-Up**: None in `security/`.

#### M-01B — Runtime Green Tool Routing in `POST /api/v1/chat`
1. **Expected Security Property**:
   - Read-only proposals generated during `POST /api/v1/chat` pass through `validate_tool_arguments` and `policy_service.evaluate(proposal, read_context)` before executing database queries.
2. **Existing Test / Evidence**:
   - Implemented in [backend/app/api/chat.py:109-129](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/chat.py#L109-L129).
   - Verified over HTTP for `GET_BALANCE` by `test_locked_balance_read_still_calls_real_p4` in [backend/tests/test_security_integration.py:164-172](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py#L164-L172), confirming `POST /api/v1/chat` invokes `security.policy.evaluate_action` with `ToolName.GET_BALANCE` and `account_locked=True`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P2 (Backend) with P4 (Security)
5. **Required Follow-Up**: None for `GET_BALANCE` routing; see M-03B for cross-account read-only HTTP test parameterization.

#### M-01C — Runtime Yellow Action Creation & Sequential Execution (`request_transfer` and `request_subscription_cancel`)
1. **Expected Security Property**:
   - Yellow proposals persist an `ActionApprovalModel` in `PENDING_CONFIRMATION` and execute upon `POST /api/v1/actions/{action_id}/confirm` with matching `action_digest`.
2. **Existing Test / Evidence**:
   - **`request_transfer` (Real P4 Policy by Default)**: Verified by `test_confirm_rechecks_real_policy_and_replays_without_new_debit` and `test_real_p1_and_real_p4_transfer_roundtrip` in [backend/tests/test_security_integration.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py#L77-L85), and `test_http_chat_real_p1_agent_with_real_p4_policy_end_to_end` in [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py#L410-L460).
   - **`request_subscription_cancel` (Real P4 Policy by Default)**: Verified in pure policy (`test_t07_cancel_subscription_yellow` in [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py#L292-L308)) and in the broader backend test suite (`133 passed, 7 skipped` with `USE_MOCK_SECURITY=false` default).
3. **Current Status**: **PASS** (Sequential execution; concurrent duplicate Yellow `/confirm` is **FAIL / UNFIXED** under **M-08B**).
4. **Responsible Owner**: P4 / P2
5. **Required Follow-Up**: P2 to implement atomic action claiming and account serialization for concurrent `/confirm` requests (see Section 3).

#### M-01D — Runtime Red Action Creation, MFA Challenge, & Sequential Execution (`request_transfer` $> 1,000.00\text{ CNY}$)
1. **Expected Security Property**:
   - Red proposals persist an `ActionApprovalModel` in `PENDING_CONFIRMATION`, transition to `PENDING_MFA` upon `/confirm` (issuing a 6-digit OTP without debiting funds), and execute only upon `POST /api/v1/actions/{action_id}/verify` with a valid, unexpired OTP.
2. **Existing Test / Evidence**:
   - Verified with real P4 policy (`USE_MOCK_SECURITY=false` default) by `test_http_proposals_call_actual_policy_at_threshold`, `test_two_pending_yellow_actions_escalate_after_first_executes`, and `test_policy_rejection_at_verify_cannot_be_overridden_by_correct_otp` in [backend/tests/test_security_integration.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py) (**16 passed**), and all **18 passed** tests in [backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py).
3. **Current Status**: **PASS** (Sequential & single-action Red `/verify`; cross-action concurrent transfers remain subject to **M-09**).
4. **Responsible Owner**: P4 / P2 / P3
5. **Required Follow-Up**: P2 to add account-level serialization in `executor.py` (see Section 3, Defect 3).

---

### Scenario 2: Unknown Tools and Malformed or Injected Arguments

#### M-02A — Unknown / Unwhitelisted Tools (`UNKNOWN_TOOL`)
1. **Expected Security Property**:
   - Any tool name outside `ToolName` (`get_balance`, `analyze_spending`, `list_subscriptions`, `request_transfer`, `request_subscription_cancel`) must be rejected fail-closed (`allowed_to_proceed=False`, `tier=Tier.RED`, `reason_code="UNKNOWN_TOOL"`).
   - At execution time (`/confirm` and `/verify`), `_current_policy` and `_execute_action` must refuse any tool other than `request_transfer` and `request_subscription_cancel`.
2. **Existing Test / Evidence**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py): `test_unknown_tool_object_rejected`, `test_action_proposal_with_unrecognized_tool_string_returns_unknown_tool`.
   - [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py): `test_unknown_tool_rejected_in_real_mode`, `test_create_action_record_with_real_policy_preserves_reason_codes`.
   - [backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py): `test_unknown_tool_fails_closed_at_verify`.
3. **Current Status**: **PASS** (Real P4 policy is active by default via `USE_MOCK_SECURITY=false`).
4. **Responsible Owner**: P4 / P2 / P3
5. **Required Follow-Up**: None.

#### M-02B — Malformed, Negative, Non-Finite, Overlong, or Injected Arguments (`INVALID_TOOL_ARGUMENTS`)
1. **Expected Security Property**:
   - All tool arguments are validated against `contracts/tool_schemas.py` (`StrictModel` with `extra="forbid"`, `PositiveMoney` with `gt=0, max_digits=16, decimal_places=2`, `ID` with `min_length=1, max_length=128`, `currency: Literal["CNY"] = "CNY"`, and `period` regex `^\d{4}-(0[1-9]|1[0-2])$`).
   - Negative, zero, `-0.00`, `NaN`, `Inf`, `-Inf`, $>2$ decimal places, $>16$ digits, lowercase `"cny"`, `"USD"`, missing/null/empty IDs, IDs $>128$ chars, and injected fields (`bypass_mfa`, `admin`, `mfa_verified`, `user_id`, `action_id`, `action_digest`, `tier`) must be rejected with `INVALID_TOOL_ARGUMENTS`.
2. **Existing Test / Evidence**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py) (**84 passed**) and [tests/test_contracts.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/tests/test_contracts.py) (**14 passed**).
   - [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py) (**27 passed**): `test_meaningful_distinction_between_mock_and_real_policy_decisions`, `test_create_action_record_with_real_policy_preserves_reason_codes`.
   - [backend/tests/test_security_integration.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py) (**16 passed**): `test_invalid_agent_arguments_do_not_issue_tickets` (verifying over HTTP `/api/v1/chat` that `-1.00`, `1.001`, injected `user_id`, and injected `action_id` are rejected with `INVALID_TOOL_ARGUMENTS` and create `0` DB rows).
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 / P2
5. **Required Follow-Up**: None.

#### M-02C — Clean `payload_json` Persistence & Stored-Payload Tampering Rejection (`INVALID_STORED_ACTION`)
1. **Expected Security Property**:
   - Server approval metadata (`action_id`, `action_digest`, `tier`) is added to the HTTP response proposal only *after* `create_action_record` validates canonical arguments, evaluates policy, and persists clean `payload_json`.
   - At execution time (`/confirm` and `/verify`), `_current_policy` re-validates `record.payload_json` against `validate_tool_arguments` and verifies `compute_action_digest(record.tool, payload) == record.action_digest`, rejecting any stored-row tampering with HTTP `403` (`INVALID_STORED_ACTION`).
2. **Existing Test / Evidence**:
   - [backend/tests/test_security_integration.py:134-144](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py#L134-L144): `test_stored_payload_tampering_blocks_execution`.
   - [security/tests/test_policy.py:1561-1606](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py#L1561-L1606): `test_server_approval_metadata_injected_into_arguments_rejected`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P2 / P4
5. **Required Follow-Up**: Separating UI tracking fields from `proposal.arguments` into dedicated response fields remains future contract cleanup noted in `docs/app/p4_integration.md`.

---

### Scenario 3: Account Ownership, Source-Account Mismatch, and Locked-Account Rejection

#### M-03A — Cross-Account Transfer Spoofing (`SOURCE_ACCOUNT_MISMATCH`)
1. **Expected Security Property**:
   - If `proposal.arguments["source_account_id"] != context.account_id`, the proposal must be rejected with `allowed_to_proceed=False`, `tier=Tier.RED`, and `reason_code="SOURCE_ACCOUNT_MISMATCH"`.
2. **Existing Test / Evidence**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py): `test_transfer_source_account_mismatch_rejected`, `test_cross_tenant_transfer_source_account_mismatch`.
   - [backend/tests/test_security_bridge.py:338-408](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py#L338-L408): `test_http_chat_differential_proof_mock_allows_vs_real_policy_rejects`.
   - [backend/tests/test_security_integration.py:115-131](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py#L115-L131): `test_invalid_agent_arguments_do_not_issue_tickets[{"source_account_id": "foreign_account"}, "SOURCE_ACCOUNT_MISMATCH"]`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 / P2
5. **Required Follow-Up**: None.

#### M-03B — Cross-Account Read-Only Query (`ACCOUNT_MISMATCH`)
1. **Expected Security Property**:
   - Read-only tool calls (`get_balance`, `analyze_spending`, `list_subscriptions`) specifying `account_id != context.account_id` must be rejected with `ACCOUNT_MISMATCH`.
2. **Existing Test / Evidence**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py): `test_get_balance_account_mismatch_rejected`, `test_cross_tenant_query_account_mismatch`, `test_analyze_spending_account_mismatch_rejected`, `test_list_subscriptions_account_mismatch_rejected`.
   - [backend/app/api/chat.py:114-129](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/chat.py#L114-L129): `chat.py` validates read tool arguments and invokes `policy_service.evaluate(proposal, read_context)`. `test_locked_balance_read_still_calls_real_p4` ([backend/tests/test_security_integration.py:164-172](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py#L164-L172)) verifies that `/api/v1/chat` invokes real P4 on `GET_BALANCE`.
3. **Current Status**: **PASS** (Policy Layer & `GET_BALANCE` HTTP policy invocation) / **PARTIAL** (Cross-account read rejection over HTTP is wired in `chat.py:114-129` but not separately parameterized in `test_security_integration.py`).
4. **Responsible Owner**: P2 / P4
5. **Required Follow-Up**: Optional HTTP test case for mismatched `account_id` on read tools.

#### M-03C — Locked-Account Rejection at Proposal Time (`ACCOUNT_LOCKED`)
1. **Expected Security Property**:
   - When `context.account_locked=True` (populated from `UserModel.is_locked`), all state-changing proposals (`request_transfer`, `request_subscription_cancel`) are rejected with `ACCOUNT_LOCKED` (`allowed_to_proceed=False`, `tier=Tier.RED`). Read-only queries remain available by default (`READ_ONLY_ACCESS`) unless `PolicyConfig(lock_denies_read_only=True)` is configured.
2. **Existing Test / Evidence**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py): `test_t11_locked_account_rejects_transfer`, `test_locked_account_rejects_subscription_cancellation`, `test_locked_account_allows_read_only_by_default`, `test_locked_account_denies_read_only_when_configured`, `test_locked_account_read_only_tools_analyze_and_subscriptions`, `test_locked_account_precedes_source_account_mismatch`.
   - [backend/tests/test_security_integration.py:164-172](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py#L164-L172): `test_locked_balance_read_still_calls_real_p4`.
   - [backend/tests/test_policy.py:86-109](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_policy.py#L86-L109): `test_locked_user_can_check_balance_but_cannot_transfer` (passes within the 133-passed broader backend suite under default `USE_MOCK_SECURITY=false`).
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 / P2
5. **Required Follow-Up**: None.

---

### Scenario 4: Real Policy Evaluation Through the Backend Adapter

#### M-04A & M-04B — `SecurityAdapterService` Configuration & Default Real Policy Mode
1. **Expected Security Property**:
   - `SecurityAdapterService(use_mock: bool | None = None)` strictly validates `use_mock` (raising `ValueError` on non-booleans) and `USE_MOCK_SECURITY` (accepting only case-insensitive `"true"` or `"false"`, raising `ValueError` on any other string or whitespace-padded value).
   - When `USE_MOCK_SECURITY` is unset, `SecurityAdapterService` defaults to `use_mock=False` ([backend/app/services/adapters.py:151](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/adapters.py#L151)), selecting the real P4 policy engine by default.
   - `MockAgentAdapter` ([backend/app/mocks/agent.py:70,133,164](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/mocks/agent.py#L70)) includes `source_account_id`, so default mock-agent tests and MFA suites run against the real P4 policy engine without regression.
2. **Existing Test / Evidence**:
   - [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py): **27 passed** (`test_security_adapter_environment_and_default_selection`, `test_security_adapter_rejects_invalid_env_values_and_allows_explicit_override`, `test_security_adapter_rejects_non_boolean_constructor_arguments`, `test_real_mode_invokes_security_policy_evaluate_action_spy`, `test_http_chat_differential_proof_mock_allows_vs_real_policy_rejects`, `test_http_chat_real_p1_agent_with_real_p4_policy_end_to_end`).
   - [backend/tests/test_security_integration.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py): **16 passed** (`test_mode_selection_is_explicit`).
   - [backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py): **18 passed**.
   - Broader backend suite (`backend/tests` excluding `test_security_concurrency.py`): **133 passed, 7 skipped**.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 (Adapter Bridge) / P2 (`MockAgentAdapter` & `actions.py`)
5. **Required Follow-Up**: None.

---

### Scenario 5: Yellow Confirmation After Account Lock

#### M-05 — Account Lock Enforcement After Proposal Creation (`/chat` $\rightarrow$ `/confirm`)
1. **Expected Security Property**:
   - If `UserModel.is_locked` becomes `True` *after* a Yellow action is proposed (`PENDING_CONFIRMATION`) but *before* `POST /api/v1/actions/{action_id}/confirm` is called, `/confirm` re-evaluates policy via `_current_policy`, marks the action `ActionStatus.REJECTED`, writes an `ACTION_POLICY_REJECTED` audit log (`reason_code="ACCOUNT_LOCKED"`), returns HTTP `403`, and leaves account balance unchanged.
2. **Existing Test / Evidence**:
   - Implemented in [backend/app/api/approvals.py:22-89, 164](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L22-L89).
   - Verified by `test_new_lock_blocks_yellow_confirm` in [backend/tests/test_security_integration.py:106-112](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py#L106-L112).
3. **Current Status**: **PASS** (Sequential)
4. **Responsible Owner**: P2 (Backend) with P4 (Security)
5. **Required Follow-Up**: Pair `_current_policy` with atomic action/account serialization under concurrent execution (see Section 3).

---

### Scenario 6: Yellow-to-Red Escalation When Cumulative Daily Transfers Change

#### M-06 — Cumulative Daily Limit Escalation Between Proposal and Confirmation (Sequential vs. Concurrent)
1. **Expected Security Property**:
   - When two Yellow transfers whose combined amount exceeds `1,000.00 CNY` are proposed while `daily_transfer_total` is low, confirming the second transfer after (or concurrently with) the first must not allow both to execute as Yellow without MFA. The second transfer must re-evaluate against the updated `daily_transfer_total`, escalate from `Tier.YELLOW` to `Tier.RED` (`ActionStatus.PENDING_MFA`), and issue an OTP challenge without debiting funds.
2. **Existing Test / Evidence**:
   - **Sequential Escalation (`PASS`)**: Implemented in [`approvals.confirm_action`](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L164-L192) and verified by `test_two_pending_yellow_actions_escalate_after_first_executes` in [backend/tests/test_security_integration.py:87-104](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py#L87-L104).
   - **Concurrent Escalation (`FAIL / UNFIXED`)**: `test_concurrent_yellow_transfers_cannot_bypass_cumulative_daily_threshold` in [backend/tests/test_security_concurrency.py:195-343](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_concurrency.py#L195-L343) **fails** because two concurrent `600.00 CNY` confirmations both read stale `daily_transfer_total == 0.00 CNY` in `_current_policy` and both complete as `YELLOW` without MFA (see Section 3, **Defect 2**).
3. **Current Status**: **PASS (Sequential)** / **FAIL / UNFIXED (Concurrent)**
4. **Responsible Owner**: P2 (Runtime Serialization) & P3 (MFA) with P4 (Policy & Concurrency Test)
5. **Required Follow-Up**: P2 to serialize same-account confirmations/executions before reading `daily_transfer_total` in `_current_policy` and `execute_transfer`.

---

### Scenario 7: Red MFA Verification After Account Lock & Execution-Time Policy Re-Evaluation

#### M-07A — Account Lock Check at Red `/verify`
1. **Expected Security Property**:
   - If a Red action is in `PENDING_MFA` and `UserModel.is_locked` becomes `True` before `POST /api/v1/actions/{action_id}/verify` is called with the valid OTP code, `/verify` rejects execution (`403`), marks the action `REJECTED`, and leaves the account balance unchanged.
2. **Existing Test / Evidence**:
   - Implemented via `_current_policy(db, user, record)` at [backend/app/api/approvals.py:302](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L302).
   - Verified by `test_account_locked_after_confirm_blocks_execution` in [backend/tests/test_mfa.py:227-237](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py#L227-L237).
3. **Current Status**: **PASS**
4. **Responsible Owner**: P3 / P2
5. **Required Follow-Up**: None.

#### M-07B — Execution-Time Policy Re-Evaluation (`_current_policy`) in `/confirm` and `/verify`
1. **Expected Security Property**:
   - Both `/confirm` and `/verify` reconstruct `ActionProposal` from `record.payload_json`, verify `action_digest`, refresh user/account state, and call `policy_service.evaluate(proposal, context)` prior to executing any state mutation. A valid OTP cannot override a policy rejection at `/verify`.
2. **Existing Test / Evidence**:
   - Implemented in [backend/app/api/approvals.py:22-89, 164, 302](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L22-L89).
   - Verified by `test_confirm_rechecks_real_policy_and_replays_without_new_debit` and `test_policy_rejection_at_verify_cannot_be_overridden_by_correct_otp` in [backend/tests/test_security_integration.py:77-85, 146-162](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py#L77-L85).
3. **Current Status**: **PASS (Sequential)** (Does not provide concurrent account/action serialization; see **M-08B** and **M-09**).
4. **Responsible Owner**: P2 / P3 / P4
5. **Required Follow-Up**: Pair `_current_policy` with account-level locking/serialization (P2).

---

### Scenario 8: Concurrent Confirmation / Verification of the Same Action

#### M-08A — Concurrent Red MFA Verification (`POST /api/v1/actions/{action_id}/verify`)
1. **Expected Security Property**:
   - Two simultaneous `/verify` requests submitting the valid OTP for the **same `action_id`** must result in at most one execution (`COMPLETED`) and one `409 Conflict` rejection, debiting the account once.
2. **Existing Test / Evidence**:
   - Implemented via atomic conditional SQL update in [backend/app/services/mfa.py:110-132](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/mfa.py#L110-L132) (`claim_challenge`).
   - Verified on file-backed SQLite by `test_concurrent_verify_loser_is_rejected_without_debit` and multi-threaded `test_truly_concurrent_verifies_debit_once` in [backend/tests/test_mfa.py:150-163, 338-414](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py#L338-L414).
3. **Current Status**: **PASS (Same-Action on File-Backed SQLite)** / **NOT VERIFIED (PostgreSQL)**. *(Note: Concurrent `/verify` calls across two **different** Red `action_id`s on the same account still depend on P2's `execute_transfer` account serialization under **M-09**.)*
4. **Responsible Owner**: P3 (MFA) / P2 (Executor Account Serialization)
5. **Required Follow-Up**: P2 account serialization in `executor.py` for cross-action Red `/verify`; PostgreSQL concurrency verification remains unverified.

#### M-08B — Concurrent Yellow Confirmation of the Same Action (`POST /api/v1/actions/{action_id}/confirm`)
1. **Expected Security Property**:
   - Two simultaneous `/confirm` requests for the **same `action_id`** in `PENDING_CONFIRMATION` must result in at most one transfer execution and debit (`tx_count == 1`, `audit_count == 1`), with the second request receiving `409 Conflict` or returning the idempotent `COMPLETED` result with the same `audit_id`.
2. **Existing Test / Evidence**:
   - Sequential replay after completion passes (`test_confirm_rechecks_real_policy_and_replays_without_new_debit` in [backend/tests/test_security_integration.py:77-85](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py#L77-L85)).
   - Concurrent execution **fails** in `test_concurrent_duplicate_yellow_confirm_executes_at_most_once` ([backend/tests/test_security_concurrency.py:70-192](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_concurrency.py#L70-L192)): both threads execute `execute_transfer`, creating 2 ledger transactions and 2 execution audit entries (see Section 3, **Defect 1**).
3. **Current Status**: **FAIL / UNFIXED** (Reproduced on file-backed SQLite; PostgreSQL concurrency **NOT VERIFIED**).
4. **Responsible Owner**: P2 (Backend Runtime) / P4 (Regression Test)
5. **Required Follow-Up**: P2 to add an atomic conditional claim on `ActionApprovalModel` and account serialization before `_execute_action`.

---

### Scenario 9: Concurrent Transfers Against the Same Account Across Distinct Action IDs

#### M-09 — Competing Transfers Across Different `action_id`s on the Same Account
1. **Expected Security Property**:
   - Concurrent confirmations/verifications of two **different transfer actions (`act_1` and `act_2`)** drawing from the same `account_id` must serialize policy re-evaluation, balance checks, and `daily_transfer_total` updates so that:
     1. Two concurrent Yellow transfers (`600 CNY + 600 CNY > 1,000 CNY`) cannot both pass `_current_policy` as Yellow and execute without MFA.
     2. Two concurrent transfers (`400 CNY + 400 CNY > 500 CNY` balance) cannot both pass `account.balance < amount` in `execute_transfer` and overdraw/corrupt the account balance and daily transfer total.
2. **Existing Test / Evidence**:
   - Reproduced as **failing** in [backend/tests/test_security_concurrency.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_concurrency.py):
     - `test_concurrent_yellow_transfers_cannot_bypass_cumulative_daily_threshold` (**FAILED** — see Section 3, **Defect 2**).
     - `test_concurrent_transfers_exceeding_balance_cannot_both_succeed` (**FAILED** — see Section 3, **Defect 3**).
3. **Current Status**: **FAIL / UNFIXED** (Reproduced on file-backed SQLite; PostgreSQL concurrency **NOT VERIFIED**).
4. **Responsible Owner**: P2 (Backend Runtime) / P4 (Regression Test)
5. **Required Follow-Up**: P2 to implement account-level serialization and atomic conditional balance/daily-total updates in `approvals.py` and `executor.py`.

---

### Scenario 10: Rejection Reason Codes and Audit Linkage

#### M-10A — Deterministic Policy Reason Codes & Successful Execution Audit Linkage
1. **Expected Security Property**:
   - Every policy decision returns an explicit `SecurityReasonCode` (`security/rules.py:15-40`).
   - Every executed transfer, subscription cancellation, and issued MFA challenge creates an `AuditLogModel` record linked by `action_id`, `user_id`, `payload_digest`, and `audit_id`.
2. **Existing Test / Evidence**:
   - Verified across **84 passed** tests in [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py), **27 passed** tests in [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py), and **18 passed** tests in [backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py).
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 / P2 / P3
5. **Required Follow-Up**: None for sequential execution audit logs.

#### M-10B — Rejection Reason Code Surfacing in `POST /api/v1/chat` and Execution-Time Rejection Auditing
1. **Expected Security Property**:
   - When `create_action_record` rejects a proposal with `PolicyRejected(reason_code)`, `POST /api/v1/chat` surfaces the specific `reason_code` and explanation in `ChatOutput.reply` with `status=ActionStatus.REJECTED` (rather than claiming every rejection is an account lock).
   - Execution-time policy rejections in `_current_policy` (`/confirm` and `/verify`) record an `AuditLogModel` entry (`action_type="ACTION_POLICY_REJECTED"`, `reason_code=reason`).
2. **Existing Test / Evidence**:
   - Implemented in [backend/app/api/chat.py:242-259](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/chat.py#L242-L259) and [backend/app/api/approvals.py:81-88](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L81-L88).
   - Verified by `test_invalid_agent_arguments_do_not_issue_tickets` (`assert reason in result["reply"] and "account is currently locked" not in result["reply"]`) in [backend/tests/test_security_integration.py:115-131](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_integration.py#L115-L131).
3. **Current Status**: **PASS**
4. **Responsible Owner**: P2 / P3 / P4
5. **Required Follow-Up**: None.

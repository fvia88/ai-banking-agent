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
2. **Opt-in real-policy tests (`USE_MOCK_SECURITY=false` / `use_mock=False`) are explicitly distinguished from the default runtime configuration**, where `USE_MOCK_SECURITY` defaults to `"true"` in [backend/app/services/adapters.py:151](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/adapters.py#L151) and activates `MockSecurityAdapter` unless overridden.

### Status Legend
- **`PASS`**: Property is implemented and verified by automated tests at the specified layer and mode.
- **`FAIL / UNFIXED`**: Inspected runtime code violates the expected security property (vulnerability or defect confirmed unfixed).
- **`NOT TESTED`**: Runtime behavior (such as a multi-threaded concurrency race or specific real-mode HTTP path) is not covered by automated tests.
- **`BLOCKED`**: Policy implementation and bridge tests exist, but end-to-end runtime activation depends on changes in shared files owned by Person 2 (Backend) or Person 3 (MFA).

---

## 2. Summary Matrix

| ID | Scenario | Layer | Current Status | Owner |
| :--- | :--- | :--- | :---: | :---: |
| **M-01A** | Policy decisions: Tier GREEN (`get_balance`, `analyze_spending`, `list_subscriptions`) | Pure Policy & Opt-in Real Adapter (`use_mock=False`) | **PASS** | P4 |
| **M-01B** | Tier GREEN routing through `POST /api/v1/chat` | Runtime HTTP (`chat.py`) | **BLOCKED** (Bypasses `policy_service`) | P2 / P4 |
| **M-01C** | Policy decisions: Tier YELLOW (`request_transfer` cumulative $\le 1,000.00\text{ CNY}$, `request_subscription_cancel`) | Pure Policy (**PASS**); E2E HTTP Real P1 + Real P4 for transfer (**PASS**); HTTP subscription cancel (**PASS** in Mock Policy / **NOT TESTED** in Real Policy HTTP) | **PASS** (Transfer Real E2E) / **PARTIAL** (Sub Cancel HTTP Mock-Only) | P4 / P2 |
| **M-01D** | Policy decisions: Tier RED (`request_transfer` cumulative $> 1,000.00\text{ CNY}$, requires confirmation + MFA) | Pure Policy & Service `create_action_record` (`use_mock=False`: **PASS**); Full HTTP `/chat` $\rightarrow$ `/confirm` $\rightarrow$ `/verify` (**PASS** in Mock Policy / **NOT TESTED** in Real Policy HTTP) | **PASS** (Policy & Service Real Mode; HTTP Mock Mode) | P4 / P2 / P3 |
| **M-02A** | Unknown / unwhitelisted tools rejected fail-closed (`UNKNOWN_TOOL`) | Pure Policy, Opt-in Real Adapter, `create_action_record`, & `/verify` dispatch (**PASS**) vs. Default Mock Policy Runtime (**FAIL**) | **PASS** (Opt-in Real Mode & `/verify`) / **FAIL** (Default Mock Runtime) | P4 / P2 / P3 |
| **M-02B** | Malformed, negative, non-finite, over-precision, or extra injected arguments (`INVALID_TOOL_ARGUMENTS`) | Pure Policy & Opt-in Real Adapter (`use_mock=False`: **PASS**) vs. Default Mock Policy Runtime (**FAIL**) | **PASS** (Opt-in Real Mode) / **FAIL** (Default Mock Runtime) | P4 / P2 |
| **M-02C** | Server metadata (`action_id`, `action_digest`, `tier`) mutated in-place on `proposal.arguments` | Runtime HTTP (`chat.py:227-232`) | **BLOCKED** | P2 / P4 |
| **M-03A** | Cross-account transfer spoofing (`source_account_id != context.account_id` $\rightarrow$ `SOURCE_ACCOUNT_MISMATCH`) | Pure Policy & Opt-in Real HTTP `/api/v1/chat` (`use_mock=False`) vs. Default Mock Policy Runtime (`use_mock=True`) | **PASS** (Opt-in Real Mode) / **FAIL** (Default Mock Runtime) | P4 / P2 |
| **M-03B** | Cross-account read-only query (`account_id != context.account_id` $\rightarrow$ `ACCOUNT_MISMATCH`) | Pure Policy (**PASS**) vs. Runtime HTTP `chat.py` (**BLOCKED**) | **PASS** (Policy) / **BLOCKED** (Runtime HTTP) | P2 / P4 |
| **M-03C** | Locked-account mutation rejection at proposal time (`ACCOUNT_LOCKED`) | Pure Policy (`use_mock=False`: **PASS**); Runtime HTTP `POST /api/v1/chat` (**PASS** in Mock Policy / **BLOCKED** in Real Policy + Mock Agent) | **PASS** (Policy & Mock HTTP) / **BLOCKED** (Real Policy + Mock Agent) | P4 / P2 |
| **M-04A** | Real policy evaluation through `SecurityAdapterService` (`USE_MOCK_SECURITY=false` / `use_mock=False`) | Adapter & HTTP Bridge (`adapters.py`) | **PASS** (Opt-in Real Mode; Disabled by Default `USE_MOCK_SECURITY="true"`) | P4 |
| **M-04B** | Enabling `USE_MOCK_SECURITY=false` by default while `USE_MOCK_AGENT=true` (`MockAgentAdapter` omits `source_account_id`) | Runtime Default Config (`adapters.py`, `app/mocks/agent.py`, `actions.py`) | **BLOCKED** | P2 |
| **M-05** | Yellow confirmation after account lock (TOCTOU between `/chat` and `/confirm`) | Runtime HTTP (`approvals.py:35-128`) | **FAIL / UNFIXED** | P2 / P4 |
| **M-06** | Yellow-to-Red escalation when cumulative daily transfers change before `/confirm` | Runtime HTTP (`approvals.py:90-128`) | **FAIL / UNFIXED** | P2 / P3 / P4 |
| **M-07A** | Red MFA verification after account lock (`UserModel.is_locked` check at `/verify`) | Runtime HTTP (`approvals.py:216-222`) | **PASS** | P3 |
| **M-07B** | Execution-time policy re-evaluation (`policy_service.evaluate`) in `/confirm` and `/verify` | Runtime HTTP (`approvals.py:89, 223-224`) | **FAIL / UNFIXED** (Not Implemented; `TODO(P4)` in `/verify`) | P2 / P3 / P4 |
| **M-08A** | Concurrent Red MFA verification of the same `action_id` (`POST /api/v1/actions/{id}/verify`) | Runtime HTTP & DB (`mfa.py:110-127`, `approvals.py:227`) | **PASS** | P3 |
| **M-08B** | Concurrent Yellow confirmation of the same `action_id` (`POST /api/v1/actions/{id}/confirm`) | Runtime HTTP & DB (`approvals.py:42-121`) | **FAIL / UNFIXED** (By Code Inspection; Concurrency Race **NOT TESTED**) | P2 |
| **M-09** | Competing transfers against the same account across distinct `action_id`s (balance & daily limit race) | Runtime Executor & DB (`executor.py:28-50`) | **FAIL / UNFIXED** (By Code Inspection; Concurrency Race **NOT TESTED**) | P2 |
| **M-10A** | Canonical rejection reason codes returned by policy and `create_action_record` | Pure Policy & Service (`security/rules.py`, `actions.py:108-109`) | **PASS** | P4 / P2 |
| **M-10B** | Rejection reason code propagation and audit logging in `POST /api/v1/chat` and `/confirm` rejections | Runtime HTTP (`chat.py:234-240`, `approvals.py`) | **FAIL / UNFIXED** | P2 / P3 |

---

## 3. Detailed Scenario Analysis

### Scenario 1: Policy Decisions for Green, Yellow, and Red

#### M-01A — Pure Policy & Adapter Tier Classification (Green / Yellow / Red)
1. **Expected Security Property**:
   - Read-only tools (`get_balance`, `analyze_spending`, `list_subscriptions`) with matching `account_id` return `Tier.GREEN`, `allowed_to_proceed=True`, `requires_confirmation=False`, `requires_mfa=False`, `reason_code="READ_ONLY_ACCESS"`.
   - `request_subscription_cancel` and `request_transfer` with `context.daily_transfer_total + amount <= 1000.00` return `Tier.YELLOW`, `allowed_to_proceed=True`, `requires_confirmation=True`, `requires_mfa=False`.
   - `request_transfer` with `context.daily_transfer_total + amount > 1000.00` returns `Tier.RED`, `allowed_to_proceed=True`, `requires_confirmation=True`, `requires_mfa=True`, `reason_code="TRANSFER_EXCEEDS_DAILY_LIMIT"`.
2. **Existing Test / Evidence**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py): `test_t01_get_balance_green`, `test_analyze_spending_green`, `test_list_subscriptions_green`, `test_t02_transfer_within_daily_limit_yellow`, `test_transfer_with_existing_daily_total_within_limit`, `test_transfer_exact_boundary_1000_zero_prior`, `test_transfer_exact_boundary_1000_split`, `test_transfer_exact_boundary_plus_one_cent_zero_prior`, `test_transfer_exact_boundary_plus_one_cent_split`, `test_t03_transfer_exceeds_daily_limit_red`, `test_very_large_transfer_red`, `test_t07_cancel_subscription_yellow`, `test_fixture_driven_expected_cases_matrix`.
   - [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py): `test_explicit_use_mock_true_and_false_behavior`, `test_real_mode_invokes_security_policy_evaluate_action_spy`, `test_create_action_record_with_real_policy_preserves_reason_codes`.
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 (Security)
5. **Required Follow-Up**: None in `security/`.

#### M-01B — Runtime Green Tool Routing in `POST /api/v1/chat`
1. **Expected Security Property**:
   - Read-only proposals generated during `POST /api/v1/chat` should pass through `policy_service.evaluate(proposal, context)` before executing database queries so that `ACCOUNT_MISMATCH`, `INVALID_TOOL_ARGUMENTS` (e.g., malformed `period`), and `PolicyConfig(lock_denies_read_only=True)` are enforced uniformly.
2. **Existing Test / Evidence**:
   - Code inspection of [backend/app/api/chat.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/chat.py#L104-L200) confirms that when `result.proposals[0].tool.value in READ_TOOLS`, `chat.py` executes the read-only query directly without calling `policy_service.evaluate()`.
3. **Current Status**: **BLOCKED** (Policy supports Green evaluation, but `chat.py` bypasses `policy_service` on the read-only double-hop path).
4. **Responsible Owner**: P2 (Backend) with P4 (Security)
5. **Required Follow-Up**: P2 to invoke `policy_service.evaluate(proposal, context)` in `chat.py` before executing read-only tools.

#### M-01C — Runtime Yellow Action Creation & Execution (`request_transfer` and `request_subscription_cancel`)
1. **Expected Security Property**:
   - Yellow proposals persist an `ActionApprovalModel` in `PENDING_CONFIRMATION` and execute upon `POST /api/v1/actions/{action_id}/confirm` with matching `action_digest`.
2. **Existing Test / Evidence**:
   - **`request_transfer` (Opt-in Real P1 + Real P4 HTTP E2E)**: Verified by `test_http_chat_real_p1_agent_with_real_p4_policy_end_to_end` in [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py#L410-L460) and service-level `test_create_action_record_with_real_policy_preserves_reason_codes` ([backend/tests/test_security_bridge.py:243-260](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py#L243-L260)). Also verified in default mock mode by `test_confirm_yellow_action_completes_successfully` ([backend/tests/test_approvals.py:6-28](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_approvals.py#L6-L28)).
   - **`request_subscription_cancel`**: Verified in pure policy by `test_t07_cancel_subscription_yellow` ([security/tests/test_policy.py:292-308](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py#L292-L308)) and over HTTP in **default mock-policy mode (`policy_service.use_mock=True`)** by `test_t07_cancel_subscription_yellow_tier_and_execution` ([backend/tests/test_subscriptions.py:47-88](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_subscriptions.py#L47-L88)) and `test_real_cancellation_selection_uses_saved_draft` ([backend/tests/test_p1_integration.py:148-156](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_p1_integration.py#L148-L156)). Not yet tested over HTTP with `policy_service.use_mock=False`.
3. **Current Status**: **PASS** (`request_transfer` in Opt-in Real P1 + Real P4 E2E HTTP) / **PARTIAL** (`request_subscription_cancel` verified in Pure Policy and Mock-Policy HTTP; **NOT TESTED** in Real-Policy HTTP).
4. **Responsible Owner**: P4 / P2
5. **Required Follow-Up**: Fix `MockAgentAdapter` in `backend/app/mocks/agent.py` to populate `source_account_id` so default runtime can switch to `USE_MOCK_SECURITY=false`.

#### M-01D — Runtime Red Action Creation, MFA Challenge, & Execution (`request_transfer` $> 1,000.00\text{ CNY}$)
1. **Expected Security Property**:
   - Red proposals persist an `ActionApprovalModel` in `PENDING_CONFIRMATION`, transition to `PENDING_MFA` upon `/confirm` (issuing a 6-digit OTP without debiting funds), and execute only upon `POST /api/v1/actions/{action_id}/verify` with a valid, unexpired OTP.
2. **Existing Test / Evidence**:
   - **Service Layer with Real Policy (`policy_service.use_mock=False`)**: Verified in `test_create_action_record_with_real_policy_preserves_reason_codes` ([backend/tests/test_security_bridge.py:261-275](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py#L261-L275)).
   - **Full HTTP Lifecycle (`/chat` $\rightarrow$ `/confirm` $\rightarrow$ `/verify`)**: Verified in **default mock-policy mode (`policy_service.use_mock=True`)** by `test_t03_red_tier_flow_requires_mfa_and_completes` ([backend/tests/test_approvals.py:48-85](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_approvals.py#L48-L85)) and `test_red_transfer_debits_once_only_after_valid_mfa` ([backend/tests/test_mfa.py:82-100](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py#L82-L100)). Not yet tested end-to-end over HTTP with `policy_service.use_mock=False` because `_red_action_pending_mfa` uses `MockAgentAdapter` (`source_account_id=None`).
3. **Current Status**: **PASS** (Pure Policy & Service-Layer Real Mode; Full HTTP in Default Mock Mode) / **BLOCKED** (Full HTTP with `USE_MOCK_AGENT=true` + `USE_MOCK_SECURITY=false` blocked on `MockAgentAdapter` omitting `source_account_id`).
4. **Responsible Owner**: P4 / P2 / P3
5. **Required Follow-Up**: Populate `source_account_id` in `MockAgentAdapter` so `test_mfa.py` and `test_approvals.py` can run under `USE_MOCK_SECURITY=false`.

---

### Scenario 2: Unknown Tools and Malformed or Injected Arguments

#### M-02A — Unknown / Unwhitelisted Tools (`UNKNOWN_TOOL`)
1. **Expected Security Property**:
   - Any tool name outside `ToolName` (`get_balance`, `analyze_spending`, `list_subscriptions`, `request_transfer`, `request_subscription_cancel`) must be rejected fail-closed (`allowed_to_proceed=False`, `tier=Tier.RED`, `reason_code="UNKNOWN_TOOL"`).
   - At execution time (`/confirm` and `/verify`), `_execute_action` must refuse any tool other than `request_transfer` and `request_subscription_cancel`.
2. **Existing Test / Evidence**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py): `test_unknown_tool_object_rejected`, `test_action_proposal_with_unrecognized_tool_string_returns_unknown_tool`.
   - [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py): `test_unknown_tool_rejected_in_real_mode` (proving `MockSecurityAdapter` erroneously returns `Tier.GREEN` / `READ_ONLY_AUTOMATIC` while real policy returns `Tier.RED` / `UNKNOWN_TOOL`), `test_create_action_record_with_real_policy_preserves_reason_codes`.
   - [backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py): `test_unknown_tool_fails_closed_at_verify`.
3. **Current Status**: **PASS** (in Opt-in Real Policy Mode `use_mock=False` and `/verify` executor dispatch) / **FAIL** (in Default Mock Policy Runtime `USE_MOCK_SECURITY="true"`, where `MockSecurityAdapter` allows unknown tools as `Tier.GREEN`).
4. **Responsible Owner**: P4 / P2 / P3
5. **Required Follow-Up**: Switch default `USE_MOCK_SECURITY` to `"false"` once P2 updates `MockAgentAdapter`.

#### M-02B — Malformed, Negative, Non-Finite, Overlong, or Injected Arguments (`INVALID_TOOL_ARGUMENTS`)
1. **Expected Security Property**:
   - All tool arguments are validated against `contracts/tool_schemas.py` (`StrictModel` with `extra="forbid"`, `PositiveMoney` with `gt=0, max_digits=16, decimal_places=2`, `ID` with `min_length=1, max_length=128`, `currency: Literal["CNY"] = "CNY"`, and `period` regex `^\d{4}-(0[1-9]|1[0-2])$`).
   - Negative, zero, `-0.00`, `NaN`, `Inf`, `-Inf`, $>2$ decimal places, $>16$ digits, lowercase `"cny"`, `"USD"`, missing/null/empty IDs, IDs $>128$ chars, and injected fields (`bypass_mfa`, `admin`, `mfa_verified`, `action_id`, `action_digest`, `tier`) must be rejected with `INVALID_TOOL_ARGUMENTS`.
2. **Existing Test / Evidence**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py): Verified within the 84 passing collected test items (specifically across Sections 8, 9, 14, 19, and 20) and 14 passing contract tests in [tests/test_contracts.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/tests/test_contracts.py).
   - [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py): `test_meaningful_distinction_between_mock_and_real_policy_decisions`, `test_create_action_record_with_real_policy_preserves_reason_codes`.
3. **Current Status**: **PASS** (in Opt-in Real Policy Mode `use_mock=False`) / **FAIL** (in Default Mock Policy Runtime `USE_MOCK_SECURITY="true"`, where `MockSecurityAdapter` does not enforce `extra="forbid"` or canonical tool schemas).
4. **Responsible Owner**: P4 / P2
5. **Required Follow-Up**: Enable `USE_MOCK_SECURITY=false` by default after P2 coordination.

#### M-02C — In-Place Server Metadata Pollution on `proposal.arguments`
1. **Expected Security Property**:
   - Server approval metadata (`action_id`, `action_digest`, `tier`) must not pollute `ActionProposal.arguments` if that `ActionProposal` instance is ever re-evaluated by `security.policy.evaluate_action` (which enforces `extra="forbid"`).
2. **Existing Test / Evidence**:
   - [backend/app/api/chat.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/chat.py#L227-L232) mutates `proposal.arguments["action_id"]`, `proposal.arguments["action_digest"]`, and `proposal.arguments["tier"]` in-place after `create_action_record` returns.
   - [backend/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_policy.py#L134-L159) (`test_agent_clean_payload_and_proposal_binding`) verifies that `ActionApprovalModel.payload_json` in the database is saved *before* this mutation and remains clean.
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py#L1561-L1606) (`test_server_approval_metadata_injected_into_arguments_rejected`) proves that passing polluted arguments to `evaluate_action` fails closed with `INVALID_TOOL_ARGUMENTS`.
3. **Current Status**: **BLOCKED** (`payload_json` in DB is clean, so execution-time re-evaluation reconstructing from `record.payload_json` is safe, but in-memory `proposal.arguments` in `chat.py` is mutated).
4. **Responsible Owner**: P2 (Backend)
5. **Required Follow-Up**: When implementing execution-time policy re-evaluation in `approvals.py`, reconstruct `ActionProposal` from `record.payload_json` (which is unpolluted), not from mutated client/chat payloads.

---

### Scenario 3: Account Ownership, Source-Account Mismatch, and Locked-Account Rejection

#### M-03A — Cross-Account Transfer Spoofing (`SOURCE_ACCOUNT_MISMATCH`)
1. **Expected Security Property**:
   - If `proposal.arguments["source_account_id"] != context.account_id`, the proposal must be rejected with `allowed_to_proceed=False`, `tier=Tier.RED`, and `reason_code="SOURCE_ACCOUNT_MISMATCH"`. The backend must **never** silently overwrite an explicitly mismatched `source_account_id` with the authenticated user's `account_id`.
2. **Existing Test / Evidence**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py): `test_transfer_source_account_mismatch_rejected`, `test_cross_tenant_transfer_source_account_mismatch`.
   - [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py#L338-L408): `test_http_chat_differential_proof_mock_allows_vs_real_policy_rejects` proves that over `POST /api/v1/chat`, `policy_service.use_mock=True` accepts `source_account_id="acc_victim_999"` (because `MockSecurityAdapter` ignores `source_account_id` and `actions.py:127` overwrites it after policy evaluation), whereas `policy_service.use_mock=False` rejects it (`status="REJECTED"`, 0 DB rows created).
3. **Current Status**: **PASS** (in Opt-in Real Policy Mode `use_mock=False`) / **FAIL** (in Default Mock Policy Runtime `USE_MOCK_SECURITY="true"`).
4. **Responsible Owner**: P4 / P2
5. **Required Follow-Up**: P2 to validate or default `source_account_id` only when absent/null prior to policy evaluation without overwriting an explicit mismatched value, and switch `USE_MOCK_SECURITY` default to `"false"`.

#### M-03B — Cross-Account Read-Only Query (`ACCOUNT_MISMATCH`)
1. **Expected Security Property**:
   - Read-only tool calls (`get_balance`, `analyze_spending`, `list_subscriptions`) specifying `account_id != context.account_id` must be rejected with `ACCOUNT_MISMATCH`.
2. **Existing Test / Evidence**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py): `test_get_balance_account_mismatch_rejected`, `test_cross_tenant_query_account_mismatch`, `test_analyze_spending_account_mismatch_rejected`, `test_list_subscriptions_account_mismatch_rejected`.
   - [backend/app/api/chat.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/chat.py#L110-L171): `chat.py` does not call `policy_service.evaluate()` for read-only tools (see M-01B).
3. **Current Status**: **PASS** (Policy Layer) / **BLOCKED** (Runtime HTTP `chat.py` Layer).
4. **Responsible Owner**: P2 / P4
5. **Required Follow-Up**: Route read-only proposals through `policy_service.evaluate()` in `chat.py`.

#### M-03C — Locked-Account Rejection at Proposal Time (`ACCOUNT_LOCKED`)
1. **Expected Security Property**:
   - When `context.account_locked=True` (populated from `UserModel.is_locked`), all state-changing proposals (`request_transfer`, `request_subscription_cancel`) are rejected with `ACCOUNT_LOCKED` (`allowed_to_proceed=False`, `tier=Tier.RED`). Read-only queries are allowed by default (`READ_ONLY_ACCESS`) unless `PolicyConfig(lock_denies_read_only=True)` is configured.
2. **Existing Test / Evidence**:
   - [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py): `test_t11_locked_account_rejects_transfer`, `test_locked_account_rejects_subscription_cancellation`, `test_locked_account_allows_read_only_by_default`, `test_locked_account_denies_read_only_when_configured`, `test_locked_account_read_only_tools_analyze_and_subscriptions`, `test_locked_account_precedes_source_account_mismatch`.
   - [backend/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_policy.py#L86-L109): `test_locked_user_can_check_balance_but_cannot_transfer` (exercises `POST /api/v1/chat` under default `policy_service.use_mock=True` and `agent_service.use_mock=True`).
3. **Current Status**: **PASS** (Pure Policy `use_mock=False` & Default Mock HTTP) / **BLOCKED** (Real-Policy HTTP with `USE_MOCK_AGENT=true`, because `MockAgentAdapter` omits `source_account_id`, causing Step 3 `INVALID_TOOL_ARGUMENTS` to fire before Step 4 `ACCOUNT_LOCKED`).
4. **Responsible Owner**: P4 / P2
5. **Required Follow-Up**: Populate `source_account_id` in `MockAgentAdapter`; see M-05 for execution-time (`/confirm`) lock enforcement.

---

### Scenario 4: Real Policy Evaluation Through the Backend Adapter

#### M-04A & M-04B — `SecurityAdapterService` Configuration & Runtime Bridge
1. **Expected Security Property**:
   - `SecurityAdapterService(use_mock: bool | None = None)` strictly validates `use_mock` (raising `ValueError` on non-booleans) and `USE_MOCK_SECURITY` (accepting only case-insensitive `"true"` or `"false"`, raising `ValueError` on any other string or whitespace-padded value).
   - When `use_mock=False` (or `USE_MOCK_SECURITY=false`), `SecurityAdapterService.evaluate` delegates directly to `security.policy.evaluate_action(proposal, context)`.
   - Note: In current runtime configuration ([backend/app/services/adapters.py:151](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/adapters.py#L151)), `USE_MOCK_SECURITY` defaults to `"true"`, so `policy_service` uses `MockSecurityAdapter` unless `USE_MOCK_SECURITY=false` or `use_mock=False` is explicitly configured.
2. **Existing Test / Evidence**:
   - [backend/app/services/adapters.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/adapters.py#L143-L166).
   - [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py): All 27 test items passing (`test_security_adapter_environment_and_default_selection`, `test_security_adapter_rejects_invalid_env_values_and_allows_explicit_override`, `test_security_adapter_rejects_non_boolean_constructor_arguments`, `test_real_mode_invokes_security_policy_evaluate_action_spy`, `test_http_chat_differential_proof_mock_allows_vs_real_policy_rejects`, `test_http_chat_real_p1_agent_with_real_p4_policy_end_to_end`).
3. **Current Status**:
   - **M-04A**: **PASS** (in Opt-in Real Policy Mode `USE_MOCK_SECURITY=false` / `use_mock=False`; disabled by default because `USE_MOCK_SECURITY` defaults to `"true"`).
   - **M-04B**: **BLOCKED** (Flipping default `USE_MOCK_SECURITY` from `"true"` to `"false"` while `USE_MOCK_AGENT=true`, because `MockAgentAdapter` in [backend/app/mocks/agent.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/mocks/agent.py) omits `source_account_id`).
4. **Responsible Owner**: P4 (Adapter Bridge) / P2 (`MockAgentAdapter` & `actions.py`)
5. **Required Follow-Up**: P2 to populate `source_account_id=account_id` in `MockAgentAdapter` (or in `actions.py` only when `source_account_id` is absent/null), then change the default in `SecurityAdapterService.__init__` to `"false"`.

---

### Scenario 5: Yellow Confirmation After Account Lock

#### M-05 — TOCTOU Account Lock Between Proposal (`/chat`) and Confirmation (`/confirm`)
1. **Expected Security Property**:
   - If a user's lock flag (`UserModel.is_locked`, mapped to `BankingContext.account_locked`) becomes `True` *after* a Yellow action is proposed (`PENDING_CONFIRMATION`) but *before* `POST /api/v1/actions/{action_id}/confirm` is called, `/confirm` must reject the action (`ActionStatus.REJECTED`, HTTP 403/400) and must not execute the transfer or subscription cancellation.
2. **Existing Test / Evidence**:
   - Code inspection of [backend/app/api/approvals.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L35-L128) confirms `confirm_action` never checks `user.is_locked` and never re-invokes `policy_service.evaluate()`. At line 117 (`audit_id, message = _execute_action(db, user, record)`), the Yellow action executes even if `user.is_locked == True`.
3. **Current Status**: **FAIL / UNFIXED** (Confirmed unfixed runtime vulnerability in `backend/app/api/approvals.py`).
4. **Responsible Owner**: P2 (Backend) with P4 (Security)
5. **Required Follow-Up**: In `confirm_action` (`backend/app/api/approvals.py`), reconstruct `ActionProposal` from `record.payload_json` and `BankingContext` from current DB state (`user.is_locked`, fresh `account.balance`, fresh `account.daily_transfer_total`), and call `policy_service.evaluate(proposal, fresh_context)` before `_execute_action`.

---

### Scenario 6: Yellow-to-Red Escalation When Cumulative Daily Transfers Change

#### M-06 — Cumulative Daily Limit Escalation Between Proposal and Confirmation
1. **Expected Security Property**:
   - Suppose `daily_transfer_total` is `0.00 CNY` and the user proposes two separate `600.00 CNY` transfers (Action A and Action B). Both are initially classified as `Tier.YELLOW` ($600.00 \le 1,000.00$).
   - After Action A is confirmed and executed (`daily_transfer_total` becomes `600.00 CNY`), confirming Action B (`600.00 + 600.00 = 1,200.00 > 1,000.00 CNY`) must re-evaluate policy against the fresh `daily_transfer_total`, escalate Action B from `Tier.YELLOW` to `Tier.RED`, issue an MFA challenge (`PENDING_MFA`), and refuse immediate execution without MFA.
2. **Existing Test / Evidence**:
   - Policy layer supports cumulative evaluation (`test_t03_transfer_exceeds_daily_limit_red` in [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py#L241-L266)).
   - Runtime inspection of [backend/app/api/approvals.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L90-L128) shows `confirm_action` only inspects the static `record.tier == Tier.RED.value` stored at proposal time (line 90) and executes Action B immediately as Yellow at line 117.
3. **Current Status**: **FAIL / UNFIXED** (Confirmed unfixed runtime TOCTOU vulnerability in `backend/app/api/approvals.py`).
4. **Responsible Owner**: P2 (Backend) & P3 (MFA) with P4 (Security)
5. **Required Follow-Up**: Re-evaluate `policy_service.evaluate()` in `confirm_action` against fresh `account.daily_transfer_total`. If `decision.tier == Tier.RED` (`decision.requires_mfa`), update `record.tier = Tier.RED.value` and route through `mfa.issue_challenge(record, now)` returning `ActionStatus.PENDING_MFA`.

---

### Scenario 7: Red MFA Verification After Account Lock vs. Execution-Time Policy Re-Evaluation

#### M-07A — Direct `user.is_locked` Check at Red `/verify`
1. **Expected Security Property**:
   - If a Red action is confirmed into `PENDING_MFA` and `UserModel.is_locked` becomes `True` before `POST /api/v1/actions/{action_id}/verify` is called with the valid OTP code, `/verify` must reject execution, mark the action `REJECTED`, and leave the account balance unchanged.
2. **Existing Test / Evidence**:
   - Implemented in [backend/app/api/approvals.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L216-L222) via a direct check `if user.is_locked:` (`record.status = ActionStatus.REJECTED.value ... raise HTTPException(status_code=403)`).
   - Verified by `test_account_locked_after_confirm_blocks_execution` in [backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py#L227-L237).
3. **Current Status**: **PASS** (Direct `user.is_locked` check at `/verify`).
4. **Responsible Owner**: P3 (MFA)
5. **Required Follow-Up**: None for the boolean `user.is_locked` check itself; see M-07B for full policy re-evaluation.

#### M-07B — Execution-Time Policy Re-Evaluation (`policy_service.evaluate`) in `/confirm` and `/verify`
1. **Expected Security Property**:
   - Both `/confirm` and `/verify` should re-run `policy_service.evaluate(reconstructed_proposal, fresh_context)` against live database state prior to executing any state mutation.
2. **Existing Test / Evidence**:
   - Code inspection of [backend/app/api/approvals.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L89-L128) and [L223-L224](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L223-L224) confirms that `policy_service.evaluate` is **not** called in either `confirm_action` or `verify_action` (lines 223–224 contain only `# TODO(P4): re-run security.policy.evaluate_action against the current BankingContext here once the real policy bridge replaces the mock`).
3. **Current Status**: **FAIL / UNFIXED** (Not implemented in runtime code).
4. **Responsible Owner**: P2 (Backend) & P3 (MFA) with P4 (Security)
5. **Required Follow-Up**: Implement execution-time policy re-evaluation in both `confirm_action` and `verify_action` in `backend/app/api/approvals.py`.

---

### Scenario 8: Concurrent Confirmation of the Same Action

#### M-08A — Concurrent Red MFA Verification (`POST /api/v1/actions/{action_id}/verify`)
1. **Expected Security Property**:
   - Two simultaneous `/verify` requests submitting the valid OTP for the same `action_id` must result in at most one execution (`COMPLETED`) and one `409 Conflict` rejection, debiting the account exactly once.
2. **Existing Test / Evidence**:
   - Implemented via atomic conditional SQL update in [backend/app/services/mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/mfa.py#L110-L127) (`claim_challenge`).
   - Verified by `test_concurrent_verify_loser_is_rejected_without_debit` and multi-threaded `test_truly_concurrent_verifies_debit_once` in [backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py#L150-L163) and [L270-L344](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py#L270-L344).
3. **Current Status**: **PASS**
4. **Responsible Owner**: P3 (MFA)
5. **Required Follow-Up**: None for single-action Red `/verify` claim.

#### M-08B — Concurrent Yellow Confirmation of the Same Action (`POST /api/v1/actions/{action_id}/confirm`)
1. **Expected Security Property**:
   - Two simultaneous `/confirm` requests for the **same `action_id`** in `PENDING_CONFIRMATION` must result in at most one execution; the second concurrent request must not execute `_execute_action` a second time.
2. **Existing Test / Evidence**:
   - Sequential replay after completion is tested in `test_atomic_money_transfer_and_idempotency` ([backend/tests/test_execution.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_execution.py#L48-L61)).
   - Code inspection of [backend/app/api/approvals.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L42-L121) shows that `confirm_action` reads `record` with a non-locking `SELECT` (line 42), checks `record.status != ActionStatus.PENDING_CONFIRMATION.value` in Python (line 73), runs `_execute_action` (line 117), and only sets `record.status = ActionStatus.COMPLETED.value` at line 119 before `db.commit()` at line 121. Unlike `mfa.claim_challenge`, there is no atomic conditional `UPDATE action_approvals SET status = ... WHERE action_id = :id AND status = 'PENDING_CONFIRMATION'` prior to `_execute_action`.
   - No dedicated multi-threaded test currently exercises concurrent `/confirm` calls on the same `action_id`.
3. **Current Status**: **FAIL / UNFIXED** (Unprotected TOCTOU window confirmed by code inspection; concurrent race **NOT TESTED** by an automated multi-threaded test).
4. **Responsible Owner**: P2 (Backend)
5. **Required Follow-Up**: Add an atomic conditional `UPDATE` claim on `ActionApprovalModel` (`WHERE action_id == action_id AND status == 'PENDING_CONFIRMATION'`) before calling `_execute_action` in `approvals.py`, and add a two-thread barrier test for `/confirm`.

---

### Scenario 9: Concurrent Transfers Against the Same Account Across Distinct Action IDs

#### M-09 — Competing Transfers Across Different `action_id`s on the Same Account
1. **Expected Security Property**:
   - Concurrent confirmations/verifications of two **different transfer actions (`act_1` and `act_2`)** drawing from the same `account_id` must serialize balance deductions and `daily_transfer_total` updates so that:
     1. The account balance cannot be overdrawn (`balance < 0`) by two competing transfers that individually pass `account.balance < amount`.
     2. Two competing transfers cannot corrupt or bypass `daily_transfer_total` accounting by reading and overwriting the same stale `AccountModel` row.
2. **Existing Test / Evidence**:
   - Code inspection of [backend/app/services/executor.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/services/executor.py#L28-L50) shows a non-atomic read-modify-write pattern on `AccountModel`:
     ```python
     account = db.query(AccountModel).filter(...).first()
     if account.balance < amount:
         raise HTTPException(...)
     account.balance -= amount
     account.daily_transfer_total += amount
     ```
   - No row-level lock or conditional SQL update (`UPDATE accounts SET balance = balance - :amount, daily_transfer_total = daily_transfer_total + :amount WHERE account_id = :id AND balance >= :amount`) is used, and no automated concurrency test exercises two distinct `action_id`s against the same account.
3. **Current Status**: **FAIL / UNFIXED** (Non-atomic account update confirmed by code inspection; concurrent race **NOT TESTED** by an automated multi-threaded test).
4. **Responsible Owner**: P2 (Backend)
5. **Required Follow-Up**: Replace the in-memory balance/daily-total mutation in `executor.py` with an atomic conditional SQL `UPDATE` on `AccountModel` checking `AccountModel.balance >= amount`, and add a two-thread concurrency test across two distinct `action_id`s.

---

### Scenario 10: Rejection Reason Codes and Audit Linkage

#### M-10A — Deterministic Policy Reason Codes & Successful Execution Audit Linkage
1. **Expected Security Property**:
   - Every policy decision returns an explicit `SecurityReasonCode` (`security/rules.py:15-40`).
   - Every executed transfer, subscription cancellation, and issued MFA challenge creates an `AuditLogModel` record linked by `action_id`, `user_id`, `payload_digest`, and `audit_id`.
2. **Existing Test / Evidence**:
   - Policy reason codes: Verified across all 84 passing collected test items in [security/tests/test_policy.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/security/tests/test_policy.py) and `test_create_action_record_with_real_policy_preserves_reason_codes` in [backend/tests/test_security_bridge.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_security_bridge.py#L233-L336).
   - Execution audit linkage: Verified in `test_atomic_money_transfer_and_idempotency` ([backend/tests/test_execution.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_execution.py#L62-L69)) and `test_red_transfer_debits_once_only_after_valid_mfa` ([backend/tests/test_mfa.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/tests/test_mfa.py#L97-L100)).
3. **Current Status**: **PASS**
4. **Responsible Owner**: P4 / P2 / P3
5. **Required Follow-Up**: None for successful execution audit logs.

#### M-10B — Rejection Audit Logging and Reason Code Fidelity in `POST /api/v1/chat` and `/confirm`
1. **Expected Security Property**:
   - When `create_action_record` rejects a proposal with `ValueError(f"Action blocked by policy: {decision.reason_code}")`, `POST /api/v1/chat` should record an audit event with `decision.reason_code` and return an accurate rejection message rather than assuming every rejection is an account lock.
   - Security rejections during `/confirm` (digest tampering) and `/verify` (3x wrong OTP lockout, locked account at execution time) should also write `AuditLogModel` records.
2. **Existing Test / Evidence**:
   - Code inspection of [backend/app/api/chat.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/chat.py#L234-L240) shows that `except ValueError as e:` ignores `e`, writes no `AuditLogModel` entry, and always returns `"Action blocked: Your account is currently locked for state-changing operations."` even when the actual reason code was `SOURCE_ACCOUNT_MISMATCH`, `INVALID_TOOL_ARGUMENTS`, or `UNKNOWN_TOOL`.
   - Code inspection of [backend/app/api/approvals.py](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L54-L60) and [L201-L222](file:///C:/Users/Admin/Documents/AI Banking Agent/ai-banking-agent/backend/app/api/approvals.py#L201-L222) shows status updates to `REJECTED` / `FAILED` without `db.add(AuditLogModel(...))`.
3. **Current Status**: **FAIL / UNFIXED** (Rejection reason codes are masked by a static message in `chat.py` and rejected actions are not recorded in `AuditLogModel`).
4. **Responsible Owner**: P2 (Backend) & P3 (MFA)
5. **Required Follow-Up**: P2 to log `AuditLogModel` on policy rejection in `chat.py` (preserving `decision.reason_code`) and on digest mismatch in `approvals.py`; P3 to log `AuditLogModel` on MFA lockout and execution-time lock rejection in `approvals.py`.

# Person 4 — Security Policy Module Documentation

Welcome to the documentation for **Person 4 (Finance Risk & Security Engineering)** of the AI Banking Agent project.

---

## 1. Module Responsibilities & Ownership

Person 4 owns:
* `security/`
  * `__init__.py`: Public package exports (`evaluate_action`, `PolicyConfig`, `SecurityReasonCode`, `DEFAULT_CONFIG`).
  * `policy.py`: The pure, fail-closed policy evaluation engine (`evaluate_action`).
  * `rules.py`: Policy rules, reason codes, threshold constants, and configuration dataclass.
  * `tests/test_policy.py`: Comprehensive test suite containing 39 tests covering all fixture cases, boundaries, and adversarial vectors.
* `docs/security/`
  * `threat_model.md`: Detailed STRIDE threat model and LLM-specific vulnerability analysis.
  * `security_assessment.md`: Rigorous security review, tier taxonomy, and defense-in-depth evaluation.
  * `integration_guide.md`: Clear integration instructions, state machine, and code examples for Person 2 (Backend).

All implementations strictly conform to frozen shared contracts v1.0.0. No contracts, fixtures, or other team members' directories have been modified.

---

## 2. Running Tests

From the repository root (`ai-banking-agent`):

```powershell
# Run Person 4 security policy tests
.\.venv\Scripts\python.exe -m pytest security/tests/test_policy.py -v

# Run the complete test suite (contracts + security)
.\.venv\Scripts\python.exe -m pytest -v
```

All 39 security tests and 14 contract tests pass with 100% success.

---

## 3. Core Policy Rules Summary

1. **Pure Fail-Closed Architecture**:
   - `evaluate_action` never throws unhandled exceptions.
   - Any invalid, missing, unauthenticated, or malformed proposal is safely rejected (`allowed_to_proceed=False`, `tier=Tier.RED`).
2. **Read-Only Actions (Tier GREEN)**:
   - `get_balance`, `analyze_spending`, `list_subscriptions` proceed automatically without explicit user confirmation or MFA.
3. **Transfers within Daily Limit (Tier YELLOW)**:
   - Cumulative daily transfers $\le \text{CNY } 1,000.00$ require explicit confirmation (`requires_confirmation=True`).
4. **Subscription Cancellation (Tier YELLOW)**:
   - `request_subscription_cancel` requires explicit confirmation (`requires_confirmation=True`).
5. **Transfers Exceeding Daily Limit (Tier RED)**:
   - Cumulative daily transfers $> \text{CNY } 1,000.00$ require explicit confirmation AND simulated Multi-Factor Authentication (`requires_mfa=True`).
6. **Account Lockout (Tier RED Rejection)**:
   - When `account_locked=True`, all state-changing mutations (`request_transfer`, `request_subscription_cancel`) are strictly rejected (`allowed_to_proceed=False`, `reason_code="ACCOUNT_LOCKED"`).

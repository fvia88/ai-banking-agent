# Security defaults and escalation auditing

Real P4 policy is now the default consistently in local Python startup and
Docker Compose. `SecurityAdapterService` uses `USE_MOCK_SECURITY=false` when the
variable is absent. Explicit `USE_MOCK_SECURITY=true` still selects the P2 mock.
The flag accepts case-insensitive true/false; invalid values and non-boolean
constructor overrides still raise errors rather than silently selecting a mode.

This flag controls security policy only. It is independent of USE_MOCK_AGENT
(P2 mock versus real P1 code) and AGENT_PROVIDER (P1's mock versus Gemini).
No provider keys or LLM configuration are changed by this update.

## Escalation event

When confirmation re-evaluates a pending Yellow action and it now needs Red
verification, the backend stores tier=RED and status=PENDING_MFA and adds:

* ESCALATED_TO_RED, with the action ID, authenticated user, canonical payload
  digest and fresh PolicyDecision.reason_code. Details identify previous_tier,
  new_tier and confirmation_policy_recheck as the trigger.
* MFA_CHALLENGE_ISSUED, preserving the existing challenge event and the audit ID
  returned in ExecutionResult.

Both events, the tier/state transition and challenge fields commit together
inside the existing execution guard. No debit occurs at escalation. Failure
before that commit rolls everything back. Initially Red actions receive a
challenge event but no escalation event; ordinary Yellow completion also emits
no escalation event. Repeated confirmation, verification and completed replay
cannot duplicate the escalation event. Concurrent threshold-crossing tests
require exactly one escalation and one challenge event on both database types.

## Verify

The combined offline suite passed all 756 tests, including PostgreSQL migration
and concurrency cases in a separate disposable test container. The former
security-default test disagreement is resolved. The two remaining warnings are
dependency deprecations, not test failures. The running app database was not used.

To activate the source changes, rebuild using your intended provider environment:

```powershell
docker compose up -d --build backend
```

No new database migration is needed. An explicit environment flag selecting mock
security still overrides the real default; set USE_MOCK_SECURITY=false if needed.

For a frontend demonstration with P1 enabled, start with enough balance and a
daily total of zero. Request two separate 600 CNY transfers before confirming
either. Confirm the first, then the second. The second requires MFA without a
debit; expand the audit panel to see ESCALATED_TO_RED and MFA_CHALLENGE_ISSUED.
An action already Red at proposal time should show only the challenge event.
If the daily total is already high, both proposals may start Red and do not
demonstrate escalation.

## Documentation ownership

This document and the updated docs/app notes describe current P2 runtime
behavior. Some P4-owned docs/security reviews still describe the older opt-in
default or earlier runtime gaps; those are historical snapshots and need a P4
refresh. They were not edited outside P2's owned paths.

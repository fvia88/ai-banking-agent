# P4 policy integration

The backend now calls `security.policy.evaluate_action(proposal, context)` by
default. No changes to P4's module or frozen contracts are required.

`USE_MOCK_SECURITY=false` selects real P4 (the default in local code and Compose).
`USE_MOCK_SECURITY=true` explicitly selects the P2 mock for isolated demos. A
failed real evaluator import is not silently replaced with a mock. P1 provider
selection is independent: real P1 with `AGENT_PROVIDER=mock` can exercise real P4
without sending any LLM request.

## Boundaries

Before storing a transfer or cancellation proposal, P2 validates arguments with
the shared tool schemas, checks backend user/context consistency, calls policy,
and stores only canonical arguments with a server-issued action ID and digest.
Duplicate action-record implementations and local duplicate argument models have
been removed. P2 mock transfer proposals now include the required source account.
Chat reports policy rejection reasons instead of calling every rejection an
account lock. Chat read tools also validate arguments and invoke policy; locked
users can still read according to P4 defaults.

Both confirmation and successful OTP verification reconstruct a proposal from
the stored payload, validate it, verify its digest and query current owned
account/user state before calling policy again. Rejections are audited and mark
the action REJECTED. If a previously Yellow proposal now exceeds the cumulative
threshold, confirmation issues an MFA challenge without debiting. A previously
Red requirement is never downgraded. Verification cannot bypass a newly denied
policy decision even with a correct OTP. Insufficient funds remain enforced by
the transfer executor, since P4 currently classifies risk rather than checking
sufficient funds.

The current UI still receives action_id/action_digest/tier inside the response
proposal's arguments for compatibility. These tracking fields are added only
after policy evaluation; execution-time checks use the clean stored payload.
Separating UI metadata into a coordinated contract remains future work.

## Verification and remaining work

HTTP tests spy on the actual P4 function and check threshold boundaries, trusted
context, invalid fields/precision/source accounts, locked reads and confirmations,
stored payload tampering, sequential cumulative escalation, changed policy during
MFA, replay, and real P1 + real P4 operation with a deterministic LLM provider.
Existing OTP lifecycle and race tests continue to run with real P4 enabled.

This integration does not establish full concurrency safety: simultaneous Yellow
confirmations or competing account transfers still need database serialization.
The existing consumed-MFA-marker/execution transaction split also remains.
Daily totals still lack a calendar reset. Recipient ownership needs verified
backend records; P4's account matching does not validate recipient ownership.
Subscription eligibility/persistence now uses the P5 integration described in
`p5_integration.md`. Repeated
OTP failure marks an action failed; it does not yet implement the challenge's
broader user/account safety-lock policy. These require follow-up work with the
relevant owners and are not guarantees of this bridge.

## Run

Docker users pull the changes and rebuild:

```powershell
docker compose up -d --build
```

Local users restart `python backend/start.py --reload` with
`USE_MOCK_SECURITY=false` (or leave it unset). No database migration is introduced
by this policy integration.

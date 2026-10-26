# Broader agent and security requirements review

Reviewed against the supplied challenge brief (technical requirements 3.2/3.3),
the interface Word draft, current executable contracts, the reference finish plan,
and current P1/P4/P2 code. Older document instructions are reference material;
they do not authorize edits outside P2's ownership or redefine current contracts.

## Current coverage

| Requirement | Current evidence and limit |
|---|---|
| Vague/omitted intent | P1 structured transfer, period, and subscription clarification; owner/conversation state persists in P2. Existing P1 and HTTP tests cover it. |
| Ordered planning | P1's explicit two-step cancellation-then-transfer plan stores steps and dependencies. Only trusted cancellation completion releases a separate transfer proposal; both require backend validation and independent approvals. This is a bounded dependency chain, not a general arbitrary DAG planner. |
| Interruption | P1 supports pause/resume, stop/abandon, and new-request switching. P2 preserves returned state. Pause stops plan progression; stop discards unfinished plan steps. The separate Cancel approval control now revokes a pending ticket; see `approval_cancellation.md`. |
| Rollback | Partial account/ledger/audit/MFA changes roll back atomically on uncommitted execution failure. Already completed transfers/cancellations are not automatically undone. Post-commit compensation would require a separately designed, authorized operation. |
| Human takeover | P1's `human takeover` pauses an active plan and explicitly directs the user to the app team. It does not contact anyone or create an assigned/persistent support review. No staff review console or human handoff queue exists. |
| Safety lock | Implemented owner-wide persistent lock after three verification failures within a fixed 15-minute observation window. Pending tickets are retired, reads remain available, and local operator reset is audited. See `safety_lock.md`. |
| Prompt injection / hallucinated execution | Strict tool schemas, backend identity/context, a closed tool dispatcher, server approval digests, trusted results, and P1 result correlation are implemented and tested. They do not grant permission based on text alone. |
| Decision/execution logs | Financial execution, escalation, policy refusal during approval, continuation observations, and safety-lock events have persisted audits. This is not yet complete audit coverage of every initial proposal/read decision, interruption, or takeover event. |
| Generated-code sandbox | The banking agent has no arbitrary generated-code execution tool. Whitelisted backend functions handle operations. Do not claim a separate generated-code sandbox has been implemented. |

## Remaining work in this group

Explicit pending-ticket cancellation is implemented with owner/digest checks,
execution-race protection, audit, and trusted P1 continuation. Completed operations
remain immutable. See `approval_cancellation.md` for supported state transitions.

1. Establish the required level of human takeover with P1/P4. The present pause
   command is truthful but is not an assigned human review workflow. Any proposed
   backend review/control state must survive restart and prevent an LLM from
   resuming itself or clearing a security lock.
2. Complete decision/control audit coverage and the security self-assessment,
   including prototype authentication, static demo recipient context, simulated
   MFA/cancellation, bounded planning, no post-commit reversal, and disabled
   generated-code execution.
3. Rehearse the supported plan, interruption, rollback/failure, lock and manual
   review behaviors through HTTP/frontend on one release commit. General DAG
   planning and real bank/operator integration are not silently claimed as done.

No `agent/`, `security/`, shared contract, or fixture changes are needed for the
safety-lock implementation. Ownership coordination remains necessary for broader
P1 semantics or changes to the frozen tool catalog.

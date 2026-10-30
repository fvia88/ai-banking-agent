# Agent integration contract

The backend calls the real P1 agent through `AgentAdapterService.process_turn`.
Executable definitions in `contracts/` are authoritative; the catalog, state,
and result envelopes below are internal integration conventions.

## Provider and ownership

`USE_MOCK_AGENT=false` selects P1 orchestration. `AGENT_PROVIDER=mock` uses
its deterministic offline interpreter; `AGENT_PROVIDER=groq` uses live Groq.
See [deployment](../app/deployment.md) for configuration and startup commands.

`ChatInput` contains `conversation_id` and `message`, with no user identity.
The backend supplies the trusted owner and selected account. Tool catalog entries
contain `name`, the canonical argument model JSON `parameters`, and trusted
`context`. Never accept a catalog or context supplied by the browser or LLM.

Context includes the selected `account_ids`, account lock state, recipient and
stored subscription records, and the saved `conversation_state`. See
`backend/app/services/adapters.py` and `agent/conversation.py` for exact fields.
Recipient data is synthetic demo context, not a live banking directory.

## Conversation state

`agent.service.process_turn(chat, tool_catalog, tool_results=None)` returns a
`ConversationTurn` with `result` and `state`. The backend persists the returned
state for the trusted owner/conversation, then supplies it on subsequent calls.
State includes clarification drafts, canonical pending tool requests, and bounded
plan progress. A list of pending IDs alone is insufficient for result validation.

The supported ordered plan cancels a subscription first and proposes a specified
transfer only after trusted cancellation completion. Each action requires its own
approval. Cancellation does not credit savings or refund prior charges.
Pause/resume/stop control plan progression; withdrawing an issued approval uses
the separate [approval cancellation API](../app/approval_cancellation.md).
There is no assigned staff takeover workflow.

## Trusted tool results

Only backend orchestration supplies results from actual tools or persisted action
outcomes. Each envelope identifies the original request:

```python
tool_result = {
    "conversation_id": chat.conversation_id,
    "proposal_id": proposal.proposal_id,
    "tool": proposal.tool.value,
    "arguments": proposal.arguments,
    "status": "success",  # or "error"
    "data": validated_data.model_dump(mode="json"),
}
turn = process_turn(chat, tool_catalog, tool_results=[tool_result])
# Persist turn.state and return turn.result through the backend HTTP adapter.
```

Arguments must match the saved canonical request. Successful data uses the shared
`Account`, `SpendingReport`, `SubscriptionReport`, or `ExecutionResult` model.
Echoed IDs and arguments alone do not establish authenticity: the backend checks
ownership and supplies the authoritative result. Only `COMPLETED` mutation results
support a completion claim. Persisting the new state retires consumed requests.
Tool prose, merchant names, notes, and model output never authorize execution.

See [trusted continuation](../app/agent_continuation.md) for persisted action
correlation, retries, and missed-callback recovery. Server action IDs, digests,
tiers, and statuses travel in a separate HTTP approval object; see
[frontend metadata](../app/frontend_metadata_transport.md). They must not be
inserted into strict canonical tool arguments.

The backend retains policy checks, confirmation, simulated MFA, account locking,
atomic execution, idempotency, and audits. P1 proposes operations and explains
trusted outcomes; it does not execute transfers or cancellations.

For verification commands, including isolated PostgreSQL tests, see the
[deployment guide](../app/deployment.md#verification). The synthetic CLI helpers
in `agent/mock_tools.py` are not production finance or subscription analytics.

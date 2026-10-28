# Person 1 agent milestone one

Standalone stateless proposal service with an English deterministic mock and
environment-configured Gemini SDK adapter. No bank connections or mutation
execution. All CLI data is synthetic; CLI spending is a fixture-only stub, not
P3 analytics. The subscription stub returns no candidates rather than pretending
to implement P5 detection. See integration.md for backend adapter conventions.

## Setup and verification from repository root

```powershell
uv venv --python 3.11 agent/.venv
uv pip install --python agent/.venv/Scripts/python.exe -r agent/requirements.txt
$env:PYTHONDONTWRITEBYTECODE = '1'
agent/.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_contracts.py agent/tests -q
agent/.venv/Scripts/python.exe -m agent.cli 'What is my balance?' --resolve-read
agent/.venv/Scripts/python.exe -m agent.cli 'Analyze spending 2026-10' --resolve-read
agent/.venv/Scripts/python.exe -m agent.cli 'Transfer 500 to Alice' --clarify 'Alice Chen'
```

If Python 3.11+ is already installed, its standard venv/pip commands can replace
uv. Dependencies are pinned for this milestone. Runtime and installs reside in
agent/.venv and are ignored; do not commit secrets or the virtual environment.

## Configuration

- AGENT_PROVIDER: mock (default) or gemini for service calls.
- GEMINI_API_KEY: environment only; required in Gemini mode.
- GEMINI_MODEL: default gemini-3.1-flash-lite; an explicit environment value overrides it.
- AGENT_TIMEOUT_SECONDS: integer 1 through 60, default 20.

CLI explicitly defaults to mock regardless of AGENT_PROVIDER; use --provider
gemini to opt in. It does not silently substitute mock results on API failure.

```powershell
$env:GEMINI_MODEL = 'gemini-3.1-flash-lite'
agent/.venv/Scripts/python.exe -m agent.cli 'What is my balance?' --provider gemini
```

That command makes a real provider request; use a free-tier project and inspect
its quota. A validated proposal confirms extraction works, not bank execution.
Missing key, SDK/network errors, invalid JSON, and invalid arguments return a
safe generic response without SDK error payloads or credentials. Retry manually
after outages; use mock mode while offline. No automatic paid-provider fallback.

## Optional Groq CLI trial

Groq is an additional provider; Gemini remains available. This trial does not
change Docker or the website's provider configuration. Install the updated
`agent/requirements.txt` into your virtual environment first.

With `GROQ_API_KEY` already configured in the same PowerShell terminal:

```powershell
$env:GROQ_MODEL = 'openai/gpt-oss-20b'
agent/.venv/Scripts/python.exe -m agent.diagnose --provider groq --message 'Could you send 50?' --expected-intent transfer --repeat 3
agent/.venv/Scripts/python.exe -m agent.cli --interactive --provider groq
```

Try `Could you send 50?`, followed by `Bob`: expect recipient clarification,
then a transfer proposal. No banking action executes in this CLI. Read results
use synthetic demo data, independently of the website database.

Use `diagnose` to compare provider request times: some CLI messages are handled
locally and therefore do not measure model latency. Offline transport tests
verify the adapter and safeguards, but live intent accuracy and connection
reliability still require a real-key trial. Groq has its own free-tier quotas.
There are no automatic retries or fallback to another provider. Use
`--provider gemini` to select Gemini again.

## Limits

Mock phrases include balance, spending YYYY-MM, list subscriptions, transfer
AMOUNT to NAME, and cancel MERCHANT. It is a test aid, not a general LLM.
AgentResult and tool arguments are validated separately. The provider extracts
a private typed Intent; Python supplies canonical IDs and constructs all public
replies. No provider-generated claim is presented as a verified banking result.
The live adapter supports broader extraction but has not been quality-evaluated
on every phrasing. Semantic intent extraction remains fallible; backend exact
payload confirmation and policy are mandatory. No DAG, automatic cancellation
then transfer, rollback, persistence, frontend, or risk engine is implemented in
this milestone. This is not the full competition deliverable.

## Verification on 15 October 2026

41 tests passed: 14 existing contract cases and 27 agent cases (including
parametrized cases). The installed Gemini SDK emits one Pydantic deprecation
warning; tests pass. Mock CLI clarification and October spending demos passed.
The live Gemini CLI returned the safe failure response; successful live model
generation remains unverified. The SDK adapter was also tested offline with a
fake SDK client for success, configured timeout/schema, and error redaction.

### Live Gemini diagnosis

The original default gemini-2.5-flash returned 404: unavailable to new users.
The original response_schema=Intent conversion returned 400 because the SDK
sent additional_properties in the legacy schema format. The adapter now uses
gemini-3.8-flash and response_json_schema=Intent.model_json_schema(). The corrected
live request returned 503 with a high-demand message. Live generation is still
unverified; this remaining service response is distinct from the two corrected
configuration errors. The user-facing service deliberately returns a generic
failure and does not forward raw provider errors.

For current troubleshooting, run this in the same terminal as the failed CLI:

```powershell
agent/.venv/Scripts/python.exe -m agent.diagnose
```

This makes one live request and reports a fixed safe error category and HTTP
code, or validates a successful balance intent. It never prints keys, raw model
output, prompts, or SDK exception payloads. Existing GEMINI_MODEL environment
overrides take precedence over the new default; remove an obsolete override
with Remove-Item Env:GEMINI_MODEL before retrying.

A subsequent live probe returned HTTP 400 with "User location is not supported
for the API use." The diagnostic now labels this unsupported_location rather
than invalid_request. This is a region-eligibility rejection, not evidence that
the JSON schema is still invalid. Prior 503/504 responses were different errors;
successful model generation was unverified at the time of that probe.

## Natural request wording verified on 17 October 2026

The service now accepts common direct polite forms, including "Could you send
500 yuan to Bob?", "Please transfer 500 to Bob", and "I want to give 500 yuan
to Bob" when the provider extracts the corresponding intent and arguments.
The exact "Could you send 500 yuan to Bob?" prompt passed a live Gemini
3.1 Flash-Lite check and returned a validated request_transfer proposal.

request_guard.py checks request framing, while the provider interprets intent.
The guard conservatively rejects negations, quotes, reported note/merchant
instructions, and hypothetical/conditional forms. This is a bounded safeguard,
not a complete semantic security mechanism; unrecognized wording asks for a
fresh explicit request. Backend validation and approval remain mandatory.
Existing numeric-amount grounding and verified recipient checks remain in force.
The mock parser still supports its original limited phrases; this change does
not give it Gemini's language capabilities. Multi-turn polite-request replay is
not broadened here and remains part of later conversation-harness work.

82 offline tests passed, including provider-independent request-framing cases
using deliberately incorrect model interpretations. The existing SDK/Pydantic
deprecation and thought-signature warnings are separate from this change.

## Milestone two completed on 17 October 2026

See milestone-2.md for the final scope, live evidence, commands, and limits.
The default model is now Gemini 3.1 Flash-Lite. Earlier default/model failures
above are historical observations. The adapter reads visible text candidate
parts directly and excludes thought parts. One metadata notice can still arise
inside the pinned SDK; the SDK/Pydantic deprecation warning also remains.

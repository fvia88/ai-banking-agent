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
- GEMINI_MODEL: default gemini-2.5-flash; configure an available free-tier model.
- AGENT_TIMEOUT_SECONDS: integer 1 through 60, default 20.

CLI explicitly defaults to mock regardless of AGENT_PROVIDER; use --provider
gemini to opt in. It does not silently substitute mock results on API failure.

```powershell
$env:GEMINI_MODEL = 'gemini-3.8-flash'
agent/.venv/Scripts/python.exe -m agent.cli 'What is my balance?' --provider gemini
```

That command makes a real provider request; use a free-tier project and inspect
its quota. A validated proposal confirms extraction works, not bank execution.
Missing key, SDK/network errors, invalid JSON, and invalid arguments return a
safe generic response without SDK error payloads or credentials. Retry manually
after outages; use mock mode while offline. No automatic paid-provider fallback.

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

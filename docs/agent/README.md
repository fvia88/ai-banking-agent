# Agent setup and integration

The agent interprets banking requests with **Groq**, validates structured intent,
retains caller-owned clarification state and proposes typed tools. The backend
supplies trusted context, applies security policy and executes approved simulator
operations. The offline mock remains available for deterministic development.

## Install and verify from the repository root

```powershell
uv venv --python 3.11 agent/.venv
uv pip install --python agent/.venv/Scripts/python.exe -r agent/requirements.txt
$env:PYTHONDONTWRITEBYTECODE = '1'
agent/.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_contracts.py agent/tests -q
```

Python 3.11+ standard venv/pip commands can replace uv. Do not commit the virtual
environment or API keys. Install the backend dependencies as well for its suite.

## Configuration

- `AGENT_PROVIDER`: `groq` for live interpretation or `mock` for offline development.
  The standalone service and CLI default to mock; Docker defaults to Groq.
- `GROQ_API_KEY`: required in the backend process environment for live requests.
- `GROQ_MODEL`: defaults to `openai/gpt-oss-20b`; an explicit setting overrides it.
- `AGENT_TIMEOUT_SECONDS`: integer from 1 through 60; default 20.
- `USE_MOCK_AGENT=false`: connects the backend to this actual agent. Setting it to
  true selects the backend stub, a different mechanism from `AGENT_PROVIDER=mock`.

Configure the key privately in the same PowerShell terminal that launches Docker:

```powershell
$key = Read-Host "Paste Groq API key" -AsSecureString
$env:GROQ_API_KEY = ([System.Net.NetworkCredential]::new('', $key).Password).Trim()
Remove-Variable key
$env:USE_MOCK_AGENT = 'false'
$env:AGENT_PROVIDER = 'groq'
$env:GROQ_MODEL = 'openai/gpt-oss-20b'
docker compose up -d --build
```

After changing environment settings without changing code, recreate the backend
with `docker compose up -d --force-recreate backend`. An existing container does
not inherit changes made later to a terminal's environment. The key is never sent
to the frontend. The website uses database data; the CLI uses synthetic fixtures.

## Live diagnosis and interactive CLI

With the key available in this terminal:

```powershell
agent/.venv/Scripts/python.exe -m agent.diagnose
agent/.venv/Scripts/python.exe -m agent.diagnose --message 'Could you send 50?' --expected-intent transfer
agent/.venv/Scripts/python.exe -m agent.cli --interactive --provider groq
```

The diagnostic makes one real extraction request and prints safe error categories,
HTTP status when available and elapsed time. It never prints the key or raw model
output. `--repeat 3` runs three sequential probes. API calls consume provider quota;
offline tests do not establish live model accuracy, availability or latency.

## Offline rehearsal

```powershell
agent/.venv/Scripts/python.exe -m agent.cli 'What is my balance?' --resolve-read
agent/.venv/Scripts/python.exe -m agent.cli 'Analyze spending 2026-10' --resolve-read
agent/.venv/Scripts/python.exe -m agent.cli --interactive --provider mock
```

The mock uses deterministic rules; it is not an LLM. CLI proposals never execute
transfers or cancellations. To use offline interpretation in the website, explicitly
set `AGENT_PROVIDER=mock` while retaining `USE_MOCK_AGENT=false`.

## Interfaces and safeguards

`process_message(ChatInput, tool_catalog, tool_results=None) -> AgentResult` remains
the public stateless interface. `process_turn` additionally returns caller-owned
state for persistence. Catalog, state and trusted-result conventions are documented
in `integration.md`; `testing_memory_trial1.md` supplies local rehearsals.

The live adapter requests strict JSON-schema intent, reuses a transport per worker
thread and validates results through the same service as the mock. Request guards,
exact amounts, verified identities, flexible spending dates and correlated tool
results are provider-independent. No automatic retry, provider fallback or generated
code execution is enabled. Failures create no new proposal. Backend confirmation,
fresh policy checks and simulated MFA remain mandatory where required.

Historical milestone documents record earlier implementation evidence; current
setup instructions and provider configuration are defined here. The submission
architecture and current scope are in `technical_documentation.md`.

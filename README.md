# Banking AI Agent — Shared starter contracts

This starter contains the **real executable contracts and synthetic fixtures**, frozen at v1.0.0. Commit these files to `main` before the five teammates start independent coding.

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-contracts.txt
python -m pytest tests/test_contracts.py -q
```

From repository root, imports such as `from contracts.models import Transaction` should work.

## Module ownership

- P1: `agent/`, `docs/agent/`
- P2: `backend/`, `frontend/`, `infra/`, `docker-compose.yml`, `docs/app/`
- P3: `finance/`, `docs/finance/`
- P4: `security/`, `docs/security/`
- P5: `subscriptions/`, `docs/subscriptions/`

Only the shared-contract maintainer edits `contracts/`, `fixtures/`, `tests/test_contracts.py`. All five coding AIs must use the same committed revision.

## IMPORTANT: changes relative to earlier Word spec

This executable package is authoritative over the preliminary Word spec. P5's `assess_cancellation` returns a typed `CancellationAssessment` (not `dict`). `Transaction.timestamp` is a timezone-aware `datetime`; money is `Decimal` in Python and a string in JSON. Shared `tool_schemas.py` contains exact argument validation. Teammates should upload this ZIP or reference the checked-out repository when prompting their coding AI.

## Security and scope

All fixture data is fake. Do not connect to live banks. LLM output is untrusted; state-changing operations must pass server-side authentication, validation, policy, approval, and audit. This package is an interface/test foundation, not a deployed or security-certified banking application.

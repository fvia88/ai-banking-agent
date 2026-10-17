# Milestone two standalone agent verification

Completed on 17 October 2026 for the bounded single-request scope below.
No teammate implementation is imported. Frozen contracts and fixtures remain
unchanged. Banking tools are synthetic; transfer/cancellation outputs are
proposals only. This is not completion of the full hackathon product.

## Verified behavior

| Area | Evidence |
| --- | --- |
| Five basic intents | Balance, spending, listing subscriptions, transfer, and cancellation proposals passed live checks across separate runs |
| Clarification | User-provided Gemini transcripts show ambiguous Alice, missing amount/recipient/month/subscription asking for details without proposals |
| Invalid amounts | Explicit correction for zero/negative values; no proposal; offline regression coverage |
| Unsupported cancellation | User-provided live CloudMusic transcript rejected unsupported cancellation |
| Account context | Offline stub tests cover absent/multiple accounts, transfer/cancellation on locked accounts, and permitted read queries |
| Alternative balance wording | User-provided live "How much money do I have?" produced get_balance |
| Typo | Live "whats my balnce?" produced get_balance |
| Natural transfer wording | Live "Could you send 500 yuan to Bob?" produced the exact 500.00 CNY transfer proposal |
| Natural cancellation | Live "Could you cancel StreamBox?" produced request_subscription_cancel with sub_streambox |
| Alternative spending | Live "How much did I spend in 2026-10?" produced analyze_spending with account_001 and 2026-10 |
| Alternative subscription wording | Live "Show my recurring charges" produced list_subscriptions |
| Non-request framing | Offline tests deliberately inject mutation interpretations for negations, quotes, note data, and hypotheticals; no mutation proposal |
| Provider failure | Safe categories distinguish unavailable service, region rejection, quota, and several transport failures; errors never silently switch to mock |

Live calls used gemini-3.1-flash-lite. Cancellation and alternative spending
first encountered 503 and passed on isolated retry. These are observations
across separate requests, not evidence of uninterrupted service reliability.
No automatic retries or paid fallback were introduced.

## Code changes in this closing step

- Gemini default changed to gemini-3.1-flash-lite; environment overrides remain.
- Response text is assembled from visible candidate parts, excluding thought
  parts and metadata rather than repeatedly accessing response.text.
- Regression tests cover visible-text parsing, empty candidates, and service
  handling of recorded interpretations for alternative read-request wording.
- 87 offline tests passed with one existing SDK/Pydantic deprecation warning.
  Live calls may still print a metadata notice from inside the pinned SDK.

## Reproduce from repository root

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
agent/.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_contracts.py agent/tests -q

# Explicit live calls; saved key must be available in this process.
$env:GEMINI_MODEL = 'gemini-3.1-flash-lite'
agent/.venv/Scripts/python.exe -m agent.cli 'whats my balnce?' --provider gemini
agent/.venv/Scripts/python.exe -m agent.cli 'Could you send 500 yuan to Bob?' --provider gemini
agent/.venv/Scripts/python.exe -m agent.cli 'Could you cancel StreamBox?' --provider gemini
agent/.venv/Scripts/python.exe -m agent.cli 'How much did I spend in 2026-10?' --provider gemini --resolve-read
agent/.venv/Scripts/python.exe -m agent.cli 'Show my recurring charges' --provider gemini
```

The pytest command is offline. Live commands consume API quota and can fail
because of provider availability or connectivity; generic failure replies are
not successful verification. To diagnose an exact prompt, use e.g.:

```powershell
agent/.venv/Scripts/python.exe -m agent.diagnose --message 'Could you cancel StreamBox?' --expected-intent cancel
```

## Limits and milestone three handoff

- Request framing is conservative English pattern matching around Gemini
  interpretation, not comprehensive semantic safety. Some legitimate phrases
  still ask for rephrasing. No claim of universal typo/language support.
- Transfer amounts must appear numerically in the request. Written-out numbers
  and general currency conversion are not supported in this milestone.
- Recipient names must match verified supplied context; aliases and pronouns
  are not generally resolved. Dates should be explicit YYYY-MM.
- Polite requests work for single turns; existing clarification replay is a
  limited shortcut. General multi-turn state, correction, interruption, and
  result-to-original-payload matching belong to milestone three.
- Catalog/context/result shapes are local conventions documented in
  integration.md. Caller authentication and backend authorization are required.
- No DAG, dependent cancellation-to-transfer workflow, actual policy engine,
  subscription detector, or execution is implemented here.
- Offline tests using recorded interpretations verify Python behavior, not
  Gemini language accuracy. Live results above provide the separate evidence.

Next: the local stub-backend conversation harness, with state outside the
stateless service and no dependency on unfinished teammate implementations.

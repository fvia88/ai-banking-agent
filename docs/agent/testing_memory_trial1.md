# Memory trial 1

> Maintenance note (30 October 2026): live commands now target Groq. Earlier
> observations describe the provider used at that milestone and are not Groq
> benchmark evidence. See README.md for current setup and technical_documentation.md
> for current capabilities; the historical limitations below may be superseded.


## Spending report explanation

### P3 merged-output validation (2026-10-19)

Validated actual finance.analytics.analyze_spending output through the P1
proposal/result round trip, rather than only the CLI's simple fixture aggregator.

| Dataset | P3 report | P1 explanation check |
| --- | --- | --- |
| Shared transactions, October 2026 | CNY 1843.00; Shopping 1200.00, Food 360.00, Transport 125.00, Education 80.00, Subscriptions 58.00, Other 20.00; no anomalies | Total and largest three categories match; three further categories acknowledged; no anomalies invented. |
| P3 synthetic transactions, September 2026 | CNY 9254.70; seven flags spanning six codes | Education 5800.00, Shopping 2680.00 and Dining 327.50 shown; first three flags shown and four further flags acknowledged. |

Each of the six actual anomaly codes was also checked individually: category
monthly spike, large versus category history, possible duplicate charge, large
transaction with insufficient history, conflicting duplicate IDs and identical
duplicate IDs. Explanations retain the transaction ID and distinction between a
possible duplicate charge and duplicate input records. No source report is mutated.

Remaining limits to confirm with P3:

- The brief reply shows only three flags in P3's supplied order; it does not
  independently rank them or expose a detail-view command.
- Thresholds, ratios, merchant names and transaction amounts are not extracted
  from free-text reasons. Ask for an agreed trusted transaction/detail format
  before explaining those specifics. No invented baseline or merchant is added.
- October diagnostics include CREDITS_EXCLUDED and REFUND_NOT_NETTED, but they
  are separate from SpendingReport. The reply states default rules, not
  report-specific diagnostic counts/amounts. Those details remain deferred.
- These checks use P3's currently merged datasets, not the new example he plans
  to send. Recheck his supplied example when it arrives.

Run only these P3/P1 compatibility tests:

```powershell
agent/.venv/Scripts/python.exe -m pytest -p no:cacheprovider agent/tests/test_tool_results.py -q -k p3
```

```powershell
agent/.venv/Scripts/python.exe -m agent.cli 'Analyze spending 2026-10' --resolve-read
```

The first response is a proposal. After a matched synthetic result, the reply
now includes the report total, up to three largest reported categories, up to
three report flags, and the team's default spending rules. Empty breakdowns and
absent anomalies are stated as missing/not reported, not proof of safety.
If category totals disagree with the reported total, the reply requests review
rather than silently replacing the total.

This command still uses fixture aggregation, not the backend or P3's real report
generator. A separate automated integration check feeds the actual merged
finance.analytics.analyze_spending output to P1's result handler:

```powershell
agent/.venv/Scripts/python.exe -m pytest -p no:cacheprovider agent/tests/test_tool_results.py -q -k spending
```

Known P3 anomaly codes get fixed friendly descriptions with their transaction
IDs. Unknown codes receive a generic flag description. Free-text reasons are
not echoed; suspicious labels/IDs are withheld. The agent does not guess a
merchant, transaction amount or historical baseline from an anomaly code.
Detailed transaction explanations and separate diagnostics await an agreed
trusted input format. No live-provider call is needed to format a returned report.

## P1 rehearsal - one command (2026-10-19)

From the repository root:

```powershell
agent/.venv/Scripts/python.exe -m pytest -p no:cacheprovider agent/tests/test_conversation_acceptance.py::test_p1_rehearsal -q -s
```

This runs a scripted demo against the actual agent service and asserts the
expected behaviour. It is offline, uses mock interpretation and synthetic
fixtures, and prints the conversation without requiring you to type each turn.
Expected ending: `PASS: all rehearsal checks passed` followed by `1 passed`.
An assertion failure stops the demo instead of reporting a successful rehearsal.
No new runtime command or backend connection was added.

### What to show and say (about 3 minutes)

| Stage | What appears | Suggested explanation |
| --- | --- | --- |
| Spending | Missing-month question, October proposal, wrong-month result rejection, then CNY 1843.00 | "The agent remembers the requested month and only reports figures after receiving a matching tool result. This figure is synthetic fixture data." |
| Transfer | Alice -> amount 500 -> Alice Chen -> exact transfer proposal | "It retains accepted details and resolves an ambiguous recipient before proposing anything. This does not move money." |
| Cancellation | Missing subscription -> StreamBox -> cancellation proposal | "The selection is checked against verified subscription context. The backend will own confirmation and execution." |
| Safety | Transfer 0 rejected, then never mind clears the draft | "Invalid amounts cannot produce a transfer proposal. Discarding a draft is different from cancelling an executed action." |

The generic safety reply during the wrong-month report is intentional: the
script explains why it was rejected, verifies the pending request survived,
and then supplies the corrected report. Separate conversation IDs/catalogs are
used for the stages. This is a P1 module demo, not an integrated app or the
competition's connected cancellation-to-transfer scenario.

### Optional live interpretation segment

```powershell
agent/.venv/Scripts/python.exe -m agent.cli --interactive --provider groq
```

Enter these lines one at a time:

```text
Where did my money go?
2026-10
Could you send money to Alice?
500
Alice Chen
Cancel my subscription
StreamBox
quit
```

Expected proposals: October spending lookup; 500.00 CNY transfer to
recipient_alice; cancellation of sub_streambox. Only exact follow-up answers are
handled locally; the live provider interprets the initial requests. Interactive mode does
not resolve tool results, so it must not report spending totals here.

Keep the offline rehearsal available if API access fails. A provider failure
does not demonstrate a successful interpretation; record it separately and use
the existing diagnose command if needed. The full offline suite after adding
the rehearsal passed 315 tests, with one existing SDK Pydantic warning.

## Extension - cancellation selection memory

```powershell
agent/.venv/Scripts/python.exe -m agent.cli --interactive
```

Enter each line at the You: prompt:

```text
Cancel my subscription
Unknown
CloudMusic
StreamBox
quit
```

Expected: asks which subscription, asks again for Unknown, reports CloudMusic
cannot be cancelled while retaining the draft, then produces exactly one
request_subscription_cancel proposal for sub_streambox. Nothing is executed.
The draft lives in pending_cancellation with awaiting=subscription; after the
proposal, it is cleared and the issued proposal remains in pending_tool_requests.

Repeat with Cancel my subscription, then never mind, then StreamBox. The draft
is discarded, so the final bare merchant name must not produce a cancellation
proposal. This does not revoke previously issued proposals or cancel a bank action.

Use --provider groq on the interactive command to interpret the initial request
online. Exact merchant-name follow-ups use local matching against the current
trusted subscription list. Matching is case-insensitive and requires the whole
merchant name. Duplicate merchant names remain ambiguous and require selection
outside this bounded demo; selecting by subscription ID is not implemented.
The agent rechecks active status, cancellation support and account lock.

## Extension - spending month memory

Start a conversation (mock works offline):

```powershell
agent/.venv/Scripts/python.exe -m agent.cli --interactive
```

Enter these lines one at a time:

```text
Analyze my spending
2026-13
2026-11
quit
```

Expected: asks for a month, rejects 2026-13 while retaining the request, then
proposes analyze_spending with account_001 and period 2026-11. No figures are
reported until a matching trusted tool result is returned. The interactive
demo remains proposal-only.

To try the live provider wording instead, start with:

```powershell
agent/.venv/Scripts/python.exe -m agent.cli --interactive --provider groq
```

Enter "Where did my money go?", then "2026-11" (without quotes). the live provider handles
the initial request; the exact YYYY-MM follow-up is validated locally. Enter
these answers at the CLI's You: prompt, not at the PowerShell prompt.

An unfinished spending request is stored in pending_spending with awaiting=period.
Standalone never mind clears it. Accepted proposals move into pending_tool_requests
for result matching. The caller still saves the returned state on every turn.
Only exact YYYY-MM follow-ups are supported here; natural month-name answers,
corrections and switching requests during clarification are deferred.

Automated acceptance coverage also checks unchanged account selection and
separate spending/transfer conversations:

```powershell
agent/.venv/Scripts/python.exe -m pytest -p no:cacheprovider agent/tests/test_conversation_acceptance.py agent/tests/test_conversation_state.py -q
```

## Task 6 - rehearsal checklist and results (2026-10-19)

Run these commands from the repository root. These demonstrations use synthetic
accounts and recipients; transfer proposals never execute banking actions.

### 1. Regression checks

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = (Get-Location).Path + ';' + (Join-Path (Get-Location) 'backend')
$env:DATABASE_URL = 'sqlite:///:memory:'
agent/.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_contracts.py agent/tests backend/tests finance/tests subscriptions/tests -q
```

Observed: **217 passed**, with one existing Google SDK Pydantic deprecation
warning. These are automated tests; they do not make live the live provider requests.
The environment settings above apply to this terminal session.

### 2. Offline rehearsal

```powershell
agent/.venv/Scripts/python.exe -m agent.cli --interactive
```

Enter each line separately:

```text
Transfer to Alice
500
Alice Chen
quit
```

Observed: asks for amount, then full name, then proposes exactly 500.00 CNY to
recipient_alice. No proposal appears before clarification finishes.

Start the interactive command again and enter:

```text
Transfer to Alice
500
never mind
Transfer 300 to Bob
quit
```

Observed: discards the unfinished Alice draft and proposes 300.00 CNY to
recipient_bob without reusing the old amount or recipient.

```powershell
agent/.venv/Scripts/python.exe -m agent.cli 'What is my balance?' --resolve-read
agent/.venv/Scripts/python.exe -m agent.cli 'Analyze spending 2026-10' --resolve-read
```

Observed: a proposal followed by CNY 5000.00 balance / CNY 1843.00 October
spending. Both figures come from fixtures, not a bank or the live provider.
Conversation isolation is covered by the regression suite and Trial 3 below.

### 3. Live provider rehearsal

If this terminal has not inherited your previously saved key, load it without
printing it:

```powershell
if (!$env:GROQ_API_KEY) {
    $env:GROQ_API_KEY = [Environment]::GetEnvironmentVariable('GROQ_API_KEY', 'User')
}
agent/.venv/Scripts/python.exe -m agent.cli 'How much money do I have?' --provider groq
agent/.venv/Scripts/python.exe -m agent.cli 'Could you send 500 yuan to Bob?' --provider groq
agent/.venv/Scripts/python.exe -m agent.cli --interactive --provider groq
```

For the interactive command enter Transfer to Alice, then 500, then Alice Chen,
then quit, each on a separate line.

Observed in live service checks: the balance wording produced get_balance;
the Bob wording produced request_transfer for 500.00 CNY to recipient_bob;
the Alice conversation asked both clarification questions and then produced the
correct proposal. The initial messages used the live provider; exact amount/name
follow-ups used local clarification logic. No banking actions executed.

The first restricted-network attempt failed with network_connection_error;
the subsequent network-enabled run passed all three scenarios. The SDK still
printed a thought_signature metadata warning, but returned usable structured
output. Live checks establish these examples worked on this run, not universal
language understanding or provider availability.

This task changed only this testing document. No runtime fixes were needed.
The separate teammate handoff is intentionally deferred.

This offline trial demonstrates a pending transfer retaining its amount and
recipient across three turns. It uses the mock provider and synthetic fixtures.
No API key is needed. No transfers or cancellations execute.

## Start the trial

The memory loop is now built into the CLI. From the repository root, run:

```powershell
agent/.venv/Scripts/python.exe -m agent.cli --interactive
```

Then type `Transfer to Alice`, `500`, and `Alice Chen` one at a time. The
expected results below apply. Type `quit`, press Ctrl+C, or end input to exit
cleanly. The old pasted block below is retained as an explanatory alternative;
you no longer need to paste it to run the trial.

To use the live provider for the initial request instead of mock interpretation:

```powershell
agent/.venv/Scripts/python.exe -m agent.cli --interactive --provider groq
```

That requires your configured key and API access. Exact amount/name answers
still use local clarification logic. Interactive mode does not support
`--clarify`, `--resolve-read`, or a positional starting message; it never executes
tools or confirms proposals.

## Original pasted-loop alternative

Open PowerShell in the repository root:

```text
C:\Users\claine\Downloads\ai-banking-agent
```

Paste this entire block into the terminal:

```powershell
$memoryDemo = @'
import os
from contracts.models import ChatInput
from agent.mock_tools import demo_catalog
from agent.service import process_turn

os.environ['AGENT_PROVIDER'] = 'mock'
catalog = demo_catalog()

print('Memory demo: type quit to exit. No banking actions execute.')

while True:
    message = input('\nYou: ').strip()
    if message.lower() == 'quit':
        break
    if not message:
        continue

    turn = process_turn(
        ChatInput(conversation_id='memory_demo', message=message),
        catalog,
    )

    print('Agent:', turn.result.reply)
    print('Remembered state:', turn.state.model_dump_json())

    for proposal in turn.result.proposals:
        print('Proposal:', proposal.model_dump_json())

    for entry in catalog:
        entry['context']['conversation_state'] = turn.state.model_dump(mode='json')
'@

agent/.venv/Scripts/python.exe -c $memoryDemo
```

## Enter these three messages

At the `You:` prompt, enter each message separately and press Enter:

```text
Transfer to Alice
500
Alice Chen
```

Do not enter all three as one message.

## Expected results

| Your input | Agent behavior | Remembered details |
| --- | --- | --- |
| `Transfer to Alice` | Asks how much CNY to transfer; no proposal | Unresolved recipient Alice; awaiting amount |
| `500` | Asks for the recipient's full name; no proposal | Amount 500.00 retained along with Alice; awaiting recipient |
| `Alice Chen` | Produces one transfer proposal; nothing executes | Pending draft cleared after the proposal is returned |

The final proposal's arguments should be:

```json
{
  "source_account_id": "account_001",
  "recipient_id": "recipient_alice",
  "amount": "500.00",
  "currency": "CNY"
}
```

The proposal ID is generated at runtime and will differ between runs.

## What to watch

- `Remembered state` shows the pending details after each turn.
- There should be no proposal after the first or second message.
- The third response must retain the amount 500.00 and select Alice Chen's ID.
- The loop passes returned state into the next call. The service does not store
  conversation memory globally.
- Clearing a completed draft means a proposal was produced, not that a transfer
  succeeded. Approval/execution records are outside this trial.

## Exit and limitations

Type `quit` to exit. Start the interactive command again for a fresh trial.
The built-in CLI handles Ctrl+C/end-of-input cleanly; the original raw block
does not catch those exceptions.

Memory exists only while this demo process runs; there is no database storage.
This trial supports a pending transfer with numeric amount answers and verified
recipient-name answers. General corrections and request switching are not
implemented yet. Standalone `never mind` / `nevermind` now discards a pending draft.

## Trial 2 - discard an unfinished request

Start the built-in interactive command again, then type:

```text
Transfer to Alice
500
never mind
Transfer 300 to Bob
quit
```

After `never mind`, expect `Unfinished request discarded.`, no proposals, and
state with pending_transfer=null and awaiting=null. The next request should
propose 300.00 CNY to recipient_bob; it must not reuse Alice or 500.00.

Abandonment is local and does not require the live provider. Matching is case-insensitive
and permits trailing sentence punctuation. Only a standalone command clears
the draft; quoted words or an embedded phrase are not an abandonment command.
The caller must retain the cleared returned state. This does not revoke a
proposal already handed to a backend or cancel an executed banking operation.
If no unfinished draft exists, the reply says so instead of claiming cancellation.

## Trial 3 - conversation isolation

The interactive CLI demonstrates one conversation per process. To verify two
conversations interleaved in the same process, run the automated checks:

```powershell
agent/.venv/Scripts/python.exe -m pytest -p no:cacheprovider agent/tests/test_conversation_turns.py -q -k 'interleaved or abandonment_in_one or foreign_snapshot or mixed_catalog'
```

Expected: 5 passed. The other tests in that file are deselected by this filter.

The main scenario alternates:

| Conversation A | Conversation B |
| --- | --- |
| Transfer 500 to Alice | Transfer to Alice |
| Waits for a full name | 300; then waits for a full name |
| Alice Chen -> 500.00 to recipient_alice | Alice Wang -> 300.00 to recipient_alice_2 |

Both completion orders are tested. Completing or discarding A must not change B.
A snapshot with the wrong conversation ID, or mixed snapshots across catalog
entries, must not produce a proposal. Rejected input must not mutate caller-owned
context. The caller keeps a separate catalog/state snapshot for each conversation.

This verifies in-process state isolation, not authentication or production
cross-user authorization. P2 must bind stored conversations to authenticated
users and use the correct snapshot when handling each request. No database,
backend code, live the live provider calls, or banking execution are involved in these tests.

## Trial 4 - tool-result round trip and matching

Run the fixture-backed read demonstrations:

```powershell
agent/.venv/Scripts/python.exe -m agent.cli 'What is my balance?' --resolve-read
agent/.venv/Scripts/python.exe -m agent.cli 'Analyze spending 2026-10' --resolve-read
```

Each command prints a proposal first, then a grounded reply: balance CNY 5000.00
or October spending CNY 1843.00. The caller retains the original proposal,
mock_tools supplies a typed synthetic result with matching arguments, and the
accepted request is consumed in returned state. No live-provider calls or mutations occur.

Run mismatch and replay checks:

```powershell
agent/.venv/Scripts/python.exe -m pytest -p no:cacheprovider agent/tests/test_tool_results.py -q
```

Tests reject wrong conversation/proposal/tool/arguments/account/month and missing
original proposal records. They also verify safe tool failures, replay rejection,
and that consuming one result leaves other pending requests intact.

Remembered state now includes pending_tool_requests for proposals already issued.
This is different from pending_transfer, which is an unfinished clarification
draft. Completing clarification or saying never mind clears the draft, not the
issued proposal history awaiting results. Only saving the returned consumed state
prevents sequential replay; backend authorization and atomic idempotency remain
P2 responsibilities. See integration.md for the proposed envelope format.

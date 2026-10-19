# Memory trial 1

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

Use --provider gemini on the interactive command to interpret the initial request
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

To try Gemini wording instead, start with:

```powershell
agent/.venv/Scripts/python.exe -m agent.cli --interactive --provider gemini
```

Enter "Where did my money go?", then "2026-11" (without quotes). Gemini handles
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
warning. These are automated tests; they do not make live Gemini requests.
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
spending. Both figures come from fixtures, not a bank or Gemini.
Conversation isolation is covered by the regression suite and Trial 3 below.

### 3. Live Gemini rehearsal

If this terminal has not inherited your previously saved key, load it without
printing it:

```powershell
if (!$env:GEMINI_API_KEY) {
    $env:GEMINI_API_KEY = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY', 'User')
}
agent/.venv/Scripts/python.exe -m agent.cli 'How much money do I have?' --provider gemini
agent/.venv/Scripts/python.exe -m agent.cli 'Could you send 500 yuan to Bob?' --provider gemini
agent/.venv/Scripts/python.exe -m agent.cli --interactive --provider gemini
```

For the interactive command enter Transfer to Alice, then 500, then Alice Chen,
then quit, each on a separate line.

Observed in live service checks: the balance wording produced get_balance;
the Bob wording produced request_transfer for 500.00 CNY to recipient_bob;
the Alice conversation asked both clarification questions and then produced the
correct proposal. The initial messages used Gemini; exact amount/name
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

To use Gemini for the initial request instead of mock interpretation:

```powershell
agent/.venv/Scripts/python.exe -m agent.cli --interactive --provider gemini
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

Abandonment is local and does not require Gemini. Matching is case-insensitive
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
backend code, live Gemini calls, or banking execution are involved in these tests.

## Trial 4 - tool-result round trip and matching

Run the fixture-backed read demonstrations:

```powershell
agent/.venv/Scripts/python.exe -m agent.cli 'What is my balance?' --resolve-read
agent/.venv/Scripts/python.exe -m agent.cli 'Analyze spending 2026-10' --resolve-read
```

Each command prints a proposal first, then a grounded reply: balance CNY 5000.00
or October spending CNY 1843.00. The caller retains the original proposal,
mock_tools supplies a typed synthetic result with matching arguments, and the
accepted request is consumed in returned state. No Gemini calls or mutations occur.

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

# Memory trial 1

This offline trial demonstrates a pending transfer retaining its amount and
recipient across three turns. It uses the mock provider and synthetic fixtures.
No API key is needed. No transfers or cancellations execute.

## Start the trial

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

Type `quit` to exit. Start the block again for a fresh trial.

Memory exists only while this demo process runs; there is no database storage.
This trial supports a pending transfer with numeric amount answers and verified
recipient-name answers. General corrections, interruptions, and `never mind`
handling are not implemented yet.

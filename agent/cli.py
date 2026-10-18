import argparse
import os
from contracts.models import ChatInput
from pydantic import ValidationError
from .service import process_message, process_turn
from .mock_tools import demo_catalog, read_result
from .conversation import ConversationState, PendingToolRequest


def _interactive(catalog):
    print("Type a message, or quit to exit. Proposals do not execute or confirm actions.")
    while True:
        try:
            message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nMemory demo ended.")
            return
        if message.casefold() == "quit":
            print("Memory demo ended.")
            return
        if not message:
            continue
        try:
            chat = ChatInput(conversation_id="interactive_demo", message=message)
        except ValidationError:
            print("Please enter a message of 1 to 4000 characters. Pending details were retained.")
            continue
        try:
            turn = process_turn(chat, catalog)
        except KeyboardInterrupt:
            print("\nMemory demo ended.")
            return
        print(turn.result.model_dump_json(indent=2))
        print("Remembered state:", turn.state.model_dump_json())
        for entry in catalog:
            entry["context"]["conversation_state"] = turn.state.model_dump(mode="json")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Synthetic banking agent demo; no mutations")
    parser.add_argument("message", nargs="?", default=None)
    parser.add_argument("--provider", choices=["mock", "gemini"], default="mock")
    parser.add_argument("--clarify", help="Follow-up answer; CLI supplies prior request explicitly")
    parser.add_argument("--resolve-read", action="store_true")
    parser.add_argument("--interactive", action="store_true", help="Run the in-memory conversation demo")
    args = parser.parse_args(argv)
    if args.interactive and (args.message is not None or args.clarify is not None or args.resolve_read):
        parser.error("--interactive cannot be combined with message, --clarify, or --resolve-read")
    os.environ["AGENT_PROVIDER"] = args.provider
    print(f"SYNTHETIC DEMO | provider={args.provider}")
    catalog = demo_catalog()
    if args.interactive:
        return _interactive(catalog)
    chat = ChatInput(conversation_id="demo", message=args.message or "What is my balance?")
    result = process_message(chat, catalog)
    print(result.model_dump_json(indent=2))
    if args.clarify and result.needs_clarification:
        for entry in catalog:
            entry["context"]["clarification_request"] = chat.message
        chat = ChatInput(conversation_id="demo", message=args.clarify)
        result = process_message(chat, catalog)
        print(result.model_dump_json(indent=2))
    if args.resolve_read and result.proposals:
        proposal = result.proposals[0]
        if proposal.tool.value.startswith("request_"):
            print("Execution unavailable: this CLI never transfers or cancels.")
            return
        for entry in catalog:
            entry["context"]["conversation_state"] = ConversationState(
                conversation_id=chat.conversation_id,
                pending_tool_requests=(PendingToolRequest(proposal=proposal.model_copy(deep=True)),),
            ).model_dump(mode="json")
        turn = process_turn(chat, catalog, [read_result(chat, proposal)])
        for entry in catalog:
            entry["context"]["conversation_state"] = turn.state.model_dump(mode="json")
        print(turn.result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

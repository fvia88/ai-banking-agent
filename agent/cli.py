import argparse
import os
from contracts.models import ChatInput
from .service import process_message
from .mock_tools import demo_catalog, read_result


def main():
    parser = argparse.ArgumentParser(description="Synthetic banking agent demo; no mutations")
    parser.add_argument("message", nargs="?", default="What is my balance?")
    parser.add_argument("--provider", choices=["mock", "gemini"], default="mock")
    parser.add_argument("--clarify", help="Follow-up answer; CLI supplies prior request explicitly")
    parser.add_argument("--resolve-read", action="store_true")
    args = parser.parse_args()
    os.environ["AGENT_PROVIDER"] = args.provider
    print(f"SYNTHETIC DEMO | provider={args.provider}")
    catalog = demo_catalog()
    chat = ChatInput(conversation_id="demo", message=args.message)
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
            entry["context"]["pending_proposal_ids"] = [proposal.proposal_id]
        result = process_message(chat, catalog, [read_result(chat, proposal)])
        print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

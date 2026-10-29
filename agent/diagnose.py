"""Opt-in live probe. Prints only fixed categories, never raw SDK errors."""
# Troubleshooting tool for the live Groq connection.
# run with python -m agent.diagnose
import argparse
from time import perf_counter
from .groq_provider import GroqProvider
from .provider import Intent, ProviderError
from pydantic import ValidationError


def main(message="What is my balance?", expected_intent="balance", provider="groq"):
    if provider != 'groq':
        raise ValueError('Only the Groq live provider is supported')
    print("Live Groq diagnostic (one request, no bank operations)")
    started = perf_counter()
    try:
        payload = GroqProvider().extract(message)
        intent = Intent.model_validate_json(payload)
        if intent.intent != expected_intent:
            print("RESULT: unexpected_intent")
            return 1
        print(f"RESULT: success; structured {intent.intent} intent validated")
        return 0
    except ProviderError as exc:
        print(f"RESULT: {exc.category}")
        if exc.http_code is not None:
            print(f"HTTP: {exc.http_code}")
        hints = {
            "missing_key": "Set GROQ_API_KEY in this terminal.",
            "provider_unavailable": "Groq is temporarily unavailable. Retry later.",
            "gateway_timeout": "The API request returned HTTP 504: a gateway/upstream timeout. Generation did not complete.",
            "gateway_error": "The API request returned HTTP 502: a gateway/upstream error.",
            "model_not_found": "Check GROQ_MODEL and your Groq model permissions.",
            "quota_or_rate_limit": "Check the Groq free-tier request/token limits; retry after the limit resets.",
            "invalid_request": "Check Groq model support for strict JSON schema and the request configuration.",
            "access_denied": "Check account, project permissions, and supported-region eligibility.",
            "sdk_or_network_error": "Check local network connectivity and SDK installation.",
            "network_timeout": "The HTTP client timed out without a completed response.",
            "proxy_error": "The HTTP client reported a proxy connection failure.",
            "network_protocol_error": "The HTTP connection ended with a protocol error before generation completed.",
            "network_connection_error": "The HTTP client could not establish or maintain the connection.",
        }
        print(hints.get(exc.category, "Provider response was unsuccessful."))
        return 1
    except ValidationError:
        print("RESULT: invalid_model_output; local Pydantic validation failed")
        return 1
    finally:
        print(f"ELAPSED_SECONDS: {perf_counter() - started:.3f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live provider intent diagnostic; no banking operations")
    parser.add_argument('--provider', choices=['groq'], default='groq')
    parser.add_argument("--message", default="What is my balance?")
    parser.add_argument("--expected-intent", default="balance",
                        choices=["balance", "spending", "subscriptions", "transfer", "cancel", "unknown"])
    parser.add_argument("--repeat", type=int, choices=range(1, 6), default=1,
                        help="Run 1-5 sequential probes in one process to compare connection reuse")
    args = parser.parse_args()
    codes = [main(args.message, args.expected_intent, args.provider) for _ in range(args.repeat)]
    raise SystemExit(max(codes))

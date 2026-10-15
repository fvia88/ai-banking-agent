"""Opt-in live probe. Prints only fixed categories, never raw SDK errors."""
# troubleshooting tool for gemini connection
# run with python -m agent.diagnose
from .gemini_provider import GeminiProvider
from .provider import Intent, ProviderError
from pydantic import ValidationError


def main():
    print("Live Gemini diagnostic (one request, no bank operations)")
    try:
        payload = GeminiProvider().extract("What is my balance?")
        intent = Intent.model_validate_json(payload)
        if intent.intent != "balance":
            print("RESULT: unexpected_intent")
            return 1
        print("RESULT: success; structured balance intent validated")
        return 0
    except ProviderError as exc:
        print(f"RESULT: {exc.category}")
        if exc.http_code is not None:
            print(f"HTTP: {exc.http_code}")
        hints = {
            "missing_key": "Set GEMINI_API_KEY in this terminal.",
            "provider_unavailable": "Gemini returned 503. Retry later or explicitly select another eligible free-tier model.",
            "gateway_timeout": "The API request returned HTTP 504: a gateway/upstream timeout. Generation did not complete.",
            "gateway_error": "The API request returned HTTP 502: a gateway/upstream error.",
            "model_not_found": "Check GEMINI_MODEL; unset an obsolete model override.",
            "quota_or_rate_limit": "Check the project's free-tier quota in AI Studio.",
            "invalid_request": "The provider rejected the request configuration.",
            "unsupported_location": "Gemini rejected the request because the user location is unsupported. Check Google's official region eligibility; changing request schema will not resolve this rejection.",
            "access_denied": "Check account, project permissions, and supported-region eligibility.",
            "sdk_or_network_error": "Check local network connectivity and SDK installation.",
        }
        print(hints.get(exc.category, "Provider response was unsuccessful."))
        return 1
    except ValidationError:
        print("RESULT: invalid_model_output; local Pydantic validation failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

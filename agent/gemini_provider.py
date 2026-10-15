# gemini_provider.py connects my agent to real gemini API
# it sends a msg w/ instructions, requests structured JSON, and convert failures into safe error categories
import os
from .provider import Intent, ProviderError
from .prompts import SYSTEM_INSTRUCTION


class GeminiProvider:
    def extract(self, message: str) -> str:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise ProviderError("Missing Gemini key", category="missing_key")
        try:
            from google import genai
            from google.genai import types
            timeout = int(os.getenv("AGENT_TIMEOUT_SECONDS", "20"))
            if not 1 <= timeout <= 60:
                raise ValueError("Invalid timeout")
            # create the api client
            with genai.Client(api_key=key, http_options=types.HttpOptions(
                timeout=timeout * 1000, retry_options=types.HttpRetryOptions(attempts=1)
            )) as client:
                # calls gemini and stores the returned response
                # this is the part tht makes the online API request
                response = client.models.generate_content(
                    model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
                    # katanya sih terminak setting $env:GEMINI_MODEL = 'gemini-3.1-flash-lite'
                    # takes precedence over the codes default, if tht env var is absent, code still defaults to 3.8 flash
                    contents=message,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        # Preserve JSON Schema keywords rather than converting to
                        # the SDK's older OpenAPI-style Schema representation.
                        response_json_schema=Intent.model_json_schema(),
                        temperature=0,
                    ),
                )
                if not response.text:
                    raise ProviderError("Empty response", category="empty_response")
                return response.text
        except ProviderError:
            raise
        except Exception as exc:
            code = getattr(exc, "code", None)
            if not isinstance(code, int):
                code = None
            category = {400: "invalid_request", 401: "authentication", 403: "access_denied",
                        404: "model_not_found", 429: "quota_or_rate_limit",
                        500: "provider_server_error", 502: "gateway_error",
                        503: "provider_unavailable", 504: "gateway_timeout"}.get(code, "sdk_or_network_error")
            # Inspect internally, but expose only a fixed category, not raw errors.
            provider_message = str(getattr(exc, "message", "")).lower()
            if code in (400, 403) and "user location is not supported" in provider_message:
                category = "unsupported_location"
            raise ProviderError("Gemini unavailable", category=category, http_code=code) from None

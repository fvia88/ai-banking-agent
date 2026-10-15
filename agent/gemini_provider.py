import os
from .provider import Intent, ProviderError
from .prompts import SYSTEM_INSTRUCTION


class GeminiProvider:
    def extract(self, message: str) -> str:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise ProviderError("Missing Gemini key")
        try:
            from google import genai
            from google.genai import types
            timeout = int(os.getenv("AGENT_TIMEOUT_SECONDS", "20"))
            if not 1 <= timeout <= 60:
                raise ValueError("Invalid timeout")
            with genai.Client(api_key=key, http_options=types.HttpOptions(
                timeout=timeout * 1000, retry_options=types.HttpRetryOptions(attempts=1)
            )) as client:
                response = client.models.generate_content(
                    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                    contents=message,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=Intent,
                        temperature=0,
                    ),
                )
                if not response.text:
                    raise ProviderError("Empty response")
                return response.text
        except Exception:
            raise ProviderError("Gemini unavailable") from None

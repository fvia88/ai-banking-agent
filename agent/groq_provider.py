"""Optional Groq intent extraction; no tools, execution or Gemini fallback."""
import os
from threading import local

from .prompts import SYSTEM_INSTRUCTION
from .provider import Intent, ProviderError

_thread_client = local()


def _close_thread_client():
    client = getattr(_thread_client, 'client', None)
    _thread_client.client = None
    _thread_client.config = None
    if client is not None:
        try:
            client.close()
        except Exception:
            pass


def _get_client(key, timeout, factory):
    config = (key, timeout, factory, *(os.getenv(name) for name in
              ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY')))
    if getattr(_thread_client, 'config', None) != config or getattr(_thread_client, 'client', None) is None:
        _close_thread_client()
        client = factory(api_key=key, base_url='https://api.groq.com',
                         timeout=timeout, max_retries=0)
        _thread_client.client = client
        _thread_client.config = config
    return _thread_client.client


class GroqProvider:
    def extract(self, message: str) -> str:
        key = os.getenv('GROQ_API_KEY', '').strip()
        if not key:
            raise ProviderError('Missing Groq key', category='missing_key')
        try:
            timeout = int(os.getenv('AGENT_TIMEOUT_SECONDS', '20'))
            if not 1 <= timeout <= 60:
                raise ValueError('Invalid timeout')
            model = os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b').strip()
            if not model:
                raise ValueError('Missing model')
        except ValueError:
            raise ProviderError('Invalid Groq configuration', category='invalid_request') from None
        try:
            from groq import Groq
            schema = Intent.model_json_schema()
            # Strict Groq schemas require every property, with null for unknown
            # values. This changes only the wire schema, not the shared Intent.
            schema['required'] = list(schema['properties'])
            for field in schema['properties'].values():
                field.pop('default', None)
            response = _get_client(key, timeout, Groq).chat.completions.create(
                model=model,
                messages=[{'role': 'system', 'content': SYSTEM_INSTRUCTION},
                          {'role': 'user', 'content': message}],
                response_format={'type': 'json_schema', 'json_schema': {
                    'name': 'banking_intent', 'strict': True, 'schema': schema}},
                reasoning_effort='low', include_reasoning=False,
                max_completion_tokens=1024, temperature=0,
            )
            choices = response.choices or []
            if len(choices) != 1 or choices[0].finish_reason != 'stop':
                raise ProviderError('Groq output incomplete', category='provider_error')
            output = choices[0].message
            text = output.content
            if getattr(output, 'refusal', None) or getattr(output, 'tool_calls', None):
                raise ProviderError('Unexpected Groq output', category='provider_error')
            if not isinstance(text, str) or not text.strip():
                raise ProviderError('Empty Groq response', category='empty_response')
            # service.py validates JSON against Intent and grounds every field.
            # Never return message.reasoning or let the model invoke a tool.
            return text
        except ProviderError:
            raise
        except Exception as exc:
            _close_thread_client()
            code = getattr(exc, 'status_code', None)
            code = code if type(code) is int else None
            category = {400: 'invalid_request', 401: 'authentication', 403: 'access_denied',
                        404: 'model_not_found', 408: 'network_timeout', 422: 'invalid_request',
                        429: 'quota_or_rate_limit', 500: 'provider_server_error',
                        502: 'gateway_error', 503: 'provider_unavailable',
                        504: 'gateway_timeout'}.get(code, 'sdk_or_network_error')
            if code is None:
                import httpx
                transport = exc.__cause__ or exc
                if isinstance(transport, httpx.TimeoutException) or type(exc).__name__ == 'APITimeoutError':
                    category = 'network_timeout'
                elif isinstance(transport, httpx.ProxyError):
                    category = 'proxy_error'
                elif isinstance(transport, httpx.ProtocolError):
                    category = 'network_protocol_error'
                elif isinstance(transport, httpx.NetworkError):
                    category = 'network_connection_error'
            raise ProviderError('Groq unavailable', category=category, http_code=code) from None

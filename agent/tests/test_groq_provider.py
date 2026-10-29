"""Real SDK serialization/error handling with an offline HTTP transport."""
import json

import groq
import httpx
import pytest

from agent import cli, diagnose, service
from agent.groq_provider import GroqProvider, _close_thread_client
from agent.mock_tools import demo_catalog
from agent.provider import Intent, ProviderError, get_provider
from contracts.models import ChatInput


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    _close_thread_client()
    monkeypatch.setenv('GROQ_API_KEY', 'synthetic-groq-secret')
    monkeypatch.setenv('AGENT_TIMEOUT_SECONDS', '20')
    monkeypatch.delenv('GROQ_MODEL', raising=False)
    yield
    _close_thread_client()


def sdk_transport(monkeypatch, payload=None, *, status=200, finish='stop', failure=None):
    requests, created = [], []
    factory = groq.Groq
    def respond(request):
        requests.append(request)
        if failure:
            raise failure('synthetic-groq-secret')
        if status != 200:
            return httpx.Response(status, json={'error': {'message': 'synthetic-groq-secret'}})
        return httpx.Response(200, json={
            'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
            'model': 'openai/gpt-oss-20b',
            'choices': [{'index': 0, 'finish_reason': finish, 'message': {
                'role': 'assistant', 'content': payload,
                'reasoning': 'private synthetic reasoning, never returned'}}],
        })
    def create(**kwargs):
        created.append(kwargs)
        return factory(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False))
    monkeypatch.setattr(groq, 'Groq', create)
    return requests, created


def test_strict_schema_sdk_request_and_no_reasoning_or_execution(monkeypatch):
    payload = Intent(intent='transfer', amount='500.00', recipient='Bob').model_dump_json()
    requests, created = sdk_transport(monkeypatch, payload)
    original = Intent.model_json_schema()
    assert GroqProvider().extract('Could you send 500 yuan to Bob?') == payload
    request = json.loads(requests[0].content)
    schema = request['response_format']['json_schema']
    assert schema['strict'] is True
    assert set(schema['schema']['required']) == set(original['properties'])
    assert schema['schema']['additionalProperties'] is False
    assert Intent.model_json_schema() == original
    assert request['model'] == 'openai/gpt-oss-20b'
    assert request['reasoning_effort'] == 'low' and request['include_reasoning'] is False
    assert request['max_completion_tokens'] == 1024
    assert 'tools' not in request and len(request['messages']) == 2
    assert request['messages'][1]['content'] == 'Could you send 500 yuan to Bob?'
    assert created[0]['max_retries'] == 0 and created[0]['timeout'] == 20
    assert str(requests[0].url) == 'https://api.groq.com/openai/v1/chat/completions'


@pytest.mark.parametrize('status,category', [(400, 'invalid_request'), (401, 'authentication'),
    (403, 'access_denied'), (404, 'model_not_found'), (422, 'invalid_request'),
    (429, 'quota_or_rate_limit'), (500, 'provider_server_error'),
    (502, 'gateway_error'), (503, 'provider_unavailable'), (504, 'gateway_timeout')])
def test_http_errors_are_redacted_and_not_retried(monkeypatch, status, category):
    requests, _ = sdk_transport(monkeypatch, status=status)
    with pytest.raises(ProviderError) as caught:
        GroqProvider().extract('private user message')
    assert caught.value.category == category and caught.value.http_code == status
    assert str(caught.value) == 'Groq unavailable'
    assert caught.value.__cause__ is None
    assert len(requests) == 1


@pytest.mark.parametrize('failure,category', [(httpx.ReadTimeout, 'network_timeout'),
    (httpx.ConnectError, 'network_connection_error'), (httpx.ProxyError, 'proxy_error'),
    (httpx.RemoteProtocolError, 'network_protocol_error')])
def test_transport_errors_remain_safe(monkeypatch, failure, category):
    requests, _ = sdk_transport(monkeypatch, failure=failure)
    with pytest.raises(ProviderError) as caught:
        GroqProvider().extract('private user message')
    assert caught.value.category == category
    assert 'secret' not in str(caught.value) and len(requests) == 1


@pytest.mark.parametrize('payload,finish,category', [('', 'stop', 'empty_response'),
    (None, 'stop', 'empty_response'), ('{"intent":"balance"}', 'length', 'provider_error')])
def test_empty_and_truncated_output_is_rejected(monkeypatch, payload, finish, category):
    sdk_transport(monkeypatch, payload, finish=finish)
    with pytest.raises(ProviderError) as caught:
        GroqProvider().extract('message')
    assert caught.value.category == category


@pytest.mark.parametrize('change,recreated', [('none', False), ('model', False), ('key', True), ('timeout', True), ('proxy', True)])
def test_transport_reuse_does_not_cache_messages(monkeypatch, change, recreated):
    requests, created = sdk_transport(monkeypatch, '{"intent":"balance"}')
    GroqProvider().extract('first')
    if change == 'model': monkeypatch.setenv('GROQ_MODEL', 'openai/gpt-oss-120b')
    if change == 'key': monkeypatch.setenv('GROQ_API_KEY', 'another-synthetic-key')
    if change == 'timeout': monkeypatch.setenv('AGENT_TIMEOUT_SECONDS', '30')
    if change == 'proxy': monkeypatch.setenv('HTTPS_PROXY', 'http://synthetic-proxy.invalid')
    GroqProvider().extract('second')
    assert len(created) == (2 if recreated else 1)
    assert [json.loads(r.content)['messages'][1]['content'] for r in requests] == ['first', 'second']
    assert json.loads(requests[-1].content)['model'] == ('openai/gpt-oss-120b' if change == 'model' else 'openai/gpt-oss-20b')


def test_failure_discards_broken_transport(monkeypatch):
    from agent import groq_provider
    sdk_transport(monkeypatch, failure=httpx.ConnectError)
    with pytest.raises(ProviderError):
        GroqProvider().extract('message')
    assert groq_provider._thread_client.client is None


@pytest.mark.parametrize('setting,value,category', [('GROQ_API_KEY', '', 'missing_key'),
    ('AGENT_TIMEOUT_SECONDS', '0', 'invalid_request'), ('AGENT_TIMEOUT_SECONDS', '61', 'invalid_request'),
    ('AGENT_TIMEOUT_SECONDS', 'bad', 'invalid_request'), ('GROQ_MODEL', '', 'invalid_request')])
def test_bad_local_configuration_never_sends_request(monkeypatch, setting, value, category):
    monkeypatch.setenv(setting, value)
    requests, created = sdk_transport(monkeypatch)
    with pytest.raises(ProviderError) as caught:
        GroqProvider().extract('message')
    assert caught.value.category == category and not requests and not created


@pytest.mark.parametrize('message,intent,tool', [
    ('How much money do I have?', Intent(intent='balance'), 'get_balance'),
    ('Where did my money go in 2026-10?', Intent(intent='spending', period='2026-10'), 'analyze_spending'),
    ('Find my recurring charges', Intent(intent='subscriptions'), 'list_subscriptions'),
    ('Could you send 500 yuan to Bob?', Intent(intent='transfer', amount='500.00', recipient='Bob'), 'request_transfer'),
    ('Cancel StreamBox', Intent(intent='cancel', subscription='StreamBox'), 'request_subscription_cancel'),
])
def test_all_five_intents_use_existing_service_validation(monkeypatch, message, intent, tool):
    monkeypatch.setenv('AGENT_PROVIDER', 'groq')
    requests, _ = sdk_transport(monkeypatch, intent.model_dump_json())
    result = service.process_message(ChatInput(conversation_id='groq_test', message=message), demo_catalog())
    assert len(result.proposals) == 1 and result.proposals[0].tool.value == tool
    assert len(requests) == 1
    assert 'succeeded' not in result.reply and 'Verified balance' not in result.reply


@pytest.mark.parametrize('payload', ['not JSON', '{"intent":"transfer","amount":500}',
                                      '{"intent":"balance","extra":"injected"}'])
def test_service_rejects_invalid_model_output(monkeypatch, payload):
    monkeypatch.setenv('AGENT_PROVIDER', 'groq')
    sdk_transport(monkeypatch, payload)
    result = service.process_message(ChatInput(conversation_id='groq_test', message='Send 500 to Bob'), demo_catalog())
    assert not result.proposals and 'did not pass validation' in result.reply


def test_provider_and_cli_can_select_groq_without_changing_default(monkeypatch, capsys):
    monkeypatch.setenv('AGENT_PROVIDER', 'groq')
    assert isinstance(get_provider(), GroqProvider)
    sdk_transport(monkeypatch, Intent(intent='transfer', amount='30', recipient='Bob').model_dump_json())
    cli.main(['Send 30 to Bob', '--provider', 'groq'])
    assert 'provider=groq' in capsys.readouterr().out
    cli.main(['What is my balance?'])
    assert 'provider=mock' in capsys.readouterr().out


def test_groq_diagnostic_uses_actual_extraction_and_reports_latency(monkeypatch, capsys):
    sdk_transport(monkeypatch, Intent(intent='transfer', amount='50').model_dump_json())
    assert diagnose.main('Could you send 50?', 'transfer', 'groq') == 0
    output = capsys.readouterr().out
    assert 'Live Groq diagnostic' in output and 'ELAPSED_SECONDS:' in output
    assert 'synthetic-groq-secret' not in output and 'reasoning' not in output


def test_groq_rate_limit_diagnostic_has_provider_specific_hint(monkeypatch, capsys):
    sdk_transport(monkeypatch, status=429)
    assert diagnose.main(provider='groq') == 1
    output = capsys.readouterr().out
    assert 'Groq free-tier' in output and 'AI Studio' not in output

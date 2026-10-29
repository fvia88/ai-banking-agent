"""Deployment gateway checks use no provider key, Docker or external database."""
import base64
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from infra.shared_app import FrontendFiles, SharedDemoGateway, SharedSettings


@pytest.fixture
def hosted(tmp_path):
    (tmp_path / 'index.html').write_text('<h1>bank.ly</h1>')
    api = FastAPI()
    @api.api_route('/api/v1/probe', methods=['GET', 'POST'])
    def probe(request: Request):
        return {'user': request.headers.get('x-demo-user-id'),
                'authorization': request.headers.get('authorization')}
    @api.get('/api/v1/error')
    def error():
        return JSONResponse({'detail': 'private server secret'}, status_code=500)
    api.mount('/', FrontendFiles(directory=tmp_path, html=True))
    settings = SharedSettings('bankly', 'long-synthetic-password', 'demo.onrender.com', tmp_path)
    now = [0.0]
    gateway = SharedDemoGateway(api, settings, clock=lambda: now[0])
    with TestClient(gateway, base_url='https://demo.onrender.com') as client:
        yield client, gateway, now


AUTH = ('bankly', 'long-synthetic-password')


@pytest.mark.parametrize('path', ['/', '/api/v1/probe', '/docs', '/openapi.json'])
def test_site_and_api_require_demo_access(hosted, path):
    client, _, _ = hosted
    response = client.get(path)
    assert response.status_code == 401
    assert 'Basic' in response.headers['www-authenticate']
    assert client.get(path, auth=('bankly', 'wrong')).status_code == 401


def test_health_is_public_but_contains_no_financial_or_secret_data(hosted):
    client, _, _ = hosted
    assert client.get('/healthz').json() == {'status': 'ok'}
    assert client.post('/healthz').status_code == 401


def test_authenticated_frontend_and_api_use_same_origin(hosted):
    client, _, _ = hosted
    assert 'bank.ly' in client.get('/', auth=AUTH).text
    response = client.get('/api/v1/probe', auth=AUTH, headers={'X-Demo-User-Id': 'other-user'})
    assert response.json() == {'user': 'usr_demo_01', 'authorization': None}
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['content-security-policy'] == "frame-ancestors 'none'"


@pytest.mark.parametrize('origin', ['https://evil.example', 'null', 'http://demo.onrender.com'])
def test_cross_origin_requests_are_refused(hosted, origin):
    client, _, _ = hosted
    assert client.post('/api/v1/probe', auth=AUTH, headers={'Origin': origin}).status_code == 403


def test_same_origin_post_is_allowed(hosted):
    client, _, _ = hosted
    assert client.post('/api/v1/probe', auth=AUTH,
        headers={'Origin': 'https://demo.onrender.com'}).status_code == 200


@pytest.mark.parametrize('path', ['/api/v1/missing', '/assets/missing.js', '/../../secret.txt'])
def test_missing_api_and_assets_never_return_spa_html(hosted, path):
    client, _, _ = hosted
    assert client.get(path, auth=AUTH).status_code == 404


def test_spa_navigation_and_server_errors(hosted):
    client, _, _ = hosted
    assert 'bank.ly' in client.get('/chat/example', auth=AUTH).text
    response = client.get('/api/v1/error', auth=AUTH)
    assert response.status_code == 500 and 'private server secret' not in response.text


def test_write_rate_limit_resets_without_limiting_reads(hosted):
    client, gateway, now = hosted
    gateway.limits = (120, 2)
    assert client.post('/api/v1/probe', auth=AUTH).status_code == 200
    assert client.post('/api/v1/probe', auth=AUTH).status_code == 200
    limited = client.post('/api/v1/probe', auth=AUTH)
    assert limited.status_code == 429 and limited.headers['retry-after'] == '60'
    assert client.get('/api/v1/probe', auth=AUTH).status_code == 200
    now[0] = 61
    assert client.post('/api/v1/probe', auth=AUTH).status_code == 200


def test_unauthenticated_requests_also_have_a_global_limit(hosted):
    client, gateway, _ = hosted
    gateway.limits = (2, 20)
    assert client.get('/').status_code == 401
    assert client.get('/').status_code == 401
    assert client.get('/').status_code == 429
    assert client.get('/healthz').status_code == 200


@pytest.mark.parametrize('header', ['Bearer token', 'Basic broken!',
    'Basic ' + base64.b64encode(b'no-colon').decode()])
def test_malformed_credentials_are_rejected(hosted, header):
    client, _, _ = hosted
    assert client.get('/', headers={'Authorization': header}).status_code == 401


def test_startup_refuses_missing_or_weak_password(monkeypatch):
    monkeypatch.delenv('BANKLY_DEMO_PASSWORD', raising=False)
    with pytest.raises(ValueError, match='at least 16'):
        SharedSettings.from_environment()


def test_valid_gateway_settings_require_a_built_frontend(monkeypatch, tmp_path):
    monkeypatch.setenv('BANKLY_DEMO_PASSWORD', 'long-synthetic-password')
    monkeypatch.setenv('RENDER_EXTERNAL_HOSTNAME', 'demo.onrender.com')
    monkeypatch.setenv('BANKLY_FRONTEND_DIR', str(tmp_path))
    with pytest.raises(ValueError, match='frontend'):
        SharedSettings.from_environment()
    (tmp_path / 'index.html').write_text('bank.ly')
    assert SharedSettings.from_environment().frontend_dir == Path(tmp_path)


@pytest.mark.parametrize('setting,value,hint', [
    ('GROQ_API_KEY', '', 'GROQ_API_KEY'),
    ('AGENT_PROVIDER', 'mock', 'AGENT_PROVIDER'),
    ('USE_MOCK_AGENT', 'true', 'real agent'),
    ('DATABASE_URL', 'sqlite:///demo.db', 'Neon PostgreSQL'),
    ('DATABASE_URL', 'postgresql://user:private-secret@host/db', 'sslmode'),
    ('PORT', '0', 'PORT'),
])
def test_hosted_startup_rejects_invalid_configuration_without_connecting(monkeypatch, tmp_path, setting, value, hint):
    from infra.start_shared import main
    (tmp_path / 'index.html').write_text('bank.ly')
    for name, configured in {
        'BANKLY_DEMO_PASSWORD': 'long-synthetic-password',
        'RENDER_EXTERNAL_HOSTNAME': 'demo.onrender.com',
        'BANKLY_FRONTEND_DIR': str(tmp_path),
        'GROQ_API_KEY': 'synthetic-key',
        'AGENT_PROVIDER': 'groq',
        'USE_MOCK_AGENT': 'false', 'USE_MOCK_SECURITY': 'false',
        'USE_MOCK_SUBSCRIPTIONS': 'false',
        'DATABASE_URL': 'postgresql://user:private-secret@host/db?sslmode=require',
        'PORT': '10000',
    }.items():
        monkeypatch.setenv(name, configured)
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError, match=hint) as caught:
        main()
    assert 'private-secret' not in str(caught.value)

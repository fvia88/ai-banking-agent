"""Opt-in shared-demo gateway; local Docker and banking business logic are unchanged."""
import base64
import binascii
import os
import secrets
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles


@dataclass(frozen=True)
class SharedSettings:
    username: str
    password: str
    hostname: str
    frontend_dir: Path

    @classmethod
    def from_environment(cls):
        username = os.getenv('BANKLY_DEMO_USERNAME', 'bankly')
        password = os.getenv('BANKLY_DEMO_PASSWORD', '')
        if not username or ':' in username or len(password) < 16:
            raise ValueError('Set a demo username and BANKLY_DEMO_PASSWORD of at least 16 characters')
        hostname = os.getenv('RENDER_EXTERNAL_HOSTNAME', '').lower()
        if not hostname or any(c in hostname for c in '/@ \r\n'):
            raise ValueError('RENDER_EXTERNAL_HOSTNAME must be the deployed hostname')
        frontend_dir = Path(os.getenv('BANKLY_FRONTEND_DIR', '/app/static'))
        if not (frontend_dir / 'index.html').is_file():
            raise ValueError('Built frontend is missing')
        return cls(username, password, hostname, frontend_dir)


class FrontendFiles(StaticFiles):
    """SPA fallback for browser routes, never for missing API routes or assets."""
    async def get_response(self, path, scope):
        normalized = path.replace('\\', '/').lstrip('/')
        if normalized == 'api' or normalized.startswith('api/'):
            raise HTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or Path(path).suffix:
                raise
            return await super().get_response('index.html', scope)


class SharedDemoGateway:
    """Shared password, fixed synthetic identity and process-wide quota protection.

    This is a private judging-demo gate, not individual banking authentication.
    Run one worker: in-memory limits are not distributed across replicas.
    """
    def __init__(self, app, settings, *, clock=time.monotonic, request_limit=120, write_limit=20):
        self.app, self.settings, self.clock = app, settings, clock
        self.limits = request_limit, write_limit
        self.requests, self.writes = deque(), deque()
        self.lock = Lock()

    def _authorized(self, headers):
        try:
            scheme, encoded = headers.get(b'authorization', b'').split(b' ', 1)
            if scheme.lower() != b'basic':
                return False
            user, password = base64.b64decode(encoded, validate=True).split(b':', 1)
        except (ValueError, binascii.Error):
            return False
        return (secrets.compare_digest(user, self.settings.username.encode())
                and secrets.compare_digest(password, self.settings.password.encode()))

    def _within_limit(self):
        with self.lock:
            now = self.clock()
            for entries in (self.requests, self.writes):
                while entries and entries[0] <= now - 60:
                    entries.popleft()
            if len(self.requests) >= self.limits[0]:
                return False
            self.requests.append(now)
            return True

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            await send({'type': 'websocket.close', 'code': 1008})
            return
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        path, method = scope['path'], scope['method']
        if path == '/healthz' and method in {'GET', 'HEAD'}:
            return await JSONResponse({'status': 'ok'})(scope, receive, send)
        write = method not in {'GET', 'HEAD', 'OPTIONS'}
        if not self._within_limit():
            return await JSONResponse({'detail': 'Demo busy; retry in a minute.'}, status_code=429,
                                      headers={'Retry-After': '60'})(scope, receive, send)
        if not self._authorized(headers):
            return await JSONResponse({'detail': 'Demo access required'}, status_code=401,
                headers={'WWW-Authenticate': 'Basic realm="bank.ly demo", charset="UTF-8"',
                         'Cache-Control': 'no-store'})(scope, receive, send)
        origin = headers.get(b'origin')
        if origin and origin.decode(errors='replace') != f'https://{self.settings.hostname}':
            return await JSONResponse({'detail': 'Cross-origin access denied'}, status_code=403)(scope, receive, send)
        if write:
            with self.lock:
                if len(self.writes) >= self.limits[1]:
                    return_response = True
                else:
                    self.writes.append(self.clock())
                    return_response = False
            if return_response:
                return await JSONResponse({'detail': 'Demo action limit reached; retry in a minute.'},
                    status_code=429, headers={'Retry-After': '60'})(scope, receive, send)
        # The hosted demo exposes only the synthetic demo user. Do not trust a
        # caller's identity selector, or pass the shared password into API code.
        scope = dict(scope, headers=[(k, v) for k, v in scope['headers']
            if k.lower() not in {b'x-demo-user-id', b'authorization'}]
            + [(b'x-demo-user-id', b'usr_demo_01')])
        replace_error = False
        async def protected_send(message):
            nonlocal replace_error
            if message['type'] == 'http.response.start':
                replace_error = message['status'] >= 500
                if replace_error:
                    return
                message = dict(message, headers=[(k, v) for k, v in message.get('headers', [])
                    if not k.lower().startswith(b'access-control-')]
                    + [(b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff'),
                       (b'referrer-policy', b'no-referrer'),
                       (b'content-security-policy', b"frame-ancestors 'none'")])
            elif message['type'] == 'http.response.body' and replace_error:
                if not message.get('more_body', False):
                    await JSONResponse({'detail': 'Demo service error; contact the team.'},
                                       status_code=500)(scope, receive, send)
                return
            await send(message)
        await self.app(scope, receive, protected_send)


def create_app():
    from app.main import app
    settings = SharedSettings.from_environment()
    app.mount('/', FrontendFiles(directory=settings.frontend_dir, html=True), name='shared-frontend')
    return SharedDemoGateway(app, settings)

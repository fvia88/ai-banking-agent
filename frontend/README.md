# Banking dashboard

React, TypeScript and Vite frontend for the Banking AI Agent. Banking operations,
policy checks, identity resolution, provider calls and secrets stay in the backend.

For the complete app, use the root [README](../README.md) and
[deployment guide](../docs/app/deployment.md).

## Local development

Use Node.js 24 and npm. From this directory:

```powershell
npm ci --legacy-peer-deps
npm run dev
```

Open http://localhost:5173. Start the backend separately on port 8000 using
`python backend/start.py --reload` from the repository root, after configuring
the database and provider environment as described in the deployment guide.

API calls use relative `/api/v1/...` URLs. The Vite development server proxies
`/api` to `http://127.0.0.1:8000`; no API key or frontend `.env` is required.
The browser uses the synthetic `usr_demo_01` profile.

## Checks

```powershell
npm test
npm run build
```

Tests use Node's test runner and Vite's module loader to check approval-card
states and API requests. The production build goes to ignored `dist/`.
`npm run lint` is also available as a separate lint check.

The `--legacy-peer-deps` installation flag matches the current Docker builder.
The checked-in `package-lock.json` must stay committed. Do not commit
`node_modules/`, `dist/`, API keys, or local environment files.

## Docker

From the repository root:

```powershell
docker compose up -d --build
```

The frontend build is served by Nginx at http://localhost:3000. Nginx proxies
`/api/` to the backend service. `npm run preview` alone does not provide this
production API proxy and is not the complete banking demo.

Approval metadata belongs in the response action's `approval` object, separate
from its canonical `arguments`. See the
[HTTP metadata contract](../docs/app/frontend_metadata_transport.md) before
changing confirmation, MFA, cancellation, or continuation requests.

# Free shared judging demo: Render + Neon + Groq

This optional deployment gives reviewers one HTTPS website. Your computer can be
off. The team configures one Groq key privately on Render; reviewers receive a
demo username/password, never the API key or database URL.

The setup uses Render's **Free** Docker web service and Neon's **Free** PostgreSQL
plan. Do not enable paid plans or automatic paid upgrades. Groq quotas still apply.
This is a synthetic, password-protected judging demo, not production banking.

## 1. Create the free Neon database

1. Sign in at https://console.neon.tech and create a project on the **Free** plan.
2. Give it a name such as `bankly-demo`. Choose a region near your Render region
   if available. The default database and role are sufficient.
3. Open **Connect**. Disable connection pooling for this simple one-worker demo
   and copy the direct PostgreSQL connection string. Preserve its TLS parameters,
   including `sslmode=require` and `channel_binding=require` when present.
4. Keep it private. You will paste it into Render's `DATABASE_URL` secret field.
   Do not put it in GitHub, screenshots, a public README or this chat.

Use a new database for the hosted demo. It is separate from local Docker data;
your previous local transfers/history will not automatically be copied.

### If the Neon CLI onboarding has already been completed

`neon init` links the local project and downloads `DATABASE_URL`,
`DATABASE_URL_UNPOOLED` and `NEON_BRANCH` into the private `.env.local` file.
`neon deploy --yes` applies the PostgreSQL-only policy from `neon.ts` and refreshes
that file. Preview with `neon config plan` first; no additional services are
required. The root Node dependencies support Neon configuration tooling, not the
Python backend runtime. `npm run build` at the root delegates to the frontend.

Local Python startup (`python backend/start.py`) loads `.env.local` without
overriding values already set in the terminal. The shared startup entry point
does the same. Standard PostgreSQL URLs are normalized to the installed
`psycopg2` driver, preserving credentials and TLS options. Docker excludes local
environment files; Render still needs its own private dashboard configuration.

Neither `.env.local` nor `.neon` should be committed. Do not paste the generated
file into issues or chat. Neon setup does not deploy the Python app or frontend;
continue with Render below to obtain the website URL.

## 2. Publish the deployment files to your repository

Review and commit this deployment change on your feature branch, then push it.
Render must use a branch containing `render.yaml`, `infra/Dockerfile.shared`,
`infra/shared_app.py` and `infra/start_shared.py`. Pulling an older `main` cannot
deploy changes that only exist locally. Follow the team's normal PR workflow.

Local `docker compose up` continues using the original separate containers. This
cloud image is a separate entry point; no frontend API URL changes are required.

## 3. Create the free Render service

1. Sign in at https://dashboard.render.com and connect the GitHub repository.
2. Choose **New > Blueprint**, select the repository and the branch containing
   this deployment change, and use the root `render.yaml`.
3. Confirm the service has the **Free** plan before creating it. The blueprint
   creates one web service only; it does not create a paid Render database.
4. When prompted for secrets, enter:

| Variable | Private value |
| --- | --- |
| `DATABASE_URL` | The direct Neon PostgreSQL connection string. |
| `GROQ_API_KEY` | Your team's Groq API key. |

The blueprint sets `AGENT_PROVIDER=groq`, `GROQ_MODEL=openai/gpt-oss-20b` and the
real agent/security/subscription flags. It generates `BANKLY_DEMO_PASSWORD` and
sets the demo username to `bankly`. Render supplies `PORT` and
`RENDER_EXTERNAL_HOSTNAME` automatically.

5. Start deployment. The build compiles the frontend and installs Python
   dependencies. Startup validates configuration, migrates Neon and seeds an
   empty database before serving traffic. Existing data is preserved on restart.
6. Once Render shows **Live**, open its `https://...onrender.com` address.
7. The browser asks for a username and password. Enter `bankly` and the generated
   `BANKLY_DEMO_PASSWORD`, available in the service's Environment settings.

For submission, list the demo URL and username (`bankly`) in the deployment instructions. Provide the actual demo password privately through the submission portal or judging channel; do not commit it or include it in the technical PDF. API keys and database connection strings remain private hosting secrets.

Do not enter your Groq key in the browser's demo-password prompt. Share the demo
password privately with judges/team members. Render terminates HTTPS; backend
and database credentials stay server-side. The generated password can be changed
in Environment settings followed by a redeploy.

## 4. Verify before sharing

- Visit `/healthz` without credentials: only `{"status":"ok"}` should appear.
- Open the website privately: it must require the demo password before showing
  chat, account data, API documentation or messages.
- Ask `what is my balance`: expect a grounded database balance.
- Ask `my spending in October`, then `2026`: expect year clarification followed
  by the selected monthly report.
- Enter `transfer to Marvel`, `20`, then `then to Bob instead`: expect only a
  CNY 20 Bob proposal, with no execution before approval.
- Make a small approved synthetic transfer and refresh: check the changed
  balance and history remain. Restart the service and verify persistence again.
- Test required MFA through the simulated demo inbox. This is not real SMS MFA.

The gate pins API requests to `usr_demo_01`, ignores caller-supplied demo-user
headers and rejects cross-origin browser requests. All authorized visitors share
the same synthetic account, conversations, transfer counters and safety locks.
Coordinate testing; this is not separate private customer access.

## 5. Limits, troubleshooting and shutdown

- Render's free service sleeps after 15 idle minutes; the next visit wakes it.
  Open and test it before a scheduled demonstration. No availability or latency
  guarantee is claimed. Avoid relying on a last-minute wake-up during judging.
- Do not store SQLite data on the free web-service filesystem: it is ephemeral.
  Neon holds the persistent database; do not use Render's expiring free database.
- Free plans have compute, storage, bandwidth and API quotas. If exhausted, the
  demo may stop serving or interpreting requests until limits reset. Monitor
  usage in the three dashboards; do not assume unlimited free operation.
- The gate allows 120 non-health requests and 20 writes per rolling minute
  across the single process. HTTP 429 means wait at least a minute; ordinary
  reads and writes still have provider/platform limits beyond this local gate.
- Missing key: check Render Environment, not your local terminal. Local saved
  keys are not automatically copied to the hosting provider.
- Database startup error: check the direct URL and TLS parameters privately.
  Never paste full database errors or credentials into public issues.
- 401: use the shared demo username/password. They are not the Groq credentials.
- A safety lock may affect every visitor because the demo identity is shared.
  Do not deliberately trigger it during judging without an agreed recovery plan.
- This is a single-worker deployment. In-memory request limits are not a
  distributed rate limiter; do not scale replicas without additional controls.
- After judging, disable/delete the Render service, revoke the dedicated Groq
  key if appropriate, and delete the Neon project only if its data is no longer
  needed. Deleting the database is destructive; take a backup first if required.

The gateway does not implement personal accounts, independent MFA, production
secret rotation or production financial integrations. Keep synthetic data only.

## Local verification evidence and references

Offline gateway checks: `python -m pytest -p no:cacheprovider infra/test_shared_app.py -q`.
They cover access control, identity pinning, same-origin checks, error redaction,
SPA fallback and request limits. They do not prove a successful hosted deployment.
Live Render/Neon/Groq verification remains required before submitting the URL.

Neon verification on 30 October 2026: the existing production branch was linked,
`neon config plan` reported PostgreSQL only with no pending changes, and
`neon deploy --yes` completed and refreshed the ignored environment file. The
first apply attempt without `--yes` returned an unspecified CLI error; the retry
succeeded. `npm run build` passed from the repository root. A real TLS database
connection, temporary write/read with rollback, migrations and non-destructive
seed all passed. A locally started HTTP service served the private frontend,
read accounts, resolved spending date clarification and saved/retrieved chat
history through the actual Neon database. One synthetic verification chat was
retained; no transfers or cancellations executed. Interpretation used the offline
mock for this database check, not live Groq. Public Render hosting and its live
Groq configuration still require verification.

- Render free-service limits: https://render.com/docs/free
- Render Blueprint configuration: https://render.com/docs/blueprint-spec
- Render environment variables: https://render.com/docs/environment-variables
- Neon connection setup: https://neon.com/docs/get-started-with-neon/connect-neon

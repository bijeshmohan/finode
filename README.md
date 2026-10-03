# finode

Personal finance API and web app built with FastAPI and SQLModel. Finode uses
a double-entry ledger: every category-like concept is an account, and every
posting is recorded as a balanced journal entry.

## Setup

Requires Python 3.14+.

```bash
uv sync                           # install dependencies
uv run alembic upgrade head       # create / migrate the database
uv run fastapi dev                # start the dev server
```

The server runs at http://localhost:8000 with auto-reload. OpenAPI docs at `/docs`.

## Web UI

A server-rendered UI (Jinja2 templates + [htmx](https://htmx.org), no JavaScript
build step) is served by the same app at http://localhost:8000/app/. Users sign
in with email and password against Supabase Auth, so set `FINODE_SUPABASE_URL`
and `FINODE_SUPABASE_ANON_KEY` first (see Configuration). Pages:

- **Dashboard** — net worth, this month's income and expenses, recent transactions
- **Accounts** — account tree with balances; create, edit, move and delete
- **Account register** — an account's activity with a running balance
- **Transactions** — filter by account and date, paginate, edit, delete
- **New transaction** — *simple* mode (amount, from, to) or *split* mode
  (any number of debit/credit rows with a live balance check)

### Invite-only sign-up

Registration is closed by default: `/app/signup` returns 404 and the login
page shows no link. To let invited people create accounts:

1. In Supabase, open Authentication → Sign In / Providers and turn **off**
   "Allow new users to sign up". Without this, anyone holding your public anon
   key could register directly against Supabase and then log into finode.
   Users created by finode go through the admin API, which this switch does
   not block.
2. Add to `.env`:
   - `FINODE_SIGNUP_CODE` — an invite code of at least 16 characters, e.g.
     `openssl rand -base64 24`
   - `FINODE_SUPABASE_SERVICE_ROLE_KEY` — the `service_role` (or `sb_secret_…`)
     key from Project Settings → API Keys. It is a server-side secret: it is
     only sent to Supabase's admin endpoint, never to browsers, and it must
     never be committed.
3. Restart (`docker compose up -d --build`) and share the code with the people
   you invite. They enter it on `/app/signup` along with an email and password
   (min. 8 characters); accounts are created pre-confirmed (no email
   verification) and the user is signed in immediately.

To close sign-up again, remove `FINODE_SIGNUP_CODE` and restart. There is no
per-IP limit on code guesses, which is why the code must be long and random.
Email verification and password reset are not implemented yet.

The browser keeps the Supabase tokens in `HttpOnly`, `SameSite=Lax` cookies
scoped to `/app`, and the UI calls the same services as the JSON API. The JSON
API itself only accepts `Authorization: Bearer` tokens. Behind HTTPS, set
`FINODE_COOKIE_SECURE=true`. htmx is vendored in `app/static/`, so no CDN is
needed.

## Docker deployment

`compose.yaml` runs finode behind an existing [Traefik](https://traefik.io)
reverse proxy, using Supabase Postgres as the database.

1. Copy `.env.example` to `.env` and fill it in:
   - `FINODE_DATABASE_URL` — the Supabase **session pooler** connection string
     with the psycopg driver, e.g.
     `postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`.
     Avoid the transaction pooler (port 6543), which does not support the
     prepared statements psycopg uses, and the direct `db.<ref>.supabase.co`
     host, which is IPv6-only and unreachable from Docker's default networks.
   - `FINODE_SUPABASE_URL`, `FINODE_SUPABASE_ANON_KEY`
   - `APP_DOMAIN` — the public host name Traefik should route to the app
   - optionally `TRAEFIK_NETWORK` (default `proxy`), `TRAEFIK_ENTRYPOINT`
     (`websecure`), `TRAEFIK_CERTRESOLVER` (`le`) and `WEB_CONCURRENCY` (`2`)
2. Build, migrate and start:

   ```bash
   docker compose up -d --build
   ```

   The one-off `migrate` service runs `alembic upgrade head`; the `app`
   service starts only after it succeeds. The app publishes no ports — it is
   reachable only through Traefik on the external proxy network, with secure
   cookies enabled.

Day-to-day:

```bash
docker compose logs -f app            # follow application logs
docker compose run --rm migrate       # run migrations on their own
git pull && docker compose up -d --build   # deploy a new version
```

The image (see `Dockerfile`) installs dependencies from `uv.lock`, runs as an
unprivileged user and has a health check on `/`. `.dockerignore` keeps `.env`,
local databases and tests out of it.

## Tests

```bash
uv run pytest
```

## Project layout

```
app/
├── main.py            FastAPI app + router registration
├── config.py          pydantic-settings (env-driven)
├── dependencies.py    engine, session, repositories and services
├── auth.py            Supabase JWT verification
├── web_auth.py        email/password sign-in and cookie sessions for the UI
├── models/            SQLModel ORM tables
├── schemas/           Pydantic request/response shapes
├── repositories/      tenant-scoped persistence over a Session
├── services/          ledger rules, balances, reports
├── routers/           FastAPI APIRouters (JSON API)
│   └── web/           HTML routers served under /app
├── templates/         Jinja2 templates (partials/ holds htmx fragments)
└── static/            stylesheet, small script, vendored htmx

migrations/            Alembic migrations
tests/                 pytest suite
```

## Configuration

Environment variables (or a `.env` file at the project root) override defaults:

- `FINODE_DATABASE_URL` — default `sqlite:///./finode.db`
- `FINODE_DATABASE_ECHO` — default `true`
- `FINODE_SUPABASE_URL` — Supabase project URL, used to fetch JWKS for protected API routes
- `FINODE_SUPABASE_AUDIENCE` — expected JWT audience, default `authenticated`
- `FINODE_SUPABASE_ANON_KEY` — Supabase anon (public) key, used by the web UI to sign users in
- `FINODE_SIGNUP_CODE`, `FINODE_SUPABASE_SERVICE_ROLE_KEY` — enable invite-only sign-up (see above); both are optional
- `FINODE_COOKIE_SECURE` — set `true` when serving over HTTPS so session cookies are `Secure`, default `false` (compose sets it to `true`)

Keys without the `FINODE_` prefix (such as the compose settings above) are
ignored by the app, so one `.env` serves both.

## Schema changes

```bash
uv run alembic revision --autogenerate -m "describe the change"
# review the generated file under migrations/versions/
uv run alembic upgrade head
```

## Accounting model

- Accounts form a tree. Each user gets five system root accounts (`Assets`,
  `Liabilities`, `Equity`, `Income`, `Expenses`), created lazily on first
  access. Every other account must have a parent, and its type is that of its
  root ancestor. Roots cannot be renamed, moved, or deleted. `GET /accounts/`
  accepts `?type=<root name>` to filter by root.
- Account balances are derived from postings. They are not stored as an
  authoritative mutable column.
- Accounts that already have postings cannot gain sub-accounts.
- Transactions live at `/transactions/` and must contain at least two
  postings with total debits equal to total credits. The list is ordered
  newest first and supports `account` (including sub-accounts), `date_from`,
  `date_to`, `limit` and `offset`.
- Opening and direct balance adjustments are posted against a system equity
  account named `Opening Balances`, which cannot be renamed, moved, deleted,
  given sub-accounts or have its balance set directly.

## Other API endpoints

- `GET /accounts/{aid}/register` — an account's transactions oldest first with a signed change and running balance
- `GET /reports/summary` — assets, liabilities, net worth, and income/expenses for `date_from`..`date_to` (default: current month)

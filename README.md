# finode

Personal finance API and web app built with FastAPI and SQLModel. Finode uses
a double-entry ledger: every category-like concept is an account, and every
posting is recorded as a balanced journal entry.

## Documentation

The full documentation is in [`docs/`](docs/index.md): a [user guide](docs/guide/getting-started.md),
the [architecture](docs/architecture/overview.md) with diagrams, and
[developer docs](docs/developer/code-map.md) (code map, conventions, the reasons behind the design).
This README keeps the setup, deployment and configuration notes.

## Setup

Requires Python 3.14+.

```bash
uv sync                           # install dependencies
uv run alembic upgrade head       # create / migrate the database
uv run fastapi dev                # start the dev server
```

The server runs at http://localhost:8000 with auto-reload. OpenAPI docs at `/docs` once you set `FINODE_API_DOCS=true` (off by default, because they are public).

## Web UI

A server-rendered UI (Jinja2 templates + [htmx](https://htmx.org), no JavaScript
build step) is served by the same app at http://localhost:8000/. Users sign
in with email and password against Supabase Auth, so set `FINODE_SUPABASE_URL`
and `FINODE_SUPABASE_ANON_KEY` first (see Configuration). Pages:

- **Dashboard** — net worth, this month's income and spending, recent
  transactions, and a "Get started" checklist for new users
- **Accounts** — accounts grouped by type with balances; each opens an
  **account page** with its activity, running balance and actions
- **Transactions** — grouped by day, filterable by account and date; tap one
  to edit or delete it
- **New transaction** — *simple* mode (amount, from, to) or *split* mode
  (any number of debit/credit rows with a live balance check). Missing an
  account? Pick **+ New account…** in any account list to add it, with an
  optional opening balance, without leaving the form.

The layout adapts to the screen: phones get a bottom tab bar and a floating
"+" button for new transactions, wider screens a top navigation bar. Light
and dark themes follow the system setting.

### Invite-only sign-up

Registration is closed by default: `/signup` returns 404 and the login
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
   you invite. They enter it on `/signup` along with an email and password
   (min. 8 characters); accounts are created pre-confirmed (no email
   verification) and the user is signed in immediately.

`FINODE_MAX_USERS` (default 10, you included; 0 = no limit) closes sign-up once that many people have an account.

With the service key set, people can also delete their own account (Profile › Your data › Delete my account): their data is erased and their Supabase login removed. Without it only "Erase my books" is offered.

Sign-in and sign-up attempts are rate limited per address (see `.env.example`), and each person has limits on accounts and transactions so nobody can fill the database.

To close sign-up again, remove `FINODE_SIGNUP_CODE` and restart. There is no
per-IP limit on code guesses, which is why the code must be long and random.
Email verification and password reset are not implemented yet.

The browser keeps the Supabase tokens in `HttpOnly`, `SameSite=Lax` cookies
sent to the whole site, and the UI calls the same services as the JSON API. The JSON
API (all under `/api`) only accepts `Authorization: Bearer` tokens. Behind HTTPS, set
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

### Forgot password

Off until you set `FINODE_PASSWORD_RESET=true`, because Supabase must be able to send email first:

1. Supabase › Authentication › Emails › SMTP Settings: enable custom SMTP with your mail provider's host, port, user and password, and a sender address on your own domain (for Zoho Mail: `smtp.zoho.com` or `smtp.zoho.in` to match your data centre, port 465, the mailbox's full address, an app password).
2. Authentication › Emails › Templates › **Reset Password**: make the link `<a href="{{ .SiteURL }}/reset?token_hash={{ .TokenHash }}">Choose a new password</a>`. The Site URL (Authentication › URL Configuration) must be the public address of this app.
3. Set `FINODE_PASSWORD_RESET=true` and restart. The sign-in page then shows "Forgot your password?".

The link only opens a form; the token is spent when the new password is submitted, so mail scanners that open links cannot use it up. `/forgot` always answers the same whether or not the address has an account, and is rate limited (`FINODE_RESET_ATTEMPTS`).

### Backups

The `backup` service dumps the database (the `public` schema: everyone's books,
settings and tokens) at 02:00 UTC every night into `./backups` as
`finode-<time>.sql.gz` and keeps 14 days. Each file is checked before it is
kept; a failed run is logged (`docker compose logs backup`) and leaves the
older files alone. Set `BACKUP_UID`/`BACKUP_GID` to your own (`id -u`, `id -g`)
so you own the files. Logins live in Supabase Auth and are not in the dump.

A dump on the same machine does not survive losing the machine: copy
`./backups` somewhere else (for example `rclone sync backups remote:finode`
from cron).

To restore into an empty Postgres (rehearsed against production data; the
restored row counts matched). On Supabase the `auth` schema already exists:

```bash
psql "$URL" -c 'drop schema public cascade'          # fresh database only
gzip -dc backups/finode-<time>.sql.gz | psql "$URL" -v ON_ERROR_STOP=1
```

A plain Postgres has no `auth.users`, so create a stand-in table with the
users' ids first or the foreign keys fail.

## Tests and code quality

```bash
uv run pytest                  # unit and web tests (about 1,000, a few minutes)
scripts/browser-tests.sh       # the browser tests in Docker (FINODE_BROWSER=webkit for Safari's engine)
uv run ruff check app tests migrations scripts && uv run ruff format --check app tests migrations scripts
uv run mypy                    # type checks app/
make check                     # lint + types + tests; `make help` lists every target
make hooks                     # install the pre-commit hook (ruff, mypy, file hygiene)
```

CI (`.github/workflows/ci.yml`) runs lint, types, the tests with coverage, the browser tests and the Docker build on every push and pull request. See [docs/developer/conventions.md](docs/developer/conventions.md) for the rules and tool settings.

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
│   └── web/           HTML routers served at the site root
├── templates/         Jinja2 templates (partials/ holds htmx fragments)
└── static/            stylesheet, small script, vendored htmx

migrations/            Alembic migrations
tests/                 pytest suite
```

## Configuration

Environment variables (or a `.env` file at the project root) override defaults:

- `FINODE_DATABASE_URL` — default `sqlite:///./finode.db`
- `FINODE_DATABASE_ECHO` — default `true`
- `FINODE_TIMEZONE` — the time zone "today" is read in, e.g. `Asia/Kolkata`; the server's own clock when empty
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
  root ancestor. Roots cannot be renamed, moved, or deleted. `GET /api/accounts/`
  accepts `?type=<root name>` to filter by root.
- Account balances are derived from postings. They are not stored as an
  authoritative mutable column.
- Everything is kept in one currency per person (INR until changed in Settings; changing it relabels, it converts nothing). There are no assets of one's own, prices or conversions.
- Accounts that already have postings cannot gain sub-accounts.
- Transactions live at `/transactions/` and must contain at least two
  postings with total debits equal to total credits. The list is ordered
  newest first and supports `account` (including sub-accounts), `date_from`,
  `date_to`, `limit` and `offset`.
- Opening and direct balance adjustments are posted against a system equity
  account named `Opening Balances`, which cannot be renamed, moved, deleted,
  given sub-accounts or have its balance set directly.

## Other API endpoints

- `GET /api/budget/?month=YYYY-MM` — ready to assign and each expense category's assigned, spent and available; `PUT /api/budget/categories/{aid}` sets a category's amount for a month
- `POST /api/budget/move`, `POST /api/budget/copy`, `PUT /api/budget/groups/{aid}`, `POST /api/budget/accounts/{aid}/include`, and goals under `/api/budget/goals` (create, change, delete, set aside, use)
- `GET /api/reports/trial-balance` — every account's debits and credits up to `as_of` (default today) and a list of problems; `balanced` is false when a transaction does not balance

Reopening accounts, an account's register, restoring deleted accounts and entries, history, related entries, pausing and resuming recurring rules, moving and copying budget money, goals and the reports are in the API too. The full list of routes, and what is left out on purpose, is in [docs/developer/api.md](docs/developer/api.md).

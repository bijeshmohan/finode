# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Apply migrations: `uv run alembic upgrade head` (run before first boot and after pulling schema changes)
- Run dev server: `uv run fastapi dev` (auto-reload, http://localhost:8000)
- Run prod-ish: `uv run fastapi run`
- Run tests: `uv run pytest`
- Generate a migration: `uv run alembic revision --autogenerate -m "description"` (always review before applying)
- Add a dependency: `uv add <pkg>` (do not edit `pyproject.toml` by hand)
- Deploy with Docker: `docker compose up -d --build` (runs migrations via the one-off `migrate` service, then the app behind Traefik; needs `.env` with `APP_DOMAIN`)
- Build the image only: `docker build -t finode .`

Python 3.14+ is required (see `pyproject.toml`). No linter or formatter is configured — do not invent commands for these.

## Architecture

All application code lives under `app/`. The core domain is a double-entry
ledger with accounts and journal entries:

- `app/models/` — SQLModel ORM tables (`table=True`). Source of truth for the schema is the model + Alembic migrations together.
- `app/schemas/` — Pydantic request/response models. Each entity exposes `*Base`, `*Create`, `*Read`, `*Update`.
- `app/repositories/` — tenant-scoped persistence classes over a `Session`.
- `app/services/` — business logic and cross-entity orchestration. Journal
  balancing and account balance derivation live here.
- `app/routers/` — FastAPI `APIRouter`s. Convert `None` from repositories/services into `HTTPException(404)`. Routers never touch the DB directly — always go through a repository or service.
- `app/routers/web/` — the HTML UI under `/app`, rendered with Jinja2 (`app/templates/`) and enhanced with vendored htmx (`app/static/`). It calls the same services as the JSON API and must not duplicate ledger rules; view-model helpers (account tree, posting pickers) live in the web routers.

`app/main.py` wires the routers. Schema is managed by Alembic — `app/main.py` does *not* run `SQLModel.metadata.create_all` at startup. Run `uv run alembic upgrade head` to bring the DB to the latest schema. The dev DB is `finode.db` (SQLite, gitignored).

`app/config.py` exposes a `settings` instance (pydantic-settings) reading `FINODE_*` env vars and an optional `.env` file (other keys are ignored because `.env` is shared with docker compose). Current settings: `database_url`, `database_echo`, `supabase_url`, `supabase_audience`, `supabase_anon_key`, `cookie_secure`. Add new configuration here rather than hardcoding constants.

`app/dependencies.py` builds the engine from `settings` and exposes `DBSession = Annotated[Session, Depends(get_db_session)]`. Route handlers should type the session parameter as `DBSession` directly rather than re-declaring `Depends(...)`.

All imports within `app/` use relative imports (e.g. `from ..models.account import Account`). The FastAPI CLI entrypoint is configured in `pyproject.toml` under `[tool.fastapi]` as `entrypoint = "app.main:app"`.

### Web UI

There is no JavaScript build step; do not add one. Templates extend `base.html`; `partials/` holds fragments returned to htmx. Mutating forms use `hx-post` (htmx 2 sends `DELETE` parameters in the URL, so use `POST` routes such as `/{id}/delete`). Handlers answer success with `HX-Redirect` / `HX-Refresh` and failures with a 4xx plus `HX-Retarget` pointing at an error element, via `routers/web/utils.py`; `static/app.js` lets htmx swap those 4xx responses.

`app/web_auth.py` signs users in through Supabase's password grant and keeps the tokens in `HttpOnly` cookies. `web_login_required` verifies the cookie (refreshing it when expired) and stores the token in `request.state`, which `require_authenticated_user` accepts in addition to a bearer header, so repositories stay tenant-scoped. The JSON API never reads cookies. In tests, `tests/conftest.py` overrides both dependencies; use a client without the `web_login_required` override (see `tests/test_web_auth.py`) to test real authentication.

### Docker

`Dockerfile` is multi-stage: uv resolves `uv.lock` into `/opt/venv`, and the runtime stage copies only that venv plus `app/`, `migrations/`, `alembic.ini` and `pyproject.toml` (needed for the `[tool.fastapi]` entrypoint). If a new top-level file is needed at runtime, add it to the `COPY` lines and check `.dockerignore`. `compose.yaml` targets an existing Traefik on an external network; production uses Supabase Postgres, so there is no database service. Uvicorn reads `WEB_CONCURRENCY` and `FORWARDED_ALLOW_IPS` from the environment.

Tests live in `tests/`. `tests/conftest.py` builds a fresh in-memory SQLite engine per test and overrides `get_db_session`, so tests are independent of `finode.db` and of Alembic.

### Double-entry ledger

`app/models/account.py` defines accounts as a tree. Each user has five system
root accounts (`Assets`, `Liabilities`, `Equity`, `Income`, `Expenses`),
created lazily on first access by `AccountService._ensure_roots` (a partial
unique index on `(user, name)` where `parent_id IS NULL` keeps this race-safe).
There is no stored type: an account's type is its root ancestor, and all
non-root accounts require a `parent_id`. Roots cannot be renamed, moved, or
deleted. Categories are not a separate table; former category concepts are
represented as income or expense accounts.

`app/models/transaction.py` defines `Transaction` and `Posting`. A transaction
contains at least two postings, every posting has a positive amount, and total
debits must equal total credits. The service layer validates those invariants
and verifies that all referenced accounts belong to the authenticated user.
Postings may not target root accounts or accounts that have sub-accounts, and
an account cannot be moved under a different root (that would silently
reclassify its history).

Account balances are derived from postings. Assets and Expenses increase
with debits; Liabilities, Equity, and Income increase with credits. Accounts
that already have postings cannot gain sub-accounts. Opening balances and
direct balance edits are posted against the system equity account named
`Opening Balances`, which cannot be renamed, moved, deleted, given
sub-accounts or have its balance set directly.

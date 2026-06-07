# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Apply migrations: `uv run alembic upgrade head` (run before first boot and after pulling schema changes)
- Run dev server: `uv run fastapi dev` (auto-reload, http://localhost:8000)
- Run prod-ish: `uv run fastapi run`
- Run tests: `uv run pytest`
- Generate a migration: `uv run alembic revision --autogenerate -m "description"` (always review before applying)
- Add a dependency: `uv add <pkg>` (do not edit `pyproject.toml` by hand)

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

`app/main.py` wires the routers. Schema is managed by Alembic — `app/main.py` does *not* run `SQLModel.metadata.create_all` at startup. Run `uv run alembic upgrade head` to bring the DB to the latest schema. The dev DB is `finode.db` (SQLite, gitignored).

`app/config.py` exposes a `settings` instance (pydantic-settings) reading `FINODE_*` env vars and an optional `.env` file. Current settings: `database_url`, `database_echo`. Add new configuration here rather than hardcoding constants.

`app/dependencies.py` builds the engine from `settings` and exposes `DBSession = Annotated[Session, Depends(get_db_session)]`. Route handlers should type the session parameter as `DBSession` directly rather than re-declaring `Depends(...)`.

All imports within `app/` use relative imports (e.g. `from ..models.account import Account`). The FastAPI CLI entrypoint is configured in `pyproject.toml` under `[tool.fastapi]` as `entrypoint = "app.main:app"`.

Tests live in `tests/`. `tests/conftest.py` builds a fresh in-memory SQLite engine per test and overrides `get_db_session`, so tests are independent of `finode.db` and of Alembic.

### Double-entry ledger

`app/models/account.py` defines accounts with one of five types: `Assets`,
`Liabilities`, `Equity`, `Income`, or `Expenses`. Categories are not a separate
table; former category concepts are represented as income or expense accounts.

`app/models/transaction.py` defines `Transaction` and `Posting`. A transaction
contains at least two postings, every posting has a positive amount, and total
debits must equal total credits. The service layer validates those invariants
and verifies that all referenced accounts belong to the authenticated user.

Account balances are derived from postings. Assets and Expenses increase
with debits; Liabilities, Equity, and Income increase with credits. Opening
balances and direct balance edits are posted against the system equity account
named `Opening Balances`.

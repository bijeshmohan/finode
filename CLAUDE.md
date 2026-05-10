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

All application code lives under `app/`. Five parallel packages, one file per domain entity (`account`, `category`, `transaction`):

- `app/models/` — SQLModel ORM tables (`table=True`). Source of truth for the schema is the model + Alembic migrations together.
- `app/schemas/` — Pydantic request/response models. Each entity exposes `*Base`, `*Create`, `*Read`, `*Update`.
- `app/repositories/` — plain functions (`create`, `read`, `read_all`, `update`, `delete`) that take a `Session` and return ORM instances or `None`. No classes, no DI inside.
- `app/services/` — business logic and cross-entity orchestration (e.g. operations spanning multiple repositories or invariants beyond a single entity). Currently empty; add a file per use case as logic emerges. Routers should call services for anything beyond pure CRUD.
- `app/routers/` — FastAPI `APIRouter`s. Convert `None` from repositories/services into `HTTPException(404)`. Routers never touch the DB directly — always go through a repository or service.

`app/main.py` wires the routers. Schema is managed by Alembic — `app/main.py` does *not* run `SQLModel.metadata.create_all` at startup. Run `uv run alembic upgrade head` to bring the DB to the latest schema. The dev DB is `finode.db` (SQLite, gitignored).

`app/config.py` exposes a `settings` instance (pydantic-settings) reading `FINODE_*` env vars and an optional `.env` file. Current settings: `database_url`, `database_echo`. Add new configuration here rather than hardcoding constants.

`app/dependencies.py` builds the engine from `settings` and exposes `DBSession = Annotated[Session, Depends(get_db_session)]`. Route handlers should type the session parameter as `DBSession` directly rather than re-declaring `Depends(...)`.

All imports within `app/` use relative imports (e.g. `from ..models.account import Account`). The FastAPI CLI entrypoint is configured in `pyproject.toml` under `[tool.fastapi]` as `entrypoint = "app.main:app"`.

Tests live in `tests/`. `tests/conftest.py` builds a fresh in-memory SQLite engine per test and overrides `get_db_session`, so tests are independent of `finode.db` and of Alembic.

### Transactions are polymorphic over one table

`app/models/transaction.py` is a single table with nullable `source` and `destination` (both FK to `accounts.aid`). The transaction *type* is implicit:

- Expense → `source` set, `destination` null
- Income → `source` null, `destination` set
- Transfer → both set

`app/schemas/transaction.py` defines three schema families (`Expense*`, `Income*`, `Transfer*`) inheriting from `TransactionBase`. Routes accept and return the union (`ExpenseCreate | IncomeCreate | TransferCreate`, etc.); FastAPI discriminates by which fields are present. The `GET /transactions/?type=...` endpoint filters in Python by inspecting `source`/`destination` nullability — there is no `type` column on the model.

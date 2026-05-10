# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Run dev server: `uv run fastapi dev` (auto-reload, http://localhost:8000)
- Run prod-ish: `uv run fastapi run`
- Add a dependency: `uv add <pkg>` (do not edit `pyproject.toml` by hand)

Python 3.14+ is required (see `pyproject.toml`). There is no test suite, linter, or formatter configured — do not invent commands for these.

## Architecture

All application code lives under `app/`. Four parallel packages, one file per domain entity (`account`, `category`, `transaction`):

- `app/models/` — SQLModel ORM tables (`table=True`). Source of truth for the DB schema.
- `app/schemas/` — Pydantic request/response models. Each entity exposes `*Base`, `*Create`, `*Read`, `*Update`.
- `app/repositories/` — plain functions (`create`, `read`, `read_all`, `update`, `delete`) that take a `Session` and return ORM instances or `None`. No classes, no DI inside.
- `app/routers/` — FastAPI `APIRouter`s. Convert `None` from repositories into `HTTPException(404)`. Routers never touch the DB directly — always go through a repository.

`app/main.py` wires the routers and creates tables in the `lifespan` startup hook via `SQLModel.metadata.create_all`. There is no migration tool (Alembic etc.) — schema changes take effect on next boot against a fresh DB. The dev DB is `finode.db` (SQLite, gitignored).

`app/dependencies.py` exposes the engine and `DBSession = Annotated[Session, Depends(get_db_session)]`. Route handlers should type the session parameter as `DBSession` directly rather than re-declaring `Depends(...)`.

All imports within `app/` use relative imports (e.g. `from ..models.account import Account`). The FastAPI CLI entrypoint is configured in `pyproject.toml` under `[tool.fastapi]` as `entrypoint = "app.main:app"`.

### Transactions are polymorphic over one table

`models/transaction.py` is a single table with nullable `from_account` and `to_account`. The transaction *type* is implicit:

- Expense → `from_account` set, `to_account` null
- Income → `from_account` null, `to_account` set
- Transfer → both set

`schemas/transaction.py` defines three schema families (`Expense*`, `Income*`, `Transfer*`) inheriting from `TransactionBase`. Routes accept and return the union (`ExpenseCreate | IncomeCreate | TransferCreate`, etc.); FastAPI discriminates by which fields are present. The `GET /transactions/?type=...` endpoint filters in Python by inspecting `from_account`/`to_account` nullability — there is no `type` column on the model.

### Field aliasing for `from` / `to`

Transaction schemas (and the model) alias `from_account` → `"from"` and `to_account` → `"to"` because `from` is a Python reserved word. `TransactionBase` sets `model_config = ConfigDict(populate_by_name=True)` so both the alias (used in JSON payloads) and the field name (used in Python construction, e.g. `Transaction(**data.model_dump())` in repositories) work as input. Preserve this when adding fields with reserved-word aliases.

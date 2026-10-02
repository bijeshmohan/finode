# finode

Personal finance API built with FastAPI and SQLModel. Finode uses a
double-entry ledger: every category-like concept is an account, and every
posting is recorded as a balanced journal entry.

## Setup

Requires Python 3.14+.

```bash
uv sync                           # install dependencies
uv run alembic upgrade head       # create / migrate the database
uv run fastapi dev                # start the dev server
```

The server runs at http://localhost:8000 with auto-reload. OpenAPI docs at `/docs`.

## Tests

```bash
uv run pytest
```

## Project layout

```
app/
├── main.py            FastAPI app + router registration
├── config.py          pydantic-settings (env-driven)
├── dependencies.py    engine, DBSession
├── models/            SQLModel ORM tables
├── schemas/           Pydantic request/response shapes
├── repositories/      tenant-scoped persistence over a Session
└── routers/           FastAPI APIRouters

migrations/            Alembic migrations
tests/                 pytest suite
```

## Configuration

Environment variables (or a `.env` file at the project root) override defaults:

- `FINODE_DATABASE_URL` — default `sqlite:///./finode.db`
- `FINODE_DATABASE_ECHO` — default `true`
- `FINODE_SUPABASE_URL` — Supabase project URL, used to fetch JWKS for protected API routes
- `FINODE_SUPABASE_AUDIENCE` — expected JWT audience, default `authenticated`

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
- Transactions live at `/transactions/` and must contain at least two
  postings with total debits equal to total credits.
- Opening and direct balance adjustments are posted against a system equity
  account named `Opening Balances`.

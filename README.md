# finode

Personal finance API built with FastAPI and SQLModel.

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
├── repositories/      plain CRUD functions over a Session
└── routers/           FastAPI APIRouters

migrations/            Alembic migrations
tests/                 pytest suite
```

## Configuration

Environment variables (or a `.env` file at the project root) override defaults:

- `FINODE_DATABASE_URL` — default `sqlite:///./finode.db`
- `FINODE_DATABASE_ECHO` — default `true`

## Schema changes

```bash
uv run alembic revision --autogenerate -m "describe the change"
# review the generated file under migrations/versions/
uv run alembic upgrade head
```

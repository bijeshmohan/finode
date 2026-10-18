# Conventions and how-tos

The rules the code follows, and the steps for the common changes. `CLAUDE.md` in the repository root has the same rules in a denser form for AI assistants; keep both in step.

## Commands

| Task | Command |
|---|---|
| Apply migrations | `uv run alembic upgrade head` |
| Dev server (auto-reload) | `uv run fastapi dev` (http://localhost:8000) |
| Unit tests | `uv run pytest` |
| Browser tests | `scripts/browser-tests.sh` (needs Docker); `FINODE_BROWSER=webkit …` for WebKit |
| New migration | `uv run alembic revision --autogenerate -m "description"` (always read it before applying) |
| Add a dependency | `uv add <pkg>` (do not edit `pyproject.toml` by hand) |
| Deploy | `docker compose up -d --build` |

Python 3.14 or newer is required. No linter or formatter is configured.

## Code conventions

- **Imports inside `app/` are relative** (`from ..models.account import Account`).
- **Routers never touch the database.** They call services or repositories and turn `None` into `HTTPException(404)`. A web route must not duplicate a ledger rule.
- **Every repository query is filtered by the user** (`self.uid`). A query without it is a bug the isolation audit exists to catch.
- **Today is `clock.local_today()`**, never `date.today()`.
- **Money is a `Decimal`.** Amounts are stored as `Numeric(24,8)` and read back without padding zeros. Do not format money with `:.2f`; use the `money` filter or `normalize_amount`.
- **Config goes in `app/config.py`**, not into constants.
- **A page must not query once per row or per account.** Load postings and transactions in bulk (`postings_for_transactions`, `read_many`, `AccountService._postings_by_account`).
- **Comments say why**, not what. A module docstring says what the module is for.

## How to add a web page

1. Add a handler in the right module under `app/routers/web/` (or a new module registered in `routers/web/__init__.py`; pages that need a login go in the `protected` router).
2. Extend `base.html` in a new template; pass `active` for the current tab, and `hide_fab=True` on form pages.
3. Format amounts with the `money` filter; lists use `partials/transaction_list.html`.
4. A mutating form posts with `hx-post`; answer success with `htmx_redirect(location, flash="key")` (add the key to `MESSAGES` in `app/flash.py`; keys are one global dictionary, so check it is free) and failure with `htmx_error(message, "#target")`.
5. Destructive actions are `POST /{id}/delete` routes, not `DELETE`.
6. If the form can be opened from several places, accept a `back` path and pass it through `safe_back`.
7. **Classify the route in `tests/test_isolation.py`**. `test_every_route_is_covered` fails until you do.
8. Add a unit test for the HTML, and a browser test (`tests/browser/`) if behaviour lives in `app.js`.

## How to add a route to the JSON API

The API is small on purpose. Prefer the web app and the MCP tools. If a route is really needed: a handler in `app/routers/`, a schema in `app/schemas/`, a test, and the classification in the isolation audit. Tests for features that are not API routes reach the code through the services (`tests/svc.py`) or the web routes.

## How to add an MCP tool

Write the function in `app/mcp_server/tools.py`, using `with services() as s:` to reach the services. Take account *paths* and resolve them with `AccountIndex.find`; return amounts as strings. Add it to `READ_TOOLS`, or to `WRITE_TOOLS` with the right annotation (`WRITE`, `IDEMPOTENT_WRITE`, `DESTRUCTIVE`). Update `INSTRUCTIONS` if a ledger rule changed, and add a test beside `tests/test_mcp_tools.py`.

## How to change the schema

1. Change the model in `app/models/`.
2. `uv run alembic revision --autogenerate -m "…"` and **read** the result. SQLite (tests) and Postgres (production) differ; use batch operations where needed.
3. If existing data could break the change, make the migration refuse to run and change nothing, as the two-levels and single-currency migrations do.
4. Add the field to the backup (`schemas/backup.py`, `services/backup.py`) and to `tests/test_backup.py`.
5. A new table with a `user` column is erased automatically by `EraseService`; a table without one will not be.
6. A migration test (`tests/test_migration_*.py`) for anything that moves data.
7. **Take a backup before deploying a migration:** `docker compose run --rm -e BACKUP_ONCE=1 backup`.

## How to add a setting

- **For the whole installation:** a field on `Settings` in `app/config.py` (`FINODE_<NAME>`), and a line in the README's configuration list.
- **For one person:** a typed column on `profiles`, a migration, a field on `ProfileUpdate`, and a form on the Settings page (`routers/web/settings.py`, `settings.html`; forms post to `/settings/...`). Do not add a key-value or JSON store, and do not use Supabase `user_metadata` (users can write it directly).
- A rarely used feature should hide behind the Advanced switch (`ProfileRepository.advanced()`).

## Testing guide

- Tests are independent: each gets a fresh in-memory SQLite and overrides the database dependency.
- Prefer testing a rule at the service (`svc` fixture) and the page at the route (`client`).
- Any new code path that writes transactions needs a test that `trial_balance().balanced`.
- If your test changes the person's currency, build fresh services afterwards: a service instance caches it.
- The browser tests start the real app on a free port; keep the Playwright version in `pyproject.toml` and `scripts/browser-tests.sh` the same.

## Git and release habits (this repository)

Work on a feature branch, merge into `develop` with `--no-ff`, and merge `develop` into `main` only when asked. The commit author and trailer follow the repository owner's preference. Deploy from the server with `docker compose up -d --build`, then check: container healthy, no tracebacks in the logs, a changed file present in the running image, and `/login` answering 200.

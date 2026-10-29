# Code map

Where everything lives, and where to start reading. For how the pieces fit together, read the [architecture overview](../architecture/overview.md) first.

## If you read only five files

1. `app/main.py` — what is wired together.
2. `app/dependencies.py` — how a request becomes "this user" with services attached.
3. `app/services/transaction.py` — the ledger rules (`_resolve` is the heart).
4. `app/services/budget.py` — the budget arithmetic (`_compute`, `_roll`).
5. `app/routers/web/transactions.py` — a full web feature end to end.

## `app/` at the top level

| File | Job |
|---|---|
| `main.py` | creates the app, mounts routers, middleware, lifespan |
| `config.py` | `settings` (FINODE_* variables) |
| `dependencies.py` | database session, repositories and services per request (`DBSession`, `Budget`, `Reports`, …) |
| `auth.py` | verifies Supabase JWTs for the JSON API and /mcp (`CurrentUser`, `require_authenticated_user`, `reject_app_token`) |
| `web_auth.py` | the web login: cookies, refresh, `web_login_required`, `safe_next` |
| `signup.py`, `reset.py` | invite-only sign-up; forgotten passwords |
| `oauth.py` | talking to Supabase's OAuth server for the consent step |
| `clock.py` | `local_today()` and friends; never call `date.today()` |
| `currencies.py` | the currency list with decimals and signs |
| `templating.py`, `flash.py`, `caching.py` | Jinja environment and filters; one-shot messages; cache headers |
| `limits.py`, `ratelimit.py` | per-person caps; slowing sign-in guessing |
| `recurring_runner.py` | background loop that records due recurring transactions |
| `version.py` | the version from `pyproject.toml` |

## Layers

| Folder | One line |
|---|---|
| `models/` | SQLModel tables: `account`, `transaction` (+ `Posting`), `transaction_history`, `account_deletion`, `category` (budget categories), `budget` (allocations, goals), `recurring`, `profile`, `api_token`, `oauth_grant`, `auth` (mirror of Supabase `users`), `utils` (timestamps, the `Amount` column type) |
| `schemas/` | Pydantic shapes per entity: `*Base`, `*Create`, `*Read`, `*Update` |
| `repositories/` | tenant-scoped queries; `transaction.py` also appends history |
| `services/` | `account`, `category`, `transaction`, `budget`, `report`, `recurring` (+ `schedule`), `profile`, `data`, `backup`, `erase`, `api_token`, `oauth_grant`, `simple`, `validation` |
| `routers/` | the JSON API (`/api`, all of it listed in [api.md](api.md)): `accounts`, `categories`, `transactions`, `profile`, `recurring`, `budget`, `reports`, `data` |
| `routers/web/` | the HTML pages, one module per area |
| `mcp_server/` | `transport` (auth, rate limit), `tools`, `accounts` (name lookup), `context` |
| `ledger/` | journal format parser and writer (import and export) |
| `templates/`, `static/` | the web UI |

## Tests

| Where | What |
|---|---|
| `tests/conftest.py` | fresh in-memory SQLite per test, dependency overrides, fixtures (`client`, `root_accounts`, `account`, `expense_account`, `svc`, …) |
| `tests/svc.py` | `services(session, user=…, origin=…)` and `plain(model)`: call the services directly without HTTP |
| `tests/test_isolation.py` | person B tries to reach person A's data by every route; classifies every route |
| `tests/test_query_counts.py` | statement counts of the main pages must not grow with the data |
| `tests/test_backup.py` | round-trips a ledger that uses every feature |
| `tests/test_web_*.py`, `test_budget.py`, … | per-feature tests |
| `tests/mcputil.py` | helpers to talk to `/mcp` in-process |
| `tests/browser/` | Playwright tests of `app.js` behaviour in a real browser |
| `tests/htmlutil.py` | tiny helpers to assert on HTML |

## Scripts and ops files

| File | Job |
|---|---|
| `scripts/db-backup.sh` | nightly `pg_dump` in the `backup` service |
| `scripts/browser-tests.sh` | runs the browser tests in Playwright's container |
| `Dockerfile`, `compose.yaml` | image and the `migrate`, `app`, `backup` services |
| `migrations/` | Alembic (`versions/` holds one file per schema change) |

## Finding your way by task

| I want to… | Start at |
|---|---|
| change a ledger rule | `services/transaction.py::_resolve`, then add a test and keep `trial_balance().balanced` |
| add or change what a category is, or how a line gets one | `services/category.py`, `repositories/category.py`, `TransactionRepository._line_categories`, `TransactionService._check_categories` |
| change the budget arithmetic | `services/budget.py::_compute` / `_roll`, `tests/test_budget.py` |
| add a page | a module in `routers/web/`, a template in `templates/`, register it in `routers/web/__init__.py`, classify the route in `tests/test_isolation.py` |
| add an MCP tool | `mcp_server/tools.py` (add to `READ_TOOLS` or `WRITE_TOOLS`), update `INSTRUCTIONS` if a rule changed |
| add a setting for people | a column on `profiles`, a migration, a field on `ProfileUpdate`, a form on `routers/web/settings.py` |
| add a table | model, migration, backup + `tests/test_backup.py`; it has a `user` column so erasing finds it |

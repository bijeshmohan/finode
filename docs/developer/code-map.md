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
| `session.py` | the Supabase session: password sign-in, refresh, the HttpOnly cookies |
| `web_auth.py` | the web pages' guard: `web_login_required`, `safe_next`, the cookie refresh middleware |
| `signup.py`, `reset.py` | invite-only sign-up; forgotten passwords |
| `auth_flows.py` | the sign-in rules (limits, checks, messages) shared by the web pages and `/api/auth` |
| `feedback.py` | the Send feedback mail link |
| `oauth.py` | talking to Supabase's OAuth server for the consent step |
| `clock.py` | `local_today()` and friends; never call `date.today()` |
| `currencies.py` | the currency list with decimals and signs |
| `templating.py`, `flash.py`, `caching.py` | Jinja environment and filters; one-shot messages; cache headers |
| `limits.py`, `ratelimit.py` | per-person caps; slowing sign-in guessing |
| `recurring_runner.py` | background loop that records due recurring transactions |
| `version.py` | the version from `pyproject.toml` |
| `tags.py` | reading `#tags` out of a note (older backups, and the assistant's notice when a note holds one) |

## Layers

| Folder | One line |
|---|---|
| `models/` | SQLModel tables: `account`, `transaction` (+ `Posting`), `category` (budget categories), `contact` (contacts and their two accounts), `budget` (allocations), `recurring`, `tag` (tags and the entries that carry them), `profile`, `api_token`, `oauth_grant`, `auth` (mirror of Supabase `users`), `utils` (timestamps, the `Amount` column type) |
| `schemas/` | Pydantic shapes per entity: `*Base`, `*Create`, `*Read`, `*Update` |
| `repositories/` | tenant-scoped queries; `cache` remembers reads for one request (dropped on any write) |
| `services/` | `account`, `cards` (a card's statement and due dates), `category`, `contact` (people with a "Due from" and a "Due to" account), `contact_errors`, `transfer`, `expense_sharing`, `income_sharing`, `splits`, `settlement`, `obligation`, `netting` (nobody is owed both ways), `contact_summary` (what is done with a person), `transaction`, `budget`, `coming_up` (entries dated ahead and rule occurrences in one list), `report`, `todo` (the to-do bell), `recurring` (+ `schedule`), `profile`, `data`, `backup`, `erase`, `api_token`, `oauth_grant`, `payee_suggestions` (the Add screen's payee chips), `simple`, `validation` |
| `routers/` | the JSON API (`/api`, all of it listed in [api.md](api.md)): `accounts`, `categories`, `contacts`, `transfers`, `settlements`, `shared_expenses`, `shared_incomes`, `transactions`, `tags`, `profile`, `recurring`, `budget`, `reports`, `todo`, `data` (also Erase and Delete my account), `auth` (sign-in for the finode app), `assistants` (tokens, connected apps, consent); `contact_utils` is what the people routes share (the retry header, how a refusal is answered) |
| `routers/web/` | the HTML pages, one module per area |
| `mcp_server/` | `transport` (auth, rate limit), `tools`, `accounts` and `categories` (name lookup), `context` |
| `ledger/` | journal format parser and writer (import and export) |
| `templates/`, `static/` | the web UI |

## Tests

| Where | What |
|---|---|
| `tests/conftest.py` | fresh in-memory SQLite per test, dependency overrides, fixtures (`client`, `root_accounts`, `account`, `expense_account`, `svc`, …) |
| `tests/books.py` | categories in tests: what used to be an Expenses or Income account is a category (`post_account`, `into`, …) |
| `tests/svc.py` | `services(session, user=…, origin=…)` and `plain(model)`: call the services directly without HTTP |
| `tests/test_isolation.py` | person B tries to reach person A's data by every route; classifies every route |
| `tests/test_query_counts.py` | statement counts of the main pages must not grow with the data |
| `tests/test_backup.py` | round-trips a ledger that uses every feature |
| `tests/test_web_*.py`, `test_budget.py`, … | per-feature tests |
| `tests/mcputil.py` | helpers to talk to `/mcp` in-process |
| `tests/browser/` | Playwright tests of `app.js` behaviour in a real browser |
| `tests/htmlutil.py` | tiny helpers to assert on HTML |

## `frontend/` (the React app, being built)

| Where | What |
|---|---|
| `src/app/` | the router (`router.tsx`), the session and today (`session.tsx`), the layout (tab bar, sidebar), toasts, the offline banner |
| `src/api/` | `schema.d.ts` (generated from `openapi.json`, which `scripts/export_openapi.py` writes), the typed client (`client.ts`), the query client, `useApi()` |
| `src/components/` | the shared parts: `Icon` (`icons.json`), `Row`, `Tile`, `Sheet`, `Chips`, `AmountField`, `MonthPill`, `EmptyState` |
| `src/features/` | one folder per area: `auth/` (sign in, sign up, forgotten password, reset, and their shared parts); `placeholder/` stands in for pages not rebuilt yet |
| `src/lib/` | `amount.ts` (typing amounts), `money.ts` (writing them), `dates.ts` (writing days) |
| `scripts/` | `check-api-types.mjs`, `css-module-types.mjs` (exact types for each CSS module) |
| `tests/browser/spa.py` (repo root) | the browser tests' server for the React app: the built app and the API on one address (`spa_page`, `signed_in_spa_page`) |

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
| add an MCP tool | `mcp_server/tools.py` (add to `READ_TOOLS`, `WRITE_TOOLS` or `MANAGE_TOOLS`), update `INSTRUCTIONS` if a rule changed; a read tool also gets a call in `tests/test_mcp_smoke.py` |
| add a setting for people | a column on `profiles`, a migration, a field on `ProfileUpdate`, a form on `routers/web/settings.py` |
| add a table | model, migration, backup + `tests/test_backup.py`; it has a `user_id` column so erasing finds it |

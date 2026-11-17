# AGENTS.md

The rulebook for AI assistants working on finode (Claude Code reads it through `CLAUDE.md`). Keep it short: it is loaded into every session. **Rules go here; how a feature works goes in `docs/`.** When behaviour or a rule changes, update the matching page in `docs/` (and this file only if a rule changed).

finode is a personal double-entry ledger with envelope budgeting: FastAPI + SQLModel + Alembic, a JSON API under `/api`, an MCP server at `/mcp` for AI assistants, and one UI, the finode app (React + TypeScript + Vite in `frontend/`), which uses only `/api`. The app and the API share one address: Traefik sends the API's paths to the `app` container and everything else to the `web` container. One currency per person, Supabase for auth, Postgres in production, SQLite in dev and tests.

## Where to read before you change something

| Area | Read first |
|---|---|
| Accounts, transactions, postings, dates, currency, depth, built-in groups, cards, recurring, related entries, tags, query budget | `docs/developer/reference/ledger.md` |
| Budget, Budgets page, categories, Coming up, to-do bell | `docs/developer/reference/budget.md` |
| The app's look, components, amounts, signs, tiles, sheets, motion, dark mode | `docs/developer/reference/ui-look.md` |
| Each screen (Home, Add, Transactions, Accounts, Categories, Settings…) | `docs/developer/reference/ui-pages.md` |
| Import, export, backup, restore, limits, erase, isolation audit, passwords, Docker | `docs/developer/reference/data-and-ops.md` |
| MCP server, tokens, OAuth, tools | `docs/developer/reference/assistants.md` |
| Contacts, shared expenses, settlements | `docs/developer/reference/people.md` |
| Features removed on purpose | `docs/developer/reference/removed.md` |
| JSON API routes | `docs/developer/api.md` |
| Architecture with diagrams, user guide | `docs/index.md` |

## Commands

- Migrate: `uv run alembic upgrade head` (before first boot and after pulling schema changes). New migration: `uv run alembic revision --autogenerate -m "…"`, always review it before applying.
- Dev: `uv run fastapi dev` (the API, http://localhost:8000) and, in `frontend/`, `npm run dev` (the app, http://localhost:5173, which passes `/api` on to the API). Prod-ish: `uv run fastapi run`.
- Tests: `uv run pytest`. Browser tests: `scripts/browser-tests.sh` (Docker; `FINODE_BROWSER=webkit` for the closest to iOS Safari), or `uv run playwright install chromium` then `uv run pytest tests/browser`. A plain `pytest` skips them without a browser. Keep the playwright version the same in `pyproject.toml` and `scripts/browser-tests.sh`.
- Lint/format: `make lint` / `make format` (ruff, line length 120, over `app tests migrations scripts`). Types: `uv run pyrefly check` (must stay clean). All of it: `make check`. Also `make coverage`, `make hooks`, `make help`.
- Dependencies: `uv add <pkg>`; never edit `pyproject.toml` by hand. Python 3.14+.
- Deploy: `docker compose up -d --build` (the `migrate` service runs migrations; needs `.env` with `APP_DOMAIN`). Images only: `docker build -t finode .` (the API) and `docker build -t finode-web frontend` (the app; `scripts/check-web-image.sh` checks what it serves). A new top-level file needed at runtime must be added to the `Dockerfile` `COPY` lines (check `.dockerignore`). A new API path outside `/api`, `/mcp` and `/.well-known` must be added to the `app` router rule in `compose.yaml`, the service worker's `navigateFallbackDenylist` and `tests/browser/server.py` (`tests/test_compose_routes.py` holds them together).

## Code rules

- **Never commit code that fails ruff or pyrefly.** The linter enforces: `raise … from None` inside `except`, no mutable defaults (form lists default to `None`, normalised at the top of the handler), no unused variables, no `assert` in `app/` (use a check or `cast`), every `# noqa` has a reason. `# pyrefly: ignore[code]` only with the code and a reason; SQLModel column typing is silenced only in `app.models.*` and `app.repositories.*`.
- **Every function parameter in `app/` is typed** (ruff `ANN001` enforces it): an untyped one is `Any` to the type checker, so a rename that misses a reader goes unseen. A new read-only assistant tool gets a call in `tests/test_mcp_smoke.py`, which runs every one against a ledger that uses every feature.
- Relative imports inside `app/`. Configuration goes in `app/config.py` (`settings`, `FINODE_*` env vars), never hardcoded.
- Layers: `models/` (SQLModel tables; schema = models + Alembic), `schemas/` (`*Base`, `*Create`, `*Read`, `*Update`), `repositories/` (tenant-scoped, over a `Session`), `services/` (business rules), `routers/` (convert `None` into 404; **never touch the DB directly**). Type the session as `DBSession`.
- No `SQLModel.metadata.create_all` at startup: Alembic only.
- **Never call `date.today()`**: use `clock.local_today()` / `local_now()` / `local_midnight_utc()` (`FINODE_TIMEZONE`). A new user-entered date field uses the `Day` type (`schemas/day.py`, 1900-01-01 to 2999-12-31).
- **Naming**: a primary key is `id`, a foreign key `<entity>_id`, the owner `user_id`; path parameters and variables are named for what they are (`{account_id}`, `{transaction_id}`), never a short code.
- **Tenant isolation**: every query is filtered by the user (`self.uid` in repositories). `tests/test_isolation.py` fails on any unclassified new route: classify it (`PUBLIC`, `LISTS`, `REFERENCES`, `OWN_DATA`) and name ids for what they are (`category_id`, `contact_id`…). Every refusal in its audit must come from a real route.
- **Queries per screen**: the database is ~16 ms away, so never one query per account or per row. Use `AccountService._postings_by_account`, `TransactionRepository.postings_for_transactions` / `read_many`, and the per-request read cache (`repositories/cache.py`; copy a shared list before sorting it). `tests/test_query_counts.py` holds each view under a ceiling: lower it when a view gets cheaper, raise it only with a reason.
- **JSON API parity**: `/api` covers everything the app does. A new feature gets its route, a test in `tests/test_api_parity.py`, its isolation classification and a row in `docs/developer/api.md`. Nothing is left out: the app uses only `/api`. A cookie write must come from the request's own address with `X-Finode: 1` (`auth.check_app_request`). What a token alone must never do (tokens, connected apps, consent, Erase, Delete my account) takes `require_cookie_session`.
- **Backup**: a new model or account/budget flag goes into `services/backup.py` and the round-trip in `tests/test_backup.py`, or it silently disappears from backups. Erase walks every table with `user_id` automatically.
- **Merging accounts**: a new table or column holding an account id must be handled in `AccountService.merge`.
- New ways of creating accounts or transactions go through the services (limits via `limits.ensure_room`, depth via `_check_depth`, references via `create_once`/`create`). Saving an entry from a form (`/api/entries`), a bill or income shared with people included, goes through `EntryService` (`services/entry.py`, `services/entry_share.py`), never a copy of its rules. Any new path that writes transactions keeps a test asserting `trial_balance().balanced`.
- Secrets: the Supabase service key stays server-side: never render, log or send it to the browser.

## Ledger invariants (detail in `reference/ledger.md`)

- Accounts are a tree under five per-user roots (`Assets`, `Liabilities`, `Equity`, `Income`, `Expenses`); the type is the root ancestor. Roots and `Opening Balances` (the system equity account for opening balances and adjustments) cannot be renamed, moved or deleted. Accounts never move to another root.
- A transaction has ≥ 2 postings, positive amounts, debits = credits, all accounts the user's own; no postings to roots except Expenses/Income; no postings to Asset/Liability groups (`GROUP_POSTING_ROOT_NAMES`); an account is never on both sides of one entry. Balances are derived from postings (up to `as_of`, today by default), never stored.
- **Categories are not accounts** (`budget_categories`): spending and income post to the `Expenses` / `Income` root and the line carries `category_id`. Nothing can be created under Expenses or Income.
- **Two levels** below a root at most (`MAX_ACCOUNT_DEPTH = 2`), for everyone.
- **One currency** per person (`profiles.currency`); changing it relabels, never converts. Amounts are `Numeric(24,8)`: format with `formatting.money` or `normalize_amount` on the server and `lib/money.ts` in the app, never `:.2f`. Decimals are limited by the currency (`check_places`).
- Built-in groups (`accounts.system_key`) are guarded by key, never by name.
- Contact accounts ("Due from X" / "Due to X") are posted to only by `TransactionService(contacts=True)`; ordinary routes, rules, imports and assistants are refused.
- A person is never owed both ways: anything that saves an obligation calls `NettingService.even_out` before it commits, and anything that undoes one calls `release` first (`reference/people.md`).
- Per-person settings are typed columns on `profiles` (column + migration + `ProfileUpdate` field), never a key-value store or Supabase `user_metadata`.

## UI rules (`frontend/`; detail in `reference/ui-look.md`, `reference/ui-pages.md`)

- Commands (in `frontend/`, Node from `.nvmrc`): `npm ci`; `npm run dev`; `npm run check` (types for CSS modules and the API, ESLint, Prettier, `tsc`, Vitest, build, `npm audit --omit=dev`; also in `make check` and CI). After an API change: `npm run gen:api` (`tests/test_openapi_file.py` fails until you do).
- **Never commit code that fails `npm run check`.** Strict TypeScript; no `any` without a reason; ESLint at zero warnings; exact dependency versions.
- Call the API only through `useApi()` (`src/api/context.tsx`), never by importing `api`; read results with `data()` inside TanStack Query. A screen reads its view endpoint (`/api/views/…`, see `docs/developer/api.md`); how a list's rows read is worked out once, in `services/transaction_rows.py`, never in the app. Cached views share the key prefix `["views"]`, so a change to the books refreshes them all.
- **Amounts are strings** end to end, never `Number`; format with `lib/money.ts`, type with `AmountField` (typing is `lib/amount.ts`; the server re-checks with `check_places`). The app's only arithmetic on money is `lib/split.ts` (big.js: what is left to allocate on the Add screen); shares and totals come from the server. Indian grouping for INR only. **Today comes from `useToday()`** (the server's, in `FINODE_TIMEZONE`), never `new Date()`. `tests/format_cases.json` holds the app's helpers and `app/formatting.py` to the same answers.
- **Phones first.** No tables; lists use the shared row (`components/Row`: name, quiet second line, figure at the right) inside bento tiles (`components/Tile`, `--surface`, `--tile-border`). Rows open a screen or a sheet; destructive actions live there, never on rows, and deleting is for good (the app asks first).
- Text inputs ≥ 16px (iOS zoom). Prefer our own chips and bottom sheets (`components/Sheet`, `components/lines/Picker`) to native pickers, except the native month and date pickers laid over our own chips.
- Colours only from the tokens in `frontend/src/styles/tokens.css`; both dark blocks define the same tokens (`tests/test_app_css.py`); `tests/test_contrast.py` guards `--muted`. Green and `+` only for money in, red for real negatives. Bars use `--bar-h`, never a per-bar size. Icons from `components/Icon` (`components/icons.json`). Styles in a CSS Module per component.
- A component used by two features lives in `src/components/`; a feature's own screens, queries and parts live in `src/features/<area>/`. New screens reuse the existing parts (`Chips`, `Row`, `Tile`, `Sheet`, `EmptyState`, `MonthPill`, `Figure`, `CalcInfo`); do not draw new ones.
- The "+" stays in the tab bar on every screen, the Add and Edit screens included (the owner's choice, 2026-11-16). A form ends in one full-width primary button with no Cancel. A screen opened from several places takes `back`, passed through `lib/safeNext.ts` (only an address inside the app).
- Behaviour that needs a real browser gets a test in `tests/browser/` (fixtures `page`, `signed_in_page`, `api`, `books`; `tests/browser/server.py` serves the built app and the API on one address, only Supabase stood in for; `scripts/browser-tests.sh` builds the app first). Browser tests run with reduced motion.

## Removed on purpose: do not bring back without the owner asking

History, undo and Recently deleted · savings goals · budget targets and notes · the period lock · the Advanced switch · Build and Earn on the budget · search box and "Recently used" on Accounts · charts and colours on Categories · quick amounts on the Add screen · pre-filled accounts or categories (payee chips fill only the name) · account order / Move up/down · per-person depth limits · multiple currencies, prices and conversions. Details: `reference/removed.md` and the reference pages.

## Testing

- `tests/conftest.py` gives each test a fresh in-memory SQLite engine and overrides `get_db_session`, `require_authenticated_user` and `require_cookie_session` (use a client without those overrides to test real auth, as `tests/test_api_cookie_auth.py` does). The session commits for real.
- MCP tests use `tests/mcputil.py` (`make_token`, `running_app`, `mcp_client`, `payload`) and are `async` with `pytest.mark.anyio`.
- Guard tests not to weaken: isolation, query counts, read memory, contrast, dark-mode token parity, backup round-trip, ledger edges and fuzz, API parity, the one-address routes (`tests/test_compose_routes.py`).

## Git

Commit only when asked; branch off `develop` (`feature/…`, `chore/…`), PRs go to `main`.

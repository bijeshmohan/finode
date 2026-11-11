# AGENTS.md

The rulebook for AI assistants working on finode (Claude Code reads it through `CLAUDE.md`). Keep it short: it is loaded into every session. **Rules go here; how a feature works goes in `docs/`.** When behaviour or a rule changes, update the matching page in `docs/` (and this file only if a rule changed).

finode is a personal double-entry ledger with envelope budgeting: FastAPI + SQLModel + Alembic, a Jinja2/htmx web UI, a JSON API under `/api` and an MCP server at `/mcp` for AI assistants. One currency per person, Supabase for auth, Postgres in production, SQLite in dev and tests.

## Where to read before you change something

| Area | Read first |
|---|---|
| Accounts, transactions, postings, dates, currency, depth, built-in groups, cards, recurring, related entries, tags, query budget | `docs/developer/reference/ledger.md` |
| Budget, Budgets page, categories, Coming up, to-do bell | `docs/developer/reference/budget.md` |
| Web UI conventions, look, amounts, signs, tiles, sheets, motion, dark mode | `docs/developer/reference/ui-look.md` |
| Each page (Home, Add, Transactions, Accounts, Categories, Settings…) | `docs/developer/reference/ui-pages.md` |
| Import, export, backup, restore, limits, erase, isolation audit, passwords, Docker | `docs/developer/reference/data-and-ops.md` |
| MCP server, tokens, OAuth, tools | `docs/developer/reference/assistants.md` |
| Contacts, shared expenses, settlements | `docs/developer/reference/people.md` |
| Features removed on purpose | `docs/developer/reference/removed.md` |
| JSON API routes | `docs/developer/api.md` |
| Architecture with diagrams, user guide | `docs/index.md` |

## Commands

- Migrate: `uv run alembic upgrade head` (before first boot and after pulling schema changes). New migration: `uv run alembic revision --autogenerate -m "…"`, always review it before applying.
- Dev server: `uv run fastapi dev` (http://localhost:8000). Prod-ish: `uv run fastapi run`.
- Tests: `uv run pytest`. Browser tests: `scripts/browser-tests.sh` (Docker; `FINODE_BROWSER=webkit` for the closest to iOS Safari), or `uv run playwright install chromium` then `uv run pytest tests/browser`. A plain `pytest` skips them without a browser. Keep the playwright version the same in `pyproject.toml` and `scripts/browser-tests.sh`.
- Lint/format: `make lint` / `make format` (ruff, line length 120, over `app tests migrations scripts`). Types: `uv run pyrefly check` (must stay clean). All of it: `make check`. Also `make coverage`, `make hooks`, `make help`.
- Dependencies: `uv add <pkg>`; never edit `pyproject.toml` by hand. Python 3.14+.
- Deploy: `docker compose up -d --build` (the `migrate` service runs migrations; needs `.env` with `APP_DOMAIN`). Image only: `docker build -t finode .`. A new top-level file needed at runtime must be added to the `Dockerfile` `COPY` lines (check `.dockerignore`).

## Code rules

- **Never commit code that fails ruff or pyrefly.** The linter enforces: `raise … from None` inside `except`, no mutable defaults (form lists default to `None`, normalised at the top of the handler), no unused variables, no `assert` in `app/` (use a check or `cast`), every `# noqa` has a reason. `# pyrefly: ignore[code]` only with the code and a reason; SQLModel column typing is silenced only in `app.models.*` and `app.repositories.*`.
- **Every function parameter in `app/` is typed** (ruff `ANN001` enforces it): an untyped one is `Any` to the type checker, so a rename that misses a reader goes unseen. A new read-only assistant tool gets a call in `tests/test_mcp_smoke.py`, which runs every one against a ledger that uses every feature.
- Relative imports inside `app/`. Configuration goes in `app/config.py` (`settings`, `FINODE_*` env vars), never hardcoded.
- Layers: `models/` (SQLModel tables; schema = models + Alembic), `schemas/` (`*Base`, `*Create`, `*Read`, `*Update`), `repositories/` (tenant-scoped, over a `Session`), `services/` (business rules), `routers/` (convert `None` into 404; **never touch the DB directly**), `routers/web/` (HTML UI; calls the same services, must not duplicate ledger rules). Type the session as `DBSession`.
- No `SQLModel.metadata.create_all` at startup: Alembic only.
- **Never call `date.today()`**: use `clock.local_today()` / `local_now()` / `local_midnight_utc()` (`FINODE_TIMEZONE`). A new user-entered date field uses the `Day` type (`schemas/day.py`, 1900-01-01 to 2999-12-31).
- **Naming**: a primary key is `id`, a foreign key `<entity>_id`, the owner `user_id`; path parameters and variables are named for what they are (`{account_id}`, `{transaction_id}`), never a short code.
- **Tenant isolation**: every query is filtered by the user (`self.uid` in repositories). `tests/test_isolation.py` fails on any unclassified new route: classify it (`PUBLIC`, `LISTS`, `REFERENCES`, `OWN_DATA`) and name ids for what they are (`category_id`, `contact_id`…). Keep test person A's names out of static template text.
- **Queries per page**: the database is ~16 ms away, so never one query per account or per row. Use `AccountService._postings_by_account`, `TransactionRepository.postings_for_transactions` / `read_many`, and the per-request read cache (`repositories/cache.py`; copy a shared list before sorting it). `tests/test_query_counts.py` holds each page under a `CEILING`: lower it when a page gets cheaper, raise it only with a reason.
- **JSON API parity**: `/api` covers everything the app does. A new feature gets its route, a test in `tests/test_api_parity.py`, its isolation classification and a row in `docs/developer/api.md`. Left out on purpose: sign-in/up, tokens and connected apps, Erase / Delete my account, the Add screen's payee chips.
- **Backup**: a new model or account/budget flag goes into `services/backup.py` and the round-trip in `tests/test_backup.py`, or it silently disappears from backups. Erase walks every table with `user_id` automatically.
- **Merging accounts**: a new table or column holding an account id must be handled in `AccountService.merge`.
- New ways of creating accounts or transactions go through the services (limits via `limits.ensure_room`, depth via `_check_depth`, references via `create_once`/`create`). Any new path that writes transactions keeps a test asserting `trial_balance().balanced`.
- Secrets: the Supabase service key stays server-side: never render, log or send it to the browser.

## Ledger invariants (detail in `reference/ledger.md`)

- Accounts are a tree under five per-user roots (`Assets`, `Liabilities`, `Equity`, `Income`, `Expenses`); the type is the root ancestor. Roots and `Opening Balances` (the system equity account for opening balances and adjustments) cannot be renamed, moved or deleted. Accounts never move to another root.
- A transaction has ≥ 2 postings, positive amounts, debits = credits, all accounts the user's own; no postings to roots except Expenses/Income; no postings to Asset/Liability groups (`GROUP_POSTING_ROOT_NAMES`); an account is never on both sides of one entry. Balances are derived from postings (up to `as_of`, today by default), never stored.
- **Categories are not accounts** (`budget_categories`): spending and income post to the `Expenses` / `Income` root and the line carries `category_id`. Nothing can be created under Expenses or Income.
- **Two levels** below a root at most (`MAX_ACCOUNT_DEPTH = 2`), for everyone.
- **One currency** per person (`profiles.currency`); changing it relabels, never converts. Amounts are `Numeric(24,8)`: format with the `money` filter or `normalize_amount`, never `:.2f`. Decimals are limited by the currency (`check_places`).
- Built-in groups (`accounts.system_key`) are guarded by key, never by name.
- Contact accounts ("Due from X" / "Due to X") are posted to only by `TransactionService(contacts=True)`; ordinary routes, rules, imports and assistants are refused.
- A person is never owed both ways: anything that saves an obligation calls `NettingService.even_out` before it commits, and anything that undoes one calls `release` first (`reference/people.md`).
- Per-person settings are typed columns on `profiles` (column + migration + `ProfileUpdate` field), never a key-value store or Supabase `user_metadata`.

## Web UI rules (detail in `reference/ui-look.md`, `reference/ui-pages.md`)

- **No JavaScript build step**; vendored htmx plus `static/app.js`. Templates extend `base.html`; `partials/` are htmx fragments. Mutations are `hx-post` (`POST /{id}/delete`, not `DELETE`). Success: `htmx_redirect(location, flash=…)` (add the key to `MESSAGES` in `app/flash.py`; keys are global, check it is free). Failure: 4xx + `HX-Retarget` (`routers/web/utils.py`).
- **Phones first.** No tables; lists use `partials/transaction_list.html` and the shared row (name, quiet second line, figure at the right) inside bento tiles (`--surface`, `--tile-border`); reuse the tile rule at the end of `style.css`. Rows link to a detail page or open a sheet; destructive actions live there, never on rows, and deleting is for good (`hx-confirm`).
- Text inputs ≥ 16px (iOS zoom). Prefer our own chips and bottom sheets (`#row-picker` etc.) to native pickers, except the native month picker.
- Colours only from the tokens at the top of `style.css`; both dark blocks define the same tokens (a test compares them); `tests/test_contrast.py` guards `--muted`. Green and `+` only for money in, red for real negatives. Bars use `--bar-h`, never a per-bar size. Icons from `partials/icons.html`.
- Forms opened from several places take `back` through `safe_back`. Form pages pass `hide_fab=True` and end in one full-width primary button with no Cancel.
- Amount fields: `cleanAmount` / `tidyAmount` / `groupAmount` in `app.js`; the server re-checks (`parse_amount`, `check_places`). Indian grouping for INR only.
- Behaviour that lives in `app.js` or needs a real browser gets a test in `tests/browser/` (the unit tests only see server HTML). Browser tests run with reduced motion.
- New pages reuse the existing parts (switcher `.chips.seg`, row, tile, `.add-row`, `.empty-state`, month pill macro); do not draw new ones.

## Removed on purpose: do not bring back without the owner asking

History, undo and Recently deleted · savings goals · budget targets and notes · the period lock · the Advanced switch · Build and Earn on the budget · search box and "Recently used" on Accounts · charts and colours on Categories · quick amounts on the Add screen · pre-filled accounts or categories (payee chips fill only the name) · account order / Move up/down · per-person depth limits · multiple currencies, prices and conversions. Details: `reference/removed.md` and the reference pages.

## Testing

- `tests/conftest.py` gives each test a fresh in-memory SQLite engine and overrides `get_db_session` and `web_login_required` (use a client without that override to test real auth, as `tests/test_web_auth.py` does). The session commits for real.
- MCP tests use `tests/mcputil.py` (`make_token`, `running_app`, `mcp_client`, `payload`) and are `async` with `pytest.mark.anyio`.
- `tests/htmlutil.py` has helpers for HTML assertions (no parser dependency).
- Guard tests not to weaken: isolation, query counts, read memory, contrast, dark-mode token parity, backup round-trip, ledger edges and fuzz, API parity.

## Git

Commit only when asked; branch off `develop` (`feature/…`, `chore/…`), PRs go to `main`.

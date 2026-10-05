# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Apply migrations: `uv run alembic upgrade head` (run before first boot and after pulling schema changes)
- Run dev server: `uv run fastapi dev` (auto-reload, http://localhost:8000)
- Run prod-ish: `uv run fastapi run`
- Run tests: `uv run pytest`
- Generate a migration: `uv run alembic revision --autogenerate -m "description"` (always review before applying)
- Add a dependency: `uv add <pkg>` (do not edit `pyproject.toml` by hand)
- Deploy with Docker: `docker compose up -d --build` (runs migrations via the one-off `migrate` service, then the app behind Traefik; needs `.env` with `APP_DOMAIN`)
- Build the image only: `docker build -t finode .`

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
- `app/routers/web/` — the HTML UI under `/app`, rendered with Jinja2 (`app/templates/`) and enhanced with vendored htmx (`app/static/`). It calls the same services as the JSON API and must not duplicate ledger rules; view-model helpers (account tree, posting pickers) live in the web routers.

`app/main.py` wires the routers. Schema is managed by Alembic — `app/main.py` does *not* run `SQLModel.metadata.create_all` at startup. Run `uv run alembic upgrade head` to bring the DB to the latest schema. The dev DB is `finode.db` (SQLite, gitignored).

`app/config.py` exposes a `settings` instance (pydantic-settings) reading `FINODE_*` env vars and an optional `.env` file (other keys are ignored because `.env` is shared with docker compose). Current settings: `database_url`, `database_echo`, `supabase_url`, `supabase_audience`, `supabase_anon_key`, `cookie_secure`, `max_account_depth`, `mcp_rate_limit`. Add new configuration here rather than hardcoding constants.

`app/dependencies.py` builds the engine from `settings` and exposes `DBSession = Annotated[Session, Depends(get_db_session)]`. Route handlers should type the session parameter as `DBSession` directly rather than re-declaring `Depends(...)`.

All imports within `app/` use relative imports (e.g. `from ..models.account import Account`). The FastAPI CLI entrypoint is configured in `pyproject.toml` under `[tool.fastapi]` as `entrypoint = "app.main:app"`.

### Web UI

There is no JavaScript build step; do not add one. Templates extend `base.html`; `partials/` holds fragments returned to htmx. Mutating forms use `hx-post` (htmx 2 sends `DELETE` parameters in the URL, so use `POST` routes such as `/{id}/delete`). Handlers answer success with `htmx_redirect(location, flash=...)` and failures with a 4xx plus `HX-Retarget` pointing at an error element, via `routers/web/utils.py`; `static/app.js` lets htmx swap those 4xx responses.

UI conventions (keep pages working on phones first):
- Layout: `base.html` renders a top bar (desktop nav, plus the profile icon at the right on every screen size), a bottom tab bar (Home, Accounts, Transactions) and a floating "+" button (phones). Sign-out lives at the bottom of the profile page, not in the top bar. Pass `active` for the current section and `hide_fab=True` on form pages.
- Lists use `partials/transaction_list.html` (rows from `transactions.to_row`, grouped by day with the `friendly_date` filter); format amounts with the `money` filter. Avoid tables — they overflow on phones.
- Rows are links to a detail or edit page; destructive actions live on that page, not on list rows.
- Forms that can be opened from several places accept a `back` path and return there after saving; always pass it through `safe_back`, which only allows paths under `/app/`.
- Confirm actions with a flash: add the message key to `MESSAGES` in `app/flash.py` and pass it to `htmx_redirect`.
- Account pickers on the transaction forms use `account_options(groups, selected, allow_new=True)` and carry `data-account-select`; `app.js` opens the `<dialog id="quick-account">` sheet (`/app/accounts/quick`) when "+ New account…" is chosen, then refreshes every picker from `/app/accounts/options` on the `account-added` event. Restore pickers synchronously (`cancel` event, cancel buttons), never from the async `close` event alone.
- Icons come from the `icon()` macro in `partials/icons.html`; styles use the CSS variables at the top of `static/style.css` (both light and dark themes).

`app/web_auth.py` signs users in through Supabase's password grant and keeps the tokens in `HttpOnly` cookies. `web_login_required` verifies the cookie (refreshing it when expired) and stores the token in `request.state`, which `require_authenticated_user` accepts in addition to a bearer header, so repositories stay tenant-scoped. The JSON API never reads cookies. In tests, `tests/conftest.py` overrides both dependencies; use a client without the `web_login_required` override (see `tests/test_web_auth.py`) to test real authentication.

### Profile and settings

`app/models/profile.py` holds one `profiles` row per user (names, depth limits, default currency) (keyed by the Supabase user id, created lazily by `ProfileRepository.get_or_create`). Per-user details and application settings are **typed columns on that table** — add a setting with a column, a migration and a field on `ProfileUpdate`, not a key-value or JSON store. Supabase `user_metadata` is deliberately not used: users can write it directly and it is copied into every token. The page is `/app/profile` (tab bar and top bar): an initials avatar header, then collapsible `<details class="setting">` rows (name, currency, depth, appearance) that `app.js` opens when the URL hash names them, and links to `/app/profile/data` (export and import). The light/dark override is per browser, kept in the `finode_theme` cookie that `base.html` reads, not a profile column. The JSON API is `/profile/`. Email and password stay with Supabase.

### Commodities, currencies and prices

Accounts hold a **commodity**: a currency, coin, share or fund (`app/models/commodity.py`). The `commodities` table has the **built-in currencies** (`user` is NULL: the full ISO 4217 list from `app/commodity_seed.py`, inserted by migrations and changed only through migrations or scripts) plus each user's **own assets** (stocks, funds, coins, anything that isn't a currency; users cannot create currencies). There is no shared price list: every price belongs to a user. A code is unique among the currencies and per user, and an asset's code may not repeat a currency code (so a ticker like `ALL` needs a suffix), so a code names one thing for one user and API fields use codes (`"USD"`), not ids. Every non-root account has exactly one commodity (`accounts.commodity_id`; a child defaults to its parent's, under a root to the default currency, and it can only change while the account has no postings). Root accounts hold nothing of their own: their total is valued in the user's default currency (`profiles.default_commodity_id`, only a `kind=currency` commodity, chosen from the built-in list). A second currency or any asset is valued only by prices the user enters or by rates implied by their own conversions.

A transaction balances in one **currency** (`transactions.currency_id`, any commodity code the user can see). A posting has an `amount` (in its account's commodity) and a `value` (the same posting in the transaction's currency). For postings in the transaction's currency `value` is the amount and may be left out; otherwise it is required. Debits and credits must balance on `value`, and amounts may have at most the commodity's `decimals` (checked in `TransactionService._resolve`; repositories only store). Amount columns are `Numeric(24,8)` through the `Amount` type, which reads values back without padding zeros (`100.00`, not `100.00000000`): do not format money with `:.2f`, use the `money` filter or `normalize_amount`.

Prices (`app/services/prices.py`): a `PriceBook` finds the latest rate on or before a day, directly, inverted or through one common commodity. Its points are the user's own manual prices (win on a tie) and the rates implied by their own conversions, which are **derived from postings on demand** (`TransactionRepository.conversions`), never stored, so edits and deletes cannot leave stale prices. A balance that cannot be valued is flagged `unpriced`, never counted as zero. Net worth values holdings at the latest price; income and expenses use each posting's value converted at the transaction's date. `AccountService.holding` reports invested (posting values), value and gain. Selling at a profit is the user's own transaction (for example to `Income › Capital Gain`); nothing computes gains automatically. Opening balances of an account holding something other than the Opening Balances account's currency are valued with `balance_value` or the latest price.

Anything that creates accounts or postings outside the services (imports) must set `commodity_id`, the transaction currency and each posting's value itself.

### Import and export

`app/ledger/` reads and writes the plain-text ledger journal format (`parse.py` / `write.py`, no dependency); `app/services/data.py` (`DataService`) maps it to accounts and transactions and also writes a CSV. Exports are always allowed (`/export`, `/app/export`). Import is **only allowed while the user has no transactions**, previews first (`?dry_run=true`, `/app/import/preview`) and is all-or-nothing in one database transaction. Debit is positive, credit negative; `Assets:Bank:HDFC` maps to the account tree, root names accept aliases (`Asset`, `Revenue`...), `Equity:Opening Balances` maps to the system account. Unsupported input (several currencies, prices, virtual postings, automated/periodic transactions, `include`, balance assignments) is an error with its line number, never silently dropped. Imported postings follow the same rules as the transaction service (no postings to roots, or to Assets/Liabilities/Equity groups); keep `DataService._plan` in step with `GROUP_POSTING_ROOT_NAMES` if that rule changes. Account names cannot contain `:` because it is the ledger path separator.

Several commodities are supported: conversions are written `100 USD @@ 8350 INR` (also `@` per unit), `P` lines carry prices, `commodity` lines carry decimals and finode's `name:`/`kind:` tags. A transaction's currency is the commodity its postings are priced in; an account may post only one commodity (others must go in sub-accounts); unknown codes become the user's own commodities; lots (`{}`) are still refused. When everything is in the default currency, exports have bare numbers exactly as before (no commodity labels, and CSV keeps its six columns); otherwise every amount is labeled and CSV gains `commodity`, `value` and `currency` columns.

### MCP server (AI assistants)

`app/mcp_server/` serves an MCP server at `/mcp` (Streamable HTTP, **stateless with JSON responses**, so any worker can answer any request) built on the official `mcp` SDK (2.x: `MCPServer`, not `FastMCP`). It is a plain ASGI route added in `app/main.py`, and `main.lifespan` runs the SDK's session managers (`transport.lifespan` builds fresh ones on every start, because tests start the app many times).

- **Auth (phase 1):** personal access tokens (`api_tokens`: only a sha256 of the `fin_…` secret is kept, plus a display prefix, scope `read`/`write`, last used, revoked). Users create and revoke them on `/app/profile/assistants`; the secret is shown once. `transport.MCPEndpoint` checks the bearer token, applies a per-token per-process rate limit (`settings.mcp_rate_limit` a minute), puts the `TokenOwner` in `context.current_owner` and hands the request to the server for that scope: read-only tokens get a server without the write tools at all. Tokens only work on `/mcp`, never on the JSON API, and cannot manage tokens. OAuth (for claude.ai/ChatGPT connectors) is phase 2.
- **Tools** (`tools.py`) call the same services as everything else through `context.services()` (which builds them for the token's user, like `dependencies.py`). They take account paths (`Assets:Bank:HDFC`, a unique end like `HDFC`, or other separators), resolved by `accounts.AccountIndex.find`, which explains ambiguous or unknown names. Amounts go out as strings. Service errors become `ToolError`s with the service's message. Write tools carry MCP annotations (`delete_transaction` is destructive). Assistants can create accounts but never delete or edit them. Keep `INSTRUCTIONS` in step with ledger rules.
- **Origin:** transactions record `created_via`/`updated_via` (`web`, `api`, `import`, `mcp:<token name>`), set by `TransactionService(origin=...)` (`dependencies.get_transaction_service` decides web vs api from the path). The list marks entries made or changed by an assistant; the edit page says who added and last changed it.
- `services/simple.py` turns from/to/amount (and a received amount for conversions) into postings for both the web form and `record_transaction`; `ReportService.breakdown` (also `/reports/breakdown`) gives per-account income or expenses.
- Tests talk to `/mcp` over HTTP with the SDK client and an in-process ASGI transport (`tests/mcputil.py`: `make_token`, `running_app`, `mcp_client`, `payload`); tests are `async` with `pytest.mark.anyio`.

### Account depth limits

Each user sets, per top-level account, how many levels of sub-accounts are allowed (`profiles.max_depth_*`; depth counts levels below the top-level account, so `Expenses › Food` is 1). `0` means no limit of their own; `settings.max_account_depth` (env `FINODE_MAX_ACCOUNT_DEPTH`, default 20) is a global ceiling no user can exceed, and `app/services/depth.py` turns a profile into effective limits. `AccountService` enforces the limit when creating or moving accounts (`_check_depth`), `ProfileService` refuses a limit below the deepest existing account or above the ceiling, and `DataService` applies it to imports. The account forms hide parents that have no room left. Any new place that creates accounts outside `AccountService` must check the limit itself.

### Docker

`Dockerfile` is multi-stage: uv resolves `uv.lock` into `/opt/venv`, and the runtime stage copies only that venv plus `app/`, `migrations/`, `alembic.ini` and `pyproject.toml` (needed for the `[tool.fastapi]` entrypoint). If a new top-level file is needed at runtime, add it to the `COPY` lines and check `.dockerignore`. `compose.yaml` targets an existing Traefik on an external network; production uses Supabase Postgres, so there is no database service. Uvicorn reads `WEB_CONCURRENCY` and `FORWARDED_ALLOW_IPS` from the environment.

Tests live in `tests/`. `tests/conftest.py` builds a fresh in-memory SQLite engine per test (seeded with the built-in currencies, plus a private `BTC` asset for the test user) and overrides `get_db_session`, so tests are independent of `finode.db` and of Alembic. The session commits for real, so a service that rolls back only undoes its own unfinished work. `tests/htmlutil.py` has tiny helpers for asserting on HTML (there is no HTML parsing dependency). The commodity migrations are tested in `tests/test_migration_commodities.py` (SQLite); they were also rehearsed on Postgres 16 with data.

### Double-entry ledger

`app/models/account.py` defines accounts as a tree. Each user has five system
root accounts (`Assets`, `Liabilities`, `Equity`, `Income`, `Expenses`),
created lazily on first access by `AccountService._ensure_roots` (a partial
unique index on `(user, name)` where `parent_id IS NULL` keeps this race-safe).
There is no stored type: an account's type is its root ancestor, and all
non-root accounts require a `parent_id`. Roots cannot be renamed, moved, or
deleted. Categories are not a separate table; former category concepts are
represented as income or expense accounts.

`app/models/transaction.py` defines `Transaction` and `Posting`. A transaction
contains at least two postings, every posting has a positive amount, and total
debits must equal total credits. The service layer validates those invariants
and verifies that all referenced accounts belong to the authenticated user.
Postings may not target root accounts. Asset and liability accounts that have
sub-accounts cannot be posted to either (and cannot gain sub-accounts once they
have postings), but Income and Expenses groups can (`GROUP_POSTING_ROOT_NAMES`
in `app/services/account.py`). An account cannot be moved under a different
root (that would silently reclassify its history).

Account balances are derived from postings. Assets and Expenses increase
with debits; Liabilities, Equity, and Income increase with credits. Asset and
liability accounts that already have postings cannot gain sub-accounts. Opening balances and
direct balance edits are posted against the system equity account named
`Opening Balances`, which cannot be renamed, moved, deleted, given
sub-accounts or have its balance set directly.

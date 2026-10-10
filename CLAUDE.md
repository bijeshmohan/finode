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
- `app/routers/web/` — the HTML UI at the site root (`/`, `/accounts`, `/login`…), rendered with Jinja2 (`app/templates/`) and enhanced with vendored htmx (`app/static/`). It calls the same services as the JSON API and must not duplicate ledger rules; view-model helpers (account tree, posting pickers) live in the web routers.

`app/main.py` wires the routers: the JSON API is mounted under `/api` (so `/accounts` is the page and `/api/accounts/` the API), `/mcp` and `/static` stay at the root, and the old `/...` paths redirect (301) to their new place. The web login cookie path is `/`. Schema is managed by Alembic — `app/main.py` does *not* run `SQLModel.metadata.create_all` at startup. Run `uv run alembic upgrade head` to bring the DB to the latest schema. The dev DB is `finode.db` (SQLite, gitignored).

`app/config.py` exposes a `settings` instance (pydantic-settings) reading `FINODE_*` env vars and an optional `.env` file (other keys are ignored because `.env` is shared with docker compose). Current settings: `database_url`, `database_echo`, `supabase_url`, `supabase_audience`, `supabase_anon_key`, `cookie_secure`, `max_account_depth`, `mcp_rate_limit`, `recurring_interval_minutes`. Add new configuration here rather than hardcoding constants.

`app/dependencies.py` builds the engine from `settings` and exposes `DBSession = Annotated[Session, Depends(get_db_session)]`. Route handlers should type the session parameter as `DBSession` directly rather than re-declaring `Depends(...)`.

All imports within `app/` use relative imports (e.g. `from ..models.account import Account`). The FastAPI CLI entrypoint is configured in `pyproject.toml` under `[tool.fastapi]` as `entrypoint = "app.main:app"`.

### Web UI

There is no JavaScript build step; do not add one. Templates extend `base.html`; `partials/` holds fragments returned to htmx. Mutating forms use `hx-post` (htmx 2 sends `DELETE` parameters in the URL, so use `POST` routes such as `/{id}/delete`). Handlers answer success with `htmx_redirect(location, flash=...)` and failures with a 4xx plus `HX-Retarget` pointing at an error element, via `routers/web/utils.py`; `static/app.js` lets htmx swap those 4xx responses.

UI conventions (keep pages working on phones first):
- Layout: `base.html` renders a top bar (desktop nav, plus the profile icon at the right on every screen size), a bottom tab bar (Home, Accounts, Transactions, Budget, Settings) and a floating "+" button (phones). Sign-out lives at the bottom of the profile page, not in the top bar. Pass `active` for the current section and `hide_fab=True` on form pages.
- Lists use `partials/transaction_list.html` (rows from `transactions.to_row`, grouped by day with the `friendly_date` filter); format amounts with the `money` filter. Avoid tables — they overflow on phones.
- Rows are links to a detail or edit page; destructive actions live on that page, not on list rows.
- Forms that can be opened from several places accept a `back` path and return there after saving; always pass it through `safe_back`, which only allows local paths of the web UI (not `/api`, `/mcp`, `/static`…).
- Confirm actions with a flash: add the message key to `MESSAGES` in `app/flash.py` and pass it to `htmx_redirect`.
- Account pickers on the transaction forms use `account_options(groups, selected, allow_new=True)` and carry `data-account-select`; `app.js` opens the `<dialog id="quick-account">` sheet (`/accounts/quick`) when "+ New account…" is chosen, then refreshes every picker from `/accounts/options` on the `account-added` event. Restore pickers synchronously (`cancel` event, cancel buttons), never from the async `close` event alone.
- Icons come from the `icon()` macro in `partials/icons.html`; styles use the CSS variables at the top of `static/style.css` (both light and dark themes).

`app/web_auth.py` signs users in through Supabase's password grant and keeps the tokens in `HttpOnly` cookies. `web_login_required` verifies the cookie (refreshing it when expired) and stores the token in `request.state`, which `require_authenticated_user` accepts in addition to a bearer header, so repositories stay tenant-scoped. The JSON API never reads cookies. In tests, `tests/conftest.py` overrides both dependencies; use a client without the `web_login_required` override (see `tests/test_web_auth.py`) to test real authentication.

### Profile and settings

The web UI keeps two pages apart: **Profile** (`/profile`, person icon) is about the user's account (name, email, AI assistants, export/import, sign out); **Settings** (`/settings`, gear icon in the top bar and the last tab) is about how the application works (default currency, account depth limits, appearance, links to recurring transactions and assets & prices). Put every new application setting on the Settings page (`routers/web/settings.py`, `settings.html`; forms post to `/settings/...`), not on Profile. Storage is unchanged, described next.

`app/models/profile.py` holds one `profiles` row per user (names, depth limits, default currency) (keyed by the Supabase user id, created lazily by `ProfileRepository.get_or_create`). Per-user details and application settings are **typed columns on that table** — add a setting with a column, a migration and a field on `ProfileUpdate`, not a key-value or JSON store. Supabase `user_metadata` is deliberately not used: users can write it directly and it is copied into every token. `/profile` has an initials avatar header and the name row; `/settings` has collapsible `<details class="setting">` rows (currency, depth, appearance) that `app.js` opens when the URL hash names them; `/profile/data` is export and import. The light/dark override is per browser, kept in the `finode_theme` cookie that `base.html` reads, not a profile column. The JSON API is `/api/profile/`. Email and password stay with Supabase.

### Commodities, currencies and prices

Accounts hold a **commodity**: a currency, coin, share or fund (`app/models/commodity.py`). The `commodities` table has the **built-in currencies** (`user` is NULL: the full ISO 4217 list from `app/commodity_seed.py`, inserted by migrations and changed only through migrations or scripts) plus each user's **own assets** (stocks, funds, coins, anything that isn't a currency; users cannot create currencies). There is no shared price list: every price belongs to a user. A code is unique among the currencies and per user, and an asset's code may not repeat a currency code (so a ticker like `ALL` needs a suffix), so a code names one thing for one user and API fields use codes (`"USD"`), not ids. Every non-root account has exactly one commodity (`accounts.commodity_id`; a child defaults to its parent's, under a root to the default currency, and it can only change while the account has no postings). Root accounts hold nothing of their own: their total is valued in the user's default currency (`profiles.default_commodity_id`, only a `kind=currency` commodity, chosen from the built-in list). A second currency or any asset is valued only by prices the user enters or by rates implied by their own conversions.

A transaction balances in one **currency** (`transactions.currency_id`, any commodity code the user can see). A posting has an `amount` (in its account's commodity) and a `value` (the same posting in the transaction's currency). For postings in the transaction's currency `value` is the amount and may be left out; otherwise it is required. Debits and credits must balance on `value`, and amounts may have at most the commodity's `decimals` (checked in `TransactionService._resolve`; repositories only store). Amount columns are `Numeric(24,8)` through the `Amount` type, which reads values back without padding zeros (`100.00`, not `100.00000000`): do not format money with `:.2f`, use the `money` filter or `normalize_amount`.

Prices (`app/services/prices.py`): a `PriceBook` finds the latest rate on or before a day, directly, inverted or through one common commodity. Its points are the user's own manual prices (win on a tie) and the rates implied by their own conversions, which are **derived from postings on demand** (`TransactionRepository.conversions`), never stored, so edits and deletes cannot leave stale prices. A balance that cannot be valued is flagged `unpriced`, never counted as zero. Net worth values holdings at the latest price; income and expenses use each posting's value converted at the transaction's date. `AccountService.holding` reports invested (posting values), value and gain. Selling at a profit is the user's own transaction (for example to `Income › Capital Gain`); nothing computes gains automatically. Opening balances of an account holding something other than the Opening Balances account's currency are valued with `balance_value` or the latest price.

Anything that creates accounts or postings outside the services (imports) must set `commodity_id`, the transaction currency and each posting's value itself.

### Import and export

`app/ledger/` reads and writes the plain-text ledger journal format (`parse.py` / `write.py`, no dependency); `app/services/data.py` (`DataService`) maps it to accounts and transactions and also writes a CSV. Exports are always allowed (`/api/export`, `/export`). Import is **only allowed while the user has no transactions**, previews first (`?dry_run=true`, `/import/preview`) and is all-or-nothing in one database transaction. Debit is positive, credit negative; `Assets:Bank:HDFC` maps to the account tree, root names accept aliases (`Asset`, `Revenue`...), `Equity:Opening Balances` maps to the system account. Unsupported input (several currencies, prices, virtual postings, automated/periodic transactions, `include`, balance assignments) is an error with its line number, never silently dropped. Imported postings follow the same rules as the transaction service (no postings to roots, or to Assets/Liabilities/Equity groups); keep `DataService._plan` in step with `GROUP_POSTING_ROOT_NAMES` if that rule changes. Account names cannot contain `:` because it is the ledger path separator.

Several commodities are supported: conversions are written `100 USD @@ 8350 INR` (also `@` per unit), `P` lines carry prices, `commodity` lines carry decimals and finode's `name:`/`kind:` tags. A transaction's currency is the commodity its postings are priced in; an account may post only one commodity (others must go in sub-accounts); unknown codes become the user's own commodities; lots (`{}`) are still refused. When everything is in the default currency, exports have bare numbers exactly as before (no commodity labels, and CSV keeps its six columns); otherwise every amount is labeled and CSV gains `commodity`, `value` and `currency` columns.

### MCP server (AI assistants)

`app/mcp_server/` serves an MCP server at `/mcp` (Streamable HTTP, **stateless with JSON responses**, so any worker can answer any request) built on the official `mcp` SDK (2.x: `MCPServer`, not `FastMCP`). It is a plain ASGI route added in `app/main.py`, and `main.lifespan` runs the SDK's session managers (`transport.lifespan` builds fresh ones on every start, because tests start the app many times).

- **Auth (phase 1):** personal access tokens (`api_tokens`: only a sha256 of the `fin_…` secret is kept, plus a display prefix, scope `read`/`write`, last used, revoked). Users create and revoke them on `/profile/assistants`; the secret is shown once. `transport.MCPEndpoint` checks the bearer token, applies a per-token per-process rate limit (`settings.mcp_rate_limit` a minute), puts the `TokenOwner` in `context.current_owner` and hands the request to the server for that scope: read-only tokens get a server whose write tools are still listed but only refuse, telling the assistant to ask the user to allow read & write under Profile › AI assistants (`tools._refused`). Tokens only work on `/mcp`, never on the JSON API, and cannot manage tokens. - **OAuth (phase 2, for claude.ai, the Claude mobile app and other connectors):** Supabase's OAuth 2.1 server (Authentication › OAuth Server in the dashboard: enabled, authorization path `/oauth/consent` (the old `/oauth/consent` still redirects there), dynamic client registration on) registers the apps, runs the sign-in and issues their access tokens; finode never issues tokens. `/.well-known/oauth-protected-resource[/mcp]` (RFC 9728, `transport.protected_resource_metadata`) names Supabase as the authorization server, and every 401 from `/mcp` carries `resource_metadata` in `WWW-Authenticate` so clients can discover it. Supabase redirects the user to `/oauth/consent?authorization_id=…` (`routers/web/oauth.py`, `app/oauth.py` calls `/auth/v1/oauth/authorizations/{id}` and `…/consent` with the user's own session token); the user picks read-only or read & write and the choice is stored in `oauth_grants` (per user and Supabase `client_id`: Supabase has no read/write scope). On `/mcp` a JWT must verify against Supabase's keys **and** carry a `client_id` **and** match a non-revoked grant of that user, which supplies the scope; ordinary sign-in tokens (no `client_id`) are refused there, and conversely an app's token is refused by the JSON API and web UI (`auth.reject_app_token`), so it can never act as a full sign-in. Disconnecting (Profile › AI assistants › Connected apps) revokes the grant and asks Supabase to revoke the app's tokens. The login page carries a `next` only for the consent page (`web_auth.safe_next`).
- **Assistants page UX:** `/profile/assistants` lists apps and tokens together (`partials/connections.html`, with Allow changes / Make read only on each, `…/access` routes, no re-creating needed) above the two ways to connect. `partials/access.html` (`level` macro) spells out each access level and is shared by the token form and the consent page, whose buttons carry the choice (`allow-read`, `allow-write`, `deny`) instead of a radio.
- **Tools** (`tools.py`) call the same services as everything else through `context.services()` (which builds them for the token's user, like `dependencies.py`). They take account paths (`Assets:Bank:HDFC`, a unique end like `HDFC`, or other separators), resolved by `accounts.AccountIndex.find`, which explains ambiguous or unknown names. Amounts go out as strings. Service errors become `ToolError`s with the service's message. Write tools carry MCP annotations (`delete_transaction` is destructive). Assistants can create accounts but never delete or edit them. Keep `INSTRUCTIONS` in step with ledger rules.
- **Origin:** transactions record `created_via`/`updated_via` (`web`, `api`, `import`, `mcp:<token name>`), set by `TransactionService(origin=...)` (`dependencies.get_transaction_service` decides web vs api from the path). The list marks entries made or changed by an assistant; the edit page says who added and last changed it.
- The transaction form (`transaction_form.html`, `partials/txn_row.html`, `recomputeTxn` in `app.js`) is one page: a large **total**, then a **From** section (credit rows) and a **To** section (debit rows), each a list of account + amount rows. Each side starts with one row whose amount is the total, shown grey (a *suggestion*: a real value, class `suggested`, selected on focus so typing replaces it). When the user types a different amount in a row, it becomes theirs (`data-touched`) and a new row appears with the remainder suggested; rows are added until the side adds up and an unused suggestion row is dropped once nothing is left. In a multi-currency ledger the currency follows the accounts (the default currency when involved) unless the user picks one; a row whose account holds something else shows a *worth* field that carries its share of the total, and the amount is typed by hand. The form always saves through `/transactions/split` or `/{tid}/edit` (the `total` field is ignored by the server; `simple_postings` and the older `POST /transactions` and `/{tid}/edit/simple` routes remain for other callers). `services/simple.py` turns from/to/amount (and a received amount for conversions) into postings for both the web form and `record_transaction`; `ReportService.breakdown` (also `/reports/breakdown`) gives per-account income or expenses.
- Tests talk to `/mcp` over HTTP with the SDK client and an in-process ASGI transport (`tests/mcputil.py`: `make_token`, `running_app`, `mcp_client`, `payload`); tests are `async` with `pytest.mark.anyio`.

### Recurring transactions

A rule (`recurring_transactions`, `app/models/recurring.py`) is a transaction on a schedule, in one of two shapes: **simple** (from/to account, amount, and `received_amount` for conversions) or **split** (`recurring_postings` rows, like a transaction's postings, and the `currency` they balance in; the simple columns are then empty). The web form is the transaction form's rows (`partials/txn_rows.html`: total, From and To rows) and saves one account on each side as a simple rule, anything else as a split (`_parse` in `routers/web/recurring.py`); the API accepts either shape (`postings`, never mixed with from/to/amount). Both records go through `RecurringService._transaction`. Other fields: payee, note, `frequency` (daily/weekly/monthly/yearly) with `every` N, `start_date`, optional `end_date`, `next_date`, `last_date`, `active` and `last_error`. `services/schedule.py` is the pure date arithmetic (occurrence n = start plus n x every units, anchored to the start so a monthly rule on the 31st falls on the last day of short months). `RecurringService` (`services/recurring.py`) validates a rule with the same checks as recording it (`TransactionService.validate`), and `process_due()` records every occurrence on or before today through `TransactionService.create(..., recurring=(rid, date))`, with `created_via="recurring"`. Each occurrence is recorded **once**: `transactions` has a unique index on `(recurring_id, recurring_date)`, so several workers or repeated visits are safe. Due occurrences are recorded in three places: when the user opens the dashboard, transactions or recurring pages (or lists/creates via the JSON API), and by `app/recurring_runner.py`, a background loop started in `main.lifespan` in every worker (`settings.recurring_interval_minutes`, default 15, 0 turns it off; the first run waits a minute). A rule that cannot be recorded (an account that can no longer be posted to) keeps its `last_error` and retries on the next run. Pausing then resuming skips what fell due meanwhile; editing continues after `last_date`; deleting keeps the recorded transactions (their link is cleared); an account used by a rule cannot be deleted. Web: `/recurring` (list, new, edit with pause/resume/delete); JSON API: `/api/recurring`; MCP: `list_recurring`, `create_recurring`, `stop_recurring`. "Today" is the server's date.

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

### Ledger integrity

- **Database checks:** `postings` has `CHECK` constraints (`amount > 0`, `value > 0`, `side IN ('DEBIT','CREDIT')`), added by migration `a3c5e7f9b124`, which refuses to run if existing rows break them. Balance and "at least two postings" cannot be a plain check, so they live in `TransactionService._resolve`; `ReportService.trial_balance` (`/api/reports/trial-balance`, MCP `check_books`) re-checks every transaction from the stored rows and names the ones that fail. Any new code path that writes transactions must keep a test asserting `trial_balance().balanced`.
- **Posting ids are stable:** `TransactionRepository._replace_postings` updates postings in place on edit (matching first on account and side, then on account), adding or removing only what is left, so anything that refers to a posting keeps working.
- **History:** `transaction_history` is append-only (no foreign key, so a deleted transaction's trace survives it). `TransactionRepository` appends a row on create, update (skipped when nothing changed) and delete, so every path (web, API, import, recurring, MCP, balance adjustments) is covered; the row holds the transaction as it stood after the action. Read it with `TransactionService.history(tid)` / `.deleted()`; the edit page shows it. Never update or delete history rows.
- **Balances by date:** account balances count postings dated up to `as_of` (today by default, so future-dated entries do not count yet; `?as_of=` on `/api/accounts`). The register still lists every entry.

### Budget (envelope budgeting)

`services/budget.py` (`BudgetService`) gives every unit of money a job, YNAB-style, **on top of the ledger without changing it**. The only stored things are the plan (`budget_allocations`: user, month = first day, expense account, amount in the default currency; unique per month and account) and the flag `accounts.on_budget` (asset or liability accounts holding a currency; new asset accounts holding a currency default to yes, a card is opted in; the migration switched on existing asset leaves). Everything else is derived on demand, so editing the ledger can never leave it stale:

- *cash* = debits minus credits on the budget's accounts (a flagged credit card counts as money owed), up to the month's last day; flagged accounts holding another currency or with sub-accounts are left out and listed;
- *activity* of a category (an Expenses account) = postings to it in transactions that touch a budget account (spending from outside the budget is ignored), converted to the default currency at the transaction's date; unconvertible spending sets `unpriced`;
- *available* rolls month by month (`BudgetService._roll`): `max(0, last month's available) + assigned - activity`. Leftovers carry forward, but an overspent category (negative at the end of a month) starts the next month at **zero** and the deficit is taken out of *ready to assign* from then on (cash overspending, the YNAB way; credit-card purchases are treated the same). In its own month an overspent category just shows negative and ready to assign does not change yet. `overspent_last_month` reports what was deducted;
- *ready to assign* = cash minus the sum of all categories' available. Moving money between categories (`move`, limited to what is available) never changes it.

Budgeting **starts with the first month anything was assigned** (`start` in `_compute`): earlier spending is ignored, because cash is the balance now and past spending already left it (counting it as overspending would deduct it twice). Spending paid from an asset/liability account that is not part of the budget (typically a credit card never switched on) is not counted in a category; it is reported as `left_out` / `left_out_accounts` and the page offers "Add to budget" per account (`POST /budget/accounts/{aid}/include`).

Groups show the sum of their sub-categories; a group posted to directly also gets an "(other)" row. Deleting a category deletes its plan rows. Web: `/budget?month=YYYY-MM` (inline assigning swaps `partials/budget_body.html`, `/budget/move` page), the account edit page has the "Part of the budget" checkbox; JSON API: `/api/budget/`, `PUT /api/budget/categories/{aid}`, `POST /api/budget/move`; MCP: `get_budget`, `assign_to_category`, `move_budget_money`. 
**Targets** (`budget_targets`, one per category: `kind`, `amount`, `target_date`; only the wish is stored): `monthly` needs the amount assigned each month, `refill` keeps the amount available (needs amount minus what carried in), `by_date` saves the missing money evenly over the months left including this one, the whole rest once the date's month arrives (`services.budget.funding`; *carried in* = available - assigned + spent). A line reports `target`, `needed` and `underfunded` (groups sum their children); `BudgetRead.underfunded` totals them. `BudgetService.fund(month)` assigns the underfunded amounts in display order until ready to assign runs out. Web: `/budget/target` form, "Assign what is needed" button (`/budget/fund`); API: `PUT/DELETE /api/budget/categories/{aid}/target`, `POST /api/budget/fund`; MCP: `set_budget_target` (kind `none` removes), `fund_budget_targets`. Not built yet: per-card payment envelopes, assigning future months from ready to assign, weekly or yearly targets.


# Code map

Where everything lives, and where to start reading. For how the pieces fit together, read the [architecture overview](../architecture/overview.md) first.

## If you read only five files

1. `backend/finode/main.py` — what is wired together.
2. `backend/finode/dependencies.py` — how a request becomes "this user" with services attached.
3. `backend/finode/services/transaction.py` — the ledger rules (`_resolve` is the heart).
4. `backend/finode/services/budget.py` — the budget arithmetic (`_compute`, `_roll`).
5. `backend/finode/routers/views.py` with `frontend/src/features/home/Home.tsx` — one screen end to end: the view the server builds and the app that shows it.

## `backend/finode/` at the top level

| File | Job |
|---|---|
| `main.py` | creates the app, mounts routers, middleware, lifespan |
| `config.py` | `settings` (FINODE_* variables) |
| `dependencies.py` | database session, repositories and services per request (`DBSession`, `Budget`, `Reports`, …) |
| `auth/identity.py` | verifies Supabase JWTs for the JSON API and /mcp (`CurrentUser`, `require_authenticated_user`, `reject_app_token`); the app's cookie session and its write check (`require_cookie_session`, `check_app_request`) |
| `auth/session.py` | the Supabase session: password sign-in, refresh, the HttpOnly cookies and the middleware that sends refreshed ones |
| `auth/signup.py`, `auth/reset.py` | invite-only sign-up; forgotten passwords |
| `auth/flows.py` | the sign-in rules (limits, checks, messages) behind `/api/auth` |
| `auth/oauth.py` | talking to Supabase's OAuth server for the consent step |
| `feedback.py` | the Send feedback mail link |
| `clock.py` | `local_today()` and friends; never call `date.today()` |
| `currencies.py` | the currency list with decimals and signs |
| `formatting.py` | an amount in words for the few sentences the server writes (`money`, `grouping_for`, `group_digits`) |
| `framing.py` | `NoFraming`: every answer forbids being shown in another site's frame |
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
| `services/` | `account`, `cards` (a card's statement and due dates), `category`, `contact` (people with a "Due from" and a "Due to" account), `contact_errors`, `transfer`, `expense_sharing`, `income_sharing`, `splits`, `settlement`, `obligation`, `netting` (nobody is owed both ways), `contact_summary` (what is done with a person), `transaction`, `budget`, `coming_up` (entries dated ahead and rule occurrences in one list), `report`, `todo` (the to-do bell), `recurring` (+ `schedule`), `profile`, `data`, `backup`, `erase`, `api_token`, `oauth_grant`, `payee_suggestions` (the Add screen's payee chips), `transaction_rows` (how every list's rows read: title, second line, kind, the month's page, a transaction's details; shared by every view), `home` (Home's glance and first steps), `accounts_view` (the Accounts page and an account's page: kinds, each card's quiet line, the register; where the account form starts), `categories_view` (the Categories page and a category's page for a month; where the category form starts), `budget_view` (the Budgets page, a group's page and Move money: the tree, how a row reads and how far its bar runs, a group's glance and minimum), `coming_up_view` (the Coming up list by day: each row's title and second line, a day's total when it adds up), `recurring_view` (the Recurring list: each rule's two sides, amount, schedule and status), `recurring_form` (where the recurring form starts, and its rows saved as a plain rule or a split, for `/api/recurring/form`), `people_view` (the People list and a person's page: each person's quiet line, the open amounts and activity with what each is called, an entry's sheet; reversing an entry the way its kind is undone; a person added with an opening balance, all or nothing), `account_tree` (the accounts as a tree), `entry` (saving the Add screen: `/api/entries`), `entry_share` (the Add screen's Split: a bill or an income shared with people, and its starting values), `entry_form` (where the Add screen starts: blank, from an account, a repeat, an edit…), `pickers` (what the account and category pickers offer, and where a new account can go), `simple`, `validation` |
| `routers/` | the JSON API (`/api`, all of it listed in [api.md](api.md)): `accounts`, `categories`, `contacts`, `transfers`, `settlements`, `shared_expenses`, `shared_incomes`, `transactions`, `tags`, `profile`, `recurring`, `budget`, `reports`, `todo`, `data` (also Erase and Delete my account), `auth` (sign-in for the finode app), `assistants` (tokens, connected apps, consent), `entries` (the Add screen's save), `views` (one screen of the finode app per call: Home, Transactions, a transaction's details, the Add screen and its related picker, Accounts, Categories, Budgets, the to-do bell, Coming up, Recurring and the recurring form, People, a person and their entries, the opening balance form); `contact_utils` is what the people routes share (the retry header, how a refusal is answered) |
| `mcp_server/` | `transport` (auth, rate limit), `tools`, `accounts` and `categories` (name lookup), `context` |
| `ledger/` | journal format parser and writer (import and export) |

## Tests

| Where | What |
|---|---|
| `backend/tests/conftest.py` | fresh in-memory SQLite per test, dependency overrides, fixtures (`client`, `root_accounts`, `account`, `expense_account`, `svc`, …) |
| `backend/tests/books.py` | categories in tests: what used to be an Expenses or Income account is a category (`post_account`, `into`, …) |
| `backend/tests/svc.py` | `services(session, user=…, origin=…)` and `plain(model)`: call the services directly without HTTP |
| `backend/tests/guards/test_isolation.py` | person B tries to reach person A's data by every route; classifies every route |
| `backend/tests/guards/test_query_counts.py` | statement counts of the views must not grow with the data |
| `backend/tests/data/test_backup.py` | round-trips a ledger that uses every feature |
| `backend/tests/<area>/` | per-feature tests by area: `api/` (routes and views), `auth/`, `budget/` (budget, categories, recurring, reports), `data/` (backup, import, erase, limits), `ledger/`, `mcp/`, `people/`, `migrations/` (one per migration that moves data) |
| `backend/tests/guards/test_compose_routes.py` | the one address: Traefik's two routers, the service worker's denylist and the browser tests' server agree |
| `backend/tests/mcputil.py` | helpers to talk to `/mcp` in-process |
| `backend/tests/e2e/` | Playwright tests of the app in a real browser (`server.py`: the built app and the API on one address; fixtures `page`, `signed_in_page`, `api`, `books`) |

## `frontend/` (the finode app)

| Where | What |
|---|---|
| `src/app/` | the router (`router.tsx`), the session and today (`session.tsx`), the layout (tab bar, sidebar), where the bar's "+" starts an entry (`newEntry.tsx`: an account's or a category's page points it there), toasts, the offline banner |
| `src/api/` | `schema.d.ts` (generated from `openapi.json`, which `backend/scripts/export_openapi.py` writes), the typed client (`client.ts`), the query client, `useApi()`, `views.ts` (`VIEWS`, the key every view's cached answer starts with), `messages.ts` (what a person reads when a call fails) |
| `src/components/` | the shared parts: `Icon` (`icons.json`), `Row`, `Tile`, `Sheet` (a bottom sheet that sits above the soft keyboard), `Chips`, `AmountField`, `MonthPill`, `EmptyState`, `Figure` (a large amount with its currency), `CalcInfo` (the "i" beside a headline figure and the sum behind it), `Menu` (the "…" menu and the "i" note of an account's or a category's page), `Page.module.css` (the title row, hero, back link, section heads, empty state, add row), `Rows.module.css` (the named rows with a figure in one tile, the switcher bar, the way back beside a month pill), `Forms.module.css` (the account, group, category, person and opening balance forms), `TestNotice`; `lines/`: the Add screen's rows, shared with the recurring form (`Lines` with `useLines` and `linesBody`; the `Picker`, `RowSettings` and `QuickAdd` sheets; `DateChip`, `PayeeField`, `NoteAndTags`; `kinds.ts`, `rows.ts`; `Form.module.css`, the form's look) |
| `src/features/` | one folder per area: `auth/` (sign in, sign up, forgotten password, reset, and their shared parts); `home/`; `transactions/` (the list, the details sheet, the Transactions page and its Filter sheet, and `RegisterList`: an account's or a category's entries); `accounts/` (the Accounts page, an account's or a group's page with its bill, the account and group forms); `categories/` (the Categories page, a category's page, the category form); `budget/` (the Budgets page with its category sheet, a group's page with its own budget, Move money, Coming up); `entry/` (Add and Edit around the shared rows of `components/lines`: related, the Split with people (`share.ts`, `ShareEditor`, `SharePreview`, `PeopleSheet`)); `todo/` (the to-do bell in the top bar and the sidebar, and its sheet with each fix); `tags/` (the Tags page and a tag's sheet); `recurring/` (the Recurring list and the recurring form with Pause, Skip, Resume and Delete); `people/` (the People list, a person's page with its entry sheet and menu, the person form and the opening balance form); `settings/` (Settings, Your data with the import and restore previews, AI assistants with the token form, its setup and `CopyButton`); `consent/` (the consent screen of "Sign in with finode") |
| `src/lib/` | `amount.ts` (typing amounts), `money.ts` (writing them), `split.ts` (what is left to allocate on a side: the app's only arithmetic on money, with big.js), `dates.ts` (writing days), `safeNext.ts`, `theme.ts` (the light or dark look kept in this browser) |
| `src/styles/` | `tokens.css` (every colour, light and dark; `tokens.test.ts` holds the dark blocks equal and the greys readable), `base.css`, the font |
| `scripts/` | `check-api-types.mjs`, `css-module-types.mjs` (exact types for each CSS module) |

## Scripts and ops files

| File | Job |
|---|---|
| `scripts/db-backup.sh` | nightly `pg_dump` in the `backup` service |
| `scripts/browser-tests.sh` | runs the browser tests in Playwright's container |
| `scripts/check-web-image.sh` | builds the app's image and checks what it serves (deep links, caching, 404s, headers, no address of ours built in, no secrets) |
| `backend/Dockerfile`, `compose.yaml` | the API's image and the `migrate`, `app`, `web`, `backup` services (Traefik: the API's paths to `app`, the rest of the address to `web`) |
| `frontend/Dockerfile`, `frontend/nginx.conf` | the app's image (the `web` service): built with Node from `frontend/` alone, served by nginx |
| `backend/migrations/` | Alembic (`versions/` holds one file per schema change) |

## Finding your way by task

| I want to… | Start at |
|---|---|
| change a ledger rule | `services/transaction.py::_resolve`, then add a test and keep `trial_balance().balanced` |
| add or change what a category is, or how a line gets one | `services/category.py`, `repositories/category.py`, `TransactionRepository._line_categories`, `TransactionService._check_categories` |
| change the budget arithmetic | `services/budget.py::_compute` / `_roll`, `backend/tests/budget/test_budget.py` |
| add a screen | a view in `routers/views.py` built by a `services/*_view.py`, classified in `backend/tests/guards/test_isolation.py` and held in `backend/tests/guards/test_query_counts.py`; `npm run gen:api`; a route in `frontend/src/app/router.tsx` and a folder in `frontend/src/features/` |
| add an MCP tool | `mcp_server/tools.py` (add to `READ_TOOLS`, `WRITE_TOOLS` or `MANAGE_TOOLS`), update `INSTRUCTIONS` if a rule changed; a read tool also gets a call in `backend/tests/mcp/test_mcp_smoke.py` |
| add a setting for people | a column on `profiles`, a migration, a field on `ProfileUpdate`, a row on `features/settings/SettingsPage.tsx` |
| add a table | model, migration, backup + `backend/tests/data/test_backup.py`; it has a `user_id` column so erasing finds it |

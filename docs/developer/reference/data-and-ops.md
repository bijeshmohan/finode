# Data and operations

Import, export, backup and restore, limits, erasing, the isolation audit, passwords, automatic backups and Docker. Dates in headings are when a decision was made. Moved out of CLAUDE.md on 2026-11-07; the rules summary is in `AGENTS.md`.

## Import and export

`app/ledger/` reads and writes the plain-text ledger journal format (`parse.py` / `write.py`, no dependency); `app/services/data.py` (`DataService`) maps it to accounts and transactions and also writes a CSV. Exports are always allowed (`/api/export`, `/export`). Import is **only allowed while the user has no transactions**, previews first (`?dry_run=true`, `/import/preview`) and is all-or-nothing in one database transaction. Debit is positive, credit negative; `Assets:Bank:HDFC` maps to the account tree, root names accept aliases (`Asset`, `Revenue`...), `Equity:Opening Balances` maps to the system account. Unsupported input (conversions between currencies, prices, virtual postings, automated/periodic transactions, `include`, balance assignments) is an error with its line number, never silently dropped. Imported postings follow the same rules as the transaction service (no postings to roots, or to Assets/Liabilities/Equity groups); keep `DataService._plan` in step with `GROUP_POSTING_ROOT_NAMES` if that rule changes. Account names cannot contain `:` because it is the ledger path separator.

finode keeps one currency, so the parser reads an amount with an optional label (`INR`, `₹`, `$`) but does not tell labels apart: `DataService._plan` accepts bare amounts and the person's own currency code or sign and refuses any other label with the line number and a pointer to Settings (change the currency first). Conversions (`@` / `@@`) and `P` price lines are errors; `commodity` directives are accepted and ignored. Exports have bare numbers and CSV has seven columns (`date, payee, note, tags, account, debit, credit`).

## Full backup and restore

`services/backup.py` (`BackupService`) writes everything a user recorded as one JSON file (`GET /api/backup`, `/backup`; format `finode-backup`, `version` 6, older files are still read, models in `schemas/backup.py`): settings, accounts (with `on_budget`, `closed_on`), transactions with their postings and origin, recurring rules (simple and split), contacts (with the ids of their two accounts) and the budget plan. Left out on purpose: access tokens and connected apps (secrets; set them up again). Writing a backup reads each kind of row once (people's shares and payments in two reads, not one per bill), and restore and import write the entries together (`TransactionRepository.create_many`). `restore()` (`POST /api/restore`, `?dry_run=true`, `/restore/preview`, `/restore`) rebuilds a ledger from it, **only into an empty one** (no accounts of the user's own, no transactions, recurring rules or budget), all or nothing in one database transaction, validating the file first (the currency is known, accounts exist, no cycles, every transaction balances) and creating everything with **new ids** (the system roots and Opening Balances map onto the user's own). A version 1 file (from before one currency) restores when everything in it is in the profile's currency; one with assets of its own, prices, another currency or a conversion is refused with a message. The legacy fields (`commodity`, `value`, `currency`, `received_amount`, `commodities`, `prices`) are read but never written (`Field(exclude=True)` in `schemas/backup.py`). `tests/test_backup.py` round-trips a ledger that uses every feature; when you add a model or an account/budget flag, add it to the backup and to that test, or it will silently be missing from backups.

## Running a test with invited people

`FINODE_TEST_NOTICE=true` shows the notice (`frontend/src/components/TestNotice.tsx`, the wording agreed with the owner: a person runs this, the data is technically reachable but not looked at, data may be reset, no financial advice) on the sign-up screen, where ticking the box is required (`accept`), and under Settings › About this test (`/api/auth/options` says whether it is on). `FINODE_FEEDBACK_EMAIL` adds Settings › Send feedback, a `mailto:` link with the build version (`app/version.py`, from pyproject) and no personal data (`feedback_url` in `/api/auth/session`). Home's "Get started" steps point only at the import; the currency and the backup live in Settings (2026-11-05). Changing the notice's wording means editing that one component.

## Limits and rate limiting

Per person (`settings.max_*`, 0 = no limit; checked by `limits.ensure_room`, which raises `LimitReached`, a `ValueError` with a message that says what to do): accounts, transactions in total, new transactions a day (not counting recurring rules or imports), postings in one transaction, and the size of a restore upload (imports stay at 5 MB). Imports and restores check them up front and report "too big for your limits" before anything is saved; services enforce them for everything else, so any new way of creating accounts or transactions must go through a service or call `ensure_room` itself. Sign-in and sign-up attempts are slowed per address (failed sign-ins also per email, `FINODE_LOGIN_ATTEMPTS`, `FINODE_SIGNUP_ATTEMPTS` in a `FINODE_ATTEMPT_WINDOW_MINUTES` window) by the in-memory `ratelimit.attempts` (per process, answers 429 with `Retry-After`). The client address comes from the proxy headers (`fastapi run --proxy-headers`, `FORWARDED_ALLOW_IPS` in compose); if that stopped working everybody would share one address, so keep it. Tests clear the counters automatically (`tests/conftest.py`).

## Erasing and leaving

Settings › Your data has two destructive actions (the person types their email to confirm; `confirm_word`): **Erase my books** (`POST /api/erase`) and **Delete my account** (`POST /api/delete-account`, only offered when `settings.can_delete_logins`, that is when the Supabase service key is configured). `services/erase.py` (`EraseService`) walks **every table that has a `user_id` column**, children first (`SQLModel.metadata.sorted_tables`), so a new table is erased without anyone remembering it; clearing the books keeps `profiles`, `api_tokens` and `oauth_grants` (what belongs to the person, not the books), deleting everything keeps nothing. Deleting the account erases everything first, then removes the Supabase login (`signup.delete_user`); if that call fails the books are already gone and the person is told to retry. Deleting the profile row also frees a place under `FINODE_MAX_USERS`. Both take `confirm` in the body (`GET /api/data-options` gives `confirm_word`) and the app's cookie session only (`require_cookie_session`), never a bearer token. These routes are classified `OWN_DATA` in the isolation audit.

## Isolation audit

`tests/test_isolation.py` is the guard for multi-user use: person A has a ledger that uses every feature, person B signs in and tries to reach it by every route that takes an id (all must answer 400/403/404 and nothing of A's may come back, A's books unchanged afterwards), by every list and page (only B's data), by naming A's accounts, categories, recurring rules or private assets inside B's own requests, through B's assistant token, and without any sign-in. Each refusal must come from a real route (a bare `{"detail":"Not Found"}` fails the audit: it would only prove the route is gone). `test_every_route_is_covered` fails when a route is added that is not classified there (`PUBLIC`, `LISTS` or `REFERENCES`; routes with an id are swept automatically), so a new endpoint cannot ship without deciding what it does with other people's data. Every query must be filtered by the user (`self.uid` in repositories); the audit was checked by removing that filter from four repositories, and it failed each time.

The interactive API docs (`/docs`, `/redoc`, `/openapi.json`) are off unless `FINODE_API_DOCS=true`.

## Forgotten passwords

`app/reset.py` and `POST /api/auth/forgot`, `POST /api/auth/reset` (`routers/auth.py`), on only when `FINODE_PASSWORD_RESET=true` (`settings.reset_enabled`; 404 otherwise, and the sign-in screen shows no link). Forgot asks Supabase (`/auth/v1/recover`, anon key) to email a link and always gives the same answer; the email template in Supabase must link to `{{ .SiteURL }}/reset?token_hash={{ .TokenHash }}`, the app's Reset screen. Opening the link sends nothing (scanners open links); saving the new password verifies the token (`/auth/v1/verify`, type recovery), sets the password (`PUT /auth/v1/user`) and signs the person in. Attempts are limited by address and email (`FINODE_RESET_ATTEMPTS`). The routes are `PUBLIC` in the isolation audit.

## Automatic backups

`scripts/db-backup.sh` runs in the `backup` compose service (postgres image): nightly `pg_dump --schema=public` gzipped into `./backups`, verified (gzip test and the ledger tables present) before it replaces a `.partial` file, old files removed after `BACKUP_KEEP_DAYS`. Restoring was rehearsed into a scratch Postgres (row counts equal to production); the dump references `auth.users`, so a restore needs Supabase or a stand-in table. The copy off the machine is not automated yet.

## Docker

`Dockerfile` is multi-stage: uv resolves `uv.lock` into `/opt/venv`, and the runtime stage copies only that venv plus `app/`, `migrations/`, `alembic.ini` and `pyproject.toml` (needed for the `[tool.fastapi]` entrypoint). If a new top-level file is needed at runtime, add it to the `COPY` lines and check `.dockerignore`. `compose.yaml` targets an existing Traefik on an external network; production uses Supabase Postgres, so there is no database service. Uvicorn reads `WEB_CONCURRENCY` and `FORWARDED_ALLOW_IPS` from the environment.

**One address, two containers.** The app and the API answer on `APP_DOMAIN`. Traefik has two routers on that host
(`compose.yaml`): the `app` container (the API) takes `/api`, `/mcp`, `/.well-known` and the API docs (`/docs`,
`/redoc`, `/openapi.json`) at priority 100, and the `web` container takes every other path at priority 1. A new API path
outside those must be added there, to the service worker's `navigateFallbackDenylist` (`frontend/vite.config.ts`) and
to `tests/browser/server.py`; `tests/test_compose_routes.py` holds the three together. The session cookies are
host-only on `APP_DOMAIN` with `SameSite=Lax`. A cookie write is accepted only with `X-Finode: 1` and an `Origin` equal
to the address the request came in on (`auth.check_app_request`: the scheme and host uvicorn sees through
`--proxy-headers`); there is no CORS. The moment the app and the API move to separate machines, one proxy in front of
both keeps this single address.

The app's image is `frontend/Dockerfile` (the `web` service), built from `frontend/` alone (`frontend/.dockerignore`):
Node builds the app, which names no address (it calls `/api` on its own origin), and nginx (`frontend/nginx.conf`)
serves it. nginx answers every app address with `index.html` and sends it, the service worker and the manifest with
`Cache-Control: no-cache`. Hashed `/assets/*` are kept a year (`immutable`). A missing asset is a 404, never the page,
so a tab open across a redeploy is not handed HTML as a script. Every answer carries `X-Content-Type-Options: nosniff`,
`Referrer-Policy: same-origin` and the anti-framing headers below. A script at the top (`sw.js`, `workbox-<hash>.js`)
is a 404 when missing, as under `/assets`; compressed answers carry `Vary: Accept-Encoding`. The image holds no
settings and no secrets. It is `nginxinc/nginx-unprivileged`, so nginx runs as uid 101 on port 8080. Both images are
pinned by tag and digest, and `HEALTHCHECK` asks for `/`. compose.yaml runs the container `read_only` with `/tmp` in
memory, `cap_drop: [ALL]` and `no-new-privileges`. `scripts/check-web-image.sh` runs it the same way and checks all of
this, and that the bundle names no host of ours.

No other site may show finode inside a frame (clickjacking). Every answer, from the API (`app/framing.py`, pure ASGI so
`/mcp`'s stream passes untouched) and from the `web` image, carries `X-Frame-Options: DENY` and
`Content-Security-Policy: frame-ancestors 'none'`. `tests/test_framing.py` guards the API; the image check guards
nginx.

The app's service worker (vite-plugin-pwa, `registerType: "prompt"`) caches only the app's own files and leaves every API path to the network. After a redeploy
it fetches the new version in the background. The new version is put in only once the page is hidden
(`src/app/update.ts`): the page then reloads, so an open screen is never reloaded under someone typing.

Tests live in `tests/`. `tests/conftest.py` builds a fresh in-memory SQLite engine per test and overrides `get_db_session`, so tests are independent of `finode.db` and of Alembic. The session commits for real, so a service that rolls back only undoes its own unfinished work. The migrations are tested on SQLite (the ones before `f4b6d8a0c2e5` stop at `e2a4c6e8f1b3`, because that one cannot be undone: `tests/test_migration_single_currency.py`); the single-currency one was also rehearsed on Postgres 16 with a copy of the production data. `migrations/env.py` reads `alembic.ini`'s logging with `disable_existing_loggers=False`: a migration run in the same process as the app (the tests, a script) must not silence the app's own loggers.

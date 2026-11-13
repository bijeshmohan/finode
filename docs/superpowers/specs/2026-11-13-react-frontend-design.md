# React frontend: design

Status: approved in conversation on 2026-11-13, awaiting review of this written spec.
Branch: `feature/react-frontend` (all work stays here until the switch; `develop` is merged in from time to time).

## Goal

Replace the Jinja2/htmx web UI with a single-page app built on the industry-standard stack, without adding
technical debt.

- **App feel, online only**: instant screen changes, no page reloads, installable to the phone home screen.
  No offline data: with no connection the app says so.
- **Same look**: today's tokens, rows, tiles, sheets and chips, rebuilt as React components. A redesign, if
  any, comes later on top.
- **One UI afterwards**: once the React app does everything today's pages do, the Jinja2 pages, `app.js`,
  the web routers and their tests are deleted.

Out of scope: offline entry, a visual redesign, moving the backend to FastAPI Cloud (a separate change), any
new feature (the feature freeze rules apply).

## Architecture

```
browser ──► app.<domain>   static files (React build) on a static host / CDN
        └─► api.<domain>   FastAPI: /api, /mcp, OAuth endpoints (no pages after the switch)
```

- The frontend lives in `frontend/` in this repo (npm, Node LTS, its own `package-lock.json`).
- `npm ci && npm run build` produces `frontend/dist`, uploaded to the static host. The API address is set at
  build time (`VITE_API_URL`). The Dockerfile stays Python-only.
- Development: `npm run dev` runs Vite and forwards `/api` to `uv run fastapi dev`, so no CORS locally.

### Sign-in

The session stays in HttpOnly cookies; the page's JavaScript never holds a token.

- `api.<domain>` sets `finode_access` / `finode_refresh`: HttpOnly, Secure, `SameSite=Lax`, host-only.
  `app.` and `api.` of one domain are the same site, so the browser sends them with the app's requests
  (and Safari does not block them).
- New `/api/auth/*` JSON endpoints wrap today's `web_auth.py` and `signup.py`: sign in, sign up, forgotten
  password, reset, refresh, sign out, with the existing rate limiter.
- `require_authenticated_user` accepts the access cookie as well as a bearer header; an expired access token
  is refreshed from the refresh cookie as the web UI does today.
- CORS: only `FINODE_FRONTEND_ORIGIN` (`https://app.<domain>`), credentials allowed.
- Forgery protection for cookie-authenticated requests that change anything: the `X-Finode: 1` header is
  required and `Origin` must equal `FINODE_FRONTEND_ORIGIN`. Bearer-authenticated requests skip both.
- Password-reset mail links and Supabase's OAuth consent URL point to `app.<domain>`.
- Connected-app tokens stay refused outside `/mcp`.

### Gaps in the API, filled first

| Gap | Note |
|---|---|
| `/api/auth/*` | as above |
| Server "today" | today in `FINODE_TIMEZONE`, so the browser never uses the phone's clock |
| Assistant tokens and connected apps | cookie session only, never a bearer token |
| OAuth consent screen | the data and the allow/deny action for `app.<domain>/oauth/consent` |
| Erase and Delete my account | cookie session only |
| Add screen payee chips | |

Each gets its route, API parity test, isolation classification and a row in `docs/developer/api.md`.
Where a React screen would need several calls, the cost is measured and one combined endpoint is added when it
is cheaper (Home is the likely one); query-count tests cover these endpoints.

## Inside the frontend

```
frontend/src/
  app/         router, providers, layout (tab bar, + button, toasts)
  api/         generated types, typed client, query keys
  features/    home, add, transactions, accounts, categories, budget, people,
               recurring, tags, todo, settings, assistants, auth
  components/  Row, Tile, Sheet, Chips, AmountField, MonthPill, Picker, EmptyState, Icon
  lib/         amount, money format, dates
  styles/      tokens.css, base.css
```

A part used by two features moves to `components/`.

- **Types**: a script writes FastAPI's OpenAPI schema to `frontend/openapi.json`; `openapi-typescript`
  generates the types. A test fails when the file is out of date.
- **Client**: `openapi-fetch`; always sends the cookie (`credentials: "include"`) and `X-Finode: 1`.
- **Server data**: TanStack Query. Cached screens show at once and refresh in the background. After a save,
  the queries it can affect are invalidated. No optimistic updates to money: buttons show progress instead.
- **401**: go to sign-in, then back to the same page.
- **Routing**: React Router, one lazily loaded chunk per page. Month, Transactions filter and open sheet live
  in the URL.
- **Forms**: React Hook Form with Zod for quick checks; the server's 400/422 messages are shown on their field.
- **Money**: amounts stay strings end to end, never JavaScript numbers. Totals come from the server; the only
  client arithmetic (the Add screen's split preview) uses `big.js`. `cleanAmount` / `tidyAmount` /
  `groupAmount` move to `lib/amount.ts` with unit tests; Indian grouping for INR only; places by currency.
- **Dates**: today comes from the server.
- **Look**: tokens copied as they are into `tokens.css` (both dark blocks); component styles in CSS Modules
  taken from `style.css`. No Tailwind, no component kit. Contrast, dark-token parity and reduced-motion checks
  move with them.
- **Installable**: web app manifest and a minimal service worker (`vite-plugin-pwa`) caching only the app's
  own files.

## Tooling and tests

- TypeScript strict; no `any` without a reason in a comment.
- ESLint (strict TypeScript rules, React hooks, `jsx-a11y`) and Prettier (width 120).
- Exact dependency versions, `package-lock.json`, `npm audit`.
- `make check` and `make hooks` also run the frontend's lint, type check, unit tests and build.
- Unit tests: Vitest and Testing Library for `lib/` and the shared components.
- Browser tests: Python `pytest-playwright` as today, reusing `tests/books.py` and the fixtures, against the
  built React app and FastAPI on SQLite, on Chromium and WebKit (`scripts/browser-tests.sh`). Each of today's
  189 browser tests is ported with its page.
- Backend: the usual tests per endpoint, plus sign-in tests: no `X-Finode` header refused, wrong `Origin`
  refused, a bearer token cannot mint assistant tokens or erase, a connected-app token is refused outside
  `/mcp`. Existing guard tests are kept as they are.

## Build order

| Step | What | Done when |
|---|---|---|
| 1 | Backend gaps (sign-in, today, tokens, consent, erase, payee chips) | backend tests green; today's pages untouched and passing |
| 2 | Frontend foundation: scaffold, tooling, types, client, tokens, layout, shared components, helpers | `make check` green; components unit-tested |
| 3 | Sign in, sign up, forgotten password, reset | flows work in the browser |
| 4 | Home, Add, Transactions, transaction detail | their browser tests ported |
| 5 | Accounts and Categories | as above |
| 6 | Budgets | as above |
| 7 | People, Recurring, Tags, to-do bell, Coming up | as above |
| 8 | Settings, data (import/export/backup/restore), assistants, consent | as above |
| 9 | Side by side: the React app on `app.<domain>`; the owner uses it, old pages stay on the current domain | the owner is happy with it |
| 10 | The switch: delete the Jinja2 pages, `app.js`, web routers and their tests; update `AGENTS.md` (drop "No JavaScript build step", add the frontend rules) and `docs/`; redirect the old domain | all checks green, then "Merge and deploy" |

Nothing reaches `develop` before step 10.

## Open decisions

- How step 9 reaches a backend that has the step 1 changes, given that nothing reaches `develop` before step 10:
  deploy the branch's backend to production for the trial (step 1 leaves today's pages working), or run the
  trial against a staging copy with its own database. The owner decides when step 9 comes.
- The subdomain names.
- The static host for `app.<domain>` (Cloudflare Pages fits, since Cloudflare is already in front).
- Whether the backend moves to FastAPI Cloud at the same time (recommended: separately).

# React frontend, step 2: the frontend foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `frontend/` React app that builds, is checked as strictly as the Python side, talks to `/api` with typed
calls, shows the signed-in shell (tab bar, sidebar, toasts, offline banner) in today's look, and has the shared
components and the money and date helpers the pages in steps 3–8 are built from.

**Architecture:** Vite + React + TypeScript (strict) in `frontend/`, served as static files. Types come from FastAPI's
OpenAPI schema; `openapi-fetch` makes the calls with the session cookie and `X-Finode: 1`; TanStack Query holds server
data; React Router picks the screen. While both UIs live, the colour tokens, the font and the icons have **one
source**: the tokens move to `app/static/tokens.css` (linked by `base.html`, imported by the React app), the font is
imported from `app/static/fonts/`, and a test holds the React icons equal to `partials/icons.html`. Number and date
formatting have a shared case file checked by both pytest and Vitest, so the two UIs cannot disagree.

**Tech Stack:** Node (current Active LTS), npm, Vite, React, TypeScript, React Router, TanStack Query,
openapi-typescript, openapi-fetch, ESLint (typescript-eslint strict, react-hooks, jsx-a11y), Prettier, Vitest,
Testing Library, jsdom, vite-plugin-pwa.

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md` (step 2 of the build order; sections "Inside
the frontend" and "Tooling and tests").

## Global Constraints

- Branch `feature/react-frontend` only; nothing reaches `develop`.
- Every dependency is installed with `--save-exact` (exact versions in `package.json`) and locked in
  `frontend/package-lock.json`. Pick the current stable version of each at install time; record Node's version in
  `frontend/.nvmrc` and `"engines"`.
- TypeScript `strict: true`, `noUncheckedIndexedAccess: true`, `exactOptionalPropertyTypes: true`; no `any` without an
  `// eslint-disable-next-line` that gives the reason.
- Prettier `printWidth: 120`. ESLint must pass with zero warnings (`--max-warnings 0`).
- **Money:** amounts are strings end to end, never `Number`. No client-side arithmetic in this step.
- **Dates:** "today" always comes from `/api/auth/session`, never `new Date()` for a calendar day.
- Colours only from the tokens; text inputs at least 16px; reduced motion respected.
- Today's pages keep working: the token move must leave `style.css` rendering exactly as before (the browser tests
  are the proof).
- No new dependency in `pyproject.toml`.
- `make` is not installed on the owner's machine: where a step says `make check`, run what the target runs
  (`uv run ruff check app tests migrations scripts`, `uv run ruff format --check …`, `uv run pyrefly check`,
  `uv run pytest -q`, and from Task 1 on `npm --prefix frontend run check`).
- Deferred to step 4 (the Add screen, the first page that needs them), as YAGNI: the account/category `Picker`
  component and `big.js` for the split preview.

## Review Focus

1. A negative amount and an amount with more than two decimals (`-1234.5`, `0.01250000`, `100.00000000`): the React
   formatter gives exactly what the Jinja `money` filter gives (`−1,234.50`, `0.0125`, `100.00`; U+2212 minus). Pinned
   by the shared case file in Task 4.
2. A currency with no decimals (JPY, places 0) typed into an AmountField: no decimal point can be typed and tidying
   adds none. Test in Task 4 and Task 6.
3. A date in another year, and today's date when the phone's clock is in another time zone: the label uses the
   server's `today`, not the device's. Test in Task 4.
4. The session call answers 401 (signed out) or the network is down: the shell goes to `/sign-in` for 401 and shows
   the offline banner (not the sign-in screen) when `fetch` fails. Tests in Task 5.
5. `openapi.json` out of date after a backend change: a test fails and names the command that refreshes it. Test in
   Task 3.

---

### Task 1: Node, the scaffold and the checks

**Files:**
- Create: `frontend/package.json`, `frontend/package-lock.json`, `frontend/.nvmrc`, `frontend/tsconfig.json`,
  `frontend/vite.config.ts`, `frontend/eslint.config.js`, `frontend/.prettierrc.json`, `frontend/index.html`,
  `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/App.test.tsx`, `frontend/src/test/setup.ts`
- Modify: `.gitignore` (`frontend/node_modules/`, `frontend/dist/`), `Makefile` (`frontend-check`, and `check` runs
  it), `.github/workflows/ci.yml` (job `frontend`: `astral-sh/setup-uv` and `uv sync --frozen` (the schema check runs
  Python), `actions/setup-node` with `node-version-file: frontend/.nvmrc`, `npm ci`, `npm run check`, in `frontend/`), `.github/dependabot.yml` (`npm` in `/frontend`, weekly),
  `.pre-commit-config.yaml` (local hook `frontend-lint`: `npm --prefix frontend run lint`, `files: ^frontend/`,
  `pass_filenames: false`)

**Interfaces:**
- Produces npm scripts: `dev` (Vite, proxy `/api` → `http://localhost:8000`), `build`, `lint`
  (`eslint . --max-warnings 0 && prettier --check .`), `typecheck` (`tsc --noEmit`), `test` (`vitest run`), `check`
  (`npm run lint && npm run typecheck && npm run test && npm run build`).
- `vite.config.ts`: `server.fs.allow: [".", "../app/static"]`; alias `@static` → `../app/static`; Vitest with
  `environment: "jsdom"`, `setupFiles: ["src/test/setup.ts"]` (Testing Library's jest-dom matchers).

- [ ] **Step 1:** Install Node's current Active LTS for the user only (no `sudo`): the official Linux x64 tarball
  from nodejs.org into `~/.local/opt/node-<version>`, with `node`, `npm`, `npx` linked into `~/.local/bin`.
  Verify: `node --version` prints the version written to `frontend/.nvmrc`.
- [ ] **Step 2: Write the failing test** `frontend/src/App.test.tsx`: `renders the app name` — render `<App />`,
  expect `screen.getByText("finode")` to be in the document.
- [ ] **Step 3:** Scaffold the files above (React + TypeScript; no template leftovers: no counter, no logos, no
  default CSS). Run `npm run test` — expected: FAIL until `App` renders "finode"; then implement `App` returning
  `<h1>finode</h1>` and run again — expected: PASS.
- [ ] **Step 4:** Run `npm run check` — expected: lint, types, 1 test and the build all pass.
- [ ] **Step 5:** Run `make check` — expected: Python checks and `frontend-check` pass.
- [ ] **Step 6:** Commit: `Frontend scaffold: Vite, React, strict TypeScript, ESLint, Prettier, Vitest`.

### Task 2: One source for tokens and the font

**Files:**
- Create: `app/static/tokens.css` (the "Design tokens" block of `style.css`, from `/* ---------- Design tokens` up
  to `/* ---------- Base`, moved unchanged), `frontend/src/styles/base.css`, `frontend/src/styles/base.test.ts`
- Modify: `app/static/style.css` (the block removed), `app/templates/base.html` (link `tokens.css` before
  `style.css` with `asset_url`), `tests/test_contrast.py`, `tests/test_web_layout.py`
  (`test_dark_theme_defines_the_same_tokens_in_both_dark_blocks`), any other test that reads tokens from
  `style.css` (`grep -l "style.css" tests/`), `frontend/src/main.tsx`

**Interfaces:**
- `frontend/src/main.tsx` imports `@static/tokens.css` then `./styles/base.css`.
- `base.css` holds only what every page needs: the `@font-face` for Anek Latin from
  `@static/fonts/anek-latin.woff2`, `body` font, background `var(--bg)`, colour `var(--text)`, inputs at 16px, and
  the `prefers-reduced-motion` rule, copied from `style.css`'s Base section.

- [ ] **Step 1: Write the failing test** `tests/test_web_layout.py::test_the_tokens_live_in_one_file`:
  `tokens.css` contains `:root {`, `@media (prefers-color-scheme: dark)` and `:root[data-theme="dark"]`, and
  `style.css` contains none of `--bg:`, `--surface:`, `--accent:`; the home page's HTML links `tokens.css` before
  `style.css`.
- [ ] **Step 2:** Run `uv run pytest tests/test_web_layout.py -q` — expected: FAIL.
- [ ] **Step 3:** Move the block; point the guard tests at `tokens.css`; link it in `base.html`.
- [ ] **Step 4:** Run `uv run pytest -q` — expected: all pass. Run `scripts/browser-tests.sh` — expected: 189 pass
  (today's pages look the same).
- [ ] **Step 5: Write the failing test** `frontend/src/styles/base.test.ts`: `base.css` declares the Anek Latin
  `@font-face` and contains `prefers-reduced-motion` (read the file with `node:fs`).
- [ ] **Step 6:** Write `base.css`, import both in `main.tsx`; `npm run check` — expected: PASS.
- [ ] **Step 7:** Commit: `Colour tokens in one file, shared by the web pages and the React app`.

### Task 3: API types and the typed client

**Files:**
- Create: `scripts/export_openapi.py`, `frontend/openapi.json`, `frontend/src/api/schema.d.ts` (generated),
  `frontend/src/api/client.ts`, `frontend/src/api/client.test.ts`, `frontend/src/api/queryClient.ts`,
  `tests/test_openapi_file.py`
- Modify: `frontend/package.json` (scripts `gen:api` and `gen:api:check`; `check` runs `gen:api:check` first)

**Interfaces:**
- `scripts/export_openapi.py`: `def schema() -> dict` returning `app.openapi()`; run as a script it writes it to
  `frontend/openapi.json` with `json.dumps(..., indent=2, sort_keys=True) + "\n"`.
- `gen:api`: `uv run python scripts/export_openapi.py && openapi-typescript openapi.json -o src/api/schema.d.ts`.
  `gen:api:check`: generate into a temp file and fail (exit 1, message "run npm run gen:api") if it differs from
  `src/api/schema.d.ts`.
- `client.ts`:
  - `export const API_HEADER = { "X-Finode": "1" } as const;`
  - `export function makeClient(options: { baseUrl: string; fetch?: typeof fetch; onUnauthorized: () => void }): Client<paths>`
    — `createClient<paths>({ baseUrl, credentials: "include", headers: API_HEADER, fetch })` plus a middleware that
    calls `onUnauthorized()` on a 401 response.
  - `export const api = makeClient({ baseUrl: import.meta.env.VITE_API_URL ?? "", onUnauthorized: goToSignIn })`
    where `goToSignIn` sends the browser to `/sign-in?next=<current path>`.
  - `export class ApiError extends Error { constructor(readonly status: number, readonly detail: unknown) }` and
    `export async function data<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T>`
    that returns `data` or throws `ApiError` (for TanStack Query's `queryFn`).
- `queryClient.ts`: `export const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000,
  retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2 } } })`.

- [ ] **Step 1: Write the failing tests:**
  - `tests/test_openapi_file.py::test_the_frontend_schema_is_up_to_date`: `json.loads(Path("frontend/openapi.json")
    .read_text()) == export_openapi.schema()`, message `"run: npm --prefix frontend run gen:api"`.
  - `frontend/src/api/client.test.ts` (a stub `fetch` that records the request and answers as told):
    - `sends the cookie and the app header`: `GET /api/profile/` → request `credentials === "include"` and header
      `X-Finode` is `"1"`.
    - `a 401 calls onUnauthorized`.
    - `data() throws ApiError with the status and detail`: a 400 `{"detail": "nope"}` → `ApiError` status 400,
      detail `"nope"`.
    - `the query client does not retry a 4xx`: `retry(0, new ApiError(404, ...)) === false`, and
      `retry(0, new ApiError(503, ...)) === true`.
- [ ] **Step 2:** Run `uv run pytest tests/test_openapi_file.py -q` and `npm run test` — expected: FAIL.
- [ ] **Step 3:** Implement; run `npm run gen:api`; commit the generated `openapi.json` and `schema.d.ts`.
- [ ] **Step 4:** Run `uv run pytest -q` and `npm run check` — expected: PASS.
- [ ] **Step 5:** Commit: `Typed API client from FastAPI's schema`.

### Task 4: Money, amounts and dates (one case file for both UIs)

**Files:**
- Create: `tests/format_cases.json`, `tests/test_format_cases.py`, `frontend/src/lib/amount.ts`,
  `frontend/src/lib/money.ts`, `frontend/src/lib/dates.ts` and a `*.test.ts` beside each

**Interfaces:**
- `amount.ts` (ported from `app/static/app.js`, with places and grouping as arguments instead of `<html>` data):
  `type Grouping = "indian" | "western"`; `cleanAmount(text: string, places: number): string`;
  `tidyAmount(text: string, places: number): string`; `groupDigits(whole: string, grouping: Grouping): string`;
  `groupAmount(text: string, grouping: Grouping): string`; `groupingFor(currency: string | null): Grouping` (INR →
  indian).
- `money.ts`: `formatMoney(value: string, grouping: Grouping): string` — the Jinja `money` filter: drop padding
  zeros beyond two decimals, at least two decimals, U+2212 for minus, grouped whole part, done on the string (no
  `Number`). `withCurrency(text: string, code: string | null): string` — the `amount` filter (`₹` in front for INR,
  else the code after).
- `dates.ts` (all take ISO `YYYY-MM-DD` strings and `today` from the session; English month and weekday names, as
  the server writes them): `friendlyDate(day: string, today: string): string` (Today / Yesterday / `Mon, 28 Sep` /
  `28 Sep 2025`), `shortDate(day: string, today: string): string`, `dateChip(day: string, today: string): string`.
- `tests/format_cases.json`: `{"money": [[value, grouping, expected], ...], "amount": [[text, code, expected], ...],
  "friendly_date": [[day, today, expected], ...], "short_date": [...], "date_chip": [...]}`, at least: `"1234567.5"`
  indian → `"12,34,567.50"`; western → `"1,234,567.50"`; `"-1234.5"` indian → `"−1,234.50"`; `"0.01250000"` →
  `"0.0125"`; `"100.00000000"` → `"100.00"`; `"0"` → `"0.00"`; `["1,200.00", "INR"]` → `"₹1,200.00"`;
  `["5.00", "USD"]` → `"5.00 USD"`; dates: today, yesterday, same year, another year, 1 January after a year change.

- [ ] **Step 1: Write the failing tests:**
  - `tests/test_format_cases.py`: for each case, `templating.money(Decimal(v), style=g) == expected`,
    `templating.amount(t, c) == expected`; the date filters with `local_today` patched to the case's `today`. (This
    pins the case file to today's server behaviour.)
  - `money.test.ts`, `dates.test.ts`: the same cases, loaded from `../../../tests/format_cases.json`.
  - `amount.test.ts`: `cleanAmount("12a.345", 2) === "12.34"`, `cleanAmount("42.00.00", 2) === "42.00"`,
    `cleanAmount("1.5", 0) === "15"`, `cleanAmount("-0012", 2) === "-12"`, `cleanAmount("1-2", 2) === "12"`;
    `tidyAmount("1.", 2) === "1.00"`, `tidyAmount("1,000", 0) === "1000"`, `tidyAmount("abc", 2) === "abc"`;
    `groupAmount("1234567.5", "indian") === "12,34,567.5"`, `groupAmount("x", "western") === "x"`.
- [ ] **Step 2:** Run `uv run pytest tests/test_format_cases.py -q` — expected: PASS (the server already behaves so;
  if a case fails, the case is wrong: fix the case, never the server). Run `npm run test` — expected: FAIL (no
  modules).
- [ ] **Step 3:** Implement the three modules.
- [ ] **Step 4:** Run `npm run check` — expected: PASS.
- [ ] **Step 5:** Commit: `Money, amount and date helpers, held to the server's by one case file`.

### Task 5: The shell: router, session, layout, toasts, offline, installable

**Files:**
- Create: `frontend/src/app/router.tsx`, `frontend/src/app/session.tsx`, `frontend/src/app/Layout.tsx`,
  `frontend/src/app/Layout.module.css`, `frontend/src/app/toast.tsx`, `frontend/src/app/Offline.tsx`,
  `frontend/src/features/placeholder/Placeholder.tsx`, and tests beside each
- Modify: `frontend/src/App.tsx`, `frontend/src/main.tsx`, `frontend/vite.config.ts` (vite-plugin-pwa)

**Interfaces:**
- `session.tsx`: `type Session = components["schemas"]["SessionRead"]`;
  `export function SessionProvider({ children }: { children: ReactNode })` loads `GET /api/auth/session` with
  TanStack Query (key `["session"]`); `export function useSession(): Session` (inside the provider only);
  `export function useToday(): string` (`session.today`). Signed out (401) → `<Navigate to="/sign-in" />`; a network
  failure → the offline banner with a Retry button, never the sign-in screen.
- `router.tsx`: `createBrowserRouter` with `/sign-in` (a placeholder until step 3, outside the layout) and, inside
  `SessionProvider` + `Layout`: `/` Home, `/budget` Budgets, `/accounts` Accounts, `/categories` Categories,
  `/transactions` Transactions, `/people` People, `/settings` Settings, each a lazily loaded `Placeholder` naming the
  page until its step; `*` → a "Page not found" empty state.
- `Layout.tsx`: the phone tab bar (Home, Budgets, the `+` button to `/transactions/new`, Accounts, Categories) and,
  at the wide breakpoint `style.css` uses, the sidebar (brand, New transaction, the six pages, To do, Settings),
  `aria-current="page"` on the active link, `<main>` for the page, the toast region (`role="status"`). Styles from
  `style.css`'s tab bar, sidebar and `.fab` rules, in `Layout.module.css`, colours from tokens only.
- `toast.tsx`: `export function useToast(): (message: string) => void`; one toast at a time, gone after 3 s.
- `Offline.tsx`: shows the banner while `navigator.onLine` is false (listens to `online` / `offline`).
- PWA: `VitePWA({ registerType: "autoUpdate", manifest: <name, icons and colours from app/static/manifest.webmanifest>,
  workbox: { navigateFallbackDenylist: [/^\/api\//] } })` — caches the app's own files only, never `/api`.

- [ ] **Step 1: Write the failing tests** (Testing Library with a `MemoryRouter`/`createMemoryRouter` and a stub API
  client injected through a React context `ApiProvider`, so no real `fetch`):
  - `Layout.test.tsx`: `the tab bar has the four pages and the plus button` (links named Home, Budgets, Accounts,
    Categories and `New transaction`); `the current page is marked` (at `/accounts`, the Accounts link has
    `aria-current="page"`).
  - `session.test.tsx`: `signed out goes to sign-in` (session answers 401 → `/sign-in` rendered);
    `useToday is the server's day` (session `today: "2026-01-31"`, a probe component prints it);
    `a network failure shows offline, not sign-in` (the stub rejects with `TypeError("Failed to fetch")`).
  - `toast.test.tsx`: `a toast shows and goes` (fake timers, gone after 3000 ms).
  - `router.test.tsx`: `an unknown path says page not found`.
- [ ] **Step 2:** Run `npm run test` — expected: FAIL.
- [ ] **Step 3:** Implement. Add `ApiProvider` / `useApi()` in `frontend/src/api/context.tsx` (the default value is
  `api` from Task 3) — a ruling on testability: components take the client from context, never import `api`
  directly.
- [ ] **Step 4:** Run `npm run check` — expected: PASS, and `dist/` contains `manifest.webmanifest` and `sw.js`.
- [ ] **Step 5:** Smoke-check in a real browser: start `uv run fastapi dev` with `FINODE_DATABASE_URL=sqlite:///./finode.db`
  and `FINODE_FRONTEND_ORIGIN=http://localhost:5173`, then `npm run dev`; open `http://localhost:5173/` signed out —
  expected: the sign-in placeholder. Stop both servers (signing in arrives in step 3).
- [ ] **Step 6:** Commit: `The app shell: router, session, tab bar and sidebar, toasts, offline, installable`.

### Task 6: Shared components and icons

**Files:**
- Create in `frontend/src/components/`: `Icon.tsx` + `icons.json`, `Row.tsx`, `Tile.tsx`, `Sheet.tsx`,
  `Chips.tsx`, `AmountField.tsx`, `MonthPill.tsx`, `EmptyState.tsx`, a `.module.css` and a `.test.tsx` for each
- Create: `tests/test_icon_parity.py`

**Interfaces** (styles taken from the matching `style.css` rules: `.row`, the tile rule at the end, `.sheet` /
`.sheet-bottom`, `.chips.seg`, the amount input, the month pill macro, `.empty-state`):
- `Icon({ name, label }: { name: IconName; label?: string })` — `IconName` is the union of `icons.json` keys; an
  `<svg>` with today's attributes; `aria-hidden` unless `label` (then `role="img"` and `aria-label`).
- `Row({ title, detail, figure, figureTone, to, onClick }: { title: ReactNode; detail?: ReactNode; figure?: ReactNode;
  figureTone?: "in" | "out" | "plain"; to?: string; onClick?: () => void })` — a link when `to`, a button when
  `onClick`, else plain. `"in"` uses the green token and a `+`; `"out"` the red token; never green or red otherwise.
- `Tile({ title, children }: { title?: string; children: ReactNode })` — `--surface`, `--tile-border`.
- `Sheet({ open, onClose, title, children }: {...})` — a native `<dialog>` from the bottom; closes on Escape and on
  backdrop tap; focus returns to the opener.
- `Chips<T extends string>({ options, value, onChange, label }: { options: { value: T; label: string }[]; value: T;
  onChange: (v: T) => void; label: string })` — a radiogroup in `.chips.seg` style.
- `AmountField({ value, onChange, places, grouping, label, id }: {...})` — `inputMode="decimal"`, font-size ≥ 16px,
  `cleanAmount` on every change, `tidyAmount` then `groupAmount` on blur; `value` is a string.
- `MonthPill({ month, onChange, max }: { month: string; onChange: (m: string) => void; max?: string })` — `YYYY-MM`,
  previous/next buttons and the native month input, as the Jinja macro.
- `EmptyState({ title, children, action }: {...})`.
- `tests/test_icon_parity.py::test_the_react_icons_are_the_web_icons`: parses `partials/icons.html` (the `name ==
  "…"` branches and their inner SVG markup) and asserts it equals `frontend/src/components/icons.json` (name →
  inner markup, whitespace collapsed).

- [ ] **Step 1: Write the failing tests:**
  - `test_icon_parity.py` as above.
  - `Icon.test.tsx`: `decorative by default` (`aria-hidden="true"`); `labelled when given a label` (`role="img"`).
  - `Row.test.tsx`: `money in is green with a plus` (class for "in" and text starts with `+`); `a row with to is a
    link`.
  - `Sheet.test.tsx`: `Escape closes it` (`onClose` called).
  - `Chips.test.tsx`: `arrow keys and clicks choose` (`onChange("b")`); the chosen one has `aria-checked="true"`.
  - `AmountField.test.tsx`: `typing letters is ignored` (type `12a.345` with places 2 → value `12.34`);
    `leaving tidies and groups` (`1234567` INR → `12,34,567.00` on blur); `no decimals for places 0` (type `1.5` →
    `15`); `the input is at least 16px` (computed `font-size` from the module class, or the class carries
    `font-size: 1rem`).
  - `MonthPill.test.tsx`: `next is disabled at max`; `previous goes back a month across a year` (`2026-01` →
    `2025-12`).
- [ ] **Step 2:** Run `uv run pytest tests/test_icon_parity.py -q` and `npm run test` — expected: FAIL.
- [ ] **Step 3:** Generate `icons.json` from `icons.html` once with a throwaway script (not committed); implement the
  components.
- [ ] **Step 4:** Run `uv run pytest -q` and `npm run check` — expected: PASS.
- [ ] **Step 5:** Commit: `Shared components and icons for the React app`.

### Task 7: Rules, docs and the whole check

**Files:**
- Modify: `AGENTS.md` (a short "Frontend (`frontend/`, being built on `feature/react-frontend`)" section: commands,
  strings for money, today from the session, `useApi()` not `api`, tokens from `app/static/tokens.css`, a component
  used by two features lives in `components/`), `docs/developer/code-map.md` (the `frontend/` tree),
  `docs/architecture/web-ui.md` (a paragraph: the React app is being built; link the spec), `README.md` ("Running the
  frontend": Node from `.nvmrc`, `npm ci`, `npm run dev`, `FINODE_FRONTEND_ORIGIN=http://localhost:5173`)

- [ ] **Step 1:** Update the docs above.
- [ ] **Step 2:** Run `make check`, `scripts/browser-tests.sh` and `FINODE_BROWSER=webkit scripts/browser-tests.sh`
  — expected: all pass; 189 browser tests on each.
- [ ] **Step 3:** Commit: `Docs and rules for the frontend foundation`, then `git push origin feature/react-frontend`.

# React frontend, step 3: the sign-in screens — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sign in, sign up, forgotten password and reset in the React app, with today's wording and rules, tested in
real browsers (Chromium and WebKit) against the real API.

**Architecture:** Four screens outside the signed-in layout (`/sign-in`, `/sign-up`, `/forgot`, `/reset`), built from
React Hook Form + Zod for the quick checks and `/api/auth/*` for the real ones (the server stays the authority and its
`detail.message` is what the person reads). After signing in, the cached session is refreshed and the person goes to
`next` (only an address inside the app) or Home. A test-only server puts the built app and the API on one origin so
the browser tests drive the React app the way a person would.

**Tech Stack:** React, React Router, TanStack Query, React Hook Form, Zod, `@hookform/resolvers`, Vitest, Python
`pytest-playwright`, Starlette (test server only).

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md` (step 3 of the build order; "Forms", "Tooling
and tests").

## Global Constraints

- Branch `feature/react-frontend` only; nothing reaches `develop`.
- All Global Constraints of the step 2 plan still hold (strict TypeScript, strings for money, `useApi()`, tokens only,
  16px inputs, `npm run check` clean, exact versions). `make` is not installed: run the commands it runs.
- **Wording is today's, word for word** (from `app/templates/login.html`, `signup.html`, `forgot.html`, `reset.html`,
  `partials/test_notice.html`, and the `password-reset` message in `app/flash.py`). The server's messages are shown as
  it sends them (`detail.message`).
- Quick checks in the browser use the server's own messages: `Enter a valid email address.`, `Password must be at
  least 8 characters.`, `Passwords do not match.`
- No form submits twice: the button is disabled while its request is in flight.
- The browser tests start the API on the in-memory test database with the recurring loop off; nothing reaches the
  production database.

## Review Focus

1. A `next` that leads off the app (`//evil.example`, `https://evil.example`, `/\evil.example`, `javascript:…`):
   ignored, the person goes Home. Test in Task 2 (`safeNext`).
2. Too many attempts (429 with `Retry-After`): the server's message ("Too many sign-in attempts. Try again in N
   minutes.") shows and the button works again. Test in Task 3.
3. The connection drops while signing in (`fetch` rejects): "finode can't be reached. Check your connection." shows,
   never a blank screen or an unhandled error. Test in Task 3.
4. A mail scanner opening the reset link: opening `/reset?token_hash=…` must not spend the token (no call to
   `/api/auth/reset` until the person submits). Test in Task 5.
5. The server answers 404 for sign-up (or reset) although the options said it was on: the person is sent to sign in,
   no crash. Tests in Tasks 4 and 5.

---

### Task 1: Browser tests for the React app

**Files:**
- Create: `tests/browser/spa.py`, `tests/browser/test_spa_shell.py`
- Modify: `tests/browser/conftest.py` (fixtures), `scripts/browser-tests.sh` (build the app first),
  `.github/workflows/ci.yml` (browser job: `actions/setup-node`, `npm ci` and `npm run build` in `frontend/` before
  the tests)

**Interfaces:**
- `tests/browser/spa.py`: `def spa_app(dist: Path) -> ASGIApp` — a Starlette app that sends every path starting with
  `/api/` to `app.main.app` and serves `dist` for the rest, answering `index.html` for any path that is not a file
  (the app's own routing). Raises `RuntimeError("build the app first: npm --prefix frontend run build")` when
  `dist/index.html` is missing.
- Fixtures in `tests/browser/conftest.py`:
  - `spa_server(session, monkeypatch) -> str`: the `spa_app` on a free port (same thread and one-at-a-time database
    pattern as `live_server`), `settings.frontend_origin` set to its own address, `settings.recurring_interval_minutes`
    0; **no** auth overrides. `auth.verify_supabase_jwt` is monkeypatched to accept the token `"test-access"` as the
    test user (`{"sub": str(TEST_USER_ID), "email": "test@example.com"}`) and refuse anything else with 401;
    `auth_flows.sign_in` returns `SessionTokens("test-access", "test-refresh", 3600)` for password `"right"` and
    raises `InvalidCredentialsError` otherwise.
  - `spa_page(browser, spa_server) -> Page`: like `page` (390×844, reduced motion, JavaScript errors fail the test),
    signed out.
  - `signed_in_spa_page(spa_page, spa_server) -> Page`: `spa_page` with the cookie `finode_access=test-access` set for
    the server's address.
- `scripts/browser-tests.sh` runs `npm --prefix frontend ci` (when `node_modules` is missing) and
  `npm --prefix frontend run build` before pytest.

- [ ] **Step 1: Write the failing tests** `tests/browser/test_spa_shell.py`:
  - `test_signed_out_lands_on_sign_in(spa_page)`: `goto("/accounts")` → URL ends with `/sign-in?next=%2Faccounts`.
  - `test_signed_in_sees_the_tab_bar(signed_in_spa_page)`: `goto("/")` → `get_by_role("navigation", name="Tab bar")`
    visible and `get_by_role("heading", name="Home")` visible.
  - `test_an_unknown_address_is_answered_by_the_app(signed_in_spa_page)`: `goto("/no-such-page")` → heading
    `Page not found`.
- [ ] **Step 2:** `npm --prefix frontend run build && scripts/browser-tests.sh -k spa_shell` — expected: FAIL (no
  fixtures).
- [ ] **Step 3:** Implement `spa.py`, the fixtures, the script and CI changes.
- [ ] **Step 4:** `scripts/browser-tests.sh -k spa_shell` and `FINODE_BROWSER=webkit scripts/browser-tests.sh -k
  spa_shell` — expected: 3 pass on each.
- [ ] **Step 5:** Commit: `Browser tests for the React app: the built app and the API on one origin`.

### Task 2: What every sign-in screen shares

**Files:**
- Create in `frontend/src/features/auth/`: `AuthScreen.tsx` + `.module.css`, `fields.tsx` (+ `.module.css`),
  `safeNext.ts`, `messages.ts`, `options.ts`, and tests `safeNext.test.ts`, `messages.test.ts`, `AuthScreen.test.tsx`
- Modify: `frontend/package.json` (`react-hook-form`, `zod`, `@hookform/resolvers`, exact versions)

**Interfaces:**
- `safeNext(next: string | null): string` — `next` when it starts with a single `/` and contains no `\` and no
  `//` at the start and is not `/sign-in…`; otherwise `"/"`.
- `messages.ts`:
  - `UNREACHABLE = "finode can't be reached. Check your connection."`
  - `messageOf(error: unknown): string` — `ApiError` with `detail.message` → that message; with a string `detail` →
    it; any other `ApiError` → `"Something went wrong. Please try again."`; anything else (a rejected `fetch`) →
    `UNREACHABLE`.
  - `RULES = { email: "Enter a valid email address.", short: "Password must be at least 8 characters.", mismatch:
    "Passwords do not match." }` and `MIN_PASSWORD_LENGTH = 8`.
- `options.ts`: `useAuthOptions()` — TanStack Query on `GET /api/auth/options`, key `["auth-options"]`,
  `staleTime: Infinity`.
- `AuthScreen({ intro, children }: { intro?: ReactNode; children: ReactNode })` — the bare page of
  `login.html`: no layout, the brand title (favicon + "finode", `h1`), a centred column with no card (the `.narrow`
  and `body.bare` rules: centred vertically on a phone, 16px gutters).
- `fields.tsx`: `TextField` (label + input, `forwardRef`-free: takes `registration: UseFormRegisterReturn`, `type`,
  `autoComplete`, `error?: string` shown under it with `role="alert"`), `FormError({ message }: { message: string |
  null })` (`.error` look, `role="alert"`), `Notice({ children })` (`.login-notice` look, `role="status"`),
  `SubmitButton({ pending, children })` (full width, `disabled` and `aria-busy` while pending), `SwitchLink` (the
  `.switch` line). Styles from the `.error`, `.login-notice`, `.switch`, `.stack`, `label` and `button` rules of
  `style.css`.

- [ ] **Step 1: Write the failing tests:**
  - `safeNext.test.ts`: `"/accounts"` → itself; `"/oauth/consent?authorization_id=x"` → itself; `null`, `""`,
    `"//evil.example"`, `"https://evil.example"`, `"/\\evil.example"`, `"javascript:alert(1)"`, `"/sign-in"` → `"/"`.
  - `messages.test.ts`: `messageOf(new ApiError(401, { message: "Invalid email or password.", code: null }))` →
    that text; `messageOf(new ApiError(400, "nope"))` → `"nope"`; `messageOf(new TypeError("Failed to fetch"))` →
    `UNREACHABLE`; `messageOf(new ApiError(500, null))` → `"Something went wrong. Please try again."`.
  - `AuthScreen.test.tsx`: shows the heading `finode` and its children, and no tab bar.
- [ ] **Step 2:** `npx vitest run src/features/auth` — expected: FAIL.
- [ ] **Step 3:** Install the three packages (`--save-exact`); implement.
- [ ] **Step 4:** `npm --prefix frontend run check` — expected: PASS.
- [ ] **Step 5:** Commit: `The sign-in screens' shared parts: layout, fields, messages, a safe next`.

### Task 3: Sign in

**Files:**
- Create: `frontend/src/features/auth/SignIn.tsx`, `SignIn.test.tsx`, `tests/browser/test_spa_sign_in.py`
- Modify: `frontend/src/app/router.tsx` (`/sign-in` → `SignIn`; `/login` → `<Navigate to="/sign-in" replace />`,
  keeping the query), delete `frontend/src/features/placeholder/SignInPlaceholder.tsx`

**Interfaces:**
- Consumes Task 2. The form: Email (`type="email"`, `autoComplete="username"`, `autoFocus`), Password
  (`autoComplete="current-password"`), button `Sign in`. Intro: `Sign in to your ledger.`
- `?created=1` shows the notice `Account created. Please sign in.`
- Links when the options allow: `Forgot your password?` → `/forgot`; `Have an invite code?` `Create an account` →
  `/sign-up`.
- Submit: `POST /api/auth/sign-in`; on success `queryClient.invalidateQueries({ queryKey: ["session"] })` then
  `navigate(safeNext(searchParams.get("next")), { replace: true })`; on failure `FormError` with `messageOf(error)`.

- [ ] **Step 1: Write the failing tests:**
  - `SignIn.test.tsx` (stub API through `renderApp`-style helper with answers per path):
    - `wrong password shows the server's message` (401 `{detail: {message: "Invalid email or password."}}`).
    - `too many attempts shows the wait and the button works again` (429 with the server's message; afterwards the
      button is enabled).
    - `a lost connection says so` (`/api/auth/sign-in` rejects with `TypeError`) → `UNREACHABLE` shown.
    - `the button is disabled while signing in` (a stub that never answers; after one click the button is disabled;
      a second click sends no second request).
    - `success goes to next` (`/sign-in?next=%2Faccounts`, sign-in 204, session then 200) → heading `Accounts`.
    - `the links follow the options` (both off → neither link; both on → both).
    - `created=1 shows the notice`.
  - `tests/browser/test_spa_sign_in.py`:
    - `test_the_form_is_centred_and_has_no_card(spa_page)`: the port of `tests/browser/test_sign_in_page.py` against
      `/sign-in` (no border, middle within 120px of 422, 16px gutters).
    - `test_signing_in_takes_you_where_you_were_going(spa_page)`: `goto("/accounts")`, fill `a@b.co` / `right`,
      click `Sign in` → heading `Accounts`, URL `/accounts`.
    - `test_a_wrong_password_says_so(spa_page)`: password `wrong` → `Invalid email or password.` visible.
- [ ] **Step 2:** Run both — expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `npm --prefix frontend run check`; browser tests `-k spa_sign_in` on Chromium and WebKit —
  expected: PASS.
- [ ] **Step 5:** Commit: `Sign in to the React app`.

### Task 4: Sign up

**Files:**
- Create: `frontend/src/features/auth/SignUp.tsx`, `SignUp.test.tsx`, `TestNotice.tsx`
- Modify: `frontend/src/app/router.tsx` (`/sign-up`; `/signup` → `/sign-up`), `tests/browser/test_spa_sign_in.py`

**Interfaces:**
- Shown only when `signup_enabled`; otherwise `<Navigate to="/sign-in" replace />`.
- Intro `Create an account. You need an invite code.`; fields Email, Password (`new-password`), Confirm password,
  Invite code (`type="password"`, `autoComplete="off"`); when `test_notice`: `TestNotice` (today's text, `role="note"`)
  and the checkbox `I understand this is a test and have read the notice above.`; button `Create account`; line
  `Already have an account?` `Sign in`.
- Zod: email has `@` (`RULES.email`), password ≥ 8 (`RULES.short`), confirm equals password (`RULES.mismatch`),
  invite code required, the checkbox required when the notice shows (`Please read the notice and tick the box to
  continue.`).
- Submit `POST /api/auth/sign-up` with `accept`; `signed_in: true` → invalidate the session, go Home;
  `signed_in: false` → `/sign-in?created=1`; a 404 → `/sign-in`; other errors → `FormError`.

- [ ] **Step 1: Write the failing tests** (`SignUp.test.tsx`): `off sends you to sign in`;
  `mismatched passwords are caught before sending` (no request made, `Passwords do not match.` shown);
  `the test notice asks for the tick` (notice on; submit without tick shows its message, no request);
  `a wrong invite code shows the server's message` (403 `Invalid invite code.`);
  `created but not signed in goes to sign in with the notice`; `signed in goes Home`;
  `a 404 from the server sends you to sign in`. Browser: `test_creating_an_account(spa_page, monkeypatch)` with
  sign-up switched on and `auth_flows.create_user` stubbed → lands on Home.
- [ ] **Step 2:** Run — expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `npm --prefix frontend run check`; the browser test on Chromium and WebKit — expected: PASS.
- [ ] **Step 5:** Commit: `Sign up in the React app`.

### Task 5: Forgotten password and reset

**Files:**
- Create: `frontend/src/features/auth/Forgot.tsx`, `Reset.tsx`, their tests
- Modify: `frontend/src/app/router.tsx` (`/forgot`, `/reset`), `frontend/src/app/toast.tsx` (a toast handed over in
  the navigation state), `tests/browser/test_spa_sign_in.py`

**Interfaces:**
- Both shown only when `reset_enabled`; otherwise `<Navigate to="/sign-in" replace />`.
- `Forgot`: intro `Enter your email address and we will send you a link to choose a new password.`; Email; button
  `Send the link`; on 202 the form is replaced by the notice `If there is an account for {email}, an email with a link
  to choose a new password is on its way. The link works for an hour. Check your spam folder if it does not arrive.`;
  line `Back to sign in`. An error passed in the navigation state (`{ error: string }`) shows as `FormError`.
- `Reset` (`/reset?token_hash=…`): **no call on opening**. Without `token_hash` → `/forgot` with the error `That link
  is not valid. Ask for a new one.` Intro `Choose a new password.`; New password, Confirm password; button `Change
  password`. Zod as sign-up. On 204 → invalidate the session and go Home with the toast `Your password was changed.
  You are signed in.`; `detail.code === "link-invalid"` → `/forgot` with that message; a 404 → `/sign-in`.
- `toast.tsx`: `ToastProvider` shows `location.state.toast` once on arrival (then clears it with
  `navigate(location.pathname + location.search, { replace: true, state: null })`) so a toast survives the move into
  the layout.

- [ ] **Step 1: Write the failing tests:** `Forgot.test.tsx`: `sending shows the same answer for anyone`; `an error
  handed over shows`; `off sends you to sign in`. `Reset.test.tsx`: `opening the link sends nothing` (only
  `/api/auth/options` was called); `no token goes to forgot with its message`; `a spent link goes to forgot with the
  server's message`; `mismatched passwords are caught before sending`; `success goes Home with the toast`.
  `toast.test.tsx`: `a toast handed over in the navigation shows once`. Browser: `test_resetting_a_password(spa_page,
  monkeypatch)` (reset on, `auth_flows.reset_password` returns the test tokens) → Home and the toast visible.
- [ ] **Step 2:** Run — expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `npm --prefix frontend run check`; browser tests on Chromium and WebKit — expected: PASS.
- [ ] **Step 5:** Commit: `Forgotten password and reset in the React app`.

### Task 6: Docs and the whole check

**Files:**
- Modify: `docs/developer/code-map.md` (`features/auth/`, `tests/browser/spa.py`), `AGENTS.md` (Frontend rules:
  "browser tests for the React app use `spa_page` / `signed_in_spa_page`; build first"), `README.md` (the browser
  tests build the app first)

- [ ] **Step 1:** Update the docs.
- [ ] **Step 2:** Run the Python checks and `uv run pytest -q`, `npm --prefix frontend run check`,
  `scripts/browser-tests.sh` and `FINODE_BROWSER=webkit scripts/browser-tests.sh` — expected: all pass (189 old
  browser tests plus the new ones, on each browser).
- [ ] **Step 3:** Commit: `Docs for the sign-in screens`, then `git push origin feature/react-frontend`.

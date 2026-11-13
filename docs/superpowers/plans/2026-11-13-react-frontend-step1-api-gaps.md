# React frontend, step 1: fill the API's gaps — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `/api` everything the React app needs that only the web pages have today (cookie sign-in from
`app.<domain>`, the sign-in flows, server "today", assistants and consent, erase, payee chips), with today's pages
unchanged and passing.

**Architecture:** The HttpOnly cookie session the web pages use becomes a third way into `/api` (after a bearer
header and the web pages' own request state), guarded by an `X-Finode: 1` header and an exact `Origin` match on any
request that changes something. The sign-in rules move out of the web router into one module both routers call, so
nothing is written twice. Each new route gets its parity test, isolation classification and `docs/developer/api.md` row.

**Tech Stack:** FastAPI, Starlette `CORSMiddleware`, pydantic-settings, pytest with `TestClient`.

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md` (steps 1 of the build order; sections
"Sign-in" and "Gaps in the API, filled first").

## Global Constraints

- Branch: `feature/react-frontend` only. Nothing is merged into `develop` in this plan.
- `make check` (ruff, format, pyrefly, tests) must be clean before every commit. No `assert` in `app/`; every
  parameter typed; `raise … from None` inside `except`.
- Today's pages keep working: no change to their URLs, forms, messages or tests other than import paths and
  monkeypatch targets.
- New setting: `FINODE_FRONTEND_ORIGIN` (`settings.frontend_origin: str | None = None`), e.g. `https://app.<domain>`.
- Cookie writes need `X-Finode: 1` **and** `Origin == settings.frontend_origin`; when the setting is empty every
  cookie write is refused (403). Bearer requests skip both checks.
- Assistant tokens, connected apps, OAuth consent, Erase and Delete my account accept the cookie session only, never
  a bearer token.
- User-facing messages are copied verbatim from today's web routers.
- The Supabase service key never leaves the server; nothing new logs or returns a token.
- Every new `/api` route: a row in `docs/developer/api.md` (`tests/test_api_doc.py`), a classification in
  `tests/test_isolation.py`, a test in `tests/test_api_parity.py` or its own test file.

## Review Focus

1. An expired access cookie with a valid refresh cookie on an `/api` call: the call succeeds and the response sets
   fresh cookies (`refreshed_cookies_middleware`). Test in Task 2.
2. A bearer header and cookies on the same request: the bearer wins, and a cookie-only route still refuses it.
   Test in Task 2.
3. `FINODE_FRONTEND_ORIGIN` unset (today's production): cookie reads work, cookie writes get 403, bearer and web
   pages unaffected. Test in Task 2.
4. A connected-app token (claims carry `client_id`) placed in the access cookie: refused like it is today. Test in
   Task 2.
5. A CORS preflight from any origin other than `FINODE_FRONTEND_ORIGIN` gets no `access-control-allow-origin`.
   Test in Task 2.

---

### Task 1: Move the Supabase session code into `app/session.py`

A pure refactor that breaks the import cycle Task 2 would create (`auth` → cookie refresh → `web_auth` → `auth`).

**Files:**
- Create: `app/session.py`
- Modify: `app/web_auth.py`, `app/signup.py`, `app/reset.py`, `app/routers/web/auth.py`, `app/routers/web/profile.py`
- Modify (imports only): `tests/test_password_reset.py`, `tests/test_limits.py`, `tests/test_web_signup.py`,
  `tests/test_signup.py`, `tests/test_erase.py`, `tests/test_web_auth.py`

**Interfaces:**
- Produces, in `app/session.py` (moved unchanged from `app/web_auth.py`): `ACCESS_COOKIE`, `REFRESH_COOKIE`,
  `REFRESH_MAX_AGE`, `InvalidCredentialsError`, `AuthUnavailableError`, `SessionTokens`, `_to_tokens`,
  `sign_in(email: str, password: str) -> SessionTokens`, `refresh_session(refresh_token: str) -> SessionTokens`,
  `set_auth_cookies(response: Response, tokens: SessionTokens) -> None`, `clear_auth_cookies(response: Response) -> None`.
  `app/session.py` must not import `app.auth` or `app.web_auth`.
- `app/web_auth.py` keeps only: `LoginRequired`, `LOGIN_PATH`, `CONSENT_PATH`, `web_login_required`, `safe_next`,
  `login_required_handler`, `refreshed_cookies_middleware`.

- [ ] **Step 1:** Create `app/session.py` with a module docstring ("The Supabase session: signing in with a password,
  refreshing, and the HttpOnly cookies that carry it.") and move the names above into it. Point every importer at
  `app.session`; no re-exports from `web_auth`.
- [ ] **Step 2:** Run `uv run pytest -q -x` — expected: all pass (1483 at the start of this plan).
- [ ] **Step 3:** Run `make lint && uv run pyrefly check` — expected: clean.
- [ ] **Step 4:** Commit: `Move the Supabase session code into app/session.py`.

### Task 2: Cookie sessions on `/api`, guarded by origin and header

**Files:**
- Modify: `app/config.py` (add `frontend_origin`), `app/auth.py`, `app/web_auth.py`, `app/main.py`, `tests/conftest.py`
- Test: `tests/test_api_cookie_auth.py` (new)

**Interfaces:**
- Consumes: `app.session.refresh_session`, `ACCESS_COOKIE`, `REFRESH_COOKIE` (Task 1).
- Produces, in `app/auth.py`:
  - `APP_HEADER = "X-Finode"`; `SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})`.
  - `token_from_cookies(request: Request) -> str | None`: the body of today's `web_login_required` (verify the
    access cookie and reject app tokens; on a 401 try the refresh cookie and set `request.state.refreshed_tokens`).
  - `check_app_request(request: Request) -> None`: raises `HTTPException(403, "this request did not come from the
    finode app")` unless `request.headers.get("x-finode") == "1"` and `settings.frontend_origin` is set and equals
    `request.headers.get("origin")`.
  - `require_authenticated_user` order: bearer header → `request.state.access_token` (web pages, no extra check) →
    `token_from_cookies` (then `check_app_request` when `request.method not in SAFE_METHODS`, and store the token in
    `request.state.access_token`) → 401.
  - `@dataclass(frozen=True) class CookieSession: user: CurrentUser; access_token: str`.
  - `require_cookie_session(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> CookieSession`:
    401 `"this needs you signed in to the finode app"` when a bearer header is present or no cookie session exists;
    `check_app_request` for unsafe methods.
- `web_login_required` becomes: `token = auth.token_from_cookies(request)`; set `request.state.access_token` or raise
  `LoginRequired`.
- `app/main.py`: `cors_options() -> dict[str, Any]` returning `allow_origins=[settings.frontend_origin]` (an empty
  list when unset), `allow_credentials=True`, `allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"]`,
  `allow_headers=["Content-Type", "X-Finode"]`; `app.add_middleware(CORSMiddleware, **cors_options())` always, added
  before `Compression` so compression stays outermost.
- `tests/conftest.py` `client` fixture also overrides `require_cookie_session` with
  `CookieSession(user=<the same CurrentUser>, access_token="test-access-token")`.

- [ ] **Step 1: Write the failing tests** in `tests/test_api_cookie_auth.py`. Use a client without the auth overrides
  (as `tests/test_web_auth.py` does), monkeypatch `auth.verify_supabase_jwt` to return
  `{"sub": str(TEST_USER_ID), "email": "test@example.com"}` for `"good"`, raise 401 for `"expired"`, and return claims
  with `client_id` for `"app-token"`; monkeypatch `session.refresh_session` to return
  `SessionTokens("good", "new-refresh", 3600)`. Set `settings.frontend_origin = "https://app.example.com"` unless the
  test says otherwise. `APP = {"X-Finode": "1", "Origin": "https://app.example.com"}`.
  - `test_a_cookie_reads_the_api`: cookie `finode_access=good`, `GET /api/profile/` → 200.
  - `test_a_cookie_write_needs_the_header_and_origin`: `PATCH /api/profile/` with `json={"first_name": "A"}` →
    403 with no headers, 403 with only `X-Finode`, 403 with `Origin: https://evil.example`, 200 with `APP`.
  - `test_an_expired_access_cookie_is_refreshed`: cookies `finode_access=expired`, `finode_refresh=r` → 200, and the
    response's `set-cookie` contains `finode_refresh=new-refresh`.
  - `test_without_a_frontend_origin_cookie_writes_are_refused`: `settings.frontend_origin = None`; GET → 200;
    PATCH with `APP` → 403.
  - `test_bearer_skips_the_origin_check`: header `Authorization: Bearer good`, no `APP` → PATCH 200.
  - `test_an_app_token_in_the_cookie_is_refused`: cookie `finode_access=app-token` → `GET /api/profile/` 401.
  - `test_cookie_only_routes_refuse_bearer`: add a throwaway route in the test (`app.get("/api/_probe")` using
    `Depends(require_cookie_session)`, removed in a `finally`) → bearer 401, cookie 200, bearer plus cookie 401.
  - `test_cors_allows_only_the_frontend`: Starlette fixes middleware options when the app is built, so this test
    wraps a fresh `FastAPI()` with one `GET /x` route in `CORSMiddleware(**cors_options())` after setting
    `settings.frontend_origin`. `OPTIONS /x` with `Origin: https://app.example.com` and
    `Access-Control-Request-Method: PATCH` → `access-control-allow-origin == "https://app.example.com"` and
    `access-control-allow-credentials == "true"`; with `Origin: https://evil.example` → no
    `access-control-allow-origin`; with `settings.frontend_origin = None` → no `access-control-allow-origin` for any
    origin.
  - `test_the_app_has_cors`: `CORSMiddleware` is among `app.user_middleware` of `app.main.app`.
- [ ] **Step 2:** Run `uv run pytest tests/test_api_cookie_auth.py -q` — expected: FAIL (cookies ignored by `/api`).
- [ ] **Step 3:** Implement the interfaces above.
- [ ] **Step 4:** Run `uv run pytest -q` — expected: all pass, including `tests/test_web_auth.py` and
  `tests/test_isolation.py::test_nothing_answers_without_a_sign_in`.
- [ ] **Step 5:** Add `FINODE_FRONTEND_ORIGIN` to the README's settings list and a "Cookie sessions on /api" paragraph
  to `docs/architecture/mcp-and-auth.md` (the three ways in, the header and origin rule, CORS).
- [ ] **Step 6:** `make check`, then commit: `Let /api take the web session cookie from the finode app`.

### Task 3: One home for the sign-in rules (`app/auth_flows.py`)

A refactor: the rate limits, checks and messages in `app/routers/web/auth.py` move to functions both routers call.

**Files:**
- Create: `app/auth_flows.py`
- Modify: `app/ratelimit.py` (add `client_address`), `app/routers/web/auth.py`
- Modify (monkeypatch targets only): `tests/test_limits.py`, `tests/test_web_signup.py`, `tests/test_erase.py`,
  `tests/test_password_reset.py`

**Interfaces:**
- Produces, in `app/ratelimit.py`: `client_address(request: Request) -> str` (today's `_client`).
- Produces, in `app/auth_flows.py`:
  - `MIN_PASSWORD_LENGTH = 8`.
  - `class FlowError(Exception)` with `message: str`, `status_code: int`, `retry_after: int | None = None`,
    `code: str | None = None` (`"link-invalid"` for a spent or expired reset link, so the app can send the person to
    "forgot password").
  - `password_sign_in(client: str, email: str, password: str) -> SessionTokens`
  - `register(db: Session, client: str, email: str, password: str, confirm_password: str, invite_code: str, accepted: bool) -> SessionTokens | None`
    (`None` = account created but the follow-up sign-in failed; the caller says "Account created. Please sign in.").
  - `request_reset(client: str, email: str) -> None`
  - `finish_reset(client: str, token_hash: str, password: str, confirm_password: str) -> SessionTokens`
  - Each raises `FlowError` with today's exact message, status and `Retry-After` value, in today's order of checks.
- `app/routers/web/auth.py` keeps its pages and form parsing and maps `FlowError` onto today's templates and statuses.

- [ ] **Step 1:** Run `uv run pytest tests/test_web_auth.py tests/test_web_signup.py tests/test_limits.py
  tests/test_password_reset.py tests/test_signup.py -q` — expected: PASS (the baseline this refactor must keep).
- [ ] **Step 2:** Create `app/auth_flows.py` and move the logic; point the tests' monkeypatches at `app.auth_flows`
  (`sign_in`, `create_user`) and `app.ratelimit.client_address`.
- [ ] **Step 3:** Run the Step 1 command — expected: PASS with no assertion changed.
- [ ] **Step 4:** `make check`, then commit: `Move the sign-in rules out of the web router into app/auth_flows.py`.

### Task 4: `/api/auth/*`: sign in, sign up, forgotten password, reset, sign out, session

**Files:**
- Create: `app/routers/auth.py`, `app/schemas/auth.py`
- Modify: `app/main.py` (include the router under `/api`), `tests/test_isolation.py`, `docs/developer/api.md`
- Test: `tests/test_api_auth.py` (new)

**Interfaces:**
- Consumes: `app.auth_flows` (Task 3), `app.auth.check_app_request`, `require_authenticated_user` (Task 2),
  `app.session.set_auth_cookies` / `clear_auth_cookies`, `app.clock.local_today`, `web.profile._feedback_url`
  (move it to `app/feedback.py` as `feedback_url() -> str | None` and import it from both places).
- Produces (router `prefix="/auth"`, `tags=["auth"]`; every POST has `dependencies=[Depends(check_app_request)]`):

| Method | Path | Body | Answer |
|---|---|---|---|
| `GET` | `/auth/options` | — | `AuthOptions{signup_enabled: bool, reset_enabled: bool, test_notice: bool}`, public |
| `GET` | `/auth/session` | — | `SessionRead{email: str \| None, today: date, feedback_url: str \| None, can_delete_login: bool}`; 401 when signed out |
| `POST` | `/auth/sign-in` | `SignIn{email, password}` | 204 + cookies |
| `POST` | `/auth/sign-up` | `SignUp{email, password, confirm_password, invite_code, accept: bool = False}` | 201 `SignUpResult{signed_in: bool}` (+ cookies when signed in); 404 when sign-up is off |
| `POST` | `/auth/forgot` | `ForgotPassword{email}` | 202 always on success; 404 when reset is off |
| `POST` | `/auth/reset` | `ResetPassword{token_hash, password, confirm_password}` | 204 + cookies; 404 when reset is off |
| `POST` | `/auth/sign-out` | — | 204, cookies cleared |

- A `FlowError` becomes `HTTPException(status_code, {"message": message, "code": code})`, with a `Retry-After` header
  when `retry_after` is set.
- Isolation: `/api/auth/options`, `sign-in`, `sign-up`, `forgot`, `reset`, `sign-out` go in `PUBLIC`;
  `GET /api/auth/session` in `LISTS`.

- [ ] **Step 1: Write the failing tests** in `tests/test_api_auth.py` (monkeypatch `app.auth_flows.sign_in`,
  `create_user`, `send_reset_email`, `reset_password`; set `settings.frontend_origin`; send `APP` headers):
  - `test_options_say_what_is_offered`: defaults → `{"signup_enabled": False, "reset_enabled": False, "test_notice": False}`.
  - `test_session_gives_today_from_the_server`: monkeypatch `app.routers.auth.local_today` to `date(2026, 1, 31)` →
    `today == "2026-01-31"` and `email == "test@example.com"`.
  - `test_sign_in_sets_the_cookies`: 204; `set-cookie` has `finode_access` and `finode_refresh`, both `HttpOnly`.
  - `test_wrong_password`: 401, `detail.message == "Invalid email or password."`.
  - `test_sign_in_is_rate_limited`: after `settings.login_attempts` failures → 429, `Retry-After` present.
  - `test_auth_posts_need_the_app_headers`: `POST /api/auth/sign-in` without `APP` → 403.
  - `test_sign_up_rules`: sign-up off → 404; on with a wrong code → 403 `"Invalid invite code."`; mismatched
    passwords → 400 `"Passwords do not match."`; success → 201 `{"signed_in": True}`.
  - `test_forgot_answers_the_same_for_anyone`: 202 for a known and an unknown address.
  - `test_a_spent_reset_link`: `reset_password` raises `ResetLinkInvalidError` → 400 with `code == "link-invalid"`.
  - `test_sign_out_clears_the_cookies`: 204 and both cookies expired in `set-cookie`.
- [ ] **Step 2:** Run `uv run pytest tests/test_api_auth.py -q` — expected: FAIL (404s).
- [ ] **Step 3:** Implement; add the seven `docs/developer/api.md` rows under a new "Sign-in" heading and the
  isolation classifications.
- [ ] **Step 4:** Run `uv run pytest -q` — expected: all pass.
- [ ] **Step 5:** `make check`, then commit: `Sign-in, sign-up, password reset and the session under /api/auth`.

### Task 5: Assistants and the consent screen under `/api`

**Files:**
- Create: `app/routers/assistants.py`, `app/schemas/assistants.py`
- Modify: `app/main.py`, `tests/test_isolation.py`, `docs/developer/api.md`
- Test: `tests/test_api_assistants.py` (new)

**Interfaces:**
- Consumes: `require_cookie_session`, `CookieSession` (Task 2); `ApiTokens`, `OAuthGrants`; `app.oauth`.
- Produces — router `prefix="/assistants"`, `dependencies=[Depends(require_cookie_session)]`:

| Method | Path | Body | Answer |
|---|---|---|---|
| `GET` | `/assistants/` | — | `AssistantsRead{mcp_url: str, tokens: list[ApiTokenRead], apps: list[ConnectedAppRead]}` (unrevoked only) |
| `POST` | `/assistants/tokens` | `ApiTokenCreate` | 201 `ApiTokenCreated` (the secret, this once) |
| `POST` | `/assistants/tokens/{token_id}/access` | `AccessChange{scope}` | `ApiTokenRead`; 404 / 400 |
| `POST` | `/assistants/tokens/{token_id}/revoke` | — | `ApiTokenRead`; 404 |
| `POST` | `/assistants/apps/{grant_id}/access` | `AccessChange{scope}` | `ConnectedAppRead`; 404 / 400 |
| `POST` | `/assistants/apps/{grant_id}/disconnect` | — | 204; calls `oauth.revoke_grant(client_id, session.access_token)` |

- And router `prefix="/oauth"`, same dependency:

| Method | Path | Body | Answer |
|---|---|---|---|
| `GET` | `/oauth/consent/{authorization_id}` | — | `ConsentRead{authorization_id, client_name, client_uri, scopes: list[str], redirect_url: str \| None}` |
| `POST` | `/oauth/consent/{authorization_id}` | `ConsentDecision{decision: Literal["allow", "deny"], access: Literal["read", "write", "manage"] = "read"}` | `ConsentResult{redirect_url: str}` |

- `ConnectedAppRead{id, client_name, scope, created, last_used}` from `OAuthGrant`.
- `mcp_url` = `str(request.base_url).rstrip("/") + "/mcp"` (move today's `mcp_url` from `web/profile.py` to
  `app/routers/assistants.py` and import it in the web router).
- `oauth.OAuthError` → 400 with its message; a non-web `redirect_url` → 400 `"The app asked to be opened in a way
  finode does not allow."`; on allow, the grant is recorded from Supabase's details, never the request (as
  `web/oauth.py::decide` does).
- Isolation: `GET /api/assistants/`, `POST /api/assistants/tokens` in `LISTS`/`REFERENCES` respectively
  (creating takes no id); `{token_id}` and `{grant_id}` routes are covered by the id audit (add a step there with
  A's token and grant ids, which the world already has); the consent routes in `PUBLIC` with the comment "a Supabase
  authorization id of the signed-in user", as the web consent page is.

- [ ] **Step 1: Write the failing tests** in `tests/test_api_assistants.py` (cookie-session override from conftest;
  monkeypatch `app.oauth.authorization_details`, `decide`, `revoke_grant`):
  - `test_make_list_change_and_revoke_a_token`: create → 201 with `secret` starting `fin_`; list shows it without
    `secret`; access to `"write"` → `scope == "write"`; revoke → gone from the list.
  - `test_bearer_cannot_mint_tokens`: a client with only the `require_authenticated_user` override and a bearer
    header (drop the `require_cookie_session` override) → `POST /api/assistants/tokens` 401.
  - `test_consent_allow_records_the_app_supabase_names`: details return client `"Claude"`; allow with `"write"` →
    `redirect_url` returned and `GET /api/assistants/` lists `Claude` with `scope == "write"` even when the request
    body named something else.
  - `test_consent_refuses_a_non_web_redirect`: `decide` returns `"javascript:alert(1)"` → 400.
  - `test_disconnect_an_app`: 204, `revoke_grant` called with the grant's `client_id` and `"test-access-token"`.
  - `test_unknown_ids`: token and grant routes → 404 for a random UUID.
- [ ] **Step 2:** Run `uv run pytest tests/test_api_assistants.py -q` — expected: FAIL.
- [ ] **Step 3:** Implement; add api.md rows ("Assistants" heading) and the isolation entries and id checks.
- [ ] **Step 4:** Run `uv run pytest -q` — expected: all pass.
- [ ] **Step 5:** `make check`, then commit: `Assistant tokens, connected apps and the consent screen under /api`.

### Task 6: Erase, Delete my account and the data page's options

**Files:**
- Modify: `app/routers/data.py`, `app/schemas/data.py`, `tests/test_isolation.py`, `docs/developer/api.md`
- Modify: `app/routers/web/profile.py` (use the shared `confirmed` helper)
- Test: `tests/test_api_parity.py` (new section "your data")

**Interfaces:**
- Produces, in `app/routers/data.py` (these three take `Depends(require_cookie_session)` on the route):

| Method | Path | Body | Answer |
|---|---|---|---|
| `GET` | `/data-options` | — | `DataOptions{can_import: bool, can_restore: bool, confirm_word: str, can_delete_login: bool}` |
| `POST` | `/erase` | `Confirmation{confirm: str}` | 204; 400 `"Type {email or DELETE} to confirm."` |
| `POST` | `/delete-account` | `Confirmation{confirm: str}` | 204 with cookies cleared; 400 as above; 503 `"Deleting your login is not set up here: ask the person who runs finode."`; 503 `"Your data was erased, but removing your login failed. Try again, or ask the person who runs finode."` |

- `confirmed(user: CurrentUser, typed: str) -> bool` moves from `web/profile.py` to `app/routers/data.py`.
- Isolation: `POST /api/erase` and `POST /api/delete-account` in `OWN_DATA`, `GET /api/data-options` in `LISTS`; extend `test_b_erasing_their_own_books_leaves_a_alone` to erase
  through `POST /api/erase` as well.

- [ ] **Step 1: Write the failing tests** in `tests/test_api_parity.py`:
  - `test_erase_needs_the_confirm_word`: `{"confirm": "nope"}` → 400; `{"confirm": "TEST@example.com"}` → 204 and
    `GET /api/transactions/` is empty.
  - `test_delete_account_when_logins_cannot_be_deleted`: → 503 with the first message; books untouched.
  - `test_delete_account`: monkeypatch `settings.supabase_service_role_key`, `settings.supabase_url` and
    `app.routers.data.delete_user` → 204, cookies cleared, profile gone.
  - `test_data_options`: `confirm_word == "test@example.com"`, `can_import` and `can_restore` as the services say.
- [ ] **Step 2:** Run `uv run pytest tests/test_api_parity.py -q -k "erase or delete_account or data_options"` —
  expected: FAIL.
- [ ] **Step 3:** Implement; api.md rows; isolation entries.
- [ ] **Step 4:** Run `uv run pytest -q` — expected: all pass.
- [ ] **Step 5:** `make check`, then commit: `Erase, Delete my account and the data options under /api`.

### Task 7: Payee chips under `/api`

**Files:**
- Create: `app/services/payee_suggestions.py`
- Modify: `app/routers/transactions.py`, `app/schemas/transaction.py`, `app/routers/web/transactions.py`,
  `tests/test_isolation.py`, `docs/developer/api.md`
- Test: `tests/test_payee_suggestions.py` (extend)

**Interfaces:**
- Produces, in `app/services/payee_suggestions.py`: `SUGGESTED_PAYEES = 6`, `SUGGESTED_PEOPLE = 8`,
  `suggested_payees(names: list[str], query: str = "", limit: int = SUGGESTED_PAYEES) -> list[str]` (moved),
  `suggest(transactions: TransactionService, contacts: ContactService, payee: str, only: str = "") -> PayeeSuggestions`
  (today's `suggest_payees` body without the template).
- Schema: `PersonChip{id: UUID, name: str}`, `PayeeSuggestions{names: list[str], people: list[PersonChip]}`.
- Route: `GET /api/transactions/payee-suggestions?payee=&only=` → `PayeeSuggestions`, declared before
  `/{transaction_id}`. The web route renders the same result into `partials/payee_chips.html`.
- Isolation: `LISTS`.

- [ ] **Step 1: Write the failing tests** in `tests/test_payee_suggestions.py`:
  - `test_api_payee_suggestions_match_the_chips`: record payees `"Swiggy"` ×2, `"Swiggy Instamart"`, `"Zepto"` →
    `?payee=swi` gives `names == ["Swiggy", "Swiggy Instamart"]`, `people == []`.
  - `test_api_suggests_people_after_an_at`: a contact `"Ada"` → `?payee=@a` gives `people == [{"id": …, "name": "Ada"}]`.
  - `test_api_only_people`: `?payee=swi&only=people` → `names == []`.
- [ ] **Step 2:** Run `uv run pytest tests/test_payee_suggestions.py -q` — expected: FAIL.
- [ ] **Step 3:** Implement; point existing imports of `suggested_payees` at the new module; api.md row; isolation.
- [ ] **Step 4:** Run `uv run pytest -q` — expected: all pass.
- [ ] **Step 5:** `make check`, then commit: `Payee suggestions under /api`.

### Task 8: Rules, docs and the whole-branch check

**Files:**
- Modify: `AGENTS.md` (the "JSON API parity" rule: the API now also covers sign-in, sign-up, assistants, connected
  apps, Erase and Delete my account; nothing is left out on purpose any more), `docs/developer/reference/assistants.md`
  and `docs/developer/reference/data-and-ops.md` (the new routes, cookie-only rule), `README.md` (Supabase:
  the reset-mail template and OAuth consent URL will point at `app.<domain>` from step 9; until then they stay as
  they are).

- [ ] **Step 1:** Update the docs above.
- [ ] **Step 2:** Run `make check` and `scripts/browser-tests.sh` (and `FINODE_BROWSER=webkit scripts/browser-tests.sh`)
  — expected: all unit tests and 189 browser tests pass on both browsers, i.e. today's pages are unchanged.
- [ ] **Step 3:** Commit: `Docs and rules for the completed API`, then `git push -u origin feature/react-frontend`.

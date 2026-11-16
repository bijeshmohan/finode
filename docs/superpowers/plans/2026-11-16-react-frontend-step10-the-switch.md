# React frontend step 10: the switch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The React app becomes finode's only UI, at `https://finode.bijesh.me`.
- The Jinja pages, `app.js`, htmx, `style.css`, the web routers and their tests go, with no dead code left behind.
- `AGENTS.md` and the docs describe one UI.
- The branch is merged and deployed on the owner's "Merge and deploy".
- Afterwards the owner removes the `app.finode.bijesh.me` DNS record.

**Architecture:** one address, two containers behind Traefik (the owner's decision, 2026-11-16).
- `finode.bijesh.me/api/…`, `/mcp` and `/.well-known/…` (and `/docs`, `/redoc`, `/openapi.json`, which only answer
  when `FINODE_API_DOCS` is on) go to the API container (`app`).
- Every other path on `finode.bijesh.me` goes to the React container (`web`), which answers every app address with the
  app.
- The app and the API share one origin, so:
  - the app calls `/api` relatively, with no `VITE_API_URL` and no `apiUrl()`;
  - there is no CORS;
  - the sign-in cookies (host-only on `finode.bijesh.me`) and today's sessions carry on as they are;
  - the assistants' `/mcp` address doesn't change;
  - Supabase's Site URL, reset link (`/reset`) and consent path (`/oauth/consent`) already point at the right host and
    the right app routes.
- The check on cookie writes (`check_app_request`) keeps `X-Finode: 1` and requires `Origin` to be the request's own
  origin (scheme and host as the proxy reports them). `FINODE_FRONTEND_ORIGIN` and `WEB_DOMAIN` go.
- The files both UIs shared (tokens, font, icons, favicon) move into `frontend/`.
- The formatting the API and the assistants still use (`money`, `grouping_for`, …) moves out of `templating.py` into a
  module with no Jinja.

**Tech Stack:** as built: FastAPI, React, TypeScript and Vite, nginx, Docker Compose and Traefik v3.

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md`, step 10: "The switch: delete the Jinja2 pages,
`app.js`, web routers and their tests; update `AGENTS.md` (drop "No JavaScript build step", add the frontend rules) and
`docs/`; redirect the old domain | all checks green, then "Merge and deploy"".
- **Superseded by the owner, 2026-11-16:** the app takes the old domain itself, so there is nothing to redirect.
- **Also superseded:** the spec's separate `app.` and `api.` hosts become one host.

## Global Constraints

- **Tests:** no test that guards the books is lost.
  - A test that asserts what is saved, refused or worked out moves to the `/api` route that does the same, unless an
    existing API test already asserts it.
  - A test that asserts how an old page looks goes, with the React test that covers that screen named.
  - Every removed test gets a ledger row: `Triage: <file>::<test> → ported to <test> | covered by <test> | old page
    only`.
- **Guard tests stay as strong:** isolation, query counts, read memory, contrast, dark-token parity, backup round-trip,
  ledger edges and fuzz, API parity. Each one that read an old page or file is pointed at what replaces it, never
  dropped.
- **The suite stays green** after every task: the old layer goes in Task 7, once nothing depends on it.
- **No dead code:**
  - what only the old pages used goes: routers, templates, static files, flash, web auth, Jinja helpers, CSS, `app.js`;
  - the cross-origin machinery the one address makes needless goes too: CORS, `VITE_API_URL`, `apiUrl()`,
    `FINODE_FRONTEND_ORIGIN` and `WEB_DOMAIN`;
  - `vulture` (once, through `uvx`, not added) and a grep for each removed name confirm it.
- **Cookie writes stay guarded:** `X-Finode: 1` and an `Origin` equal to the request's own origin. A request from any
  other origin is refused, as before.
- **Secrets, dates and tenant rules** are unchanged (`AGENTS.md`).
- **The deploy is the switch.**
  - It happens only on the owner's "Merge and deploy".
  - Before it: a verified fresh dump, the running images tagged `finode:pre-switch` and `finode-web:pre-switch`, and
    `.env` copied.
  - The rollback is the old images with `develop`'s compose file before the merge (Task 11).
- **Branches:** `develop` takes the branch with a merge commit; `main` gets a PR only if the owner asks.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A rule that was tested only through an old page loses its test.** Every removed test needs a ledger row naming its
   port or its cover; the reviewer samples the rows against the code.
2. **The one address:**
   - each of these reaches the right container: `/api/…`, `/mcp`, `/mcp/`, `/.well-known/oauth-protected-resource/mcp`,
     `/`, `/login`, `/reset?token_hash=…`, `/oauth/consent?authorization_id=…`, `/accounts/<id>`;
   - a path that merely starts with "api" or "mcp" (`/apiary`, `/mcpx`) goes to the app;
   - the service worker never answers `/api`, `/mcp` or `/.well-known` with the app's page.

   Test in Task 7 (compose rules and the browser test server), checked live in Task 11.
3. **Cookie writes:**
   - with CORS gone and the origin read from the request, a write from another origin, from no origin, or without
     `X-Finode` is still refused;
   - behind Traefik the request's own origin reads `https://finode.bijesh.me`, not `http://…:8000`.

   Test in Task 7, checked live in Task 11.
4. **The guards point at the right files after the move:**
   - contrast and dark-token parity read `frontend/src/styles/tokens.css`;
   - icon parity becomes "`icons.json` is the one source";
   - query ceilings cover every view endpoint that had a page twin;
   - isolation still fails on an unclassified route.

   Test in Tasks 1 and 7.
5. **The switch itself:**
   - the old pages are gone and `finode.bijesh.me/` is the app;
   - a session made before the switch still works;
   - `/mcp` with a token answers 200;
   - the rollback restores the old pages.

   Checked in Task 11.

---

### Task 1: The shared files move into the app; the guards follow them

**Files:**
- Move to `frontend/src/styles/` and `frontend/public/`:
  - `app/static/tokens.css`;
  - `app/static/fonts/`;
  - `favicon.svg` and `apple-touch-icon.png` (one copy each).
- Keep the old pages working until Task 7: they read the moved files through the same `/static/...` URLs, mounted
  from the new place.
- Modify: `frontend/vite.config.ts` (drop the `@static` alias and `server.fs.allow`), `frontend/src/main.tsx` and
  `frontend/Dockerfile` (no more `app/static`, so the build context becomes `frontend/` with its own `.dockerignore`).
- Modify the guards:
  - `tests/test_contrast.py` and the dark-token parity test;
  - `tests/test_icon_parity.py`, renamed `test_icons.py`: `icons.json` is valid and every `Icon name` used in `src/`
    exists in it;
  - `tests/test_motion_css.py`, which reads the reduced-motion rule in `frontend/src/styles/base.css`;
  - `tests/test_format_cases.py`, which holds React and the Python formatting to the same answers, not the Jinja
    filters.
- Test: those guard tests, `npm run check`, `scripts/check-web-image.sh`, the browser tests.

- [ ] **Step 1:** Point each guard test at the new paths. Run it. Expected: FAIL, because the files have not moved.
- [ ] **Step 2:** `git mv` the files, and mount `/static` from the new folder for the old pages. Run Step 1 again.
  Expected: PASS.
- [ ] **Step 3:** Run the whole check. Expected: green. Commit `The shared look moves into the app`.

### Tasks 2–6: Triage the tests that use old pages, by area

The same procedure for each area:
1. List the tests in the area that call an old page.
2. For each test:
   - **Ported:** write the API test first. It passes at once when the API already behaves that way; it must not be
     weaker than the old one.
   - **Covered:** name the existing API, Vitest or browser test.
   - **Old page only:** say so.
3. Delete or trim the old tests, and add the ledger rows.
4. Run the whole check, then commit `Tests of <area> through the API`.

| Task | Area | Files (old-page calls) |
|---|---|---|
| 2 | Accounts, groups, categories | `test_web_accounts.py`, `test_web_accounts_page.py`, `test_categories.py`, `test_account_groups.py`, `test_pinned_accounts.py`, `test_web_fixed_parents.py`, `test_close_accounts.py`, `test_account_depth.py`, `test_currency.py`, `test_limits.py`, `test_fixed_parents.py`, `test_web_quick_account.py`, `test_indian_grouping.py`, `test_rupee_and_auto.py` |
| 3 | Entries, transactions, tags, recurring | `test_web_transaction_form.py`, `test_web_transactions.py`, `test_related_transactions.py`, `test_web_tags.py`, `test_payee_suggestions.py`, `test_register_paging.py`, `test_transactions_sheet_search.py`, `test_transaction_references.py`, `test_recurring.py`, `test_recurring_skip.py`, `test_recurring_tags.py`, `test_posting_dates.py`, `test_ledger_edges.py`, `test_ledger_integrity.py`, `test_opening_fold.py`, `test_clock.py` |
| 4 | Budgets, Coming up, to-do, cards | `test_web_budget.py`, `test_web_budget_heads.py`, `test_budget.py`, `test_budget_categories.py`, `test_upcoming.py`, `test_coming_up.py`, `test_todo_card_bills.py`, `test_card_bills.py`, `test_pace_marker.py`, `test_new_user_ease.py`, `test_web_dashboard.py` |
| 5 | People | `test_web_people.py`, `test_people_through_plus.py`, `test_loan_payments.py`, `test_api_people_views.py` (its two old-page calls) |
| 6 | Sign-in, settings, data, assistants | `test_web_auth.py`, `test_web_signup.py`, `test_password_reset.py`, `test_web_profile.py`, `test_web_data.py`, `test_erase.py`, `test_backup.py` (its old-page calls), `test_web_assistants.py`, `test_mcp_oauth.py`, `test_manage_access.py`, `test_mcp_tools.py` (its old-page calls), `test_test_notice.py`, `test_web_flash.py`, `test_web_layout.py`, `test_web_assets.py`, `test_root.py`, `test_ios_controls.py` |

`test_isolation.py` and `test_query_counts.py` are handled in Task 7. A file missing from this table that calls an old
page is found by Task 7's check and triaged there.

### Task 7: The old layer goes; one address for the app and the API

**Files:**
- Delete:
  - `app/routers/web/`, `app/templates/`, `app/static/`, `app/flash.py`, `app/web_auth.py` and `app/templating.py`;
  - the web parts of `app/dependencies.py` and `app/main.py` (the `/static` mount, the `LoginRequired` handler, the
    page middlewares; keep any the API uses);
  - the static branch of `app/caching.py`;
  - the CORS middleware and `cors_options`;
  - `tests/htmlutil.py`, the old-page browser tests (every `tests/browser/test_*.py` that is not `test_spa_*`, each
    with its ledger row naming the `test_spa_*` port) and the `page`/`live_server` fixtures.
- Create: `app/formatting.py`, taking from `templating.py` what the API and the assistants use (`money`,
  `grouping_for`, `group_digits`, `places`, `symbol`, `amount` and the date words they need).
- Modify:
  - `app/auth.py` (`check_app_request`: the request's own origin);
  - `app/config.py` (drop `frontend_origin`);
  - the MCP server's `website_url`, which becomes the request's own origin, as `/.well-known` already builds its
    addresses;
  - `frontend/src/api/client.ts` (no `API_URL`, no `apiUrl()`), its callers and `env.d.ts`;
  - `frontend/vite.config.ts` (the service worker's `navigateFallbackDenylist` adds `/mcp` and `/.well-known`);
  - `compose.yaml`;
  - `scripts/check-web-image.sh` (no API address built in; the bundle names no other host);
  - `.env.example`;
  - `tests/test_isolation.py` (drop the web routes and the `web_login_required` override);
  - `tests/test_query_counts.py` (only `/api/views/*` in `PAGES`, with the same ceilings);
  - `tests/conftest.py`, `tests/test_api_cookie_auth.py` and `Dockerfile` with `.dockerignore`.
- Change `compose.yaml` like this:
  - the `app` router's rule becomes ``Host(`${APP_DOMAIN}`) && (PathPrefix(`/api/`) || Path(`/api`) || Path(`/mcp`) || PathPrefix(`/mcp/`) ||
    PathPrefix(`/.well-known/`) || Path(`/docs`) || Path(`/redoc`) || Path(`/openapi.json`))``, with `priority: 100`;
  - the `web` router's rule becomes ``Host(`${APP_DOMAIN}`)``, with `priority: 1`;
  - `VITE_API_URL` and `WEB_DOMAIN` go.

- [ ] **Step 1: Write the failing tests:**
  - **`tests/test_api_cookie_auth.py`:** a cookie write whose `Origin` equals the request's own origin
    (`http://testserver`) passes. Another origin, no origin, or no `X-Finode` gets `403`. Behind a proxy that sends
    `X-Forwarded-Proto: https` and `Host: finode.example`, `Origin: https://finode.example` passes and
    `http://finode.example` doesn't.
  - **`tests/test_routes.py`:** the API answers nothing outside `/api`, `/mcp`, `/.well-known` and the docs. Every
    route of `app.routes` is under those prefixes.
  - **`tests/test_compose_routes.py`:** load `compose.yaml` and assert the two routers' rules and priorities as above.
    A `/apiary` path must not match the `app` rule; the rule's matcher is reproduced in the test from the rule's
    `PathPrefix`/`Path` parts.

  Run them. Expected: FAIL.
- [ ] **Step 2: Delete the old layer and make the one address:**
  - write `formatting.py`, the origin check and the compose rules;
  - drop CORS, `frontend_origin`, `VITE_API_URL`, `apiUrl()` and `WEB_DOMAIN`.

  Run Step 1 again, then the whole check. Expected: PASS and green.
- [ ] **Step 3: Remove dead code:**
  - `uvx vulture app --min-confidence 60`; check each candidate by hand and remove what only the old pages used;
  - grep the repo for every removed name (`templating`, `flash`, `htmx`, `hx-`, `web_auth`, `frontend_origin`,
    `FINODE_FRONTEND_ORIGIN`, `WEB_DOMAIN`, `VITE_API_URL`, `apiUrl`, `static/`);
  - grep `tests/` for old-page calls (`client.(get|post)("/[^a]`) and for `htmlutil`.

  Expected: none left outside history and plans.
- [ ] **Step 4: Run the whole check**, `scripts/check-web-image.sh` included. Expected: green. Commit
  `The old pages go; the app and the API share one address`.

### Task 8: One set of browser tests

- [ ] Rename:
  - each `tests/browser/test_spa_*.py` to `test_*.py`;
  - the fixtures `spa_page` → `page`, `signed_in_spa_page` → `signed_in_page`, `spa_api` → `api`, `spa_books` →
    `books` and `spa_server` → `server`;
  - `tests/browser/spa.py` → `server.py`, which already serves the app and the API on one address, as production now
    does.

  Use `git mv` and `sed`, with no other change in the same commit.
- [ ] Run both browsers. Expected: the same number of tests passing. Commit `One set of browser tests`.

### Task 9: One UI in `AGENTS.md` and the docs

- [ ] **`AGENTS.md`:**
  - drop "No JavaScript build step" and the Jinja-only Web UI rules (`hx-post`, `htmx_redirect`, `MESSAGES`,
    `HX-Retarget`, `partials/`, `safe_back`, `hide_fab`, `app.js` helpers);
  - keep the look rules, now for the app (tokens, phones first, rows and tiles, 16px inputs, green and red for money);
  - the Frontend section becomes the UI section;
  - the description at the top: one UI, the React app, at the same address as the API.
- [ ] **The docs:**
  - `docs/developer/reference/ui-look.md` and `ui-pages.md` describe the app's components and pages;
  - also update `data-and-ops.md` (Docker: the one address and the two routers; the cookie-write check), `assistants.md`
    (the consent screen is the app's), `people.md`, `budget.md` and `ledger.md` wherever they name a template or an
    old route;
  - `docs/index.md`'s architecture and the user guide;
  - `code-map.md` and `api.md`;
  - `README.md`: setup, the Supabase steps and deployment.
- [ ] Run the whole check, `test_api_doc` included. Commit `One UI in the docs`.

### Task 10: Final review and its fix pass

- [ ] Build the review package over Tasks 1–9, and dispatch one fresh reviewer on the most capable model with this
  Review Focus and the ledger.
- [ ] Re-grade by effect. Run one fix pass, each fix RED→GREEN, then the whole check.
- [ ] Report to the owner:
  - every ruling and deferred minor;
  - the triage totals;
  - what the deploy does;
  - then wait for "Merge and deploy".

### Task 11: Merge and deploy (the owner's word only)

- [ ] **Merge:**
  - `git fetch origin develop`, then merge `origin/develop` into the branch;
  - run the whole check;
  - `git checkout develop && git merge --no-ff feature/react-frontend`, then push `develop`;
  - note the `develop` commit before the merge, for the rollback.
- [ ] **Safety:**
  - a verified fresh dump;
  - `docker tag finode:latest finode:pre-switch` and `docker tag finode-web:latest finode-web:pre-switch`;
  - `.env` copied (mode 600) into the scratchpad.
- [ ] **Deploy:**
  - remove `FINODE_FRONTEND_ORIGIN` and `WEB_DOMAIN` from `.env`;
  - `docker compose up -d --build`, which switches Traefik's routes;
  - remove `finode-web-check` leftovers if any.
- [ ] **Smoke checks:**
  - `finode.bijesh.me/` is the app's page;
  - `/login` and `/reset?token_hash=x` are the app;
  - `/api/auth/options` → `200` JSON;
  - `/mcp` → `401` without a token;
  - `/.well-known/oauth-protected-resource/mcp` → `200`;
  - a `POST /api/auth/sign-out` with `Origin: https://evil.example` → `403`;
  - `app.finode.bijesh.me` no longer routes (its router is gone), so the owner can remove the record;
  - no errors in the logs.
- [ ] **The owner signs in** at `https://finode.bijesh.me` (a session from before the switch should carry on). Then
  they remove the `app.finode.bijesh.me` DNS record. A home-screen icon added from `app.finode.bijesh.me` is
  re-added from `finode.bijesh.me`.
- [ ] **Rollback, if needed:**
  - check out the pre-merge `develop` commit's `compose.yaml`;
  - restore `.env`;
  - `docker tag finode:pre-switch finode:latest && docker tag finode-web:pre-switch finode-web:latest &&
    docker compose up -d --no-build`.

  No database change to undo.
- [ ] Update memory. Ask the owner whether `develop` should go to `main` by PR. Delete the scratchpad `.env` copy once
  confirmed.

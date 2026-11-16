# React frontend step 10: the switch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The React app becomes finode's only UI.
- The Jinja pages, `app.js`, htmx, `style.css`, the web routers and their tests go.
- Every old page address sends the browser to the same address on the app.
- `AGENTS.md` and the docs describe one UI.
- The branch is merged and deployed on the owner's "Merge and deploy".

**Architecture:**
- `finode.bijesh.me` keeps the API, `/mcp` and `/.well-known`. Any other `GET` or `HEAD` there answers `308` to the
  same path and query on `FINODE_FRONTEND_ORIGIN`.
- `app.finode.bijesh.me` (the `web` container) is the UI.
- The files both UIs shared (tokens, font, icons, favicon) move into `frontend/`.
- The formatting the API and the assistants still use (`money`, `grouping_for`, …) moves out of `templating.py` into a
  module with no Jinja.

**Tech Stack:** as built: FastAPI, React, TypeScript and Vite, nginx, Docker Compose and Traefik.

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md`, step 10: "The switch: delete the Jinja2 pages,
`app.js`, web routers and their tests; update `AGENTS.md` (drop "No JavaScript build step", add the frontend rules) and
`docs/`; redirect the old domain | all checks green, then "Merge and deploy"".

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
- **The suite stays green** after every task: the old layer goes last (Task 7), once nothing depends on it.
- **The API stays at `finode.bijesh.me`.** Assistants' connector URLs (`/mcp`), the sign-in cookies and the OAuth
  resource metadata don't move. The spec's `api.<domain>` is left for later, if the owner wants it.
- **Redirects:**
  - only `GET` and `HEAD`, with path and query kept: `308`, which keeps the method;
  - anything else at an old page address gets `404`;
  - never for `/api`, `/mcp`, `/.well-known`, `/docs`, `/redoc` or `/openapi.json`;
  - with `FINODE_FRONTEND_ORIGIN` empty (development, tests), `404`.
- **Secrets, dates and tenant rules** are unchanged (`AGENTS.md`).
- **The deploy:**
  - only on the owner's "Merge and deploy";
  - a verified fresh dump first;
  - the running images tagged `finode:pre-switch` and `finode-web:pre-switch`.
- **Branches:** `develop` takes the branch with a merge commit; `main` gets a PR only if the owner asks.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A rule that was tested only through an old page loses its test.** Every removed test needs a ledger row naming its
   port or its cover; the reviewer samples the rows against the code.
2. **Old addresses:**
   - a bookmark, a home-screen icon or an emailed reset link (`/reset?token_hash=…`), and `/oauth/consent?…` while
     Supabase still points there, reach the same screen on the app with the query intact;
   - `/api/*` and `/mcp` answer exactly as before, with no redirect;
   - a `POST` to an old form address gets `404`, not a redirect that re-sends a form.

   Test in Task 7.
3. **The guards point at the right files after the move:**
   - contrast and dark-token parity read `frontend/src/styles/tokens.css`;
   - icon parity becomes "`icons.json` is the one source";
   - query ceilings cover every view endpoint that had a page twin;
   - isolation still fails on an unclassified route.

   Test in Tasks 1 and 7.
4. **Dead code:** helpers only the old pages used are removed; nothing the API, the views or the assistants use is.
   `vulture` (run once with `uvx`, not added) lists candidates; each one is checked by hand.

   Checked in Task 7.
5. **The deploy:**
   - the old pages are gone, and `finode.bijesh.me/` sends people to the app;
   - a cookie session made on either host still works on the API;
   - `/mcp` with a token still answers 200;
   - the rollback (both images tagged) works.

   Checked in Task 11.

---

### Task 1: The shared files move into the app; the guards follow them

**Files:**
- Move to `frontend/src/styles/` and `frontend/public/`:
  - `app/static/tokens.css`;
  - `app/static/fonts/`;
  - `favicon.svg` and `apple-touch-icon.png` (the app's `public/` copies stay, one copy each).
- Keep the old pages working meanwhile: they read the moved files through the same `/static/...` URLs, mounted from
  the new place, until Task 7.
- Modify: `frontend/vite.config.ts` (drop the `@static` alias and `server.fs.allow`) and `frontend/src/main.tsx`.
- Modify: `tests/test_contrast.py`, the dark-token parity test, `tests/test_icon_parity.py` (rename to
  `test_icons.py`: `icons.json` is valid and every `Icon name` used in `src/` exists in it), `tests/test_motion_css.py`
  (the reduced-motion rule in `frontend/src/styles/base.css`) and `tests/test_format_cases.py` (React and the Python
  formatting module, not the Jinja filters).
- Test: those guard tests, `npm run check`, the browser tests.

- [ ] **Step 1:** In each guard test, point it at the new paths. Run it. Expected: FAIL, because the files have not
  moved.
- [ ] **Step 2:** `git mv` the files; mount `/static` from the new folder for the old pages. Run Step 1 again.
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

### Task 7: The old layer goes; old addresses lead to the app

**Files:**
- Delete:
  - `app/routers/web/`, `app/templates/`, `app/static/` (what is left of it), `app/flash.py` and `app/web_auth.py`;
  - the web parts of `app/dependencies.py` and `app/main.py` (the `/static` mount, the `LoginRequired` handler, the
    flash and cookie-refresh middlewares the pages used; keep any the API uses), and the static branch of
    `app/caching.py`;
  - `tests/htmlutil.py`, the old-page browser tests (every `tests/browser/test_*.py` that is not `test_spa_*`,
    each with its ledger row naming the `test_spa_*` port), and the `page`/`live_server` fixtures.
- Create:
  - `app/formatting.py`, taking from `templating.py` what the API and the assistants use (`money`, `grouping_for`,
    `group_digits`, `places`, `symbol`, `amount` and the date words they need), with `templating.py` deleted;
  - `app/routers/old_addresses.py`, the redirect;
  - `tests/test_old_addresses.py`.
- Modify:
  - `tests/test_isolation.py`: drop the web routes and the `web_login_required` override;
  - `tests/test_query_counts.py`: keep only `/api/views/*` in `PAGES`, with the same ceilings;
  - `tests/conftest.py`;
  - the MCP server's `website_url`, which becomes `settings.frontend_origin` (falling back to no link);
  - `Dockerfile` and `.dockerignore`.

- [ ] **Step 1: Write `test_old_addresses.py`.** With `FINODE_FRONTEND_ORIGIN=https://app.example`:
  - `GET /accounts?x=1` → `308`, `Location: https://app.example/accounts?x=1`;
  - `HEAD /` → `308`;
  - `GET /reset?token_hash=abc` → `308` to `…/reset?token_hash=abc`;
  - `GET /oauth/consent?authorization_id=a` → `308` to the same on the app;
  - `POST /transactions/new` → `404`;
  - `GET /api/accounts/` → its usual answer;
  - `GET /api/nope` → `404` JSON;
  - `POST /mcp` with no token → `401`;
  - `GET /.well-known/oauth-protected-resource/mcp` → `200`.

  With the origin unset, `GET /accounts` → `404`. Run it. Expected: FAIL, because today the old pages answer.
- [ ] **Step 2: Delete the old layer** and write `formatting.py` and the redirect, the last route registered. Run
  Step 1 again, then the whole check. Expected: PASS and green.
- [ ] **Step 3: Remove dead code.** `uvx vulture app --min-confidence 60`; check each candidate by hand and remove what
  only the old pages used. Then grep `tests/` for old-page calls (`client.(get|post)("/[^a]`) and `htmlutil`.
  Expected: none left; any left goes through the triage.
- [ ] **Step 4: Run the whole check.** Expected: green. Commit `The old pages go; their addresses lead to the app`.

### Task 8: One set of browser tests

- [ ] Rename:
  - each `tests/browser/test_spa_*.py` to `test_*.py`;
  - the fixtures `spa_page` → `page`, `signed_in_spa_page` → `signed_in_page`, `spa_api` → `api`, `spa_books` →
    `books` and `spa_server` → `server`;
  - `tests/browser/spa.py` → `server.py`.

  Use `git mv` and `sed`, with no other change in the same commit.
- [ ] `scripts/browser-tests.sh` and CI: unchanged commands. Run both browsers. Expected: the same number of tests
  passing. Commit `One set of browser tests`.

### Task 9: One UI in `AGENTS.md` and the docs

- [ ] **`AGENTS.md`:**
  - drop "No JavaScript build step" and the Jinja-only Web UI rules (`hx-post`, `htmx_redirect`, `MESSAGES`,
    `HX-Retarget`, `partials/`, `safe_back`, `hide_fab`, `app.js` helpers);
  - keep the look rules, now for the app (tokens, phones first, rows and tiles, 16px inputs, green and red for money);
  - the Frontend section becomes the UI section;
  - the description at the top: one UI, the React app.
- [ ] **The docs:**
  - `docs/developer/reference/ui-look.md` and `ui-pages.md` describe the app's components and pages (CSS Modules,
    `components/`, `features/`), not the templates;
  - also update `data-and-ops.md`, `assistants.md` (the consent screen is the app's), `people.md`, `budget.md` and
    `ledger.md` wherever they name a template or an old route;
  - `docs/index.md`'s architecture and the user guide;
  - `code-map.md`;
  - `README.md`: setup, the Supabase steps with the Site URL on the app, and deployment.
- [ ] Run the whole check, `test_api_doc` included. Commit `One UI in the docs`.

### Task 10: Final review and its fix pass

- [ ] Build the review package over Tasks 1–9, and dispatch one fresh reviewer on the most capable model with this
  Review Focus and the ledger.
- [ ] Re-grade by effect. Run one fix pass, each fix RED→GREEN, then the whole check.
- [ ] Report to the owner:
  - every ruling and deferred minor;
  - the triage totals;
  - the Supabase change in Task 11;
  - then wait for "Merge and deploy".

### Task 11: Merge and deploy (the owner's word only)

- [ ] **The owner, in Supabase (Authentication › URL Configuration):**
  - set the Site URL to `https://app.finode.bijesh.me`;
  - add it to the redirect URLs;
  - keep the OAuth Server's authorization path as `/oauth/consent`, now under the app;
  - the Reset Password template's `{{ .SiteURL }}/reset` then opens the app's reset screen.

  I check with a consent request and a reset email if reset is on.
- [ ] **Merge:**
  - `git fetch origin develop`, then merge `origin/develop` into the branch;
  - run the whole check;
  - `git checkout develop && git merge --no-ff feature/react-frontend`, then push `develop`.
- [ ] **Safety:** a verified fresh dump, and `docker tag finode:latest finode:pre-switch` and
  `docker tag finode-web:latest finode-web:pre-switch`.
- [ ] **Deploy:** `docker compose up -d --build` from `develop`.
- [ ] **Smoke checks:**
  - `finode.bijesh.me/` → `308` to the app;
  - `/login` → `308`;
  - `/mcp` → `401` without a token;
  - `/api/auth/options` → `200`;
  - the app signs in;
  - no errors in the logs.
- [ ] **Rollback:** `docker tag finode:pre-switch finode:latest && docker tag finode-web:pre-switch finode-web:latest
  && docker compose up -d --no-build app web`. No database change to undo.
- [ ] Update memory and the code map. Ask the owner whether `develop` should go to `main` by PR.

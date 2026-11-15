# React frontend, step 8: Settings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the last placeholder, Settings, and the pages under it in the React app as today's pages are:
- **Settings** (`/settings`):
  - your name;
  - Currency and Appearance;
  - the Your data links (Backup, export and import · Tags · People · Recurring transactions · AI assistants);
  - About (Send feedback, About this test);
  - Sign out.
- **Your data** (`/profile/data`):
  - Export (ledger, CSV) and Backup, with Restore (preview, then confirm);
  - Import (preview, then confirm);
  - Erase my books and Delete my account.
- **AI assistants** (`/profile/assistants`):
  - what is connected (signed-in apps and tokens), with their access and Disconnect / Revoke;
  - Sign in with Claude (the address to copy);
  - Use a token (name, access, the secret shown once with the setup filled in);
  - the setup instructions.
- **The consent screen** (`/oauth/consent?authorization_id=`): the app asking to connect, the three access levels, Deny.

After this step no page of the app is a placeholder.

**Architecture:** Step 1 already gave the API everything these pages do; this step adds no route.
- **Reads:**
  - `/api/profile/` and `/api/profile/currencies`;
  - `/api/auth/session` (`email`, `feedback_url`, `can_delete_login`) and `/api/auth/options` (`test_notice`);
  - `/api/data-options`, `/api/assistants/`, `/api/oauth/consent/{authorization_id}`.
- **Writes:**
  - `PATCH /api/profile/`;
  - `POST /api/import` and `/api/restore` (`dry_run=true` for the preview; the file as multipart);
  - `POST /api/erase`, `/api/delete-account`;
  - `/api/assistants/tokens…` and `…/apps…`;
  - `POST /api/oauth/consent/{authorization_id}`;
  - `POST /api/auth/sign-out`.
- **Downloads** (`/api/export`, `/api/backup`) are plain links to the API's address: `app.` and `api.` are one site, so the
  session cookie goes with them, and the API answers with `Content-Disposition: attachment`.
- **The theme** was a cookie the server read on the web pages. The app is static files on another host, so it keeps the
  choice in the browser (`localStorage`, key `finode_theme`). A small script in `index.html` sets `data-theme` before
  the first paint, as `base.html` does. The page says so already ("Applies to this browser only").
- **The app:** pages live in `frontend/src/features/settings/` (Settings, Your data, AI assistants) and
  `features/consent/`.

**Tech Stack:** React, React Router, TanStack Query, Vitest, Python `pytest-playwright`.

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md` (step 8: "Settings, data (import/export/
backup/restore), assistants, consent — as above", i.e. their browser tests ported).

## Global Constraints

- **Branch:** `feature/react-frontend` only; nothing reaches `develop`. `make` is not installed: run what it runs.
- **Earlier constraints:** all Global Constraints of steps 2 to 7b hold:
  - strict TypeScript; amounts as strings, never `Number`;
  - `useApi()`, `useToday()`, tokens only;
  - `npm run check` clean; exact dependency versions;
  - a component used by two features lives in `src/components`.
- **Today's pages stay exactly as they are.** No server code changes. The proof is the web tests and the whole browser
  suite (344 on each browser before this step).
- **Security:**
  - the Supabase service key stays server-side: never render, log or send it to the browser;
  - a token's secret is shown once, from the create answer only, and kept in no cache or storage;
  - Erase and Delete my account go only through the cookie session (`require_cookie_session`), as the API already
    insists;
  - the consent screen sends the browser only to the `redirect_url` the API checked (`is_web_url`).
- **Wording is today's.** It comes from:
  - the templates `settings.html`, `profile_data.html`, `assistants.html`, `oauth_consent.html` and the partials
    `connections.html`, `access.html`, `mcp_setup.html`, `token_created.html`, `import_preview.html`,
    `restore_preview.html` and `test_notice.html`;
  - the flash texts `profile-updated`, `currency-updated`, `books-erased`, `your-account-deleted`, `import-done`,
    `restore-done`, `token-revoked`, `access-changed` and `app-disconnected`;
  - the API's own refusals.
- **Shared parts move to `src/components/`:** `TestNotice` (sign-up and Settings) and the copy button (the assistants
  page and the token card), as `CopyButton`.
- **Not here:** the side-by-side run (step 9) and the switch (step 10).

## Review Focus

1. **The theme:**
   - a choice applies at once, survives a reload and is in place before the first paint (no flash of the other theme);
   - `Match device` removes it;
   - the row's value says the choice;
   - it touches only this browser.

   Test in Task 1.
2. **Erase my books and Delete my account:**
   - each asks the browser's confirmation, then needs the confirm word typed exactly; a wrong word shows the API's
     `Type {word} to confirm.`;
   - after Erase the app goes Home with every view refreshed and toasts `books-erased`'s text;
   - after Delete the session is gone (the cache cleared too) and the sign-in screen shows `your-account-deleted`'s
     text;
   - with `can_delete_login` false the row only explains.

   Test in Task 2.
3. **Import and restore:**
   - a preview comes first; Confirm shows only when the preview has no errors;
   - errors and warnings are listed as the web partials list them;
   - after confirming the app goes Home, every view refreshed;
   - with `can_import` / `can_restore` false the rows say why instead;
   - a file too big, of the wrong kind or not chosen shows the API's words.

   Test in Task 2.
4. **A token's secret is shown once:**
   - after Create, the card shows the secret and the setup snippets filled with it, and the list refreshes;
   - leaving the page and coming back shows no secret;
   - Revoke and the access buttons ask as the web page does (`Revoke '{name}'? Assistants using it stop working at
     once.`, `Let {who} record, edit and delete transactions?`, …);
   - Disconnect works the same for a signed-in app.

   Test in Task 3.
5. **The consent screen:**
   - an authorization already decided sends the browser straight back to its `redirect_url`;
   - a refusal (unknown id, an address finode does not allow) shows `Can't connect` with the API's words and the way
     back to AI assistants;
   - arriving signed out goes to sign-in and comes back with the `authorization_id`;
   - Deny sends back too.

   Test in Task 3.

---

### Task 1: Settings, the theme and sign out

**Files:**
- Create in `frontend/src/features/settings/`:
  - `SettingsPage.tsx`, `queries.ts`;
  - `Settings.module.css` (from `.settings`, `.setting`, `.setting-title`, `.setting-value`, `.settings-label`,
    `.signout-row`, `.grid-form`);
  - tests.
- Create: `frontend/src/lib/theme.ts` (`readTheme()`, `chooseTheme(choice)`, the `Theme` type), with its test.
- Modify:
  - `frontend/index.html`: the script that sets `data-theme` from `localStorage` before the app loads;
  - `app/router.tsx` (`/settings`; the `Placeholder` and its folder go);
  - `features/auth/TestNotice.tsx` → `components/TestNotice.tsx`.
- Test: `tests/browser/test_spa_settings.py` (ported from `test_settings_page.py`).

**Interfaces:**
- **A row** is a disclosure (a button with `aria-expanded`, the title, the value at the right, the chevron) that opens
  its form below, or a link. Opening `/settings#currency` (or `#name`, `#appearance`) opens that row.
- **The name row:**
  - title `{first last}` or `Your profile`, value the email;
  - `First name`, `Last name` (max 40);
  - the hint `Your email ({email}) is used to sign in and can't be changed here.`;
  - `Save name` → `PATCH /api/profile/`, toasting `Profile saved`.
- **Currency:**
  - the hint `Changing it only changes the label: nothing is converted.`;
  - a select labelled `Currency` of `{code} · {name}`;
  - `Save currency` toasts `Currency saved`. Every view refreshes, and the amounts take the new symbol.
- **Appearance:**
  - `Applies to this browser only.`;
  - `Match device` · `Light` · `Dark`, as pressed buttons in a group labelled `Theme`;
  - the value reads the choice.
- **Your data:** the five links (`/profile/data`, `/tags`, `/people`, `/recurring`, `/profile/assistants`).
- **About:**
  - `Send feedback` when `feedback_url` is set;
  - `About this test` (value `Please read`) opening the `TestNotice` when `test_notice` is on.
- **Sign out:** a red row. It sends `POST /api/auth/sign-out`, clears the query cache and goes to `/sign-in`.
- `lib/theme.ts`: `chooseTheme("auto" | "light" | "dark")` stores the choice (`localStorage`, wrapped in try/catch)
  and sets or removes `data-theme` on `<html>`. The `index.html` script reads the same key.

- [ ] **Step 1: Write the failing Vitest tests:**
  - each row's title and value;
  - saving the name and the currency (bodies, toasts);
  - the hash opening a row;
  - Appearance storing and applying the choice, and `Match device` removing it;
  - feedback and the test notice only when set;
  - sign out (sent, cache cleared, on `/sign-in`);
  - `theme.test.ts`.
- [ ] **Step 2:** Run `cd frontend && npx vitest run src/features/settings src/lib/theme.test.ts`.
  - Expected: FAIL.
- [ ] **Step 3:** Build it, and move `TestNotice`.
- [ ] **Step 4: Port the browser tests** into `tests/browser/test_spa_settings.py`:
  - saving the currency shows the new one (and the amounts on Home follow);
  - a touched row is not painted grey;
  - values sit beside the chevron and Sign out is a red row;
  - the theme survives a reload with `data-theme` set before the app's script runs;
  - sign out lands on the sign-in screen and a page then asks to sign in again.
- [ ] **Step 5:** Run Step 2's command, `npm --prefix frontend run check` and `scripts/browser-tests.sh -q -k
  "spa_settings or spa_shell or spa_sign_in"`.
  - Expected: all PASS.
- [ ] **Step 6:** Commit: `Settings, the theme and sign out in the app`.

### Task 2: Your data

**Files:**
- Create in `frontend/src/features/settings/`: `DataPage.tsx`, `ImportRestore.tsx` (the preview and confirm of
  either), tests.
- Modify:
  - `frontend/src/api/client.ts`: `apiUrl(path)`, the API's own address for a link (the client's `baseUrl`);
  - `app/router.tsx` (`/profile/data`).
- Test: `tests/browser/test_spa_data.py` (ported from `test_erase.py`, with import and restore).

**Interfaces:**
- **Export:**
  - `Ledger format opens in hledger and similar tools; CSV opens in a spreadsheet.`;
  - links `Export ledger file` (`apiUrl("/api/export?format=ledger")`) and `Export CSV`, each with `download`.
- **Backup:**
  - the hint, and `Download backup` (`apiUrl("/api/backup")`);
  - then, by `can_restore`: `Restore a backup` with a file field (`.json`) and `Preview restore`, or `Restoring only
    works on an empty ledger.`
- **Import:**
  - by `can_import`: the hint, a file field and `Preview import`;
  - or `Importing is only available before you record transactions. Export your data first if you want to start
    over.`
- **A preview** (`POST …?dry_run=true`, multipart `file`) draws what `import_preview.html` / `restore_preview.html`
  draw:
  - the counts;
  - the errors (no Confirm then) and the warnings;
  - a `Confirm import` / `Confirm restore` button that sends the same file without `dry_run`.

  On success it toasts `Import complete` / `Backup restored`, refreshes every view and goes to `/`. A refusal on
  confirm draws the preview again with its errors.
- **Erase my books:**
  - the hint;
  - `Type {confirm_word} to confirm` and a field;
  - `Erase my books` asks `Erase all your accounts, transactions and budget? This cannot be undone.`, then sends
    `POST /api/erase {confirm}`. Success toasts `Your books were erased`, refreshes every view and goes to `/`.
- **Delete my account:**
  - with `can_delete_login`: the hint, the word, and `Delete my account` asking `Delete your account and everything in
    it? This cannot be undone.`, then `POST /api/delete-account`. Success clears the cache and goes to `/sign-in` with
    `Your account was deleted. Goodbye!`.
  - otherwise only `Deleting your login isn't set up here. Erase your books above and ask the person who runs finode
    to remove your login.`
- The two danger rows sit under `Erase or leave`, with the red title the web page gives them.

- [ ] **Step 1: Write the failing Vitest tests:**
  - the export and backup links;
  - each `can_*` reading;
  - a preview with counts, errors and warnings, and Confirm only without errors;
  - a confirm sent without `dry_run`, then Home;
  - Erase with a wrong word (the API's refusal shown) and a right one;
  - Delete with and without `can_delete_login`.
- [ ] **Step 2:** Run `cd frontend && npx vitest run src/features/settings`.
  - Expected: FAIL.
- [ ] **Step 3:** Build the page.
- [ ] **Step 4: Port the browser tests** into `tests/browser/test_spa_data.py`:
  - erasing the books;
  - deleting the account (with the login removal stood in for, as `test_erase.py` does);
  - an import of a small ledger file previewed then confirmed;
  - a backup downloaded and restored into empty books (preview, confirm);
  - the export links download a file.
- [ ] **Step 5:** Run Step 2's command, `npm --prefix frontend run check` and `scripts/browser-tests.sh -q -k
  "spa_data or erase"`.
  - Expected: all PASS.
- [ ] **Step 6:** Commit: `Your data in the app`.

### Task 3: AI assistants and the consent screen

**Files:**
- Create:
  - `frontend/src/features/settings/AssistantsPage.tsx`, `Access.tsx` (the three access levels in words, shared by the
    token form and the consent screen; `access.html`), `McpSetup.tsx` (`mcp_setup.html`), tests;
  - `frontend/src/features/consent/ConsentPage.tsx`, `Consent.module.css`, tests;
  - `frontend/src/components/CopyButton.tsx`.
- Modify: `app/router.tsx` (`/profile/assistants`; `/oauth/consent` inside the signed-in routes, so a signed-out
  arrival goes to sign-in with `next`).
- Test: `tests/browser/test_spa_assistants.py`.

**Interfaces:**
- **Connected** (`/api/assistants/`): each app and token as `connections.html` lists it:
  - the name, the access badge (`read only` / `read & write` / `read, write & manage accounts`);
  - `Signed in · connected {day} · last used {day}` or `never used`, or `Token {prefix}… · created {day} · …`;
  - the access buttons (`Make read only`, `Stop account changes`, `Allow changes`, `Allow account changes`, with the web
    page's confirmations);
  - `Disconnect` / `Revoke` with theirs.

  `Nothing connected yet.` when empty. Changes toast `access-changed` / `token-revoked` / `app-disconnected`'s text.
- **Sign in with Claude:** the hint and the `mcp_url` with a `Copy` button.
- **Use a token:**
  - `Name` with its hint;
  - `Access` (`Read` · `Write` · `Manage`) with the chosen level's words under it;
  - `Create token` → `POST /api/assistants/tokens`.

  The answer's secret goes into the card `{name} is ready`, with `Copy token` and the setup filled in. It is held in
  the page's state only: leaving the page drops it.
- **Setup instructions for tokens:** `McpSetup` with `YOUR_TOKEN`.
- `CopyButton({ text, label })`: `navigator.clipboard.writeText` inside the click, falling back to selecting the text;
  it says `Copied` for a moment.
- **The consent screen** (`/oauth/consent?authorization_id=`):
  - no id: `Can't connect` with `This page is opened by an app that wants to connect. Start from the app's connector
    settings.`;
  - a `redirect_url` in the answer: `window.location.assign(redirect_url)` at once;
  - otherwise `Connect {client_name}?`, the line about the app (with `client_uri`), the three `Access` cards each with
    its `Allow …` button, the note, and `Deny`.

  A decision sends `POST /api/oauth/consent/{id}` and then goes to the answer's `redirect_url`. A refusal shows `Can't
  connect` with the API's words and the back link `AI assistants`.

- [ ] **Step 1: Write the failing Vitest tests:**
  - the connected list for apps and tokens, and the empty text;
  - each access button with its confirmation, and its body;
  - Revoke and Disconnect;
  - creating a token: the body, the card with the secret and the filled setup, and no secret after leaving and coming
    back;
  - the copy buttons;
  - consent: no id, already decided (`assign` called), allow each level, deny, a refusal.
- [ ] **Step 2:** Run `cd frontend && npx vitest run src/features/settings src/features/consent`.
  - Expected: FAIL.
- [ ] **Step 3:** Build the pages.
- [ ] **Step 4: Write the browser tests** in `tests/browser/test_spa_assistants.py`:
  - a token created shows its secret once and works against `/mcp`;
  - revoking it stops it;
  - changing access;
  - the consent screen with Supabase's authorization stood in for (monkeypatched `app.oauth` as the web tests do):
    allowing records the app and sends the browser to the redirect; a signed-out arrival comes back after sign-in.
- [ ] **Step 5:** Run Step 2's command, `npm --prefix frontend run check` and `scripts/browser-tests.sh -q -k
  "spa_assistants"`.
  - Expected: all PASS.
- [ ] **Step 6:** Commit: `AI assistants and the consent screen in the app`.

### Task 4: Docs and the whole check

**Files:**
- Modify:
  - `docs/developer/code-map.md` (`features/settings`, `features/consent`, `lib/theme.ts`, the `placeholder/` folder
    gone);
  - `docs/developer/reference/ui-pages.md` (the app keeps the theme in the browser).

- [ ] **Step 1:** Update the docs.
- [ ] **Step 2: Run the whole check:**
  - `uv run ruff check app tests migrations scripts`, `uv run ruff format --check app tests migrations scripts`,
    `uv run pyrefly check`;
  - `uv run pytest -q -p no:cacheprovider`;
  - `npm --prefix frontend run check`;
  - `scripts/browser-tests.sh -q -p no:cacheprovider`, and the same with `FINODE_BROWSER=webkit`.
  - Expected: all PASS.
- [ ] **Step 3:** Commit `Docs for Settings`, then `git push origin feature/react-frontend`.

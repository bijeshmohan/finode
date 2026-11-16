# React frontend step 9: side by side — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The React app runs at `https://app.finode.bijesh.me`, against the feature branch's backend deployed as
`finode.bijesh.me`. The owner uses it on real books, and today's pages stay where they are.

**Architecture:**
- The built app is served by a small static container (`web`, nginx) in `compose.yaml`, behind the Traefik that
  already serves finode.
- The app calls the API at `https://finode.bijesh.me` (`VITE_API_URL`, set at build time), and the API allows that one
  origin (`FINODE_FRONTEND_ORIGIN`).
- The sign-in cookies stay host-only on `finode.bijesh.me`. The two hosts are same-site (`bijesh.me`), so `SameSite=Lax`
  cookies go with the app's credentialed calls.
- Before the trial, the Add screen gets the one parity gap still known: the note under a person on a transfer.

**Tech Stack:** nginx (alpine image, exact tag), Docker Compose, Traefik v3 with Let's Encrypt (already running), Node
from `frontend/.nvmrc` (26.13.1) for the build stage.

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md`. Step 9 reads "Side by side: the React app on
`app.<domain>`; the owner uses it, old pages stay on the current domain | the owner is happy with it". The open
decisions were settled by the owner on 2026-11-15:
- the trial backend is the branch, deployed to production;
- the address is `app.finode.bijesh.me`;
- the app is served by a container behind Traefik.

## Global Constraints

- Nothing reaches `develop` before step 10. The branch is deployed to production from this checkout; `develop` and
  `main` are untouched.
- The deploy (Task 4) stops for the owner's go-ahead before `docker compose up`. Before deploying:
  - the newest file in `backups/` is from today's 02:00 UTC run;
  - a fresh dump is taken;
  - the running image is tagged `finode:pre-trial`, so a rollback is one command.
- Preview servers touch the production database through the recurring loop. Anything started locally for screenshots
  runs with `FINODE_DATABASE_URL=sqlite:///…` and `FINODE_RECURRING_INTERVAL_MINUTES=0`, and is killed afterwards.
- The Supabase service key stays server-side: never rendered, logged or sent to the browser. The `web` container gets no
  `.env`; its only setting is the build argument `VITE_API_URL`.
- Images are pinned to exact tags: `node:26.13.1-alpine` and an exact `nginx:<x.y.z>-alpine`, checked with `docker pull`.
- The React app's only money arithmetic is `lib/split.ts` (big.js); amounts stay strings.
- The note's words are the web's, exactly (`app/static/app.js`, `noteForPeople`).
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; pushes go to `feature/react-frontend` only.

## Review Focus

1. **Deep links and stale chunks:**
   - every app address serves `index.html` (`/accounts/<id>`, `/oauth/consent?authorization_id=…`, `/profile/data#erase`);
   - a missing `/assets/*.js` answers 404, never `index.html`. Otherwise a tab left open across a redeploy loads HTML as
     a script and shows a white screen.

   Test in Task 2.
2. **A redeploy reaches people:**
   - `index.html`, `sw.js` and `manifest.webmanifest` are sent `Cache-Control: no-cache`; `sw.js` and its `workbox-*.js`
     are real scripts (the app registers the worker itself, so there is no `registerSW.js`);
   - hashed `/assets/*` are `public, max-age=31536000, immutable`.

   Test in Task 2.
3. **The two hosts:**
   - only `https://app.finode.bijesh.me` gets CORS answers with credentials;
   - a cookie write from any other origin is refused;
   - signing in on the app leaves today's pages signed in too (one cookie, one host);
   - Safari on the owner's iPhone keeps the session.

   Checked in Task 4 (curl, then the owner).
4. **Today's pages and assistants after the deploy:**
   - `/`, `/sign-in` and `/mcp/` answer as before (`/mcp/` gives 401 without a token);
   - the recurring loop still runs once (one backend only);
   - an assistant's connector URL is unchanged.

   Checked in Task 4.
5. **The transfer note:**
   - each of the web's six sentences appears for its case: nothing owed, no amount yet, part, in full, more than owed,
     and each side;
   - the note follows the row's amount, or the total when the row has none;
   - typed grouping (`1,00,000`) and a currency with no decimals both work;
   - the note goes away when no person is on the entry.

   Test in Task 1.

---

### Task 1: The note under a person on a transfer

**Files:**
- Modify: `frontend/src/lib/split.ts` (add `personNote`), `frontend/src/lib/split.test.ts`.
- Modify: `frontend/src/features/entry/EntryScreen.tsx` (the Add screen; the recurring form, which shares
  `components/lines`, has no note on the web either), with the note under the rows, as the web's
  `[data-person-note]` sits.
- Modify (only if Step 1 finds it missing): the entry-form view's People options, so each carries `balance`.
- Test: `tests/browser/test_spa_people.py`: ports of `tests/browser/test_people.py`'s note assertions (lines 26, 49, 51, 126, 199).

**Interfaces:**
- Consumes: the entry-form view's People options (`PickOptionRead.balance`): positive means they owe you, negative
  means you owe them, as `data-owes` on the web.
- Produces: `personNote(person: { name: string; owes: string }, toThem: boolean, amount: string, currency: Currency): string`.
  `amount` is the row's amount, or else the total, as typed (grouping allowed); `""` counts as zero. `money()` from
  `lib/money.ts` formats the figures.

- [ ] **Step 1: Check the view gives what the person owes.** Read the API's entry-form answer for a ledger with a
  person (`/api/views/entry-form`) in an existing test; the People options' `balance` must be set. If it is `None`,
  add a failing test in `tests/test_api_views*.py` first, then fill it from the same service the web page uses.
- [ ] **Step 2: Write the failing unit tests** in `split.test.ts`, one per sentence, with Alice and INR:
  - owes `0`, to them: `Alice will owe you this. It is not spending, so your budgets stay as they are.`
  - owes `0`, from them: `You will owe Alice this. It is not income, so your budgets stay as they are.`
  - owes `500`, from them, amount `""`: `Alice owes you ₹500.00. This pays it back first.` (the figure as `money()`
    writes it)
  - owes `500`, from them, amount `200`: `Alice pays back ₹200.00 of the ₹500.00 owed to you.`
  - owes `500`, from them, amount `500`: `Alice pays back in full.`
  - owes `500`, from them, amount `1,200`: `Alice pays back ₹500.00. The other ₹700.00 is borrowed: you will owe Alice it.`
  - owes `-300`, to them: `You pay back ₹100.00 of the ₹300.00 you owe Alice.` (amount 100), `You pay back Alice in
    full.` (amount 300), `You pay back ₹300.00. The other ₹50.00 is lent: Alice will owe you it.` (amount 350).
  - owes `500` but to them (they owe you, you give more): `Alice will owe you this. …` (nothing owed in that direction).
  - a JPY case with no decimals: owes `500`, from them, amount `200`.
- [ ] **Step 3: Run them.** `npm --prefix frontend run test -- split`. Expected: FAIL, `personNote` is not exported.
- [ ] **Step 4: Implement `personNote`** with big.js, following `noteForPeople`'s branches exactly. The figures go
  through `money()`. Run Step 3 again. Expected: PASS.
- [ ] **Step 5: Write the failing browser tests**, ported from the web ones named above, with the `signed_in_spa_page`
  fixture. Run them (`scripts/browser-tests.sh -k spa_people`). Expected: FAIL, no note.
- [ ] **Step 6: Show the note.** On the Add screen, for the last row that names a person (as the web loops and keeps
  the last), render `<p className=… aria-live="polite">{note}</p>` only when there is a note. Take `owes` from the
  picked option's `balance`, and `toThem` from the row's side (debit = to them). Run Step 5 again. Expected: PASS.
- [ ] **Step 7: Run the whole frontend check.** `npm --prefix frontend run check`. Expected: exit 0.
- [ ] **Step 8: Commit** `The Add screen says what a transfer with a person does` and push.

### Task 2: The `web` container and its deploy docs

**Files:**
- Create:
  - `frontend/Dockerfile` (stage 1: `node:26.13.1-alpine`, `npm ci`, `ARG VITE_API_URL`, `npm run build`; stage 2: the
    pinned nginx alpine image, `dist/` into `/usr/share/nginx/html`, `nginx.conf`);
  - `frontend/nginx.conf`;
  - `frontend/.dockerignore` (`node_modules`, `dist`, `*.log`).
- Create: `scripts/check-web-image.sh`, the test. It builds the image, runs it on a free local port with no network
  beyond loopback, checks each case below with `curl`, and removes the container on exit.
- Modify: `compose.yaml`. Add a `web` service:
  - `build: { context: frontend, args: { VITE_API_URL: "https://${APP_DOMAIN}" } }`, `restart: unless-stopped`,
    `networks: [proxy]`, no `env_file`;
  - Traefik labels on ``Host(`${WEB_DOMAIN:?set WEB_DOMAIN in .env}`)``, the same entrypoint and resolver as `app`,
    port 80.

  Document `WEB_DOMAIN` in the header comment.
- Modify: `docs/developer/reference/data-and-ops.md` (Docker), `README.md` (deploy), `docs/developer/code-map.md`:
  - the `web` service;
  - `WEB_DOMAIN` and `FINODE_FRONTEND_ORIGIN` in `.env`;
  - the DNS A record;
  - that the API stays on `APP_DOMAIN`;
  - the rollback (`docker tag finode:pre-trial finode:latest && docker compose up -d --no-build app`).

**Interfaces:**
- Produces: the image `finode-web`, serving the built app on port 80; the `.env` keys `WEB_DOMAIN` and
  `FINODE_FRONTEND_ORIGIN`.

- [ ] **Step 1: Pin the images.** `docker pull node:26.13.1-alpine`, and `docker pull` the newest stable
  `nginx:<x.y.z>-alpine`. Expected: both pulled for this machine's architecture (arm64). Record the nginx tag in the
  ledger.
- [ ] **Step 2: Write the failing check** `scripts/check-web-image.sh`. It exits non-zero on the first case that does
  not hold:
  - `/` → 200, `text/html`, `Cache-Control: no-cache`;
  - `/accounts/00000000-0000-4000-8000-000000000001`, `/oauth/consent?authorization_id=x` and `/profile/data` → 200
    with the same `index.html` body;
  - the first `/assets/*.js` named in `index.html` → 200, `application/javascript` or `text/javascript`,
    `Cache-Control: public, max-age=31536000, immutable`;
  - `/assets/missing-0000.js` → 404 (not HTML);
  - `/sw.js` and `/manifest.webmanifest` → 200 with `no-cache`; `/sw.js` and the `workbox-*.js` it names are JavaScript, not the page (the manifest
    `application/manifest+json`);
  - every answer has `X-Content-Type-Options: nosniff` and `Referrer-Policy: same-origin`;
  - `index.html` names `https://finode.bijesh.me` as the API: the build argument reached the bundle (grep the built
    JS);
  - no answer contains the strings `supabase_service_role_key`, `sb_secret_` or `FINODE_`.

  Run it. Expected: FAIL (no Dockerfile).
- [ ] **Step 3: Write `Dockerfile`, `.dockerignore` and `nginx.conf`:**
  - `location /assets/ { try_files $uri =404; … immutable }`;
  - an exact-match location for each no-cache file;
  - `location / { try_files $uri /index.html; no-cache }`;
  - `server_tokens off`;
  - the two headers with `always`;
  - gzip for text types.

  Run Step 2 again. Expected: PASS.
- [ ] **Step 4: Add the `web` service** to `compose.yaml`. Run `docker compose config --quiet` with
  `WEB_DOMAIN=app.finode.bijesh.me APP_DOMAIN=finode.bijesh.me`. Expected: exit 0. Run it again without `WEB_DOMAIN`.
  Expected: it fails, naming `WEB_DOMAIN`.
- [ ] **Step 5: Write the docs** listed above.
- [ ] **Step 6: Run the whole check** (ruff, format, pyrefly, pytest, `npm --prefix frontend run check`, both browsers,
  `scripts/check-web-image.sh`). Expected: all green.
- [ ] **Step 7: Commit** `The React app's own container behind Traefik` and push.

### Task 3: The final review and its fix pass

- [ ] Build the review package over Tasks 1–2 (`review-package <this plan> <BASE of Task 1> HEAD`). Dispatch one fresh
  reviewer on the most capable model with this plan's Review Focus and the ledger's rulings.
- [ ] Re-grade by effect. Run one fix pass with each fix RED→GREEN, run the whole check again, then commit and push.
- [ ] Report to the owner: every ruling, every deferred minor, and the deploy steps of Task 4. Wait for the go-ahead.

### Task 4: The deploy (only on the owner's go-ahead)

- [ ] **Step 1: The owner adds the DNS record:** `A app.finode.bijesh.me → 129.154.41.151`, not proxied, like
  `finode.bijesh.me`. Check: `dig +short app.finode.bijesh.me`. Expected: `129.154.41.151`.
- [ ] **Step 2: Safety:**
  - `ls -t backups | head -1`. Expected: today's `finode-<date>T020000Z.sql.gz`.
  - `docker compose exec backup /bin/sh /backup.sh` (or the script's one-off form). Expected: a new dump file.
  - `docker tag finode:latest finode:pre-trial`.
- [ ] **Step 3: `.env`:** add `WEB_DOMAIN=app.finode.bijesh.me` and
  `FINODE_FRONTEND_ORIGIN=https://app.finode.bijesh.me`. Show the owner the two lines only; never print the file.
- [ ] **Step 4: Deploy** from this checkout (`feature/react-frontend` at the reviewed head):
  `docker compose up -d --build`. Expected: `migrate` completes, then `app`, `backup` and `web` are running.
- [ ] **Step 5: Smoke checks** with `curl` from this machine:
  - `https://finode.bijesh.me/sign-in` → 200 HTML;
  - `https://finode.bijesh.me/mcp/` with no token → 401;
  - `https://app.finode.bijesh.me/` → 200 with a valid certificate;
  - `OPTIONS https://finode.bijesh.me/api/auth/session` with `Origin: https://app.finode.bijesh.me` → it allows that
    origin with credentials;
  - the same with `Origin: https://evil.example` → no allow-origin;
  - `docker compose logs app` shows the recurring loop starting once and no tracebacks.
- [ ] **Step 6: The owner signs in** at `https://app.finode.bijesh.me` on the phone (Safari) and on the computer, and
  checks in that same browser that today's pages are still signed in. Then they add the app to the home screen. On iOS
  an installed app keeps its own cookies, apart from Safari, so it asks to sign in once.
- [ ] **Rollback, if anything is wrong:**
  - `docker tag finode:pre-trial finode:latest && docker compose up -d --no-build app`;
  - `docker compose rm -sf web`;
  - remove `FINODE_FRONTEND_ORIGIN` from `.env`, and keep `WEB_DOMAIN`. This checkout's `compose.yaml` requires it for
    every compose command, and it does nothing once `web` is gone.

  No database change needs undoing: the branch changes no tables.

### Task 5: The trial

- [ ] Before the trial:
  - publish a private side-by-side page for the owner: each page in today's UI and in the app, at phone width, light
    and dark;
  - make it from a local copy seeded with `tests/books.py` on SQLite (see Global Constraints), never from the
    production data;
  - check the theme-colour status bar there (step 8's deferred ruling).

  The script lives in the scratchpad, not the repo: step 10 deletes the old pages.
- [ ] Each thing the owner reports:
  - write a test that fails;
  - fix it on `feature/react-frontend`;
  - run the whole check;
  - redeploy with `docker compose up -d --build web app`;
  - say what changed.
- [ ] Done when the owner says they are happy with it. Then write the step 10 plan (the switch).

# The app: conventions, look and motion

How the finode app (`frontend/`, React + TypeScript + Vite) is built and how it looks and moves: amounts, signs, tiles, sheets, dark mode, the design system. Dates in headings are when a decision was made; most were made on the server-rendered pages the app replaced on 2026-11-17 and carried over unchanged. The rules summary is in `AGENTS.md`.

## How the app is put together

- **One address.** The app is static files served by the `web` container (nginx); the API answers on the same address (Traefik sends `/api`, `/mcp`, `/.well-known` and the API docs to the `app` container). The app calls `/api/...` on its own origin with the session cookie and `X-Finode: 1`; nothing else is built in.
- **Data.** Every screen reads its view endpoint (`/api/views/…`) through TanStack Query (`useApi()`, `data()`); cached views share the key prefix `["views"]` and a change to the books refreshes them all. Rows, totals, words and signs come from the server (`services/transaction_rows.py` and the `*_view.py` services); the app does no ledger arithmetic.
- **Layout** (`frontend/src/app/Layout.tsx`): on phones a slim top bar (the wordmark, the to-do bell, an avatar to Settings) and a bottom tab bar of four tabs (Home, Budgets, Accounts, Categories) with the **"+" docked in the middle** (nothing floats over the page). Transactions has no tab: it is reached from "View all" on Home and from the sidebar. From 60rem a fixed sidebar (the new-entry button, the four sections, Transactions last, Settings at the foot) replaces the bars, and the page is one calm column. The "+" stays on every screen, the Add and Edit screens included (2026-11-16). On an account's or a category's page the "+" starts an entry for it and comes back there (`frontend/src/app/newEntry.tsx`).
- **The tab's title** is the screen's name and "finode" ("Accounts · finode"): each route's `handle: { title }` in `frontend/src/app/router.tsx`, or, once loaded, the name of the account, category, person or budget group shown (`useTabTitle`, `frontend/src/app/title.tsx`). Home is plain "finode". A new screen gets a title; `frontend/src/app/title.test.tsx` lists the routes without one.
- **Forms** end in one full-width primary button with no Cancel (the back link is the cancel; sheets keep theirs). A screen opened from several places takes `back`, passed through `lib/safeNext.ts` (only an address inside the app).

## Amount fields

`AmountField` and `lib/amount.ts`: as it is typed or pasted an amount keeps only digits, commas and **one** decimal point (none for a currency without decimals), and no more decimals than the currency keeps (rupees 2, yen 0); zeros in front are dropped. When the field is left it is written out whole (`tidyAmount`: `1.` is 1.00, `.5` is 0.50; empty stays empty). The server checks again (`check_places`). Amounts are strings end to end, never `Number`.

On a new entry the amount takes the focus only on a computer (`(hover: hover) and (pointer: fine)`); on a phone the grey 0.00 stays until the first digit, since focusing would raise the keypad over the screen. The rupee sign sits right against the digits and the field is as wide as what is typed, with no box or ring around it.

## Lakhs and crores

For INR the whole part of an amount is grouped the Indian way (`12,34,567.00`), every other currency in thousands (`1,234,567.00`): `groupingFor` in the app, `formatting.grouping_for` on the server for the few sentences it words itself. `backend/tests/format_cases.json` holds both to the same answers. Only the rupee is grouped this way.

## The rupee sign and what was added automatically

For INR the unit is the rupee sign, **in front**; in a large figure (`components/Figure`: Home, Budgets' Ready to assign, an account's balance) it is smaller (0.62 of the digits), muted and raised. Other currencies keep their code after the amount; the amounts in lists carry no unit. The sign comes from our own fonts (both IBM Plex files carry U+20B9). What an assistant or a recurring rule added is **violet** (`--auto`): the "Recurring" / "Added by Claude" line under a row and the matching facts in the details sheet.

## Signs and the pace notch

Lists show **no minus on ordinary spending**: income is `+` and green, transfers plain. A real negative (an overdrawn account, an overspent category's "left", a debt) keeps its `−` and red, and in a large figure the minus comes after the rupee sign (`₹−1,200.00`). **Green and "+" mean money coming in**: on an account's page that is what raises an asset and a payment into a card or loan. The server decides each row's sign (`inflow`, `negative` on the row).

Every progress bar is **3 px thick**, from the one token `--bar-h`: change it there, never per bar. Bars of the current month carry a **pace notch** (a small triangle under the bar) at how far through the month today is (`pace`, from `clock.month_progress`; none for other months).

## The "i" beside Home's and Budgets' figure

A round, faint `i` (`components/CalcInfo`) beside **Left to spend** (Home) and **Ready to assign** (Budgets) opens, under the figure, the sum behind it with the person's own numbers. Home: carried in + assigned this month − spent = left. Budgets: money in the accounts − set aside for card bills − left in the categories − assigned to later months = ready to assign (the panel shows the true figure; the headline stays at zero). Every line shows even at zero so the column adds up; a negative line flips its sign. If the budget's arithmetic changes, change these lines and their tests.

## Offline and failed saves

`frontend/src/app/Offline.tsx` shows "You're offline…" while the device has no connection. A save that cannot reach the server says "finode can't be reached" and a server failure "Something went wrong"; the server's own words show only when it gave them as JSON (`api/messages.ts`). **A form is never cleared on failure.** There is no offline queue: nothing is saved until the connection is back. Browser tests: `backend/tests/e2e/test_states.py`. Empty states are a short sentence and one next step (`components/EmptyState`).

## Bento tiles

Rows are grouped into soft rounded tiles (`components/Tile`: `--surface` with a `--tile-border` hairline, a hairline between rows, a gap between tiles): a tile per day in transaction lists, per group of categories on Budgets, per section in Settings. New lists reuse the tile, never their own borders.

## Contrast (2026-11-04)

`--muted` is `#5a6560` in light (5.3 : 1 on the paper, 5.9 : 1 on a tile, 4.8 : 1 on a grey chip) and `#949eb0` in dark; `--faint` (3.7 : 1) is for placeholders and glyphs, not sentences. `frontend/src/styles/tokens.test.ts` fails if `--muted` drops under 4.5 : 1 in either theme.

## The Ledger look (2026-11-21)

Replaced the passbook look (2026-11-07) on the owner's pick of three directions (proposal: https://claude.ai/artifact/7G2Jcdo9rEDwWyLARcPzCy). **Ink on near-white paper, and no brand colour**: the page is `--bg` `#f4f5f2`, tiles are white (`--surface`) with a hairline (`--tile-border`), text is ink (`--text` `#16181d`), and **whatever you can act on is the same ink** (`--accent`: the primary button, the docked "+", the chosen switcher chip, focus and every progress bar). Dark is the mirror: a near-black page (`#0e0f11`), off-white ink (`#eceee9`) for text and actions. Because the interface itself has no colour, **green (money in) and red (a real negative) are the only colours on a screen**, and violet only marks what was added automatically.

**Type** is IBM Plex (OFL), self-hosted in `frontend/src/styles/fonts/` (`README.txt` says how each file was cut; about 40 KB for all three): **IBM Plex Sans** (variable, weight 400–700) for text (`--font-sans`), and **IBM Plex Mono** (500 and 600) for amounts (`--font-figure`), so every figure in a list lines up at the decimal point like a passbook column. The big figures (Home, Budgets, Accounts, an account, the Add screen's amount) are Mono 500 at 2.5rem with tight tracking: a monospaced figure is wide, so do not make it bigger, or a crore no longer fits a phone. That figure is the one loud thing on a screen; keep everything else quiet.

**Labels** over a figure, a day's heading in a list, the Add screen's "Paid from" / "Spent on" and Settings' section names are small **uppercase** labels (0.72–0.75rem, weight 600, `letter-spacing: 0.07em`, `--muted`).

**Corners** follow what a thing is: tiles and sheets `--radius` (14px), fields `--radius-sm` (10px), buttons `--radius-button` (10px), the docked "+" a rounded square (`--radius`); chips and switchers stay fully round.

## Colours and dark mode

Every colour is a token in `frontend/src/styles/tokens.css`. Both dark blocks (the automatic `prefers-color-scheme` one and the chosen `data-theme="dark"` one) define the same tokens (`frontend/src/styles/tokens.test.ts`). The look (auto, light, dark) is chosen on Settings and kept in this browser (`lib/theme.ts`); `index.html` applies it before the first paint. Form fields use `--field-border`, stronger than the hairline `--border` in dark. `favicon.svg` and `apple-touch-icon.png` follow the ink palette (`favicon.svg` in both themes); the phone's status bar takes the page's own colour (`theme-color`).

## One design system (2026-10-23)

Every screen is made of the same parts (`frontend/src/components/`), so none looks like it came from another app:

- **Switcher** (`Chips`): one segmented control for every "which list" (Spending · Earning on Categories, the Add screen's Expense · Income · Transfer).
- **Row** (`Row`): a title, a quiet second line, the figure at the right. An entry with no payee leads with where the money went. Rows open a screen or a sheet; destructive actions live there, never on rows, and deleting is for good (the app asks first).
- **Head** (`components/Page.module.css`): the title row (with the month pill, `MonthPill`, where the screen has a month), a label over one large figure (`Figure`) and one quiet line under it; Accounts, Categories and Budgets open the same way.
- **Month pill** (`MonthPill`): ‹ Nov 2026 › as plain text, with the native month picker laid invisibly over the name.
- **Empty state** (`EmptyState`): a sentence and one pill button.
- **Day labels** in transaction lists carry what was spent that day at the right, on a day with more than one entry.

New screens reuse these parts, not draw their own. **Undo was removed** with the history (see [removed.md](removed.md)): a toast is a message only. **What needs a decision** sits under the bell (`features/todo`).

## Sheets and the wide screen

`components/Sheet` is a modal `<dialog>`: it slides up from the edge on phones and rises gently on wide screens, Escape and a tap on the dim area close it, and focus goes back to what opened it. **A press that starts inside a sheet never closes it**, even when the sheet moves under the finger. While a field in a bottom sheet has focus the sheet sits above the soft keyboard (`--kb`, and on an iPhone or iPad `--kb-bar` for Safari's form bar). Pickers are our own sheets (`components/lines/Picker`: a search, group headings, a balance beside an account, the other side's account greyed, "＋ New"), the same on iOS and Android.

From 60rem with a mouse (`(min-width: 60rem) and (hover: hover)`), a transaction's details open as a **panel beside the list** (`panelOnWide`: not modal, with a close button; another row replaces it). Phones, touch screens and narrower windows keep the bottom sheet.

## Motion

Sheets slide (CSS `@starting-style` on the dialog) and toasts rise in and fade. Reduced motion turns movement off; the browser tests run with reduced motion so measured positions never catch a screen mid-move.

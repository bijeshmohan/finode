# React frontend, step 4a: Home, Transactions and the transaction sheet — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Home, the Transactions page (month, filters, upcoming, show more) and a transaction's details (bottom sheet
on a phone, a panel beside the list on a wide screen, with Delete) in the React app, as today's pages show them.

**Architecture:** The rows of a list are built on the server, once: the row helpers move out of the web router into
`app/services/transaction_rows.py`, which the Jinja pages and four new **view endpoints** under `/api/views/` share.
A view endpoint answers what one screen shows in one call (Home's glance and first steps, a page of the list with its
summary and upcoming entries, the Filter sheet's choices, one transaction's details), so the React app formats
nothing it would otherwise have to work out twice. The React screens are built from step 2's components, with TanStack
Query (`useInfiniteQuery` for "Show more") and the month and filters in the URL.

**Tech Stack:** FastAPI, Pydantic, React, React Router, TanStack Query, Vitest, Python `pytest-playwright`.

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md` (step 4 of the build order, split: 4a here; 4b,
the Add/edit screen with the account picker and `big.js`, gets its own plan once 4a has landed). "Keeping it fast"
section: one combined endpoint per screen where that is cheaper.

## Global Constraints

- Branch `feature/react-frontend` only; nothing reaches `develop`. `make` is not installed: run what it runs.
- All Global Constraints of the step 2 and 3 plans hold (strict TypeScript, strings for money, `useApi()`,
  `useToday()`, tokens only, `npm run check` clean, exact versions).
- **Today's pages stay exactly as they are** for a person: the move of the row helpers changes no HTML (the 197
  browser tests are the proof).
- Every new `/api` route: a row in `docs/developer/api.md`, a classification in `tests/test_isolation.py`, a test, and
  a query-count ceiling in `tests/test_query_counts.py` no higher than the Jinja page it serves
  (`/api/views/home` ≤ 15, `/api/views/transactions` ≤ 12).
- View endpoints that list entries record what has fallen due first (`recurring.catch_up()`), as the pages do.
- Wording is today's (`dashboard.html`, `transactions.html`, `partials/transaction_days.html`, `txn_sheet.html`,
  `upcoming.html`, `get_started.html`, `calc_info.html`, `flash.py` `transaction-deleted`).
- Links to screens not rebuilt yet (Edit, Repeat, Related → the Add/edit screen of step 4b; a person's page; Recurring;
  the account and category pages) go to their future React addresses (`/transactions/{id}/edit`,
  `/transactions/new?repeat={id}`, `/transactions/new?related={id}`, `/people/{id}`, `/recurring`, `/accounts/{id}`,
  `/categories/{id}`), which show a placeholder until their step.

## Review Focus

1. A month with more entries than one page, where a day runs over the page's end: "Show more" must not repeat or
   drop an entry at the seam. Test in Task 2 (API) and Task 5 (browser).
2. Filters in the URL that point at something gone or not the person's (`?account=<another person's id>`,
   `?account=not-a-uuid`): an empty list or the error line, never a crash or someone else's names. Test in Task 2.
3. A transaction deleted from the sheet while "Show more" pages are loaded: the list refreshes without the entry and
   without duplicates. Test in Task 4.
4. Entries dated ahead in the current month: they show in the "upcoming" card, not in the list, and a past month has
   no upcoming card. Test in Task 2.
5. An amount with more than two decimals and a negative balance in Home's glance (overspent): written by `formatMoney`
   as the Jinja `money` filter writes it, the minus as U+2212, red only for the real negative. Test in Task 6.

---

### Task 1: One home for the rows of a list

A refactor: the row helpers leave `app/routers/web/transactions.py`.

**Files:**
- Create: `app/services/transaction_rows.py`
- Modify: `app/routers/web/transactions.py`, `app/routers/web/dashboard.py`, `app/routers/web/coming_up.py` (and any
  other importer: `grep -rn "from .transactions import" app/routers/web`), `app/templates/partials/transaction_days.html`

**Interfaces:**
- Produces in `app/services/transaction_rows.py` (moved unchanged unless noted): `AccountIndex`, `TransactionRow`,
  `to_row`, `list_rows`, `related_info`, `summary_of(found: list[TransactionRead], index: AccountIndex) -> Summary`
  (today's `_summary`, returning a `Summary` dataclass `count: int`, `total: Decimal | None`, `word: str`),
  `filter_options(...)` (today's `_filter_options`), `upcoming_items(ahead: list[TransactionRead], index) ->
  list[UpcomingItem]` (the loop in `transactions_page`), `PAGE_SIZE`, `UPCOMING_LIMIT`, `HOME_FIRST`, `HOME_MORE`,
  `KIND_FILTERS`. `UpcomingItem` moves here from `routers/web/utils.py`.
- `TransactionRow` gains two properties, the logic now in `transaction_days.html`:
  - `title -> str`: the payee, else the debit names joined with ", ".
  - `sub -> str`: for an opening balance or adjustment (`is_system`), the account names without "Opening Balances";
    with a payee, `credits → debits`; else the credits; then ` · ` and the note, except the stock note "Initial
    account balance" on a system row.
  - and `is_system -> bool`, `by_assistant -> str | None` ("Added by X" / "Changed by X", from `created_via` /
    `updated_via` starting `mcp:`), `recurring -> bool`.
- `transaction_days.html` uses `row.title`, `row.sub`, `row.is_system`, `row.by_assistant`, `row.recurring`.

- [ ] **Step 1:** `uv run pytest tests/test_web_transactions.py tests/test_web_dashboard.py tests/test_coming_up.py -q`
  — expected: PASS (the baseline).
- [ ] **Step 2: Write the failing test** `tests/test_transaction_rows.py`: `test_a_row_names_itself_as_the_list_does`
  — a payee entry (`title == "Swiggy"`, `sub == "Card → Food"`), one without a payee (`title == "Food"`,
  `sub == "Card"`), an opening balance (`sub == "Bank"`, no "Opening Balances", no stock note), a note
  (`sub` ends with ` · lunch`), an assistant's entry (`by_assistant == "Added by Claude"`).
- [ ] **Step 3:** Run it — expected: FAIL (no module).
- [ ] **Step 4:** Move the helpers; add the properties; point the template and importers at them.
- [ ] **Step 5:** Run Step 1's command, the new test and `scripts/browser-tests.sh -k "transactions_page or
  budget_page"` — expected: PASS.
- [ ] **Step 6:** Commit: `The rows of a list are built in one place, services/transaction_rows.py`.

### Task 2: View endpoints for the Transactions page and a transaction's details

**Files:**
- Create: `app/routers/views.py`, `app/schemas/views.py`, `tests/test_api_views.py`
- Modify: `app/main.py`, `tests/test_isolation.py`, `tests/test_query_counts.py`, `docs/developer/api.md`

**Interfaces** (router `prefix="/views"`, `tags=["views"]`, `dependencies=[Depends(require_authenticated_user)]`):
- `RowRead`: `id: UUID`, `date: date`, `title: str`, `sub: str`, `amount: Decimal`, `kind: Literal["expense",
  "income", "transfer"]`, `is_system: bool`, `is_opening: bool` (payee "Opening balance": folded when several share a
  day), `related: RelatedRef | None`, `recurring: bool`, `by_assistant: str | None`.
- `GET /views/transactions` — query `month` (`YYYY-MM`, default this month, never later), `account`, `category`,
  `merchant`, `tag`, `q`, `kind`, `offset` (≥ 0), `limit` (1–100, default `PAGE_SIZE`) → `TransactionsView`:
  `month: str`, `is_current: bool`, `rows: list[RowRead]`, `total: int`, `summary: SummaryRead | None` (only with an
  account, category, merchant or tag filter), `upcoming: list[UpcomingRead]` and `upcoming_total: Decimal | None` (only
  at `offset=0` of the current month), `error: str | None` (`"Invalid filter: …"`, as the page says), `applied:
  list[AppliedFilter]` (`key`, `label`, `name`). The same reads, in the same order, as `transactions_page` +
  `more_transactions`.
- `GET /views/transaction-filters` → `FilterOptions`: `accounts`, `categories` (each `id`, `name`, `sub`), `merchants`.
- `GET /views/transactions/{transaction_id}` → `TransactionDetails`: `row: RowRead`, `from_label`, `to_label`,
  `from_lines` / `to_lines` (`name`, `amount`, `posted_on: date | None`), `comment`, `tags`, `related_to: RowRead |
  None`, `related: list[RowRead]`, `person: PersonRef | None` (`id`, `name`), `loan_like: bool`, `with_names:
  list[str]`, `source`, `source_url`, `external_id`, `added_by: str | None`, `changed_by: str | None` (assistants'
  names, as the sheet prints them). 404 for an unknown or another person's id.
- Deleting uses the existing `DELETE /api/transactions/{transaction_id}`.
- Isolation: the two lists in `LISTS`; `{transaction_id}` is covered by the id sweep.

- [ ] **Step 1: Write the failing tests** in `tests/test_api_views.py` (the API fixtures of `tests/test_api_parity.py`):
  - `test_a_page_of_the_month`: 30 entries this month → `len(rows) == 25`, `total == 30`; `offset=25` gives the other
    5; together the 30 ids, none twice (Review Focus 1, with five on the last day of the first page).
  - `test_rows_say_what_the_list_says`: one row's `title`, `sub`, `kind`, `amount` equal Task 1's row for it.
  - `test_upcoming_is_apart_from_the_list`: an entry dated tomorrow → in `upcoming`, not in `rows`; a past month →
    `upcoming == []`.
  - `test_a_filter_sums_what_matches`: `?category=<food>` → `summary == {"count": 2, "total": "…", "word": "spent"}`
    and `applied[0]["name"] == "Food"`.
  - `test_filters_that_are_not_yours_find_nothing`: another person's account id → `rows == []`, no other person's
    names anywhere in the answer; `?account=nope` → `error` starts with `Invalid filter`.
  - `test_the_filter_choices`: accounts without Expenses/Income, categories with their parent as `sub`, payees.
  - `test_details_of_a_split_and_a_related_entry`: two lines on one side with amounts; `related_to` set on the refund
    and `related` listing it on the original; `posted_on` when it differs.
  - `test_details_of_someone_elses_entry_are_not_found`: 404.
  - `test_recurring_falls_due_before_the_list`: a rule due yesterday → its entry is in `rows`.
  - In `tests/test_query_counts.py`: `"/api/views/transactions": 12` in the ceilings, with growth checked as for pages.
- [ ] **Step 2:** `uv run pytest tests/test_api_views.py -q` — expected: FAIL (404s).
- [ ] **Step 3:** Implement, reusing Task 1's functions; the web routes keep their own templates.
- [ ] **Step 4:** `uv run pytest tests/test_api_views.py tests/test_isolation.py tests/test_api_doc.py
  tests/test_query_counts.py -q` — expected: PASS. Then `npm --prefix frontend run gen:api`.
- [ ] **Step 5:** Commit: `View endpoints for the Transactions page and a transaction's details`.

### Task 3: The Home view endpoint

**Files:**
- Modify: `app/routers/views.py`, `app/schemas/views.py`, `app/routers/web/dashboard.py` (the glance and the steps
  move to `app/services/home.py`), `tests/test_api_views.py`, `tests/test_query_counts.py`, `docs/developer/api.md`
- Create: `app/services/home.py`

**Interfaces:**
- `app/services/home.py`: `home_view(when: date, *, accounts, categories, reports, transactions, budget) -> Home`, the
  body of today's `dashboard()` without the template; `dashboard()` renders from it.
- `GET /views/home?month=` → `HomeView`: `month`, `is_current`, `has_recorded: bool`, `glance: GlanceRead`
  (`has_budget`, `left`, `spent`, `assigned`, `carried`, `of`, `percent: int`, `pace: int | None`), `spent: Decimal`
  (the month's spending, for a person with no budget), `steps: list[StepRead] | None` (`key: Literal["account",
  "spend", "budget"]`, `done`, `title`, `hint`), `steps_done`, `steps_total`, `rows: list[RowRead]`, `total: int`.
  The app maps a step's `key` to its own address.
- `"/api/views/home": 15` in the query-count ceilings.

- [ ] **Step 1: Write the failing tests:** `test_home_with_nothing_recorded` (`has_recorded` false, three steps, the
  first not done); `test_home_glance_when_overspent` (a budget of 100, spent 150.5 → `left == "-50.50"`, `percent ==
  100`); `test_home_first_rows_and_total` (12 entries → 8 rows, `total == 12`); `test_home_past_month_has_no_pace`.
- [ ] **Step 2:** Run — expected: FAIL.
- [ ] **Step 3:** Implement; `dashboard()` renders from `home_view`.
- [ ] **Step 4:** `uv run pytest tests/test_api_views.py tests/test_web_dashboard.py tests/test_query_counts.py -q` and
  `scripts/browser-tests.sh -k "home or budget_page"` — expected: PASS. Regenerate the API types.
- [ ] **Step 5:** Commit: `The Home view endpoint, sharing Home's numbers with the web page`.

### Task 4: The list and the sheet in the React app

**Files:**
- Create in `frontend/src/features/transactions/`: `TransactionList.tsx` (+ `.module.css`, test), `RelatedPill.tsx`,
  `TransactionSheet.tsx` (+ `.module.css`, test), `queries.ts`
- Modify: `frontend/src/components/Sheet.tsx` (a `panelOnWide` mode), `frontend/src/app/router.tsx`

**Interfaces:**
- `queries.ts`: `transactionsKey(filters)`, `useTransactionsPages(filters)` (`useInfiniteQuery` over
  `/api/views/transactions`, next page from `offset + rows.length` while `< total`), `useTransactionDetails(id)`,
  `useDeleteTransaction()` (`DELETE /api/transactions/{id}`; on success invalidates `["views"]` and the toast
  `Transaction deleted`).
- `TransactionList({ rows, onOpen }: { rows: Row[]; onOpen: (id: string) => void })`: day sections newest first (the
  heading `friendlyDate(day, useToday())`, `Spent X` at the right on a day with more than one entry and some
  spending), rows from step 2's `Row` (title with `RelatedPill`, `sub`, the Recurring and assistant markers, the
  figure: `+` and green for income only), several opening balances on one day folded into `Opening balances · N
  accounts`.
- `RelatedPill({ related, onOpen })`: the link glyph, `shortDate` and the amount; opens the related entry's sheet and
  stops the row's own click.
- `TransactionSheet({ id, onClose, onOpen })`: the sheet's content as `txn_sheet.html` draws it (title, date — with
  the full date after Today/Yesterday — amount, the From/To facts with per-line amounts when there are several and
  "posts {day}", Note, Tags as links to `/transactions?month=…&tag=…`, the More row with related entries, the
  assistant or Recurring line and the source; the actions: Edit, then Repeat · Related · Delete, or the person's page
  for an entry made through a person). Delete asks `Delete this transaction? Account balances will change. This
  cannot be undone.` (`window.confirm`, as today) and closes the sheet on success; a refusal shows in the sheet's
  error line. Placeholders while loading; a load that fails closes the sheet.
- `Sheet` gains `panelOnWide?: boolean`: at `(min-width: 60rem) and (hover: hover)` the dialog opens with `show()`
  (not modal) as a panel beside the list with a close button (`aria-label="Close"`), the rules of `dialog.side-panel`.

- [ ] **Step 1: Write the failing tests** (Vitest, stub API): `TransactionList.test.tsx`: day headings and the
  `Spent` total; the opening-balance fold; `+` only on income; the pill opens the related entry and not the row.
  `TransactionSheet.test.tsx`: the facts of a split; Delete asks first (`confirm` false → no request) and then deletes
  and closes; a refusal shows; an entry made through a person offers only `Open {name}`; a failed load closes.
- [ ] **Step 2:** Run — expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `npm --prefix frontend run check` — expected: PASS.
- [ ] **Step 5:** Commit: `The transaction list and its details sheet in the React app`.

### Task 5: The Transactions page

**Files:**
- Create: `frontend/src/features/transactions/TransactionsPage.tsx` (+ `.module.css`, test), `FilterSheet.tsx`,
  `UpcomingCard.tsx`, `tests/browser/test_spa_transactions.py`
- Modify: `frontend/src/app/router.tsx` (`/transactions` → `TransactionsPage`)

**Interfaces:**
- The URL holds `month`, `account`, `category`, `merchant`, `tag`, `q`, `kind`; the month pill changes `month`
  (never past this month); `?open=<id>` opens a sheet (the back button closes it).
- The line above the list: `N transactions · X spent` with a filter (the summary), else `N transactions`, else
  `No transactions`; the Filter button with the number applied; the applied filters as removable chips (`aria-label`
  `Remove the {label} filter`).
- `FilterSheet`: Account, Category, Merchant, Tag rows, each opening a searchable list (`Any …` first, search as you
  type); `Show transactions` applies; `Clear all` when any is set. Tags from `GET /api/tags/`.
- `UpcomingCard`: `N upcoming · X in all` (the total only when nothing is income), closed unless filtering left the
  list empty; each row opens the sheet.
- `Show N more` / `N left` under the list; at the end `That is all of {Month} · N transactions`.
- Empty: `No transactions yet.` with `Record a transaction` (→ `/transactions/new`), or `Nothing matches.` with `Show
  everything`.

- [ ] **Step 1: Write the failing tests:** Vitest — the summary line; a filter chip removes its filter; show more
  appends the next page; the empty states. Browser (`signed_in_spa_page`, data through the API) — ports of
  `test_tapping_a_row_opens_the_details_sheet`, `test_the_sheet_closes_with_escape_and_with_a_tap_outside`,
  `test_deleting_an_entry_asks_first_and_it_is_gone_for_good`,
  `test_the_filter_sheet_narrows_the_list_and_each_filter_can_be_removed`, `test_the_filter_lists_search_as_you_type`,
  `test_filtering_leaves_the_upcoming_row_closed_when_something_matches`, `test_show_more_loads_the_rest_of_the_month_in_place`
  (with a day across the seam), `test_the_pill_opens_the_original_and_the_row_opens_its_own_sheet`,
  `test_the_sheets_extras_sit_behind_a_more_row_that_keeps_edit_clear`, and the side panel's
  `test_the_details_open_beside_the_list_and_another_row_replaces_them`,
  `test_the_panel_closes_with_its_cross_and_with_escape`, `test_a_phone_and_a_narrow_window_keep_the_bottom_sheet`;
  plus `test_deleting_after_show_more_leaves_no_duplicates` (Review Focus 3).
- [ ] **Step 2:** Run — expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `npm --prefix frontend run check`; the browser tests on Chromium and WebKit — expected: PASS.
- [ ] **Step 5:** Commit: `The Transactions page in the React app`.

### Task 6: Home

**Files:**
- Create: `frontend/src/features/home/Home.tsx` (+ `.module.css`, test), `Glance.tsx`, `CalcInfo.tsx`,
  `GetStarted.tsx`, `tests/browser/test_spa_home.py`
- Modify: `frontend/src/app/router.tsx` (`/` → `Home`)

**Interfaces:**
- `?month=` (never past this month) with the month pill; `?open=<id>` as on Transactions.
- Nothing recorded: the month's name, `Nothing recorded yet.`, `Add your first transaction and this page starts to
  fill in.`, `Get started · N of 3` and the steps, `Already keep a ledger file? Import it` (→ `/settings/data#import`).
- Otherwise the glance: `Left to spend` / `Over budget` (with the "i" that opens `How this is worked out`: Carried in
  from earlier months, Assigned in {Month}, Spent so far / Spent, the total and the note, as `calc_panel`) or `Spent`
  with `Set up your budget to see what is left to spend`; the figure (`withCurrency(formatMoney(…))`, red only when
  over), the bar (`--bar-h`, width `percent`%, the pace notch at `pace`%, `role="img"` with today's label), `Spent so
  far X of Y`. Then Get started (when not all done), `Transactions` with `View all ›` (→ `/transactions?month=…`), the
  list (Task 4) with Show more, or `Nothing was recorded in {Month}.`
- A step's `key` maps to `account` → `/accounts/new`, `spend` → `/transactions/new`, `budget` → `/budget`.

- [ ] **Step 1: Write the failing tests:** Vitest — the empty Home; the glance when overspent (`Over budget`, the
  figure `₹−50.50` with U+2212, the red class only then); the calc panel's lines add up; the steps map to addresses.
  Browser — ports of `test_the_sheet_opens_from_home_too`, `test_home_starts_short_and_show_more_finishes_the_month`,
  and `test_home_is_centred_beside_the_sidebar_and_its_day_label_lines_up` (wide).
- [ ] **Step 2:** Run — expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `npm --prefix frontend run check`; the browser tests on both browsers — expected: PASS.
- [ ] **Step 5:** Commit: `Home in the React app`.

### Task 7: Docs and the whole check

**Files:**
- Modify: `docs/developer/api.md` (a "Views" section's intro: what a view endpoint is and when to add one),
  `docs/developer/code-map.md` (`services/transaction_rows.py`, `services/home.py`, `routers/views.py`,
  `features/transactions/`, `features/home/`), `AGENTS.md` (Frontend rules: "a screen reads its view endpoint; the
  rows of a list are built in `services/transaction_rows.py`, never in the app")

- [ ] **Step 1:** Update the docs.
- [ ] **Step 2:** The Python checks and `uv run pytest -q`, `npm --prefix frontend run check`, and the browser tests on
  Chromium and WebKit — expected: all pass.
- [ ] **Step 3:** Commit: `Docs for Home and the Transactions page`, then `git push origin feature/react-frontend`.

# React frontend, step 5: Accounts and Categories — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Accounts and Categories areas in the React app as today's pages are, replacing the two
placeholders. That means:
- the Accounts page (net worth, Pinned, a row of cards per kind, closed accounts behind Load more, New group);
- an account's or a group's own page (balance, bill with Pay bill, cards of a group, coming up, its entries with
  running balance and Load more, the menu: Pin, Edit, Add account, Close, Reopen);
- the account form (add, edit, delete), the group form;
- the Categories page (month pill, Spending / Earning, ranked rows with what is inside and their share);
- a category's page (month figure, subcategories and "Everything else", its entries, the menu: Edit, See in Budgets,
  Add subcategory, Delete, Restore);
- the category form (add, edit, delete).

**Architecture:** It follows step 4a.
- **The server:** what each page shows is worked out in `app/routers/web/accounts.py` and `categories.py` today
  (`kinds`, `kind_groups`, `account_context`, `_figures`, `_by_amount`, `_share`, `_period`, the form helpers). It
  moves into `app/services/accounts_view.py` and `app/services/categories_view.py`.
- **The views:** the web pages render from those services unchanged, and new view endpoints under `/api/views/` answer
  the same things as JSON.
- **Saving:** writes use the existing `/api/accounts` and `/api/categories` routes (create, `PATCH`, close, reopen,
  delete, groups).
- **The app:** pages live in `frontend/src/features/accounts/` and `frontend/src/features/categories/`.

**Tech Stack:** FastAPI, Pydantic, React, React Router, TanStack Query, Vitest, Python `pytest-playwright`.

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md` (step 5: "Accounts and Categories — their
browser tests ported").

## Global Constraints

- **Branch:** `feature/react-frontend` only; nothing reaches `develop`. `make` is not installed: run what it runs.
- **Earlier constraints:** all Global Constraints of steps 2 to 4b-2 hold:
  - strict TypeScript; amounts as strings, never `Number`;
  - `useApi()`, `useToday()`, view endpoints and tokens only;
  - `npm run check` clean; exact dependency versions.
- **Today's pages stay exactly as they are.** The move into services changes no HTML. The proof is the web tests and
  the browser suite (258 on each browser).
- **The rules stay on the server.** The app never works out:
  - which kinds an account can be made in, where it may move, or whether it can hold a budget flag or a bill;
  - an account's net worth, a card's bill, or what is "stale";
  - a category's ranking, its share or its month total.

  It shows what the views say.
- **New `/api/views` routes:** each gets a row in `docs/developer/api.md`, a classification in `tests/test_isolation.py`
  (ids named for what they are), a test, and a query-count ceiling in `tests/test_query_counts.py` no higher than the
  Jinja page it serves:
  - `/api/views/accounts` ≤ 5;
  - `/api/views/categories` ≤ 4;
  - an account's page and a category's page: measured, set at what they make, and not growing with the books.
- **Entries dated ahead:** views that list entries record what has fallen due first (`recurring.catch_up()`), as the
  pages do.
- **Edits send only what changed.** An account edit sends only the fields the person changed, as the web form does. In
  particular, a `balance` is sent only when it differs, because a balance change records an adjustment against Opening
  Balances.
- **Wording is today's**, from:
  - the templates `accounts.html`, `account_card.html`, `account.html`, `account_entries.html`, `card_bill.html`,
    `account_form.html`, `group_form.html`, `categories.html`, `category.html`, `category_entries.html` and
    `category_form.html`;
  - the confirms (`Close {name}? You can reopen it later.`, `Delete account '{name}'?`, the category delete text);
  - the flash texts in `app/flash.py` for `account-created`, `account-updated`, `account-closed`, `account-reopened`,
    `account-pinned`, `account-unpinned`, `account-deleted`, `group-created`, `category-created`, `category-updated`,
    `category-deleted` and `category-restored`.
- **Links:** links to screens not rebuilt yet (Budgets, a person's page, Recurring) go to their future React addresses,
  which show a placeholder until their step.

## Review Focus

1. **An account page with more entries than one chunk:** "Load more" never repeats or drops an entry at the seam, and
   the running balance stays right across chunks. Test in Task 1 (API) and Task 4 (browser).
2. **Closed accounts:**
   - Every open account shows. Closed ones show only after "Load more".
   - A kind whose accounts are all closed hides whole until then.
   - A closed account is never in Pinned.

   Test in Task 1 and Task 4.
3. **An account edit that changes nothing:** no request writes anything, and no adjustment is recorded. Changing only
   the note leaves the balance and its history alone. Test in Task 5.
4. **A category group's page:**
   - The figure is the whole group's month.
   - The list holds only what was labelled with the group itself.
   - "Everything else" shows only when the group has entries of its own besides its subcategories.

   Test in Task 2.
5. **Addresses that point at something gone, someone else's, or not a month** (`/accounts/<another person's id>`,
   `/categories/<id>?month=13-2026`): the error line ("not found", or the month message as `/api/views/transactions`
   words it), never a crash or someone else's names. Test in Tasks 1 and 2.

---

### Task 1: The Accounts views

A refactor plus two view endpoints.

**Files:**
- Create: `app/services/accounts_view.py`, `tests/test_api_accounts_views.py`
- Modify:
  - `app/routers/web/accounts.py`: renders from the service; the HTML is unchanged.
  - `app/routers/views.py`, `app/schemas/views.py`
  - `tests/test_isolation.py`, `tests/test_query_counts.py`
  - `docs/developer/api.md`

**Interfaces:**
- `services/accounts_view.py` (the logic now in the web router):
  - `kind_groups`, `kinds`, `mark_closed`, `STALE_DAYS`, `KIND_ORDER`;
  - `accounts_page(accounts: AccountService) -> AccountsPage`;
  - `account_page(accounts: AccountService, account_id: UUID, offset: int = 0) -> AccountPage`, raising `LookupError`
    for an account that is not the person's.

  The two dataclasses hold what `accounts_page` and `account_context` hand the templates today. Each card's quiet line
  is worked out here, as the template's `card` macro does today: `Bill overdue`, `Bill due 5 Dec` (with `due` when within
  `DUE_SOON_DAYS`), `No entries yet`, `No entry since 2 Oct`, or nothing. `account_context` stays for the category page's
  reuse only if it is still needed after Task 2; otherwise it goes.
- `GET /views/accounts` → `AccountsView`:
  - `net_worth`, `account_count`, `has_budget_accounts`;
  - `pinned: list[AccountCard]`;
  - `kinds: list[KindRow]`, where `KindRow` is `name`, `group_id | None`, `total`, `owed: bool`, `open_count`,
    `all_closed: bool`, `add_url`, and `cards: list[AccountCard]`;
  - `has_closed`.
- `AccountCard`: `id`, `name`, `balance`, `on_budget`, `closed`, `pinned`, `line: str | None`, `line_due: bool`.
- `GET /views/accounts/{account_id}?offset=` → `AccountView`:
  - `id`, `name`, `details`, `kind`, `badge` (`system` | `closed` | null), `sub` (the kind line under the name:
    `Bank Accounts` / `Other you owe` / `Group · money I own` / `Built in · money I owe`), `closed_on`, `balance`,
    `balance_after`, `direct`;
  - `bill: CardBill | None`, `can_set_days`;
  - `is_group`, `cards: list[AccountCard]` (a group's open accounts);
  - `can_add_child`, `can_pin`, `pinned`, `can_edit` (`kind == "user"`), `postable`;
  - `upcoming: list[UpcomingRead]`, `upcoming_total`;
  - `entries: list[RegisterRow]`, `has_more`, `next_offset`.
- `RegisterRow` (worked out once, in `services/transaction_rows.py`):
  - `id` (the transaction), `date`, `title`, `sub`, `posts_on: Date | None` (when it differs from the date);
  - `related: RelatedRef | None`;
  - `amount` (no sign), `inflow: bool` (green and `+`), `balance: Decimal | None` (the running balance; none on a
    category's page).

- [ ] **Step 1:** Run the baseline: `uv run pytest -q tests/test_web_accounts.py tests/test_web_accounts_page.py
  tests/test_account_groups.py tests/test_pinned_accounts.py tests/test_close_accounts.py tests/test_card_bills.py
  tests/test_query_counts.py`.
  - Expected: PASS. Note the counts.
- [ ] **Step 2: Write the failing tests** in `tests/test_api_accounts_views.py`:
  - `test_the_accounts_page_view`: net worth; kinds in `KIND_ORDER` with totals and `owed`; a card's line (`No entries
    yet`, `No entry since …`, a card's `Bill due …` with `line_due`).
  - `test_pinned_never_holds_a_closed_account` (Review Focus 2).
  - `test_a_kind_whose_accounts_are_all_closed_says_so` (`all_closed`, `has_closed`).
  - `test_an_accounts_page_view` (balance, `sub`, the menu flags, upcoming, entries with running balance and `inflow`).
  - `test_load_more_never_repeats_or_drops_an_entry` (Review Focus 1: 3 chunks over 70 entries, ids unique, the union is
    every entry, each balance right).
  - `test_a_groups_page_lists_its_open_accounts_as_cards`.
  - `test_a_cards_bill_and_the_days_to_set`.
  - `test_another_persons_account_is_not_found` (404; Review Focus 5).
  - The isolation classification and the ceilings.
- [ ] **Step 3:** Run them.
  - Expected: FAIL.
- [ ] **Step 4:** Move the logic and add the routes.
- [ ] **Step 5:** Run Step 1's command plus the new file, `tests/test_isolation.py` and `tests/test_api_doc.py`; then
  `npm --prefix frontend run gen:api` and `scripts/browser-tests.sh -q -k "accounts_page or card_bills or account_info
  or fixed_parents"`.
  - Expected: all PASS.
- [ ] **Step 6:** Commit: `The Accounts page and an account's page as views`.

### Task 2: The Categories views

**Files:**
- Create: `app/services/categories_view.py`, `tests/test_api_categories_views.py`
- Modify: `app/routers/web/categories.py`, `app/routers/views.py`, `app/schemas/views.py`, `tests/test_isolation.py`,
  `tests/test_query_counts.py`, `docs/developer/api.md`

**Interfaces:**
- `services/categories_view.py`: `category_tree`, `CatNode`, `period(month) -> (start, end, is_current) | None`,
  `categories_page(...)`, `category_page(...)`, with today's `_figures`, `_by_amount` and `_share` rules.
- `GET /views/categories?month=&tab=expense|income` → `CategoriesView`:
  - `month`, `is_current`, `tab`, `grand`;
  - `rows: list[CategoryRow]`, where `CategoryRow` is `id`, `name`, `total`, `hint` (`Fuel · Taxi · +2`) and `share`
    (`34%`).
- `GET /views/categories/{category_id}?month=` → `CategoryView`:
  - `id`, `name`, `details`, `kind`, `built_in`, `closed_on`, `group: PersonRef-like {id, name} | None`, `total`;
  - `subs: list[{id, name, total}]`, `own_here`;
  - `can_add_child`, `can_delete` (not built in, not closed), `month`, `is_current`;
  - `entries: list[RegisterRow]` (no running balance; `inflow` only for earning and above zero).
- A `month` that is not a month answers 400 with the message `/api/views/transactions` uses. A category that is not
  the person's answers 404.

- [ ] **Step 1: Write the failing tests:**
  - `test_categories_are_ranked_with_what_is_inside_and_their_share`;
  - `test_every_category_is_listed_even_with_nothing_in_the_month`;
  - `test_the_earning_tab`;
  - `test_a_groups_page` (Review Focus 4: the figure, the subcategories, "Everything else" only with its own entries,
    the list is its own);
  - `test_a_bad_month_and_a_stranger` (Review Focus 5);
  - the classification and the ceilings.
- [ ] **Step 2:** Run.
  - Expected: FAIL.
- [ ] **Step 3:** Move the logic and add the routes.
- [ ] **Step 4:** Run `uv run pytest -q tests/test_api_categories_views.py tests/test_categories.py
  tests/test_isolation.py tests/test_query_counts.py tests/test_api_doc.py` and `scripts/browser-tests.sh -q -k
  categories_page`, then `npm --prefix frontend run gen:api`.
  - Expected: PASS.
- [ ] **Step 5:** Commit: `The Categories page and a category's page as views`.

### Task 3: The forms' views

**Files:**
- Modify: `app/services/accounts_view.py`, `app/services/categories_view.py`, `app/routers/web/accounts.py`,
  `app/routers/web/categories.py`, `app/routers/views.py`, `app/schemas/views.py`, `tests/test_api_accounts_views.py`,
  `tests/test_api_categories_views.py`, `tests/test_isolation.py`, `docs/developer/api.md`

**Interfaces:**
- `GET /views/account-form?parent=&root=assets|liabilities` (new) or `?account_id=` (edit) → `AccountFormView`:
  - `editing`, `is_group`, `name`, `details`, `balance`, `parent_id`;
  - `kinds: list[KindChoice]` (the chips), `placed: {label, value} | None` (`Kind · Other`, `Inside · HDFC`), and
    `parent_options: list[KindChoice]`;
  - `KindChoice` is `id`, `name`, `root`, `can_budget`, `can_bill`, `budget_default`. These are the server's rules for
    a new account in that place, from `_starts` and the root: an asset starts in the budget, a card or loan outside
    it, and a built-in group as it says.
  - `on_budget`, `statement_day`, `due_day`, `bill_rounding`, `new_accounts_in_budget` (a group's own choice; null for
    an account).
- `GET /views/category-form?parent=&root=expense|income` or `?category_id=` → `CategoryFormView`: `editing`, `kind`,
  `name`, `details`, `parent_id`, and `groups: list[{id, name}]` (none for a group that holds categories). A `parent`
  that is not the person's answers 404, as the web page does.
- The web form pages render from the same services.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_new_account_form_by_kind` (no kind chosen; `root=liabilities` places it under Other you owe with a bill;
    `parent=<a group>` chooses it);
  - `test_an_edit_form` (a group has no kinds and no balance; an account keeps its parent among the options);
  - `test_a_category_form` (a new one from a group takes its kind; a group that holds categories gets no groups);
  - `test_a_strangers_parent_is_not_found`.
- [ ] **Step 2:** Run.
  - Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the two view test files, the web form tests, `tests/test_isolation.py` and
  `tests/test_api_doc.py`, then `scripts/browser-tests.sh -q -k "accounts_page or under_picker or fixed_parents or
  card_bills"` and `npm --prefix frontend run gen:api`.
  - Expected: PASS.
- [ ] **Step 5:** Commit: `The account and category forms as views`.

### Task 4: The Accounts page and an account's page in the app

**Files:**
- Create in `frontend/src/features/accounts/`: `AccountsPage.tsx`, `AccountCard.tsx`, `AccountPage.tsx`,
  `CardBill.tsx`, `RegisterList.tsx`, `queries.ts`, `fixtures.ts`, their CSS modules (from the `.acc-kind`,
  `.acc-head`, `.acc-rail`, `.acc-card*`, `.pin-mark`, `.budget-dot`, `.account-hero`, `.acct-*`, `.bill*`,
  `.note-info`, `.menu` and `.hero-balance` rules of `style.css`), and tests (`AccountsPage.test.tsx`,
  `AccountPage.test.tsx`).
- Modify: `frontend/src/app/router.tsx` (`/accounts`, `/accounts/:accountId`).
- Test: `tests/browser/test_spa_accounts.py`

**Interfaces:**
- `RegisterList` is shared with the category page (Task 6). It shows the days, with each row's title, sub, `Posts …`,
  the related pill, and the figure: `+` and green for `inflow`, with the running balance small beneath when there is
  one. A tap opens the transaction sheet of step 4a.
- The menu holds:
  - **Pin to top / Unpin:** `PATCH /api/accounts/{id}` with `{pinned}`; toast `account-pinned` / `account-unpinned`.
  - **Close account:** confirm, then `POST …/close`, toast, back to `/accounts`.
  - **Reopen account.**
  - **Edit** and **Add account / Add sub-account:** links to Task 5's form.

  The menu's notes (`Done with …? Closing it …`, `It has to be empty first: it still holds …`) are worded from the view.
- "Load more" on the Accounts page shows the closed cards (client state; the view already lists them). On an account's
  page it fetches `?offset=next_offset` and appends.
- The empty state: `No transactions yet.` with `Record a transaction` (when `postable`) →
  `/transactions/new?account={id}&back=/accounts/{id}`.

- [ ] **Step 1: Write the failing tests:**
  - `AccountsPage.test.tsx`: kinds as rows with totals and `owed`, Pinned without totals, card lines, closed cards only
    after Load more (Review Focus 2), the New group link.
  - `AccountPage.test.tsx`: hero and sub line, bill with Pay bill (`/transactions/new?pay=…&amount=…&back=…`), the
    menu's actions call the API and toast, Load more appends without repeats, a 404 says so.
  - `tests/browser/test_spa_accounts.py`, ported from `test_accounts_page.py`, `test_account_info.py`,
    `test_card_bills.py` (Pay bill) and `test_fixed_parents.py` (the five shelves):
    - every kind is a row of cards under its heading;
    - a long row scrolls sideways on its own;
    - room between kinds and a heading larger than a card's name;
    - a card opens the account, and the add card opens the form on that kind;
    - every open account shows and only closed ones are tucked away;
    - closing from its page;
    - the cards of a row are the same size;
    - Edit is in the menu;
    - Load more loads the next chunk in place;
    - going back lands on Accounts;
    - an entry started from an account comes back to it;
    - a group's heading opens its page;
    - the pin button and the Pinned row;
    - the description opens from the i, and no description means no i;
    - Pay bill;
    - an empty page shows the five shelves.
- [ ] **Step 2:** Run.
  - Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm --prefix frontend run check` and `scripts/browser-tests.sh -q -k spa_accounts`.
  - Expected: PASS.
- [ ] **Step 5:** Commit: `The Accounts page and an account's page in the app`.

### Task 5: The account and group forms in the app

**Files:**
- Create in `frontend/src/features/accounts/`: `AccountForm.tsx`, `GroupForm.tsx`, their CSS module (from `.form-narrow`,
  `.kind-chips`, `.check-row`, `.bill-days`, `.add-note`, `.danger-zone`), and `AccountForm.test.tsx`.
- Modify: `router.tsx` (`/accounts/new`, `/accounts/new-group`, `/accounts/:accountId/edit`), `queries.ts`.
- Test: `tests/browser/test_spa_accounts.py`

**Interfaces:**
- **Adding:** `POST /api/accounts/` with `name`, `parent_id`, `details`, `balance` (`0` when empty), and:
  - `on_budget` only when the chosen kind `can_budget`;
  - `statement_day`, `due_day` and `bill_rounding` only when it `can_bill`.

  On success: toast `Account added`, then the new account's page. Without a kind: the server's `choose what kind of
  account it is!` is shown, worded on the app side because nothing is sent without a parent.
- **Editing:** `PATCH /api/accounts/{id}` with only the changed fields (Global Constraints). With nothing changed it
  sends nothing and goes back (Review Focus 3). Toast `Account updated`.
- **The kind chips** set the parent. The budget box and the bill fields follow the chosen kind's `can_budget`,
  `can_bill` and `budget_default`, as the web form's script does.
- **Labels follow the root:** `Amount you owe now` for a liability, `Current balance` when adding, `Balance` when
  editing; a hint when editing.
- **Rounding:** `Exactly, to the paisa` / `To the nearest ₹1` / `Up to the next ₹1`, using the currency's sign from
  `useSymbol()`.
- **Delete:** `DELETE /api/accounts/{id}` after `Delete account '{name}'?`; toast; back to `/accounts`. A refusal shows
  in the danger zone.
- **The group form:** `POST /api/accounts/groups` with `name`, `root` (`Money I own` → Assets, `Money I owe` →
  Liabilities) and `new_accounts_in_budget`. Without a choice the server's message shows. Toast `Group added`, then
  `/accounts`.

- [ ] **Step 1: Write the failing tests:**
  - `AccountForm.test.tsx`:
    - the budget box by kind;
    - the bill fields only for a card or loan;
    - an edit sends only what changed, and nothing when nothing did (Review Focus 3);
    - a refusal shows the server's words;
    - delete confirms and leaves.
  - Browser tests, ported from `test_accounts_page.py`, `test_card_bills.py`, `test_fixed_parents.py` and
    `test_under_picker.py`:
    - the new account form asks about the budget by its kind;
    - the budget box works when the form opens on a type or a kind;
    - a group is made from the foot of the page, and its accounts start as it says;
    - the days are asked only for a card or loan;
    - a group's own page adds inside it;
    - the budget line follows the group chosen;
    - a new account without a kind is told to choose one.
- [ ] **Step 2:** Run.
  - Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm --prefix frontend run check` and `scripts/browser-tests.sh -q -k spa_accounts`.
  - Expected: PASS.
- [ ] **Step 5:** Commit: `Adding, editing and deleting accounts and groups in the app`.

### Task 6: Categories in the app

**Files:**
- Create in `frontend/src/features/categories/`: `CategoriesPage.tsx`, `CategoryPage.tsx`, `CategoryForm.tsx`,
  `queries.ts`, `fixtures.ts`, CSS modules (from `.cat-bar`, `.cat-chips`, `.cat-hero`, `.crow*`, `.sub-tile`), and
  tests.
- Modify: `router.tsx` (`/categories`, `/categories/new`, `/categories/:categoryId`, `/categories/:categoryId/edit`).
- Test: `tests/browser/test_spa_categories.py`

**Interfaces:**
- **Month and tab** live in the URL (`?month=2026-11&tab=income`). The page uses the `MonthPill` and `Chips`
  components (`Spending` / `Earning`).
- **A row** reads `{name}` with `{hint} · {share}`, `{share} of spending|earnings` or `Nothing yet`, and the figure (or a
  quiet `–`).
- **The category page:**
  - the hero with `built in` and `closed` badges and the i-note;
  - the menu: Edit; See in Budgets (spending only, → `/budget`); Add subcategory; Delete or Restore, with today's
    confirm;
  - Subcategories with "Everything else", the entries (`RegisterList`), and `Nothing in {Month}.` when there are none.
- **Delete:** `POST /api/categories/{id}/delete`. **Restore:** `POST …/reopen`. Toasts `category-deleted` /
  `category-restored`.
- **The form:**
  - `POST /api/categories/` or `PATCH` with only the changed fields;
  - `Under` uses the step 4b `Picker` with `None (top level)`;
  - `+ Add a note`;
  - Delete with its hint.

- [ ] **Step 1: Write the failing tests:**
  - Vitest:
    - ranked rows with hint and share;
    - the tab and month in the URL;
    - a group's page with "Everything else";
    - delete and restore;
    - the form's Under, and an edit that sends only what changed.
  - `tests/browser/test_spa_categories.py`, ported from `test_categories_page.py` and `test_under_picker.py`:
    - the tab bar has Categories;
    - categories are ranked, and a category opens its page with what is inside;
    - the month total and the income tab;
    - every category is listed even with nothing in the month;
    - a category opens its page, and adding a transaction comes back to it;
    - room between the figure and the first row;
    - the month pill sits in the title row;
    - the month in the pill is a picker that goes straight to that month;
    - the head is the same on Accounts and Categories;
    - Under on the category form can be none.
- [ ] **Step 2:** Run.
  - Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm --prefix frontend run check` and `scripts/browser-tests.sh -q -k spa_categories`.
  - Expected: PASS.
- [ ] **Step 5:** Commit: `Categories in the app`.

### Task 7: Docs and the whole check

**Files:**
- Modify:
  - `docs/developer/code-map.md`: `accounts_view`, `categories_view`, and `features/accounts/` and `categories/`.
  - `docs/developer/api.md`: confirm the rows.
  - `AGENTS.md`: only if a rule changed.
  - `frontend/src/app/router.tsx`: no placeholder is left for `/accounts` and `/categories`.

- [ ] **Step 1:** Write the docs.
- [ ] **Step 2:** The whole check:
  - `uv run ruff check app tests migrations scripts` and `uv run ruff format --check app tests migrations scripts`;
  - `uv run pyrefly check`;
  - `uv run pytest -q`;
  - `npm --prefix frontend run check`;
  - `scripts/browser-tests.sh -q`, then `FINODE_BROWSER=webkit scripts/browser-tests.sh -q`.

  Expected: all PASS.
- [ ] **Step 3:** Commit `Docs for Accounts and Categories`, then `git push origin feature/react-frontend`.

# React frontend, step 6: Budgets — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Budgets area in the React app as today's pages are, replacing the placeholder:
- **The Budgets page:**
  - Ready to assign, with the "i" sum behind it and the coming-up line;
  - Copy last month's amounts;
  - the first-time intro, the overspent warning;
  - the categories ranked with a bar each, unused groups tucked away, the empty states.
- **The category sheet:** assign, what was spent, Move money.
- **A group's page:** its glance block and its categories; the group's own budget in a sheet, never below its
  subcategories.
- **The Move money page.**

**Architecture:** It follows steps 4a and 5.
- **The server:** what the pages show is worked out in `app/routers/web/budget.py` today (`Node`, `build_tree`,
  `other_line`, `_by_assigned`, `_hint`, `_glance`, `_context`, `_group_context`). It moves into
  `app/services/budget_view.py`.
- **The views:** the web pages render from it unchanged, and new view endpoints answer the same things as JSON.
- **Saving:** the existing `/api/budget` routes save (`PUT /categories/{id}`, `PUT /groups/{id}`, `POST /move`,
  `POST /copy`); the coming-up line reads `/api/budget/coming-up`.
- **The app:** pages live in `frontend/src/features/budget/`.

**Tech Stack:** FastAPI, Pydantic, React, React Router, TanStack Query, Vitest, Python `pytest-playwright`.

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md` (step 6: "Budgets — their browser tests ported").

## Global Constraints

- **Branch:** `feature/react-frontend` only; nothing reaches `develop`. `make` is not installed: run what it runs.
- **Earlier constraints:** all Global Constraints of steps 2 to 5 hold:
  - strict TypeScript; amounts as strings, never `Number`;
  - `useApi()`, `useToday()`, view endpoints and tokens only;
  - `npm run check` clean; exact dependency versions;
  - a component used by two features lives in `src/components`.
- **Today's pages stay exactly as they are.** The move into `budget_view.py` changes no HTML. The proof is the web
  tests (`test_web_budget.py`, `test_web_budget_heads.py`, `test_budget.py`) and the browser suite (292 on each
  browser).
- **The rules stay on the server.** The app never works out:
  - Ready to assign, a row's "of" figure, its bar's width, overspent / all spent;
  - which groups are unused, a group's glance;
  - the least a group can be given.

  It shows what the views say.
- **New `/api/views` routes:** each gets a row in `docs/developer/api.md`, a classification in `tests/test_isolation.py`,
  a test, and a query-count ceiling:
  - `/api/views/budget` ≤ 6, the web page's own;
  - a group's view and the move view: measured, not growing with the books, and no higher than their web pages.
- **Wording is today's**, from:
  - the templates `budget.html`, `budget_body.html`, `budget_rows.html`, `budget_sheet.html`, `budget_group.html`,
    `budget_group_body.html`, `budget_group_sheet.html`, `budget_move.html`, `coming_note.html` and `calc_info.html`;
  - the flash text `budget-moved`;
  - the messages `Choose the category to move from and the one to move to.` and the server's own refusals.
- **Not here:** the Coming up list (`/budget/coming-up`) is step 7. The coming-up line links to that address, which shows
  a placeholder until then.

## Review Focus

1. **Assigning in the sheet** changes Ready to assign, the row and its bar without a reload. A refused amount (more
   decimals than the currency keeps, or not a number) shows the server's words in the sheet, which stays open. Test in
   Task 2.
2. **A group's own budget below what its subcategories add up to:**
   - The field turns red as it is typed (`aria-invalid`), from the view's `minimum`.
   - Saving sends nothing.
   - A value at or above the minimum saves.

   Test in Task 3.
3. **Over-assigned:**
   - Ready to assign below zero shows `0` as the figure and `Over-assigned by ₹… · take some back from a category`.
   - Zero shows `Every ₹ has a job`.
   - Nothing assigned and no categories shows `Nothing to assign yet`.

   Test in Task 1 (view) and Task 2.
4. **Unused groups** are tucked away once anything is in use, with `N unused groups hidden · Show` and then `Hide the N
   unused`. Plain top-level categories always show. Test in Task 1 and Task 2.
5. **Moving money and copying last month:**
   - Move money leaves Ready to assign as it was and needs both categories.
   - Copy fills only the categories with nothing assigned, and its button goes once nothing is left to copy.

   Test in Task 4 and Task 2.

---

### Task 1: The Budgets views

A refactor plus three view endpoints.

**Files:**
- Create: `app/services/budget_view.py`, `tests/test_api_budget_views.py`
- Modify:
  - `app/routers/web/budget.py`: renders from the service; the HTML is unchanged.
  - `app/routers/views.py`, `app/schemas/views.py`
  - `tests/test_isolation.py`, `tests/test_query_counts.py`
  - `docs/developer/api.md`

**Interfaces:**
- `services/budget_view.py` holds what the web router has today:
  - `Node`, `build_tree`, `other_line`, `by_assigned`, `hint`, `glance`;
  - `budget_page(budget, month) -> BudgetPage`;
  - `group_page(budget, month, category_id) -> GroupPage` (LookupError for a group that is not the person's);
  - `move_lines(budget, month)`.

  `parse_month` and `shift` move with them, and the web router imports them.
- **How a row reads** is worked out here, once, as `budget_rows.html` reads it today. It is `BudgetRowRead`:
  - `category_id`, `name` (`Everything else` for a group's own line), `is_group`, `other` (a group's own line);
  - `assigned`, `activity`, `available`, `overspent_last_month`;
  - `of: Decimal | None` (`of 25,000.00`, or none for `nothing assigned`), `state` (`overspent` | `all_spent` | null),
    `hint` (`Fuel · Taxi · +2`, `₹500.00 overspent last month`, or for a group's own line `kept on the group itself`);
  - `percent` (the bar's width, 100 when over) and `over`;
  - `group_name` (the sheet's second line), `unused`.

  The web macro reads these fields; its HTML stays the same.
- `GET /views/budget?month=` → `BudgetView`:
  - `month`, `is_current`, `pace` (current month only), `ready_to_assign`;
  - `sum`: `money_in_accounts`, `reserved_for_cards`, `available`, `assigned_to_later_months`;
  - `copyable`, `show_intro`, `has_budget_accounts`, `overspent`;
  - `rows: list[BudgetRowRead]`, biggest first, and `unused_count`.
- `GET /views/budget/groups/{category_id}?month=` → `GroupView`:
  - `id`, `name`, `month`, `is_current`, `pace`;
  - `glance` (`left`, `spent`, `of`, `percent`, `planned`) and `assigned`;
  - `minimum` (from `budget.group_minimum`);
  - `kids: list[BudgetRowRead]`, the group's own line included.

  404 for a category that is not a group of the person's.
- `GET /views/budget-move?month=&source=` → `{ month, lines: [{category_id, path ("Food › Dining"), available}],
  source }`. 404 for a `source` that is not among them.
- A `month` that is not a month is this month, as the other views treat it. A future month is allowed only up to
  `LAST_MONTH`, as the page's `shift` already allows.

- [ ] **Step 1:** Run the baseline: `uv run pytest -q -p no:cacheprovider tests/test_web_budget.py
  tests/test_web_budget_heads.py tests/test_budget.py tests/test_budget_categories.py tests/test_query_counts.py`.
  - Expected: PASS. Note the counts.
- [ ] **Step 2: Write the failing tests** in `tests/test_api_budget_views.py`:
  - `test_the_head` (ready to assign, the sum, `copyable`, `show_intro` before the first amount);
  - `test_over_assigned_and_overspent` (Review Focus 3);
  - `test_the_rows_read_as_the_page` (of, state, hint, percent, biggest first);
  - `test_unused_groups_are_marked_once_anything_is_used` (Review Focus 4);
  - `test_a_groups_view` (glance, kids with Everything else, minimum);
  - `test_the_move_view` (paths, available; a stranger's `source` is 404);
  - `test_strangers_and_bad_months` (404 for another person's group; a bad month is this month);
  - the classification and the ceilings.
- [ ] **Step 3:** Run.
  - Expected: FAIL.
- [ ] **Step 4:** Move the logic and add the routes.
- [ ] **Step 5:** Run Step 1's command plus the new file, `tests/test_isolation.py` and `tests/test_api_doc.py`; then
  `npm --prefix frontend run gen:api` and `scripts/browser-tests.sh -q -k "budget or coming_up or side_panel"`.
  - Expected: all PASS.
- [ ] **Step 6:** Commit: `The Budgets page, a group's page and Move money as views`.

### Task 2: The Budgets page and the category sheet in the app

**Files:**
- Create in `frontend/src/features/budget/`:
  - `BudgetPage.tsx`, `BudgetRows.tsx` (a row with its bar, shared with the group page), `CategorySheet.tsx`;
  - `queries.ts`, `fixtures.ts`, `Budget.module.css` (from the `.budget-list`, `.has-bar`, `.bar`, `.crow-of`,
    `.copy-last`, `.intro`, `.ready-warn`, `.sheet-title`, `.sheet-amount`, `.sheet-facts` and `.sheet-actions` rules);
  - tests.
- Move: `features/home/CalcInfo.tsx` to `src/components/CalcInfo.tsx` (now used by Home and Budgets).
- Modify: `router.tsx` (`/budget`).
- Test: `tests/browser/test_spa_budget.py`

**Interfaces:**
- **Month in the address** (`?month=`), with the `MonthPill` in the title row.
- **The "i" panel:** the sum rows, `Money in your accounts that has no job yet, counted up to today` (or `the end of
  {Month}`), and in the current month the coming-up line from `/api/budget/coming-up`: `{n} payments coming up by
  {day} · {total}`, linking to `/budget/coming-up`.
- **A row** opens the category sheet; a group row links to `/budget/groups/{id}?month=`.
- **The category sheet:**
  - title `{name}` (or `{group} · everything else`), `{Month}{ · group}`;
  - the amount left, `Assigned this month` (an `AmountField`, filled with what is assigned);
  - Spent and Overspent last month;
  - Save: `PUT /api/budget/categories/{id}` with `{month, amount}`. On success the views refresh and the sheet closes.
    A refusal shows in the sheet.
  - Move money: a link to `/budget/move?month=&source={id}`.
- **Copy:** `POST /api/budget/copy`. The views refresh.
- **The unused toggle** is client state.

- [ ] **Step 1: Write the failing tests:**
  - Vitest:
    - the head in its three states (Review Focus 3);
    - the sum panel and the coming-up line;
    - a row's second line and bar;
    - a group row links to its page;
    - assigning sends and refreshes, and a refusal stays in the sheet (Review Focus 1);
    - Copy sends and its button goes;
    - the unused toggle (Review Focus 4);
    - the empty states (no budget accounts, no categories).
  - `tests/browser/test_spa_budget.py`, ported from `test_budget_page.py`:
    - assigning changes Ready to assign without a reload;
    - copying last month's amounts;
    - a card the budget includes is in the sum;
    - the rows have no notch under their bars;
    - every bar runs the full width of its row;
    - names and amounts line up;
    - the "i" opens the sum and survives assigning;
    - Save works on the first tap;
    - Save is above the keyboard on a phone and a small phone;
    - a tap beside the sheet while typing only puts the keyboard away;
    - tapping the amount in a sheet focuses it;
    - the month pill sits on the same line on Home and the other pages.

    Also the comparisons step 5 left for Budgets: the head is the same on Accounts, Categories and Budgets; the month
    pill ends at the same edge.
- [ ] **Step 2:** Run.
  - Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm --prefix frontend run check` and `scripts/browser-tests.sh -q -k spa_budget`.
  - Expected: PASS.
- [ ] **Step 5:** Commit: `The Budgets page and the category sheet in the app`.

### Task 3: A group's page and its own budget

**Files:**
- Create: `frontend/src/features/budget/GroupPage.tsx`, `GroupSheet.tsx`, and tests.
- Modify: `router.tsx` (`/budget/groups/:categoryId`, and `/budget/group/:categoryId` redirecting to it, as old
  addresses do), `queries.ts`.
- Test: `tests/browser/test_spa_budget.py`

**Interfaces:**
- **The page:**
  - back to `/budget?month=` (`Budgets`), the month pill, the group's name as the title;
  - the glance block (`Over budget` only when over; `Spent X of Y` or `Nothing assigned yet`; the bar with today's
    tick in the current month), which opens the group sheet;
  - the rows (`BudgetRows`), each opening the category sheet.
- **The group sheet:** like the category sheet, without Move money and Overspent last month.
  - `Assigned this month` turns red (`aria-invalid`) when below `minimum`, and Save then sends nothing.
  - Otherwise it sends `PUT /api/budget/groups/{id}` with `{month, total}`.

- [ ] **Step 1: Write the failing tests:**
  - Vitest:
    - the glance and the rows;
    - below the minimum is red and sends nothing, at or above saves (Review Focus 2).
  - Browser: `a group opens its page and its budget cannot go below its categories` (ported).
- [ ] **Step 2:** Run.
  - Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm --prefix frontend run check` and `scripts/browser-tests.sh -q -k spa_budget`.
  - Expected: PASS.
- [ ] **Step 5:** Commit: `A group's budget page in the app`.

### Task 4: Move money

**Files:**
- Create: `frontend/src/features/budget/MovePage.tsx` and tests.
- Modify: `router.tsx` (`/budget/move`), `queries.ts`.
- Test: `tests/browser/test_spa_budget.py`

**Interfaces:**
- **The page:**
  - back to `/budget?month=`;
  - `Move money` with `{Month} · from one category's available money to another. Ready to assign stays the same.`;
  - Amount (`AmountField`);
  - From and To: the step 4b `Picker`, the options' second figure being what each has left (`{x} left`); From starts
    at `source`.
- **Moving:** `POST /api/budget/move`. On success: toast `Money moved` (the `budget-moved` flash text), then
  `/budget?month=`.
- **Without both categories:** `Choose the category to move from and the one to move to.` (the web route's own words),
  and nothing is sent.

- [ ] **Step 1: Write the failing tests:**
  - Vitest:
    - From starts at the source;
    - both categories are needed;
    - a move sends and leaves;
    - a refusal shows.
  - Browser (ported):
    - move money picks in our sheet with what each has left;
    - move money without both categories says so.
  - API: `test_moving_keeps_ready_to_assign` (Review Focus 5, in `tests/test_api_budget_views.py`).
- [ ] **Step 2:** Run.
  - Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the Vitest files and `scripts/browser-tests.sh -q -k spa_budget`.
  - Expected: PASS.
- [ ] **Step 5:** Commit: `Move money in the app`.

### Task 5: Docs and the whole check

**Files:**
- Modify:
  - `docs/developer/code-map.md`: `budget_view`, `features/budget/`, `components/CalcInfo`.
  - `docs/developer/api.md`: confirm the rows.
  - `frontend/src/app/router.tsx`: no placeholder for `/budget`.

- [ ] **Step 1:** Write the docs.
- [ ] **Step 2:** The whole check:
  - `uv run ruff check app tests migrations scripts` and `uv run ruff format --check app tests migrations scripts`;
  - `uv run pyrefly check`;
  - `uv run pytest -q`;
  - `npm --prefix frontend run check`;
  - `scripts/browser-tests.sh -q`, then `FINODE_BROWSER=webkit scripts/browser-tests.sh -q`.

  Expected: all PASS.
- [ ] **Step 3:** Commit `Docs for Budgets`, then `git push origin feature/react-frontend`.

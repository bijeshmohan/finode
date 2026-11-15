# React frontend, step 7a: the to-do bell, Coming up, Tags and Recurring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild four areas in the React app as today's pages are:
- **The to-do bell:** the count in the top bar and the sidebar, and its sheet with the fix on each item:
  - a category for a payment;
  - Add to budget;
  - Pay bill;
  - Open rule.
- **Coming up** (`/budget/coming-up`): what is dated ahead and what rules will record, by day.
- **Tags** (`/tags`): the list, and per tag a sheet with View entries, Rename, Merge into… and Delete.
- **Recurring** (`/recurring`): the list, and the form that makes, changes, pauses, skips, resumes and deletes a rule.

Step 7 of the spec is split, as step 4 was: **7b is People** (the list, a person's page, the person form, opening
balances, an entry's sheet and undoing it). It is 490 lines of web routes on its own.

**Architecture:** As in steps 4a to 6.
- **The server:** what a page shows moves out of its web router into a service, and the web page renders from it with
  its HTML unchanged:
  - `services/coming_up_view.py`, from `routers/web/coming_up.py`;
  - `services/recurring_view.py`, from `routers/web/recurring.py`'s `RuleRow`, `_status`, `_paths`, `_name`, `_row`;
  - `services/recurring_form.py`, from `_parse` and `_form_page`.
- **The views:** new view endpoints answer the same things as JSON.
- **Saving uses the existing `/api` routes:**
  - `/api/tags/{name}` (PATCH renames, and merges onto a tag that exists; DELETE);
  - `/api/recurring/{id}/pause|resume|skip`, `DELETE /api/recurring/{id}`;
  - `/api/budget/accounts/{id}/include`.
- **Two new write routes:**
  - labelling a payment (the bell's only fix with no `/api` route today);
  - saving a rule from the Add screen's rows, so the app sends rows exactly as the Add screen does. The server turns
    them into a rule as the web form does today, with one function shared by both.
- **The app:**
  - the Add screen's rows (kinds, amount, the two sides, the swap, the picker, row settings, quick add) move out of
    `EntryScreen.tsx` into one shared component, which the Add screen and the recurring form both use;
  - pages live in `features/todo/`, `features/tags/`, `features/recurring/`; Coming up joins `features/budget/`.

**Tech Stack:** FastAPI, Pydantic, React, React Router, TanStack Query, Vitest, Python `pytest-playwright`.

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md` (step 7: "People, Recurring, Tags, to-do bell,
Coming up — as above", i.e. their browser tests ported).

## Global Constraints

- **Branch:** `feature/react-frontend` only; nothing reaches `develop`. `make` is not installed: run what it runs.
- **Earlier constraints:** all Global Constraints of steps 2 to 6 hold:
  - strict TypeScript; amounts as strings, never `Number`;
  - `useApi()`, `useToday()`, view endpoints and tokens only;
  - `npm run check` clean; exact dependency versions;
  - a component used by two features lives in `src/components`.
- **Today's pages stay exactly as they are.** Moving their logic into services changes no HTML. The proof is:
  - the web tests (`test_web_recurring*.py`, `test_recurring*.py`, `test_coming_up*.py`, `test_todo*.py`,
    `test_tags*.py`);
  - the web browser tests (`test_recurring_form.py`, `test_coming_up.py`, `test_todo_bell.py`, `test_tags.py`,
    `test_posting_date.py`);
  - the whole browser suite (310 on each browser before this step).
- **The rules stay on the server.** The app never works out:
  - a rule's status (active, paused, ended, failing), its schedule words, or its amount for a split;
  - whether a rule is plain (one account each side, same amount) or a split;
  - a day's total on Coming up, or a row's title and second line;
  - what the bell counts.

  It shows what the views say.
- **New routes:** each gets:
  - a row in `docs/developer/api.md`;
  - a classification in `tests/test_isolation.py`;
  - a test, and for a view a query-count ceiling no higher than its web page's.

  The write routes also get a case in `tests/test_api_parity.py`.
- **Wording is today's.** It comes from:
  - the templates `todo_sheet.html`, `coming_up.html`, `tags.html`, `tag_sheet.html`, `recurring.html` and
    `recurring_form.html`;
  - the flash texts `recurring-saved`, `-paused`, `-skipped`, `-resumed` and `-deleted`, and `tag-renamed`, `-merged`
    and `-deleted` (`app/flash.py`);
  - the server's own refusals.
- **Shared parts move to `src/components/lines/`:** the Add screen's rows are now used by two features, and so are
  `Picker` (entry, categories, budget, recurring), `RowSettings`, `QuickAdd`, `DateChip`, `kinds.ts` and `rows.ts`.
  Nothing else moves.
- **Not here:**
  - People (7b) and Settings (step 8). Settings is where Recurring and Tags are reached from today. Until step 8 they
    are reached by address and from the bell, Coming up and the tag chips. Their way back still says `Settings` and goes
    to `/settings` (a placeholder).

## Review Focus

1. **The bell follows the fixes.**
   - Labelling a payment or adding an account to the budget updates the count in both places and the sheet, without a
     reload.
   - The badge is hidden at zero, and the sheet then says `Nothing needs you.`
   - A refusal shows in the sheet.

   Test in Tasks 1 and 3.
2. **A rule keeps its shape through the form:**
   - one account each side with the same amount is saved plain (`from_account_id`, `to_account_id`, `amount`), never as
     postings;
   - two or more on a side is a split;
   - a category posts on Expenses (or Income) with its `category_id`;
   - editing a plain rule and saving without changes leaves it plain and the same;
   - a person, or an account that is not the person's, is refused with nothing saved.

   Test in Tasks 2 and 4.
3. **A rule's line on the list reads as today's:**
   - `Couldn't record: {error}` for a failing rule;
   - `{schedule} · paused`;
   - `{schedule} · ended` when the end date has passed;
   - otherwise `{schedule} · next {day}`.

   Pause, Resume and Skip change it, Resume skips what fell due while paused, and the paused and ended rules sit under
   `Paused`. Test in Tasks 1 and 4.
4. **Coming up's days:**
   - a day's total shows only when every row goes one way and there is more than one;
   - income reads `+` in green;
   - a rule's row opens the rule; an entry's row opens it with `back=/budget/coming-up`;
   - nothing coming up reads `Nothing is coming up before {day}.`

   Test in Tasks 1 and 3.
5. **Tags with awkward names:**
   - a tag with a space, a `/`, `%` or a non-Latin letter opens, renames, merges and deletes (the name is
     URL-encoded in the path);
   - renaming onto another tag makes them one;
   - deleting keeps the entries.

   Test in Task 3.

---

### Task 1: The bell, Coming up and the Recurring list as views

**Files:**
- Create:
  - `app/services/coming_up_view.py`, `app/services/recurring_view.py`;
  - `tests/test_api_small_views.py`.
- Modify:
  - `app/routers/web/coming_up.py`, `app/routers/web/recurring.py` (the list), `app/routers/web/todo.py`: render from
    the services; HTML unchanged.
  - `app/routers/views.py`, `app/schemas/views.py`;
  - `app/routers/transactions.py`: the new label route.
  - `tests/test_isolation.py`, `tests/test_query_counts.py`, `tests/test_api_parity.py`, `docs/developer/api.md`.

**Interfaces:**
- `coming_up_view.coming_days(service, accounts, categories) -> ComingDays`:
  - `data` (the `ComingUpRead`);
  - `days`: `[{date, total: Decimal | None, rows: [{item, title, sub}]}]`.
  - `total` is set only when every row of the day goes one way **and** there is more than one row. The template's
    `len(rows) > 1` test moves into the service; the template reads `day.total`.
- `recurring_view.rule_rows(recurring, accounts, categories) -> RuleRows`:
  - runs `catch_up()` first, as today;
  - answers `rows`, `live` (active or error) and `stopped` (paused or ended);
  - each row is `RuleRow(rule, from_name, to_name, amount, schedule, status)`.

  `status(rule)` and `describe` stay as they are.
- `GET /api/views/todo` → `TodoView`:
  - `count`;
  - `uncategorised`: the `BudgetUncategorised` fields;
  - `left_out_accounts`: `account_id`, `path`, `spent`, `entries`;
  - `card_bills`: `account_id`, `name` (the path's last part), `bill`, `due_date`, `days_to_due`;
  - `failing_rules`: `recurring_id`, `name`, `error`;
  - `categories`: `[{id, path}]`, the spending categories as the sheet's select lists them (`Food › Dining`).
- `POST /api/transactions/{transaction_id}/category` with `{category_id}` → the `TransactionRead`:
  - calls `transactions.label_payment`;
  - 404 for an entry that is not the person's;
  - 400 with the service's words otherwise (`nothing to label`, a category that is not theirs…).
- `GET /api/views/coming-up` → `ComingUpView`:
  - `through`, `count`, `total`;
  - `days`: `[{date, total, rows: [{title, sub, amount, income, recurring_id, transaction_id}]}]`.
- `GET /api/views/recurring` → `RecurringView`: `live` and `stopped`, each a list of `RuleRowRead`:
  - `id`, `title` (the payee, else the To name), `amount`, `schedule`, `status`, `next_date`, `last_error`.
- **Classification:** the three views are `LISTS`. The label route is `REFERENCES` (`transaction_id`). The label route
  also gets a parity case.

- [ ] **Step 1:** Run the baseline: `uv run pytest -q -p no:cacheprovider -k "recurring or coming or todo or tag"`.
  - Expected: PASS. Note the counts.
- [ ] **Step 2: Write the failing tests** in `tests/test_api_small_views.py`:
  - `test_the_todo_view_counts_and_lists_what_needs_you`: an unlabelled payment, a left-out account, a bill due in 2
    days, a failing rule, the category paths;
  - `test_labelling_a_payment_takes_it_off_the_list`: the count falls by one; a stranger's entry is 404; an entry with
    nothing to label is 400 with the service's words;
  - `test_coming_up_days`: a two-row expense day has a total; a mixed day and a one-row day have none; income is
    `income: true`; a rule's row has `recurring_id`, an entry's `transaction_id`;
  - `test_the_recurring_view`: the status of each kind of rule (Review Focus 3), split amounts, `Paused` holding
    paused and ended rules, the title falling back to the To name;
  - a stranger sees none of it.

  Add the classifications, the parity case and the ceilings:
  - `/api/views/todo` and `/api/views/coming-up` no higher than the page that draws them;
  - `/api/views/recurring` ≤ `/recurring`.

  Measure the web pages first.
- [ ] **Step 3:** Run.
  - Expected: FAIL (no routes).
- [ ] **Step 4:** Add the services, render the web pages from them, add the routes and schemas.
- [ ] **Step 5:** Run Step 1's command plus the new file, `tests/test_isolation.py`, `tests/test_query_counts.py`,
  `tests/test_api_parity.py` and `tests/test_api_doc.py`; then `npm --prefix frontend run gen:api` and
  `scripts/browser-tests.sh -q -k "recurring or coming_up or todo_bell"`.
  - Expected: all PASS.
- [ ] **Step 6:** Commit: `The to-do bell, Coming up and the Recurring list as views`.

### Task 2: A rule saved from the Add screen's rows

**Files:**
- Create: `app/services/recurring_form.py`, `tests/test_api_recurring_form.py`.
- Modify:
  - `app/routers/web/recurring.py`: `_parse` and `_form_page` call the service;
  - `app/routers/views.py`:
    - the Add screen's picker groups, `account_parents` and `category_parents` become helpers both form views use;
  - `app/routers/recurring.py` (the two new routes), `app/schemas/recurring.py`, `app/schemas/views.py`;
  - `tests/test_isolation.py`, `tests/test_query_counts.py`, `tests/test_api_parity.py`, `docs/developer/api.md`.

**Interfaces:**
- `recurring_form.rule_fields(rows: list[EntryRow], places: Mapping[UUID, UUID], *, payee, comment, tags, frequency,
  every: int, start_date: date, end_date: date | None) -> dict`:
  - what `_parse` does today after its own text parsing: fewer than two rows is
    `choose where the money comes from and where it goes!`;
  - one debit and one credit of the same amount is a plain rule;
  - anything else is `postings`.

  The web form builds `EntryRow`s from its lists (`form_entry_rows`) and calls it.
- `recurring_form.form_start(recurring, accounts, rule: RecurringRead | None) -> RuleStart`: `kind`, `total`,
  `from_rows`, `to_rows`, `keep` (the accounts it uses), as `_form_page` works them out today.
- `RecurringForm` (request body):
  - `payee`, `comment`, `tags`;
  - `rows: list[EntryRow]` (`posted_on` must be null: a rule has no posting day, 400 otherwise);
  - `frequency`, `every: int ≥ 1`;
  - `start_date: Day`, `end_date: Day | None`.
- `POST /api/recurring/form` → 201 `RecurringRead`, then `process_due()`, so a past start is recorded at once.
- `PUT /api/recurring/{recurring_id}/form` → `RecurringRead`. 404 for a rule that is not the person's.
- Refusals are 400 with the service's words; an account or category that is not the caller's is 404, as
  `/api/entries`.
- `GET /api/views/recurring-form?recurring_id=` → `RecurringFormView`:
  - from the rule: `editing`, `kind`, `total`, `payee`, `comment`, `tags`, `from_rows`, `to_rows` (the Add screen's
    `FormRow`);
  - for the pickers: `groups` (the Add screen's, **without People**), `account_parents`, `category_parents`;
  - the schedule: `frequency`, `every`, `start_date`, `end_date`, `frequencies` (`[{value, name}]`: day, week, month,
    year);
  - when editing: `status`, `schedule`, `active`, `next_date`, `last_date`, `skipped_date`, `last_error`.

  A new rule starts on `kind: expense`, `every: 1`, `monthly`, starting today. 404 for a stranger's rule.
- **Classification:** `POST /api/recurring/form` is `OWN_DATA`, the PUT is `REFERENCES` (`recurring_id`), and the view
  is classified as `/api/views/entry-form` is. Both writes get parity cases.

- [ ] **Step 1: Write the failing tests** in `tests/test_api_recurring_form.py`:
  - `test_a_plain_rule_from_rows_stays_plain`;
  - `test_two_lines_on_a_side_make_a_split`;
  - `test_a_category_row_posts_on_expenses_with_its_category`;
  - `test_editing_without_changes_keeps_the_rule` (Review Focus 2);
  - `test_a_past_start_is_recorded_at_once`;
  - `test_a_person_or_a_strangers_account_is_refused_and_nothing_is_saved`;
  - `test_a_posting_day_on_a_row_is_refused`;
  - `test_the_form_view_new_and_editing`: defaults; a rule's rows, schedule and status; no People group; a stranger's
    rule is 404.
- [ ] **Step 2:** Run.
  - Expected: FAIL.
- [ ] **Step 3:** Add the service, move the web form onto it, add the schemas and routes.
- [ ] **Step 4:** Run the new file, the web recurring tests, `tests/test_isolation.py`, `tests/test_query_counts.py`,
  `tests/test_api_parity.py` and `tests/test_api_doc.py`; then `npm --prefix frontend run gen:api` and
  `scripts/browser-tests.sh -q -k "recurring or posting_date"`.
  - Expected: all PASS.
- [ ] **Step 5:** Commit: `A recurring rule saved from the Add screen's rows`.

### Task 3: The bell, Coming up and Tags in the app

**Files:**
- Create:
  - `frontend/src/features/todo/`: `TodoBell.tsx` (the button with its count), `TodoSheet.tsx`, `queries.ts`,
    `Todo.module.css` (from `.bell-badge`, `.todo-item`, `.todo-empty`), tests;
  - `frontend/src/features/budget/ComingUpPage.tsx`, with its test;
  - `frontend/src/features/tags/`: `TagsPage.tsx`, `TagSheet.tsx`, `queries.ts`, `Tags.module.css` (from `.tag-row`,
    `.tag-count`, `.sheet-extra`), tests.
- Modify:
  - `app/Layout.tsx`: the bell in the top bar before Settings, and in the sidebar after the pages;
  - `app/router.tsx`: `/budget/coming-up`, `/tags`.
- Test: `tests/browser/test_spa_small_pages.py` (ported from `test_todo_bell.py`, `test_coming_up.py` and
  `test_tags.py`'s Tags-page tests).

**Interfaces:**
- **The bell:**
  - a button labelled `To do` (title too), showing `count` in a badge, hidden at zero;
  - in the sidebar it reads `To do` with the badge;
  - it reads `/api/views/todo` under the `["views", "todo"]` key, so any change to the books refreshes it.
- **The sheet** (the shared `Sheet`, titled `To do`): `Nothing needs you.` when the count is zero, otherwise four kinds
  of item:
  - **Payments with no category:**
    - heading `{n} payment has no category` / `{n} payments have no category`;
    - text `The money left the budget and no category paid for it.`;
    - one line each: `{payee or account} · {short day} · {amount}`, with a select labelled
      `Category for {payee or account}`, first option `Choose category…`;
    - choosing a category sends the label at once.

    A native select as on the web page: one tap in a sheet, no nested sheet.
  - **An account left out:**
    - heading `{path} is not in the budget`;
    - text `{spent} spent this month in {n} entry/entries is in no category.`;
    - an `Add to budget` button.
  - **A bill:**
    - heading `{name} bill is overdue by {n} day(s)` / `due today` / `due in {n} day(s)`;
    - text `{bill} · due {short day}`;
    - a `Pay bill` link to `/transactions/new?pay={id}&amount={bill}&back=/accounts/{id}`.
  - **A failing rule:**
    - heading `{name} could not be recorded`;
    - the error;
    - an `Open rule` link to `/recurring/{id}/edit`.

  Refusals show in the sheet (`role="alert"`). The sheet stays open after a fix and redraws from the view.
- **Coming up** (`/budget/coming-up`), as `coming_up.html`:
  - back `Budgets`; `Coming up`;
  - the head `Until {friendly day}`, the figure when `total` is set,
    `{n} payment(s) that touch(es) your budget accounts`;
  - then the days (friendly day, the total when set), with rows in the shared `Row`:
    - a `Repeats` marker for a rule;
    - `+` and green for income;
    - a rule's row links to `/recurring/{id}/edit`, an entry's to `/transactions/{id}/edit?back=/budget/coming-up`;
  - empty: `Nothing is coming up before {friendly day}.`
- **Tags** (`/tags`), as `tags.html`:
  - back `Settings`; `Tags`;
  - one tile of rows `#{tag}` with the count; a row opens the tag's sheet;
  - empty: `No tags yet. Add one with the # button when you record or edit an entry.` and `Record a transaction`
    (`/transactions/new`).
- **The tag sheet:**
  - `#{tag}`, `{n} entry/entries · last used {friendly day}`;
  - `View entries` → `/transactions?month={last used YYYY-MM}&tag={tag}`;
  - **Rename:** opens a field (max 30, no capitals forced), the hint `If the new name is another of your tags, the two
    become one.` and a `Rename` button. It sends `PATCH /api/tags/{encoded}` with `{name}`.
  - **Merge into…** (only when there are other tags): a select of the others and `Merge`. It sends the same PATCH with
    the chosen name.
  - **Delete tag:** confirms with `Delete the tag {tag}? It comes off {n} entry/entries; they are not deleted.`
  - A success toasts the flash text and closes the sheet; a refusal shows in it.
- **Friendly and short days** come from `lib/dates` (add `friendlyDate` if missing, with a case in
  `tests/format_cases.json` beside the Jinja filter).

- [ ] **Step 1: Write the failing Vitest tests:**
  - the bell's count and hidden badge;
  - each item's wording;
  - labelling sends `{category_id}` and the count falls;
  - Add to budget;
  - a refusal stays in the sheet;
  - Coming up's head, day totals, links and empty text;
  - the Tags list, empty state, View entries link;
  - rename, merge and delete sending the encoded name (`a b/c%`).
- [ ] **Step 2:** Run `cd frontend && npx vitest run src/features/todo src/features/tags src/features/budget`.
  - Expected: FAIL.
- [ ] **Step 3:** Build the parts.
- [ ] **Step 4: Port the browser tests** into `tests/browser/test_spa_small_pages.py`:
  - no count when nothing needs you;
  - a payment fixed from the sheet, and the count follows;
  - a bill due soon, with Pay bill opening the form;
  - Coming up opened from the Budgets "i";
  - nothing coming up;
  - the Tags page renaming, merging and deleting;
  - Tags rows inside one tile.

  Add comparisons of the bell sheet and the Tags page with the web pages (row height, font sizes) as step 6 did.
- [ ] **Step 5:** Run Step 2's command, then `npm --prefix frontend run check` and
  `scripts/browser-tests.sh -q -k "spa_small or todo_bell or coming_up or tags"`.
  - Expected: all PASS.
- [ ] **Step 6:** Commit: `The to-do bell, Coming up and Tags in the app`.

### Task 4: Recurring in the app, with the Add screen's rows shared

**Files:**
- Move to `frontend/src/components/lines/`: `Picker`, `RowSettings`, `QuickAdd`, `DateChip` (with their CSS and
  tests), `kinds.ts`, `rows.ts`. Their importers change (entry, categories, budget).
- Create:
  - `frontend/src/components/lines/Lines.tsx`;
  - `frontend/src/features/recurring/`: `RecurringPage.tsx`, `RecurringForm.tsx`, `queries.ts`,
    `Recurring.module.css` (from `.rep-row`, `.rep-label`, `.end-chip`, `.end-clear`, `.rep-hint`), tests.
- Modify:
  - `features/entry/EntryScreen.tsx`: it renders `Lines`;
  - `app/router.tsx`: `/recurring`, `/recurring/new`, `/recurring/:recurringId/edit`, and `/recurring/:recurringId`
    sending on to the edit page.
- Test: `tests/browser/test_spa_recurring.py` (ported from `test_recurring_form.py` and the recurring case of
  `test_posting_date.py`).

**Interfaces:**
- `Lines` holds everything between the kinds and the payee, and the two sides with the swap. Its props:
  - `state` (`kind`, `total`, `credit`, `debit`, the date) and `onChange`;
  - `groups`, `accountParents`, `categoryParents`;
  - `dated: boolean` (row settings offer a posting day only when true);
  - `children`, drawn where the Add screen draws the payee, the date and the Split.

  `linesBody(state, places)` returns the rows as `EntryRow`s (`choice`, `side`, `amount`, `category_id`, `posted_on`)
  or the problem (`every posting needs an account!`, `amount is required!`, `Enter the amount.`), as `send()` builds
  them today.
- **The Add screen is unchanged to the person:** its tests (`EntryScreen.test.tsx`, `EntryFields.test.tsx`,
  `test_spa_entry*.py`) pass unchanged; that is the proof of the move.
- **The Recurring list**, as `recurring.html`:
  - back `Settings`; `Recurring`;
  - the live rules, then `Paused` with the paused and ended ones (quiet rows);
  - each row reads its title, the amount, and the second line of Review Focus 3, with `{day}` from `lib/dates`
    `shortDate`;
  - empty: `Nothing on repeat yet. Rent, salary, subscriptions: set once, recorded on schedule.`;
  - the add row `New recurring` (`/recurring/new`).
- **The form**, as `recurring_form.html`:
  - back `Recurring`; `New recurring transaction` / `Edit recurring transaction`;
  - when editing, the origin line: `{schedule} · next on {friendly day}` (or `· ended` / `· paused`), then
    `· last recorded {day}` and `· skipped {day}` as today. A failing rule adds the alert
    `Couldn't record {error}. It will try again on the next run; fix the accounts or this rule.`
  - `Lines` (not dated), with the payee field as its child;
  - **The repeat row:** `Every`, a number field labelled `Every how many` (1 to 366), and a select labelled `Unit`
    whose options read `day`/`days` and so on with the number.
  - **The date chips:** `Starts` (today for a new rule) and `Ends`, reading `never` until set, with the `✕` button
    `No end date` once set. `DateChip` gains `prefix` and `emptyLabel`.
  - `A start date in the past is recorded right away for every missed date.`, only for a start before today;
  - note and tags;
  - `Save` / `Save changes`. Saving sends `POST /api/recurring/form` or the PUT, toasts `recurring-saved`'s text and
    goes to `/recurring`. A refusal shows above the button.
- **When editing,** a section titled `Active` or `Paused`:
  - **Active:** `Pause it to stop recording without losing the rule.` and `Pause`; then `Just this once? Skip the next
    one ({friendly day}) and carry on after it.` and `Skip {friendly day}`, confirming with
    `Skip {DD Mon YYYY}? Nothing will be recorded for it.`
  - **Paused:** `Occurrences missed while paused are skipped.` and `Resume`.
  - **Ended:** `It has ended. Move the end date to carry on.`
  - `Delete`, confirming with `Delete this recurring transaction? Transactions it already recorded are kept.`

  Each of the four toasts its flash text and goes to `/recurring`, as the web page's redirect does.

- [ ] **Step 1:** Move the shared files and extract `Lines` and `linesBody`; run
  `cd frontend && npx vitest run src/features/entry src/features/categories src/features/budget` and
  `scripts/browser-tests.sh -q -k "spa_entry"`.
  - Expected: PASS unchanged. Commit: `The Add screen's rows as a shared part`.
- [ ] **Step 2: Write the failing Vitest tests** for the list and the form:
  - the rows' second lines;
  - the Paused group;
  - empty;
  - a plain rule sent as rows, with the rows and the schedule in the body;
  - the unit words following the number;
  - the end chip clearing;
  - the past-start hint;
  - no posting day in row settings;
  - Pause, Skip (with its confirm), Resume and Delete;
  - a refusal shown.
- [ ] **Step 3:** Run `cd frontend && npx vitest run src/features/recurring`.
  - Expected: FAIL.
- [ ] **Step 4:** Build the pages.
- [ ] **Step 5: Port the browser tests** into `tests/browser/test_spa_recurring.py`:
  - a split rule from the form;
  - a plain rule stays plain;
  - skipping from the edit page;
  - tags on a rule;
  - the repeat row's unit and the end chip;
  - the list as flat rows in a tile;
  - the past-start hint;
  - no date in a rule's row settings;
  - the bell's `Open rule` reaching the form.

  Add a comparison of the list and the form head with the web pages.
- [ ] **Step 6:** Run Step 3's command, `npm --prefix frontend run check` and `scripts/browser-tests.sh -q -k
  "spa_recurring or spa_entry or recurring_form"`.
  - Expected: all PASS.
- [ ] **Step 7:** Commit: `Recurring in the app`.

### Task 5: Docs and the whole check

**Files:**
- Modify: `docs/developer/code-map.md`:
  - the three services;
  - `components/lines/`;
  - `features/todo`, `tags`, `recurring`;
  - Coming up.

- [ ] **Step 1:** Update the code map. Check the `api.md` rows added in Tasks 1 and 2 read as the routes behave.
- [ ] **Step 2: Run the whole check:**
  - `uv run ruff check app tests migrations scripts`, `uv run ruff format --check app tests migrations scripts`,
    `uv run pyrefly check`;
  - `uv run pytest -q -p no:cacheprovider`;
  - `npm --prefix frontend run check`;
  - `scripts/browser-tests.sh -q -p no:cacheprovider`, and the same with `FINODE_BROWSER=webkit`.
  - Expected: all PASS.
- [ ] **Step 3:** Commit `Docs for the bell, Coming up, Tags and Recurring`, then `git push origin
  feature/react-frontend`.

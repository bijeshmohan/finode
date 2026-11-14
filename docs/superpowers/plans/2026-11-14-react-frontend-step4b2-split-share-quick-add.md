# React frontend, step 4b-2: several lines, sharing with people, adding an account or category — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the React Add/Edit screen so it does everything today's form does. That means:
- several lines on a side, each with its own amount and posting date, set in the row settings sheet;
- Split: an expense or an income shared with people, with the server's preview as you type;
- adding an account or a category from the picker sheet;
- editing any entry the form edits today, so the "edit it on the web page for now" notice goes.

**Architecture:**
- **The server:** saving a shared bill or income is still worked out in the web router (`expense_data`, `income_data`,
  `editor_values`, `income_values`, the share branches of `create_split_transaction` and `update_transaction`). It moves
  into `services/entry_share.py` and `EntryService`, so the web form and `/api/entries` share one path. The share
  travels as a typed `share` object on `EntryForm`, which mirrors the form's own fields. The server still decides what
  "you paid the rest" means.
- **The form's view:** `GET /api/views/entry-form` adds:
  - the people and the share's starting values;
  - where a new account or category can go;
  - `mode`.
- **The preview:** comes from a new `POST /api/views/entry-share-preview`.
- **The app:** keeps the rows of each side in state. It works out only what is left to allocate, with `big.js`, as the
  spec allows.

**Tech Stack:** FastAPI, Pydantic, React, TanStack Query, `big.js` 7.0.1 (`@types/big.js` 7.0.0), Vitest, Python
`pytest-playwright`.

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md` (step 4; "Money": the only client arithmetic is
the Add screen's split preview, with `big.js`). Step 4b-1's plan
(`docs/superpowers/plans/2026-11-14-react-frontend-step4b1-add-screen.md`) defined this step's scope.

## Global Constraints

- **Branch:** `feature/react-frontend` only; nothing reaches `develop`. `make` is not installed: run what it runs.
- **Earlier constraints:** all Global Constraints of steps 2, 3, 4a and 4b-1 hold:
  - strict TypeScript; amounts as strings;
  - `useApi()`, `useToday()`, view endpoints and tokens only;
  - `npm run check` clean; exact dependency versions.
- **Today's pages stay exactly as they are.** The move of the share branches changes no answer of the web routes. The
  proof is their tests and the browser suite (238 on each browser).
- **The rules stay on the server.** The app never works out:
  - a share, what someone owes, or "you paid whatever the others did not";
  - which account a category posts to, or what an edit releases.

  It sends what the person typed and shows the server's preview and messages.
- **`big.js` is for the remainder only.** It works out what is left to allocate on a side, the suggested amount of the
  open row, and whether a row differs from the total. Nothing else in the app does arithmetic on money.
- **New `/api` routes:** every one gets a row in `docs/developer/api.md`, a classification in `tests/test_isolation.py`
  and a test. The views get query-count ceilings:
  - `/api/views/entry-form`, blank: at most 5. It is 4 today; the people may add one.
  - `/api/views/entry-form`, editing a shared bill, and `/api/views/related-entries`: measured in Task 2 and set at
    what they make, with a comment naming each read.
  - `/api/views/entry-share-preview`: the same.

  No view may query once per row, person or account.
- **Every new write path** keeps a test asserting `trial_balance().balanced`.
- **Wording is today's**, from:
  - the templates `txn_rows.html`, `txn_row.html`, `people_editor.html`, `income_editor.html`, `people_sheet.html`,
    `expense_preview.html`, `income_preview.html`, `quick_account.html` and `quick_category.html`;
  - `app.js` (`left to allocate`, `over`, `Posts <day>`, `left`);
  - the flash texts `Expense recorded`, `Income recorded`, `Transaction updated`.
- **Still out of scope:**
  - the recurring form, which shares `txn_rows.html` today and moves in step 7;
  - entries a person's page looks after, which still open that page.

## Review Focus

1. **Editing a shared bill back into Simple** (or an ordinary expense into a shared one): what it was is released first,
   in one transaction, and a failure leaves it as it was. Test in Task 1.
2. **A person taken out of a split** after a share or a payment was typed for them: nothing of theirs is sent, so no
   share or debt is recorded for them. Test in Task 4.
3. **Rows that add up to more or less than the total:** the side says `₹200.00 INR over` or `… left to allocate`. Save
   still sends the rows, and the server's refusal shows. This holds in a currency without decimals too: JPY `1000` with
   a row of `333` suggests `667`. Test in Task 3.
4. **Adding from the picker:**
   - From an Expense's To side, it makes a spending category; from an Income's From side, an earning category; from an
     account side, an account under the chosen parent.
   - The new one is chosen on that row.
   - A name already taken shows the server's message inside the sheet, and the sheet stays open.

   Test in Task 5.
5. **Changing the kind while in Split:** a transfer goes back to Simple and keeps the rows. Coming back to Expense keeps
   the people ticked. Test in Task 4.

---

### Task 1: Sharing goes through the entry service

A refactor: the web routes' share branches move into the service.

**Files:**
- Create: `app/services/entry_share.py`, `tests/test_entry_share.py`
- Modify:
  - `app/schemas/entry.py`
  - `app/services/entry.py`
  - `app/routers/web/transactions.py`: the share branches call `Entries`.
  - `app/routers/web/people.py`: `expense_data` and `income_data` become thin form readers over the new service
    functions; the preview routes use them too.
  - `app/dependencies.py`: `Entries` also gets `ExpenseSharingService` and `IncomeSharingService` if it does not have
    them yet.

**Interfaces:**
- `app/schemas/entry.py`:
  - `PersonShare`:
    - `contact_id: UUID`
    - `value: Decimal | None = None`: their share for `exact` / `percentage` / `shares`.
    - `paid: Decimal | None = None`: what they paid of the bill.
  - `ExpenseShare`:
    - `kind: Literal["expense"]`
    - `category_id: UUID | None`
    - `account_id: UUID | None`: "You paid from".
    - `method: Literal["equal", "exact", "percentage", "shares"] = "equal"`
    - `self_value: Decimal | None = None`
    - `self_paid: Decimal | None = None`: blank means whatever the others did not pay.
    - `people: list[PersonShare]`
  - `IncomePart`:
    - `contact_id: UUID`
    - `theirs: Decimal | None = None`
    - `received: Decimal | None = None`
  - `IncomeShare`:
    - `kind: Literal["income"]`
    - `category_id: UUID | None`
    - `account_id: UUID | None`: "Paid into".
    - `people: list[IncomePart]`
  - `EntryForm`:
    - Gains `total: Decimal | None = None` (the bill's or income's amount, used with `share`).
    - Gains `share: ExpenseShare | IncomeShare | None = Field(default=None, discriminator="kind")`.
    - `rows` defaults to `[]`, because a share has none.
  - `EntrySaved.recorded`: `Literal["transaction", "transfer", "expense-shared", "income-shared"]`.
- `app/services/entry_share.py`:
  - `expense_create(form: EntryForm, share: ExpenseShare, people: set[UUID]) -> SharedExpenseCreate`: today's
    `expense_data` rules, with the same messages (`choose the account you paid from!`).
  - `income_create(form: EntryForm, share: IncomeShare, people: set[UUID]) -> SharedIncomeCreate`: today's `income_data`
    (`choose the account it was paid into!`).
  - Both take `people`, the person's own active contacts. A `contact_id` outside it is `ValueError("person not found")`.
  - `expense_start(bill: SharedExpenseRead | None, with_id: UUID | None) -> ExpenseShare`.
  - `income_start(shared: SharedIncomeRead | None) -> IncomeShare`.

  The two start functions replace `editor_values` and `income_values`. The web templates read the same values from the
  typed objects; the template changes are mechanical (`ed.checked` becomes `{p.contact_id for p in ed.people}`, and so
  on).
- `EntryService.create(form)`:
  - With `share`, records it through `expenses.create(…, confirm=True)` or `incomes.create(…)`.
  - Answers `recorded="expense-shared"` or `"income-shared"`, with the new entry's id.
- `EntryService.update(transaction_id, form)`:
  - With `share`: `release(transaction_id, purposes, "bill" | "income")`, then `expenses.convert` or `incomes.convert`,
    in one transaction.
  - Without `share`, as today. That path already releases a bill or an income.

- [ ] **Step 1:** Run the baseline: `uv run pytest tests/test_web_transaction_form.py tests/test_people_through_plus.py
  tests/test_shared_expenses.py tests/test_shared_incomes.py tests/test_entry_service.py -q`.
  - Expected: PASS. Note the counts.
- [ ] **Step 2: Write the failing tests** in `tests/test_entry_share.py`:
  - `test_an_equal_split_owes_each_their_part`: 900 among you and Alice gives Alice a receivable of 450; balanced.
  - `test_a_blank_self_paid_is_what_the_others_did_not_pay`: 1000; Alice paid 1000, `self_paid=0`; Alice payable 500.
  - `test_choose_the_account_you_paid_from`: the message.
  - `test_income_part_theirs`: 10000 with Alice's part 4000; your income is 6000.
  - `test_a_person_who_is_not_yours_is_refused`: a contact id of user B raises `ValueError("person not found")`.
  - `test_an_ordinary_expense_edited_into_a_shared_bill`: in place, the date kept.
  - `test_a_shared_bill_edited_back_into_simple_releases_it`: Review Focus 1; the receivable is gone, the entry stays,
    balanced.
  - `test_a_failed_share_edit_leaves_the_bill_as_it_was`: Review Focus 1; the edit's share has no account, so it is
    refused and the bill is unchanged.
  - `test_the_start_values_of_a_bill`: `expense_start` of a percentage bill gives the values, Alice's `paid` and
    `self_paid`.
- [ ] **Step 3:** Run the new tests.
  - Expected: FAIL (no module).
- [ ] **Step 4:** Move the logic. The web share branches become `entries.create(EntryForm(…, share=…))` and
  `entries.update(…)`, with the share read from the form by `expense_share_from_form(form, people)` and
  `income_share_from_form(form, people)` in `routers/web/people.py`. The redirects and flash keys stay as they are.
- [ ] **Step 5:** Run Step 1's command plus `tests/test_entry_share.py`.
  - Expected: PASS, same counts plus the new ones.
- [ ] **Step 6:** Run `scripts/browser-tests.sh -q -k "people or transaction_form or posting_date"`.
  - Expected: PASS.
- [ ] **Step 7:** Commit: `Sharing a bill or an income goes through the entry service`.

### Task 2: The API for sharing, adding and editing everything

**Files:**
- Modify:
  - `app/routers/entries.py`
  - `app/routers/views.py`
  - `app/schemas/views.py`
  - `tests/test_api_entries.py`
  - `tests/test_api_views.py`
  - `tests/test_query_counts.py`: the ceilings in Global Constraints. This also clears 4b-1's stray comment.
  - `tests/test_isolation.py`
  - `tests/test_api_parity.py`
  - `docs/developer/api.md`
  - `frontend/openapi.json`, `frontend/src/api/schema.d.ts` (via `npm run gen:api`)

**Interfaces:**
- `POST /api/entries` and `PUT /api/entries/{transaction_id}` take `share`. Errors:
  - `LookupError` → 404;
  - `ConflictError` (from `contact_errors`) → 409, e.g. a bill already paid back;
  - other `ValueError` → 400.

  This settles 4b-1's deferred minor.
- `EntryFormView`:
  - Drops `simple`: every entry the web form edits is editable here.
  - Gains `mode: Literal["simple", "split"]`, `people: list[PersonRef]` (the active contacts) and
    `expense_share: ExpenseShare`.
  - Also gains `income_share: IncomeShare`. Both are starting values: the bill or income being edited, or blank with
    `?with=` ticked.
  - Gains `account_parents: list[ParentOption]` and `category_parents: list[CategoryParent]`.
    - `ParentOption`: `id`, `name`, `depth`, `root`, and `opening_balance: bool` (the root takes a current balance).
    - `CategoryParent`: `id`, `name`, `kind`.
    - The lists offer what the quick sheets offer today (`_parent_options`, the top-level categories).
- `GET /views/entry-form` takes `mode=split` (with `with`), as `/transactions/new?mode=split&with=` does.
- `POST /api/views/entry-share-preview`:
  - Body: `{ total: Decimal, date: Day | None, payee: str, share: ExpenseShare | IncomeShare }`.
  - Answers `SharePreview`: `{ kind, message: str | None, expense: ExpensePreview | None, income: IncomePreview | None }`.
  - A refusal is a 200 with `message`, as today's preview shows it inline.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_bill_shared_through_the_api` (201 `expense-shared`, Alice receivable, balanced).
  - `test_an_income_shared_through_the_api`.
  - `test_a_shared_bill_edited_through_the_api` (PUT).
  - `test_a_conflict_is_409`.
  - `test_the_form_view_of_a_shared_bill` (`mode == "split"`, its `expense_share`).
  - `test_the_form_view_of_several_lines` (two rows on the To side, each with its amount and `posted_on`).
  - `test_split_with_a_person_starts_ticked` (`?mode=split&with=`).
  - `test_the_parents_a_new_account_can_go_under` (no Expenses or Income; groups with depth; `opening_balance` on Assets
    and Liabilities).
  - `test_the_share_preview` (Alice owes 450) and `test_the_share_preview_says_what_is_wrong` (`message`).
  - The isolation sweep for the preview's `contact_id`, `account_id` and `category_id`: user B's ids give `person not
    found` or `account not found`.
  - The three ceilings.
- [ ] **Step 2:** Run.
  - Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `tests/test_api_entries.py tests/test_api_views.py tests/test_query_counts.py
  tests/test_isolation.py tests/test_api_parity.py tests/test_api_doc.py`, then `npm --prefix frontend run gen:api`.
  - Expected: PASS.
- [ ] **Step 5:** Commit: `Sharing, the share preview and the quick-add parents in the API`.

### Task 3: Several lines on a side

**Files:**
- Create:
  - `frontend/src/lib/split.ts` and `split.test.ts`
  - `frontend/src/features/entry/RowSettings.tsx`, a CSS module from `.row-settings` and `.pick-fields` in
    `style.css`, and `RowSettings.test.tsx`
- Modify:
  - `frontend/src/features/entry/EntryScreen.tsx`: `RowState` becomes a list per side.
  - `EntryScreen.test.tsx`
  - `frontend/package.json`: `big.js` 7.0.1, `@types/big.js` 7.0.0, exact versions.
- Test: `tests/browser/test_spa_entry_lines.py`

**Interfaces:**
- `lib/split.ts`, the only place `big.js` is used:
  - `left(total: string, amounts: string[]): string`: total minus the rows that have an amount, as a plain decimal
    string.
  - `allocation(total: string, amounts: string[], places: number): { left: string; over: boolean; balanced: boolean }`.
  - `differs(amount: string, total: string): boolean`.
  - Inputs are cleaned amounts (`tidyAmount` without grouping). An empty or invalid amount counts as nothing.
- Each side's state is `RowState[]`, with `RowState = { key, choice, category, amount: string, postedOn, touched }`.
  The rules are today's `recomputeTxn`:
  - At most one open (untouched) row on a side, and only while something is left.
  - Its suggestion is what is left; a row typed in becomes touched.
  - A side with one row has no Remove.
  - A side with several rows shows each row's amount. A single row shows its amount only when it differs from the total.
- `RowSettings`: a bottom sheet titled with the row's account, opened by the glyph `Amount and date`. It holds:
  - `Amount`, an `AmountField`;
  - `Date`, a native date input, shown only on an account (not on a category or a person);
  - a `Done` pill, and a red `Remove` link below it when the side has more than one row.

  A posting date equal to the entry's date is sent as `null`. The row shows `Posts 2 Nov` when it differs.
- The side status (`aria-live="polite"`) reads `₹400.00 INR left to allocate` or `₹200.00 INR over`, and nothing when
  balanced.

- [ ] **Step 1: Write the failing tests:**
  - `split.test.ts`:
    - `left("1,000.00", ["600"]) === "400.00"`;
    - over: `allocation("1000", ["600", "600"], 2)` is `{left: "-200.00", over: true}`;
    - JPY: `left("1000", ["333"])` with places 0 is `"667"` (Review Focus 3);
    - an empty or invalid amount counts as 0;
    - `differs("1,000.00", "1000") === false`.
  - `EntryScreen.test.tsx`:
    - `typing less in a row adds a row with what is left`;
    - `removing a row brings the remainder back to one row`;
    - `several rows are sent, each with its amount and posting date`;
    - `a side that does not add up says so and Save still sends it, showing the server's refusal` (Review Focus 3).
  - `RowSettings.test.tsx`:
    - `the date is offered only on an account`;
    - `Remove only when there are several rows`.
  - `tests/browser/test_spa_entry_lines.py`, ported from `test_transaction_form.py`, `test_posting_date.py` and
    `test_category_chip.py`:
    - typing less adds a row with the remainder; removing a row brings it back;
    - a later posting date is stored, shown on the row and changes the bill;
    - a split across two cards has a date for each;
    - editing shows a posting date and keeps it;
    - a row is removed from its own sheet;
    - the settings sheet has two cells, a Done pill and a red Remove below it;
    - a row shows its amount only when it differs from the total;
    - removing a row brings one category back.
- [ ] **Step 2:** Run `npm --prefix frontend run test -- split RowSettings EntryScreen`.
  - Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the same, then `scripts/browser-tests.sh -q -k spa_entry`.
  - Expected: PASS.
- [ ] **Step 5:** Commit: `Several lines on a side, each with its amount and posting date`.

### Task 4: Split: a bill or an income shared with people

**Files:**
- Create in `frontend/src/features/entry/`:
  - `ShareEditor.tsx` (expense) and `IncomeShareEditor.tsx`;
  - `PeopleSheet.tsx` ("Split with");
  - `SharePreview.tsx`;
  - their CSS modules from `.people-editor`, `.share-row`, `.preview` and `.preview-list` in `style.css`;
  - `ShareEditor.test.tsx`.
- Modify: `EntryScreen.tsx`, `queries.ts` (`useSharePreview`)
- Test: `tests/browser/test_spa_entry_share.py`

**Interfaces:**
- The `Simple` / `Split` switch (`role="radiogroup"`, `How it is recorded`) shows only for Expense and Income. Split
  hides the From and To sides and opens the editor. On the first switch, the editor takes over what the rows already
  say (today's `CARRY`):
  - expense: From → "You paid from", To → Category;
  - income: To → "Paid into", From → "Earned from".
- Split also clears a payee person.
- The expense editor has:
  - `Category`, and `You paid from` (the account picker);
  - `Split`: `Equally`, `Amounts`, `%`, `Shares`;
  - a `You` row (always in) and one row per ticked person, each with a value field when the method is not equal and a
    `Remove <name>` button;
  - `+ Add people`;
  - `Someone else paid some of it` (a disclosure) with `You paid` (blank: whatever the others did not) and `<name> paid`.
- The income editor has:
  - `Earned from` and `Paid into`;
  - `Their part` rows;
  - `Someone else received some of it for you` with `<name> received`.
- With no people at all, either editor shows `Add the people you share costs with first.` (income: `share money with`)
  and an `Add a person` link to `/people/new`.
- The preview asks `entry-share-preview` 400 ms after the last change, with the body Save would send. It shows the
  server's lines with today's wording, or its `message`. It is announced with `aria-live="polite"`.
- Save sends `rows: []` and `share`. Only the ticked people are sent, so a removed person's typed values are dropped
  (Review Focus 2). The toast is `Expense recorded` or `Income recorded` when adding, `Transaction updated` when editing.
- Switching to Transfer or Other leaves Split for Simple and keeps the rows and the ticked people (Review Focus 5).

- [ ] **Step 1: Write the failing tests:**
  - `ShareEditor.test.tsx`:
    - `the rows carry over into the editor`;
    - `a removed person's values are not sent` (Review Focus 2);
    - `the preview shows the server's words`;
    - `a transfer goes back to Simple and Expense comes back with the people` (Review Focus 5);
    - `with no people it asks to add one`.
  - `tests/browser/test_spa_entry_share.py`, ported from `test_people.py`:
    - more rows is still Simple: Split is for people;
    - a bill shared shows its result as you type (Equally and then %, saved, receivables 270 and 180);
    - switching to Split carries over what the rows say;
    - a friend who paid can be recorded;
    - the share rows sit in a line;
    - an old expense can be edited into a shared bill, and opens again in Split;
    - income shared with a person from the Add screen;
    - only the people added are listed, and the sheet adds and removes them.
- [ ] **Step 2:** Run.
  - Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm --prefix frontend run test -- ShareEditor EntryScreen` and `scripts/browser-tests.sh -q -k
  spa_entry`.
  - Expected: PASS.
- [ ] **Step 5:** Commit: `Split: a bill or an income shared with people, with the server's preview`.

### Task 5: Adding an account or a category from the picker

**Files:**
- Create: `frontend/src/features/entry/QuickAdd.tsx`, its CSS module from `.sheet-head` in `style.css`,
  `QuickAdd.test.tsx`
- Modify: `Picker.tsx` (a `New account` / `New category` option at the end, as `pick_dialog.html` has it),
  `EntryScreen.tsx`, `queries.ts` (`useAddAccount`, `useAddCategory`)
- Test: `tests/browser/test_spa_entry.py` (two tests ported from `test_account_picker.py` and
  `test_transaction_form.py`)

**Interfaces:**
- **Where it opens:**
  - From a side whose picker offers categories, the sheet is `New category`, with:
    - `Name` (placeholder `e.g. Pharmacy`, or `e.g. Freelance` for earning);
    - `Under`, offering `None (top level)` and the `category_parents` of that kind.

    The kind is spending on an Expense's To side and earning on an Income's From side.
  - Otherwise it is `New account`, with:
    - `Name`;
    - `Belongs under`: the `account_parents`, indented by depth, with the side's first root chosen;
    - `Current balance` (optional; `Recorded as an opening balance dated today.`), only when the parent's
      `opening_balance` is true.
- **Saving:** `Add account` posts `/api/accounts/` and `Add category` posts `/api/categories/`. On success:
  - the views are refreshed;
  - the new one is chosen on the row the sheet was opened from;
  - the sheet closes.
- **A refusal** shows the server's message in the sheet (`role="alert"`), and the sheet stays open (Review Focus 4).
- `Cancel` and the close button keep the row as it was.

- [ ] **Step 1: Write the failing tests:**
  - `QuickAdd.test.tsx`:
    - `from an expense's To side it makes a spending category and chooses it`;
    - `from an income's From side, an earning one`;
    - `an account under the chosen parent, with a balance only where it takes one`;
    - `a name already taken keeps the sheet open with the server's words` (Review Focus 4).
  - Browser tests:
    - `test_a_new_account_can_be_made_from_the_sheet` (Kotak is chosen and exists);
    - `test_adding_a_category_from_the_picker` (Coffee is chosen and exists).
- [ ] **Step 2:** Run.
  - Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the Vitest files and `scripts/browser-tests.sh -q -k spa_entry`.
  - Expected: PASS.
- [ ] **Step 5:** Commit: `An account or a category added from the picker`.

### Task 6: Every entry opens in the React app; docs; the whole check

**Files:**
- Modify:
  - `frontend/src/features/entry/EntryRoute.tsx`: the notice goes, and `mode` and `with` are passed.
  - `EntryRoute.test.tsx`
  - `docs/developer/code-map.md`: `entry_share`, and the `entry/` files.
  - `docs/developer/api.md`: confirm the rows.
  - `docs/developer/reference/ui-pages.md`: the Add screen's React notes, if it has a React section; otherwise nothing.
  - `AGENTS.md`: only if a rule changed. The share rule joins the `EntryService` bullet: "a shared bill or income too".

**Interfaces:**
- `EntryRoute` passes `mode` and `with` from the address (`/transactions/new?mode=split&with=<person>`).
- An entry a person's page looks after still opens that page. Everything else opens in the form.

- [ ] **Step 1: Write the failing tests:**
  - `EntryRoute.test.tsx`:
    - `a shared bill opens in Split`;
    - `an entry with several lines opens with them`;
    - `?mode=split&with= starts with the person ticked`.
  - The 4b-1 test `an entry with several lines says where to edit it for now` is removed, because the behaviour it
    pinned is gone.
- [ ] **Step 2:** Run.
  - Expected: FAIL.
- [ ] **Step 3:** Implement and write the docs.
- [ ] **Step 4:** The whole check:
  - `uv run ruff check app tests migrations scripts` and `uv run ruff format --check app tests migrations scripts`;
  - `uv run pyrefly check`;
  - `uv run pytest -q`;
  - `npm --prefix frontend run check`;
  - `scripts/browser-tests.sh -q`, then `FINODE_BROWSER=webkit scripts/browser-tests.sh -q`.

  Expected: all PASS.
- [ ] **Step 5:** Commit `Every entry opens in the React app; docs for 4b-2`, then `git push origin
  feature/react-frontend`.

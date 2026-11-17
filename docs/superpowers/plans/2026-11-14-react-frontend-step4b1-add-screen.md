# React frontend, step 4b-1: the Add/Edit screen, Simple mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record and edit an entry in the React app the way today's Add screen does in its Simple mode: Expense,
Income or Transfer (or any accounts), one amount, From and To chosen in our own picker sheet, the payee with its chips
(and naming a person after an `@`), the date chip, a related entry, the note and its tags, the category of a payment
into a loan or fund; Save, Save changes and Delete; opened blank, from an account or category, as Repeat or Related,
or to pay a card bill.

**Architecture:** Saving an entry of any kind is today worked out in the web router (`create_split_transaction`,
`update_transaction`, `_release`, `_person_rows`, `named_person`, `split_postings`): it moves to
`app/services/entry.py`, which the web routes and a new `POST /api/entries` / `PUT /api/entries/{transaction_id}` share.
The form's starting values and its picker groups come from one view, `GET /api/views/entry-form`, built from the same
code as today's form (`form_context`, `form_rows`, `infer_kind`), and the related picker from
`GET /api/views/related-entries`. The React screen keeps the form's state in React Hook Form, amounts as strings, and
sends rows as `{choice, side, amount}` like the web form does.

**Tech Stack:** FastAPI, Pydantic, React, React Router, TanStack Query, React Hook Form, Zod, Vitest, Python
`pytest-playwright`.

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md` (step 4). Step 4 is split: 4a (lists, done),
4b-1 here, and 4b-2 (Split mode with several rows and `big.js`, row amounts and posting dates, bills and income shared
with people, adding an account or a category from the picker), planned once this one has landed.

## Global Constraints

- Branch `feature/react-frontend` only; nothing reaches `develop`. `make` is not installed: run what it runs.
- All Global Constraints of steps 2, 3 and 4a hold (strict TypeScript, strings for money and no arithmetic on them in
  the app, `useApi()`, `useToday()`, view endpoints, tokens only, `npm run check` clean, exact versions).
- **Today's pages stay exactly as they are**: the move to `services/entry.py` changes no answer of the web routes
  (their tests and the 216 browser tests are the proof).
- **The rules of an entry stay on the server.** The app never decides which account a category posts to, whether a
  person's row makes a loan, or what an edit releases: it sends what the person chose and shows the server's message.
- Every new `/api` route: a row in `docs/developer/api.md`, a classification in `tests/test_isolation.py`, a test, and
  for the form view a query-count ceiling no higher than `/transactions/new` (4).
- New ways of writing transactions keep a test asserting `trial_balance().balanced` (AGENTS.md).
- Wording is today's (`transaction_form.html`, `txn_rows.html`, `txn_row.html`, `txn_payee.html`, `tags_box.html`,
  `tags_dialog.html`, `related_picker.html`, `related_results.html`, `pick_dialog.html`, flash keys
  `transaction-saved`, `transaction-updated`, `transfer-recorded`, `transaction-deleted`).
- Not in this step (they keep their web pages until 4b-2): Split mode, several rows on a side, a row's own amount and
  date, sharing with people, adding an account or a category from the picker. An entry being edited that has several
  rows on a side, or is a shared bill or income, opens a notice `This entry has several lines: edit it on the web page
  for now.` with a link to today's `/transactions/{id}/edit` — and nothing else — until 4b-2.

## Review Focus

1. A category is chosen on a row: the API receives the category's id and the server posts the line on Expenses or
   Income with that category, exactly as the web form does (`category_places`). Test in Task 2.
2. Editing an entry that was a loan, a gift or a shared bill into an ordinary entry (or back): what it was is released
   first, in one transaction; a failure leaves it as it was. Test in Task 1.
3. The kind switch: a chosen account survives a kind that still offers it and is cleared by one that does not; tapping
   the selected kind again offers every account. Test in Task 4.
4. Two quick taps on Save record one entry. Test in Task 4.
5. A pasted amount (`1,500.00`, `₹ 1,500`, `−1,234.50`) is cleaned without moving the cursor to the end, and grouped
   as typed (the step 2 minor). Test in Task 4.

---

### Task 1: One service for saving an entry

A refactor of the web routes' save logic into `app/services/entry.py`.

**Files:**
- Create: `app/services/entry.py`, `app/schemas/entry.py`, `tests/test_entry_service.py`
- Modify: `app/routers/web/transactions.py` (`create_split_transaction`, `update_transaction` call the service for
  everything but a shared bill or income), `app/dependencies.py` (`Entries`)

**Interfaces:**
- `app/schemas/entry.py`:
  - `EntryRow`: `choice: UUID` (an account, a category or a person), `side: PostingSide`, `amount: Decimal`,
    `category_id: UUID | None = None` (a payment into a loan or fund), `posted_on: Day | None = None`.
  - `EntryForm`: `kind: Literal["expense", "income", "transfer", "other"]`, `date: Day | None`, `payee: str | None`,
    `comment: str | None`, `tags: list[str] = []`, `related_id: UUID | None`, `payee_contact: UUID | None` (a person
    named after `@`), `rows: list[EntryRow]`.
  - `EntrySaved`: `transaction_id: UUID`, `recorded: Literal["transaction", "transfer"]` (a transfer with a person is
    recorded by the people services).
- `app/services/entry.py`: `class EntryService` built from `TransactionService`, `ContactService`, `TransferService`,
  `ExpenseSharingService`, `IncomeSharingService`, `AccountService`, `CategoryService`:
  - `create(form: EntryForm) -> EntrySaved` — today's non-share branch of `create_split_transaction`: a person on a row
    → `transfers.move` (`_person_rows`); else postings from the rows (`split_postings`' rules: a category choice posts
    on Expenses/Income with the category), the gift named (`named_person` + `name_gift`), one commit; any failure
    discards.
  - `update(transaction_id: UUID, form: EntryForm) -> EntrySaved` — today's non-share branch of `update_transaction`,
    `_release` included.
  - Raises `ValueError` with today's messages; `LookupError` for an unknown transaction.
  - `_person_rows`, `named_person`, `split_postings`, `category_places`, `infer_kind`, `form_rows`, `_release` move
    here (the web router imports what it still needs).
- `app/dependencies.py`: `Entries = Annotated[EntryService, Depends(get_entry_service)]`.

- [ ] **Step 1:** `uv run pytest tests/test_web_transaction_form.py tests/test_web_transactions.py
  tests/test_people_through_plus.py tests/test_contact_transfers.py tests/test_splits.py tests/test_related_transactions.py
  -q` — expected: PASS (the baseline).
- [ ] **Step 2: Write the failing tests** `tests/test_entry_service.py` (with `svc`-style services and the books
  helpers): `test_an_expense_on_a_category` (the line is on Expenses with the category; balanced);
  `test_a_payment_into_a_loan_keeps_its_category`; `test_a_person_on_a_transfer_is_a_loan` (`recorded ==
  "transfer"`); `test_naming_a_person_after_at_is_a_gift`; `test_editing_a_loan_into_an_ordinary_entry_releases_it`
  (the person's obligation is gone, the entry stays, balanced); `test_a_failed_edit_leaves_the_loan_as_it_was`
  (Review Focus 2: an edit that fails validation after the release → the loan is still there); `test_messages`
  (`every posting needs an account!`, `a person goes on one side, one of your accounts on the other, for one amount!`).
- [ ] **Step 3:** Run — expected: FAIL (no module).
- [ ] **Step 4:** Move the logic; the web routes call `Entries` and keep only form parsing, the share branches and
  their redirects.
- [ ] **Step 5:** Step 1's command and the new tests — expected: PASS. `scripts/browser-tests.sh -k
  "transaction_form or people or row_category or tags or account_picker"` — expected: PASS.
- [ ] **Step 6:** Commit: `Saving an entry is one service, shared by the web form and the API`.

### Task 2: `POST /api/entries` and `PUT /api/entries/{transaction_id}`

**Files:**
- Create: `app/routers/entries.py`
- Modify: `app/main.py`, `tests/test_isolation.py` (`REFERENCES`; the id sweep covers the PUT), `docs/developer/api.md`
  (an "Entries" section: what the Add screen saves, and how it differs from `/transactions`)
- Test: `tests/test_api_entries.py`

**Interfaces:**
- `POST /entries` body `EntryForm` → 201 `EntrySaved`; `PUT /entries/{transaction_id}` → 200 `EntrySaved`;
  `ValueError` → 400 with the message; `LookupError` → 404. Router `tags=["entries"]`,
  `dependencies=[Depends(require_authenticated_user)]`.

- [ ] **Step 1: Write the failing tests:** `test_an_entry_on_a_category_posts_as_the_web_form_does` (Review Focus 1:
  the same postings as `POST /transactions/split` with the same choices); `test_a_transfer_to_a_person_is_a_loan`;
  `test_editing_an_entry`; `test_refusals_say_why` (400 with the message); `test_another_persons_entry_is_not_found`
  (404); `test_the_books_stay_balanced` (`trial_balance().balanced` after each).
- [ ] **Step 2:** Run — expected: FAIL. **Step 3:** Implement. **Step 4:** Run with `tests/test_isolation.py
  tests/test_api_doc.py` — expected: PASS; `npm --prefix frontend run gen:api`.
- [ ] **Step 5:** Commit: `The Add screen's save under /api/entries`.

### Task 3: The form's view and the related picker's

**Files:**
- Modify: `app/routers/views.py`, `app/schemas/views.py`, `tests/test_api_views.py`, `tests/test_query_counts.py`,
  `tests/test_isolation.py`, `docs/developer/api.md`

**Interfaces:**
- `GET /views/entry-form` — query: `transaction_id` (edit), `repeat`, `related`, `account`, `category`, `pay` with
  `amount`, `move` with `with` (as `/transactions/new` takes them) → `EntryFormView`:
  - `editing: bool`, `kind`, `date`, `total: Decimal | None`, `payee`, `payee_person: PersonRef | None`, `comment`,
    `tags`, `related: RowRead | None`, `from_rows` / `to_rows`: `list[FormRow]` (`choice: UUID | None`, `amount`,
    `category_id`, `posted_on`), `simple: bool` (one row each side and no sharing: what this step can edit),
    `person_page: UUID | None` (an entry another way of recording looks after: the app opens the person's page).
  - `groups: list[PickGroup]` — `title` (`Assets`, `Liabilities`, `Equity`, `People`, `Spending`, `Earning`… as
    `form_context` names them), `root` (the root the options belong to), `options: list[PickOption]` (`id`, `label`,
    `budget: bool`, `balance: Decimal | None`).
  - Built from `form_context` / `form_rows` / `infer_kind` (moved in Task 1), so the web form and the view cannot
    differ. 404 for an unknown `transaction_id`, `repeat` or `related`.
- `GET /views/related-entries?q=&exclude=` → `list[RowRead]`: the newest 30 up to today matching `q`, without
  `exclude` and the system payees (today's `related_picker`).
- `"/api/views/entry-form": 4` in the query ceilings (with `/transactions/new`).

- [ ] **Step 1: Write the failing tests:** blank (kind `expense`, one blank row each side, today's date); from an
  account (`from_rows[0].choice`); from a spending and an earning category; Repeat (payee, note, tags, rows, the
  kind inferred, `editing` false, today's date); Related (`related` set); pay a card (`kind == "transfer"`, `total`);
  editing a simple entry (`simple` true) and a split one (`simple` false); a loan opens with the person on its row; a
  settlement gives `person_page`; the groups name the roots and carry `budget` and `balance`; `related-entries`
  narrows by `q` and leaves out `exclude`.
- [ ] **Step 2:** Run — expected: FAIL. **Step 3:** Implement. **Step 4:** Run with isolation, api_doc,
  query_counts — expected: PASS; regenerate the API types.
- [ ] **Step 5:** Commit: `The Add screen's form and related picker as views`.

### Task 4: The Add/Edit screen: kind, amount, From and To

**Files:**
- Create in `frontend/src/features/entry/`: `EntryScreen.tsx` (+ `.module.css`, test), `kinds.ts` (+ test),
  `Picker.tsx` (+ `.module.css`, test), `queries.ts`
- Modify: `frontend/src/components/AmountField.tsx` (+ test): the caret stays where it was when cleaning changes the
  text, and the field is grouped as typed (`data-group` in `app.js`) — the step 2 minor, needed here

**Interfaces:**
- `kinds.ts`: `KINDS` — for each of `expense`, `income`, `transfer`, `other` the roots offered on each side and the
  side titles (`Paid from` / `Spent on`, `Earned from` / `Paid into`, `From` / `To`), as `app.js` `KINDS`;
  `offered(kind, side, groups) -> PickGroup[]`; `keepsChoice(kind, side, choice, groups) -> boolean`.
- `Picker({ title, groups, value, onChange, otherSide, clearable })`: a bottom sheet listing the groups (the group's
  title as a heading, each option's name, the group under it in search results, its balance at the right), a search
  field, the chosen one bold, the option chosen on the other side greyed; `Uncategorised`/`No category` first when
  `clearable`.
- `EntryScreen({ form })`: the Expense · Income · Transfer switch (tapping the chosen one again → `other`); the amount
  (big, the currency sign beside it); From and To, one row each, in the kind's order (Income lists the category first
  on screen), the swap button between them for a transfer or `other` (swapping an expense makes it `other`); the row
  category under an account outside the budget when money leaves the budget (`syncRowCategories`); `Save` /
  `Save changes`; the error line; `Back`; on edit, `Delete transaction` (asks today's question). Save sends
  `POST /api/entries` or `PUT /api/entries/{id}`, then invalidates `["views"]` (every list and Home refresh), shows
  the toast (`Transaction saved` / `Transaction updated` / `Transfer recorded`) and goes back.

- [ ] **Step 1: Write the failing tests:** `kinds.test.ts` (each kind's roots and titles; Review Focus 3 rules);
  `Picker.test.tsx` (search narrows; the other side's choice is greyed; the chosen one is bold); `AmountField.test.tsx`
  additions (Review Focus 5: a paste keeps the caret after the same digits; `1234567` typed reads `12,34,567`
  while typing); `EntryScreen.test.tsx`: saving an expense sends `{kind, rows: [{choice: card, side: "credit",
  amount}, {choice: food, side: "debit", amount}]}`; tapping the chosen kind again offers every account; a choice
  survives a kind that still offers it; the swap is there for a transfer, not an expense; the row category shows only
  when money leaves the budget and nothing is filled in; two quick Saves send one request (Review Focus 4); a refusal
  shows the server's message and keeps what was typed.
- [ ] **Step 2:** Run — expected: FAIL. **Step 3:** Implement. **Step 4:** `npm --prefix frontend run check` —
  expected: PASS.
- [ ] **Step 5:** Commit: `The Add screen in the React app: kind, amount, From and To`.

### Task 5: Payee, date, related, note and tags

**Files:**
- Create in `frontend/src/features/entry/`: `PayeeField.tsx`, `DateChip.tsx`, `RelatedChip.tsx`,
  `RelatedPicker.tsx`, `NoteAndTags.tsx`, `TagsSheet.tsx`, their `.module.css` and tests
- Modify: `EntryScreen.tsx`

**Interfaces:**
- `PayeeField`: the payee input; under it, as you type, up to six chips from `/api/transactions/payee-suggestions`
  (names only: a chip fills the payee and moves on to the amount, never an account); after an `@`, your people (a
  chip names the person on the entry: `payee_contact`, the payee becomes their name, a `✕` unlinks); on an edit the
  chips offer people only; people only for an expense or an income (another kind unlinks).
- `DateChip`: the calendar glyph and `dateChip(date, today)`, a native date input over it.
- `RelatedChip` / `RelatedPicker`: `Related` opens the sheet (`Related to…`, search `Search payee, note or account`,
  the rows of `/api/views/related-entries`, `Nothing matches.` / `No earlier transactions.`); a choice shows
  `Related to {payee} · {dd Mon} · {amount}` with `✕` to remove it.
- `NoteAndTags`: the note (`Note (optional)`, 200 characters) with the `#` button; the chosen tags as one quiet line
  under it (tapping it reopens the sheet); `TagsSheet` lists the tags in use (`/api/tags/`), search, tick to choose,
  and `New tag "{name}"` to make one on the fly; a `#` typed in the note stays text.

- [ ] **Step 1: Write the failing tests:** a payee chip fills the payee only; typing a known payee fills nothing; the
  chips narrow as you type; `@a` offers people and choosing one names them (`payee_contact` sent); switching to a
  transfer unlinks the person; the date chip names the day (`Today, 14 Nov`); relating an entry sends `related_id` and
  `✕` removes it; choosing tags sends them; a new tag made in the sheet is sent; a `#` in the note is not a tag.
- [ ] **Step 2:** Run — expected: FAIL. **Step 3:** Implement. **Step 4:** `npm --prefix frontend run check` —
  expected: PASS.
- [ ] **Step 5:** Commit: `Payee, date, related entry, note and tags on the Add screen`.

### Task 6: Routes, prefill and the browser tests

**Files:**
- Modify: `frontend/src/app/router.tsx` (`/transactions/new`, `/transactions/:id/edit`), `EntryScreen.tsx` (reads
  `/api/views/entry-form` with the address's query; `person_page` → navigate to `/people/{id}`; `simple` false → the
  notice and the web link)
- Create: `tests/browser/test_spa_entry.py`

**Interfaces:**
- `/transactions/new?account=&category=&repeat=&related=&pay=&amount=&move=&with=&back=` and
  `/transactions/:id/edit?back=`; after Save or Delete the app goes to `back` (inside the app only: `safeNext`) or
  where it came from.
- The Sheet's `Edit`, `Repeat`, `Related` links (step 4a) land here.

- [ ] **Step 1: Write the browser tests** (`signed_in_spa_page`, `spa_books`, `spa_api`), ports of
  `test_transaction_form.py` (`test_the_kind_buttons_narrow_the_pickers`, `test_the_order_and_the_default`,
  `test_a_choice_survives_a_kind_that_still_offers_it`, `test_saving_an_expense`,
  `test_swapping_from_and_to_keeps_a_transfer_and_an_expense_has_no_swap`, `test_editing_keeps_what_was_recorded`,
  `test_a_payee_chip_fills_the_payee_only_and_moves_on_to_the_amount`, `test_the_chips_narrow_as_you_type`,
  `test_the_amount_is_focused_on_a_computer_but_not_on_a_phone`,
  `test_an_amount_cannot_be_typed_with_two_decimal_points_or_letters`,
  `test_pasting_a_messy_amount_keeps_the_good_part_and_the_cursor`, `test_the_amount_is_grouped_as_it_is_typed_and_the_cursor_stays`,
  `test_add_related_opens_the_form_linked_and_saves_the_link`, `test_the_picker_relates_an_entry_and_the_chip_removes_it`,
  `test_from_and_to_are_the_same_size_and_the_swap_sits_between_them`, `test_the_date_is_a_chip_that_names_the_day`),
  of `test_account_picker.py` (`test_an_account_is_chosen_in_a_sheet`, `test_the_account_on_the_other_side_is_greyed`,
  `test_the_chosen_account_is_bold_and_the_scroll_bar_stays_clear_of_the_balances`,
  `test_pressing_an_option_keeps_the_search_focused_so_the_sheet_does_not_move`), of `test_row_category.py` (the
  first four and the income one), of `test_tags.py` (`test_choosing_tags_on_the_add_screen`,
  `test_a_note_with_a_hash_stays_a_note`, `test_editing_an_entry_shows_its_tags_and_saves_the_changes`,
  `test_a_new_tag_is_made_on_the_fly_and_saved_with_the_entry`), and the sheet's
  `test_add_again_opens_the_form_filled_in` and `test_edit_from_the_sheet_goes_to_the_edit_page`.
- [ ] **Step 2:** Run on Chromium — expected: FAIL. **Step 3:** Implement the routes and prefill. **Step 4:** The
  browser tests on Chromium and WebKit — expected: PASS.
- [ ] **Step 5:** Commit: `Add and Edit in the React app, opened from everywhere today's form is`.

### Task 7: Docs and the whole check

**Files:**
- Modify: `docs/developer/code-map.md` (`services/entry.py`, `routers/entries.py`, `features/entry/`), `AGENTS.md`
  (Code rules: "saving an entry from a form goes through `EntryService`"), `docs/developer/api.md`

- [ ] **Step 1:** Update the docs.
- [ ] **Step 2:** The Python checks and `uv run pytest -q`, `npm --prefix frontend run check`, the browser tests on
  Chromium and WebKit — expected: all pass.
- [ ] **Step 3:** Commit: `Docs for the Add screen`, then `git push origin feature/react-frontend`.

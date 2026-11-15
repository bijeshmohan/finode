# React frontend, step 7b: People — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild People in the React app as today's pages are, replacing the `/people` placeholder.
- **The People list:**
  - the switcher All · Owe you · You owe (· Archived once someone is archived);
  - the head saying what is owed to you or by you in total;
  - one row per person with their quiet line and what is owed either way.
- **A person's page:**
  - what they owe you or you owe them;
  - the short-hands Expense · Lend · Borrow · Settle (to the Add screen);
  - the open amounts and the activity, each opening its sheet with Reverse (and Edit for an opening balance);
  - the menu: Edit, Add an opening balance, Archive or Restore, Remove.
- **The person form** (add, with an opening balance; edit) and **the opening balance form** (add; edit, held to what
  was already paid back).

This is the second half of step 7 (7a was the bell, Coming up, Tags and Recurring).

**Architecture:** As in steps 4a to 7a.
- **The server:** what the pages show and the two rules the web router holds today move into
  `app/services/people_view.py`:
  - from `routers/web/people.py`: `SHOWS`, `SOURCE_NAMES`, `PersonRow`, the list's quiet line, `describe_obligation`;
  - from the templates `person.html` and `person_entry_sheet.html`: an activity item's title, second line and sheet
    text;
  - **reversing an entry by what it is:** a settlement, a shared income, a shared bill, or else a transfer;
  - **adding a person with an opening balance:** all or nothing.

  The web pages render from it with their HTML unchanged.
- **The views:** new view endpoints answer the same things as JSON.
- **Saving uses the existing `/api` routes:**
  - `PATCH /api/contacts/{id}`, `POST …/archive`, `POST …/restore`, `DELETE /api/contacts/{id}` (`outcome` deleted or
    archived);
  - `POST /api/contacts/{id}/opening-balance`, `PATCH /api/transfers/{id}` (an opening balance).
- **Two writes change:**
  - `POST /api/contacts/` takes an optional `opening`, made with the person or not at all (it is two calls the app would
    have to undo today);
  - a new `POST /api/contacts/{contact_id}/entries/{transaction_id}/reverse` reverses an entry the way its kind is
    reversed, so the app never picks the route by purpose.
- **The app:** pages live in `frontend/src/features/people/`.

**Tech Stack:** FastAPI, Pydantic, React, React Router, TanStack Query, Vitest, Python `pytest-playwright`.

**Spec:** `docs/superpowers/specs/2026-11-13-react-frontend-design.md` (step 7: "People … — as above", i.e. their
browser tests ported).

## Global Constraints

- **Branch:** `feature/react-frontend` only; nothing reaches `develop`. `make` is not installed: run what it runs.
- **Earlier constraints:** all Global Constraints of steps 2 to 7a hold:
  - strict TypeScript; amounts as strings, never `Number`;
  - `useApi()`, `useToday()`, view endpoints and tokens only;
  - `npm run check` clean; exact dependency versions;
  - a component used by two features lives in `src/components`.
- **Today's pages stay exactly as they are.** The move into `people_view.py` changes no HTML. The proof is:
  - the web tests (`test_web_people.py`, `test_contacts.py`, `test_contact_opening.py`, `test_contact_summary.py`,
    `test_contact_transfers.py`, `test_people_through_plus.py`);
  - `tests/browser/test_people.py`;
  - the whole browser suite (332 on each browser before this step).
- **The rules stay on the server.** The app never works out:
  - who owes whom, a person's quiet line, the totals;
  - an entry's title, second line or sheet text;
  - which way an entry is reversed;
  - whether a person can be archived, or what Remove does to them.

  It shows what the views say.
- **The ledger rules hold:**
  - a person is never owed both ways (`NettingService`): reversing goes through the services that `release` first, as
    the web route does today;
  - every new write path keeps a `trial_balance().balanced` test.
- **New routes:** each gets:
  - a row in `docs/developer/api.md`;
  - a classification in `tests/test_isolation.py` (with bodies in the by-id sweep);
  - a test, and for a view a query-count ceiling no higher than its web page's.

  The two writes also get cases in `tests/test_api_parity.py`.
- **Wording is today's.** It comes from:
  - the templates `people.html`, `person.html`, `person_form.html`, `person_opening.html` and
    `partials/person_entry_sheet.html`;
  - the flash texts `person-added`, `person-updated`, `person-archived`, `person-restored`, `person-deleted`,
    `opening-added`, `opening-updated` and `entry-reversed`;
  - the server's own refusals.
- **Not here:** Settings (step 8), from where People is reached on the phone today. Until then it is in the sidebar,
  as now, and reached by address. Its way back still says `Settings`.

## Review Focus

1. **A person owed both ways reads as the web page:**
   - an open row says `· they owe you` / `· you owe them` only when the person has both;
   - a partly paid amount says `· {paid} of {original} paid`;
   - the head says `{name} owes you`, `You owe {name}` or `All settled up`, with the figure unsigned.

   Test in Tasks 1 and 2.
2. **Reversing:**
   - it asks first (`Reverse this? It is removed for good.`);
   - a refusal (409: something was paid back against it) shows in the sheet, which stays open;
   - an evened-out entry (`netoff`) has no Reverse;
   - after a reverse the page and the bell refresh and it toasts `entry-reversed`'s text;
   - `trial_balance()` stays balanced.

   Test in Tasks 1 and 2.
3. **Adding a person with an opening balance is all or nothing:**
   - an amount that cannot be saved (too many decimals, not a number, zero) leaves no person behind and shows the
     server's words;
   - an empty amount adds the person alone.

   Test in Tasks 1 and 3.
4. **Archive and Remove:**
   - Archive is offered only when nothing is owed either way;
   - Remove of someone with history archives them (`Person archived. Their history stays.`);
   - Remove of someone never dealt with deletes them (`Person removed`), back on `/people`;
   - an archived person's page offers Restore, and neither the short-hands nor `Add an opening balance`;
   - the Archived chip appears only once someone is archived.

   Test in Tasks 1 and 2.
5. **Editing an opening balance once part of it was paid back:**
   - the who-owes-whom choice is gone (the direction is kept as it is);
   - the warning `{paid} of this has been paid back. The amount can't go below that, and who owes whom can't change.`
     is shown;
   - an amount below what was paid is refused with the server's words.

   Test in Tasks 1 and 3.

---

### Task 1: People as views, and the two writes

**Files:**
- Create: `app/services/people_view.py`, `tests/test_api_people_views.py`.
- Modify:
  - `app/routers/web/people.py`: renders from the service, and `create_person` and `reverse_entry` call it; HTML
    unchanged.
  - `app/templates/person.html`, `app/templates/partials/person_entry_sheet.html`: read the titles, lines and texts
    from the service instead of the templates' own `names` dicts. The output is the same.
  - `app/routers/views.py`, `app/schemas/views.py`;
  - `app/routers/contacts.py`, `app/schemas/contact.py` (`ContactCreate.opening: OpeningBalanceCreate | None`);
  - `tests/test_isolation.py`, `tests/test_query_counts.py`, `tests/test_api_parity.py`, `docs/developer/api.md`.

**Interfaces:**
- `people_view.people_page(contacts, show: str, money: Money) -> PeoplePage`:
  - `show` (`all` for anything unknown), `shows`, `has_archived`;
  - `rows` (`PersonRow(person, sub)`, as the web route works them out today);
  - `owed_total`, `owe_total`, `everyone`.
- `people_view.person_page(contact_id, contacts, obligations, summaries) -> PersonPage`:
  - `person`;
  - `open`: each `OpenRow(obligation, name, who, partly)`;
  - `activity`: each `ActivityRow(item, title, sub, income)`, the newest 30;
  - `more_activity`.

  `LookupError` for a person who is not the caller's.
- `people_view.entry_sheet(contact_id, transaction_id, contacts, summaries) -> EntrySheet`:
  - `item`, `title`, `notes` (the lines the sheet shows under the title, in order);
  - `can_edit` (an opening balance), `can_reverse` (not `netoff`).
- `people_view.reverse(item, settlements, incomes, expenses, transfers)`: what `reverse_entry` does today. A refusal
  raises `ValueError` (or `ConflictError` where the service raises it).
- `people_view.add_person(contacts, transfers, data: ContactCreate) -> ContactRead`:
  - the opening is checked before anyone is made, as today;
  - a failure after the person is made deletes them again.

  `POST /api/contacts/` calls it.
- `GET /api/views/people?show=` → `PeopleView`:
  - `show`, `shows` (`[{key, name}]`), `has_archived`, `everyone`;
  - `owed_total`, `owe_total`;
  - `rows`: `[{id, name, sub, net}]`.
- `GET /api/views/people/{contact_id}` → `PersonView`:
  - the person: `id`, `name`, `phone`, `email`, `notes`, `archived`, `receivable`, `payable`, `net`;
  - `open`: `[{transaction_id, name, date, who, settled, original, outstanding, receivable: bool}]`, where `who` is
    set only when the person is owed both ways and `settled` only when part is paid;
  - `activity`: `[{transaction_id, title, sub, amount, income: bool}]`;
  - `more_activity`.
- `GET /api/views/people/{contact_id}/entries/{transaction_id}` → `PersonEntryView`: `transaction_id`, `title`,
  `date`, `amount`, `notes: list[str]`, `can_edit`, `can_reverse`. 404 for an entry that is not this person's.
- `GET /api/views/opening-form?contact_id=&transaction_id=` → `OpeningFormView`:
  - `person_name`, `editing`;
  - `direction`, `amount`, `date`, `description`;
  - `paid` (what was paid back, editing only).

  404 for a person or an entry that is not the caller's, or an entry that is not this person's opening balance.
- `POST /api/contacts/{contact_id}/entries/{transaction_id}/reverse` → 204:
  - 404 for an entry that is not this person's;
  - 409 while something was paid back against it;
  - 400 for the rest, with the service's words.
- **Classification:**
  - `/api/views/people` is `LISTS`;
  - the person view, the entry view and the reverse route are swept by id (`contact_id`, `transaction_id`);
  - `/api/views/opening-form` is classified as `/api/views/entry-form` is.

- [ ] **Step 1:** Run the baseline: `uv run pytest -q -p no:cacheprovider tests/test_web_people.py tests/test_contacts.py
  tests/test_contact_opening.py tests/test_contact_summary.py tests/test_contact_transfers.py
  tests/test_people_through_plus.py`.
  - Expected: PASS. Note the counts.
- [ ] **Step 2: Write the failing tests** in `tests/test_api_people_views.py`:
  - `test_the_list_and_its_switcher` (each `show`, `Archived` only once someone is archived, the quiet lines `Nothing
    yet`, `Settled up`, `Even · … each way`, `Last 2 Nov`, totals);
  - `test_a_persons_page_owed_both_ways` (Review Focus 1);
  - `test_the_activity_reads_as_the_page` (a loan, a settlement each way, a shared bill, a shared income, an opening
    balance, an evened-out entry: titles and lines);
  - `test_an_entrys_sheet` (notes, `can_edit` only for an opening, `can_reverse` not for `netoff`);
  - `test_reversing_each_kind` (a loan, a settlement, a shared bill, a shared income; balanced after; 409 after part was
    paid back);
  - `test_adding_a_person_with_an_opening_balance_is_all_or_nothing` (Review Focus 3);
  - `test_the_opening_form_view` (new, editing, `paid`; a stranger's or a loan entry is 404);
  - `test_strangers` (404 for another person's contact and entry; their list is empty);
  - the classification, the parity cases and the ceilings:
    - `/api/views/people` ≤ `/people`;
    - the person view ≤ `/people/{id}`;
    - both not growing with the books.
- [ ] **Step 3:** Run.
  - Expected: FAIL.
- [ ] **Step 4:** Add the service, move the web router and templates onto it, add the routes and schemas.
- [ ] **Step 5:** Run Step 1's command plus the new file, `tests/test_isolation.py`, `tests/test_query_counts.py`,
  `tests/test_api_parity.py` and `tests/test_api_doc.py`; then `npm --prefix frontend run gen:api` and
  `scripts/browser-tests.sh -q -k "people"`.
  - Expected: all PASS.
- [ ] **Step 6:** Commit: `People as views, a person added with an opening balance, an entry reversed`.

### Task 2: The People list and a person's page in the app

**Files:**
- Create in `frontend/src/features/people/`:
  - `PeoplePage.tsx`, `PersonPage.tsx`, `EntrySheet.tsx`, `queries.ts`, `fixtures.ts`;
  - `People.module.css` (from `.person-actions`, `.person-entry` and the `crow` rows as Categories draws them);
  - tests.
- Modify: `app/router.tsx` (`/people`, `/people/:contactId`; the placeholder goes).
- Test: `tests/browser/test_spa_people.py`.

**Interfaces:**
- **The People list** (`/people?show=`), as `people.html`:
  - back `Settings`; `People`;
  - the switcher (`Chips`), shown only when there is someone (or on Archived);
  - **the head:** `Owed to you` / `You owe` / `Everything is settled`, the figure, and
    `{owed} owed to you · {owe} you owe` or `in total`;
  - **the rows:** name, the quiet line, and the net: green for what is owed to you, red (`--negative`, the web's
    `out-amount`) for what you owe, or `–`;
  - **empty:** `Nobody here.`; with nobody at all, `Keep track of money you lend, borrow and share with people.` and
    `Add a person`;
  - the add row `Add person` (`/people/new`), not on Archived.
- **A person's page** (`/people/:contactId`), as `person.html`:
  - back `People`;
  - the title with the `archived` badge, the phone and email line;
  - **the menu:** `Edit`, `Add an opening balance`, `Restore {name}` / `Archive` (with its note) only as the view
    allows, and `Remove`, confirming with `Remove {name}? Someone you never dealt with is deleted; otherwise they are
    archived.` Remove toasts by its `outcome` and goes to `/people`.
  - **the head:** `{name} owes you` / `You owe {name}` / `All settled up`, and the figure;
  - **the short-hands** (not for an archived person): `Expense`, `Lend`, `Borrow`, and `Settle` when anything is owed.
    They are links to `/transactions/new?mode=split|move=lend|borrow|settle&with={id}&back=/people/{id}`.
  - **`Open`:** a row per open amount, its line from `open` (Review Focus 1);
  - **`Activity`:** a row per item, `{n} older entr(y|ies) not shown.`, or `Nothing yet with {name}.`;
  - a row opens the entry's sheet.
- **The entry sheet:**
  - title, `{friendly day} · {name}` and the amount;
  - the `notes`;
  - `Edit` (to `/people/{id}/opening/{transaction_id}/edit`) when `can_edit`;
  - when `can_reverse`, the hint `Reversing removes it for good, as if it had never happened. It can't be reversed while
    something has been paid back against it.` and `Reverse`, asking `Reverse this? It is removed for good.` A reverse
    toasts, refreshes the views and closes the sheet; a refusal stays in it.

- [ ] **Step 1: Write the failing Vitest tests:**
  - the list: each switcher state, the head's three readings, the row figures, the two empty states;
  - the person page: the heads, the menu for live, owed and archived people, Remove by outcome;
  - the short-hand links;
  - the open rows' lines;
  - the activity and its empty and "older" texts;
  - the sheet: notes, Edit, no Reverse for `netoff`, a reverse sent and toasted, a refusal shown.
- [ ] **Step 2:** Run `cd frontend && npx vitest run src/features/people`.
  - Expected: FAIL.
- [ ] **Step 3:** Build the pages.
- [ ] **Step 4: Port the browser tests** into `tests/browser/test_spa_people.py` (from `test_people.py`):
  - add a person and lend them money (through the short-hand);
  - Settle opening the Add screen with what is owed;
  - reversing asks first;
  - the figures carry the rupee sign and there is no stray wrapping;
  - what two people owe each other evens out by itself;
  - the two ways show and hide what they should.

  Add a comparison of the list's rows and the person head with the Categories rows and the account head (row height,
  figure size), as step 5 did.
- [ ] **Step 5:** Run Step 2's command, `npm --prefix frontend run check` and `scripts/browser-tests.sh -q -k
  "spa_people or people"`.
  - Expected: all PASS.
- [ ] **Step 6:** Commit: `The People list and a person's page in the app`.

### Task 3: The person form and the opening balance form in the app

**Files:**
- Create in `frontend/src/features/people/`: `PersonForm.tsx`, `OpeningForm.tsx`, with their tests.
- Modify: `app/router.tsx`: `/people/new`, `/people/:contactId/edit`, `/people/:contactId/opening`,
  `/people/:contactId/opening/:transactionId/edit`.
- Test: `tests/browser/test_spa_people.py`.

**Interfaces:**
- **The person form**, as `person_form.html`:
  - back `People` (new) or `{name}` (edit); `Add person` / `Edit person`;
  - `Name` (max 30, focused when new), `Phone (optional)`, `Email (optional)`, `Note (optional)`;
  - **new only, an `Already owes you, or is owed?` expander:**
    - the choice `They owe you` / `You owe them`;
    - `Amount` (an `AmountField`) and `Since` (the date chip, today);
    - the hint `Added to your opening balances. Your accounts and budgets don't change. It can be paid back with Settle
      up.`
  - one full-width button, `Add person` / `Save changes`.
  - **New** sends `POST /api/contacts/` with `opening` when an amount is typed. **Edit** sends `PATCH` (an emptied
    field is sent as null).
  - Success toasts `person-added` / `person-updated` and goes to the person's page; a refusal shows above the button.

  The person's details for editing come from `GET /api/contacts/{id}`.
- **The opening balance form**, as `person_opening.html`:
  - back `{name}`; `Opening balance` / `Edit opening balance`;
  - **new:** `What {name} already owed before you started with finode. It touches none of your accounts or budgets.`
  - **editing with `paid`:** the warning (Review Focus 5), and no choice;
  - otherwise the choice `{name} owes you` / `You owe {name}`;
  - `Amount`, `Since`, `Note (optional)`;
  - `Add opening balance` / `Save changes`.
  - **New** sends `POST /api/contacts/{id}/opening-balance`; **edit** sends `PATCH /api/transfers/{id}` with what
    changed.
  - Success toasts `opening-added` / `opening-updated` and goes to the person's page.

- [ ] **Step 1: Write the failing Vitest tests:**
  - new with and without an opening balance;
  - edit;
  - a refusal shown with no navigation (Review Focus 3);
  - the opening form new, editing, and editing once part was paid (Review Focus 5).
- [ ] **Step 2:** Run `cd frontend && npx vitest run src/features/people`.
  - Expected: FAIL.
- [ ] **Step 3:** Build the forms.
- [ ] **Step 4: Port the browser tests:**
  - a new person can start with an opening balance;
  - an opening balance can be edited from its sheet;
  - a bad opening amount leaves nobody behind.
- [ ] **Step 5:** Run Step 2's command, `npm --prefix frontend run check` and `scripts/browser-tests.sh -q -k
  "spa_people"`.
  - Expected: all PASS.
- [ ] **Step 6:** Commit: `The person and opening balance forms in the app`.

### Task 4: Docs and the whole check

**Files:**
- Modify: `docs/developer/code-map.md` (`people_view`, `features/people`).

- [ ] **Step 1:** Update the code map. Check the `api.md` rows from Task 1 read as the routes behave.
- [ ] **Step 2: Run the whole check:**
  - `uv run ruff check app tests migrations scripts`, `uv run ruff format --check app tests migrations scripts`,
    `uv run pyrefly check`;
  - `uv run pytest -q -p no:cacheprovider`;
  - `npm --prefix frontend run check`;
  - `scripts/browser-tests.sh -q -p no:cacheprovider`, and the same with `FINODE_BROWSER=webkit`.
  - Expected: all PASS.
- [ ] **Step 3:** Commit `Docs for People`, then `git push origin feature/react-frontend`.

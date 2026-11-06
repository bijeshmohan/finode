# Contacts, expense sharing and settlements: plan and status

Owner request 2026-11-06 (feature freeze overridden by asking). Built phase by phase, each on its own branch off
`develop`, each waiting for "Merge and deploy". The owner chose, when asked: **the full plan as written** (obligation and
settlement tables included), **the no-history rule stays** (nothing auditable beyond `created_via`/`updated_via`), and
**all six phases**.

| Phase | What | Status |
|---|---|---|
| 1 | Contacts, their two accounts, API, backup v6, tests | built on `feature/contacts` |
| 2 | Plain transfers: lend, borrow, gift, advance | not started |
| 3 | Shared expenses (equal, exact, percentage, shares; several payers) | not started |
| 4 | Obligations and settlements (FIFO, manual, partial, idempotency, locking) | not started |
| 5 | Contact summary and activity | not started |
| 6 | Web pages (mock-ups first) | not started |

All phases are built on the one branch `feature/contacts`; nothing is merged until the owner says so.

## Deviations from the plan (and why)

- **Layout.** The repository is flat (`app/models`, `app/services`, `app/repositories`, `app/schemas`, `app/routers`),
  so contacts follow it instead of `src/application/contacts/`.
- **Names.** `user_id`, `created`/`updated` (the repository's `TimestampMixin`), tables' key is `id`.
  Child tables (`contact_accounts` and the later ones) carry `user_id` too, like `transaction_tags`, so Erase (which
  walks every table with a `user_id`) and the isolation audit cover them.
- **No `avatar_url`.** Nothing uploads or shows one; the pages use initials. Add it with the page that needs it.
- **No soft deletion in general.** `DELETE /contacts/{id}` removes a contact no money moved with and archives one with
  entries (as categories do); `archive`/`restore` are explicit routes. Archiving is refused while anything is owed.
- **Names of contacts** are unique per person (capitals aside) and at most 30 characters ("Due from " takes 9 of an
  account name's 40). The plan left the policy open.
- **Where the accounts live.** Directly under Assets and Liabilities, outside the budget. The Accounts page will hide
  them in phase 6 (they show under "Others" until then).
- **Migrations are per phase**, not one set in dependency order, so each phase deploys on its own.
- **Backup** is version 6 from phase 1; every later table is added to it and to `tests/test_backup.py`.

## Rules for the next phases

- A line on a contact's account must be refused by `TransactionService` unless the contact services made it, so the
  books never hold a debt without its obligation (and an obligation never exists without postings).
- Contacts' money moves only through `TransactionService.create`; the contact services never write postings.
- No history tables: reversals are ordinary entries or deletions, as everywhere else.

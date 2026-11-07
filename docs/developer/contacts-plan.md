# Contacts, expense sharing and settlements: plan and status

Owner request 2026-11-06 (feature freeze overridden by asking). Built phase by phase, each on its own branch off
`develop`, each waiting for "Merge and deploy". The owner chose, when asked: **the full plan as written** (obligation and
settlement tables included), **the no-history rule stays** (nothing auditable beyond `created_via`/`updated_via`), and
**all six phases**.

| Phase | What | Status |
|---|---|---|
| 1 | Contacts, their two accounts, API, backup v6, tests | built |
| 2 | Plain transfers: lend, borrow, gift, advance; obligations; the guard on contact accounts | built |
| 3 | Shared expenses (equal, exact, percentage, shares; several payers) | built |
| 4 | Settlements (FIFO, manual, partial, excess named, idempotency, locking) | built |
| 5 | Contact summary, activity, list search/sort/filter | built |
| 6 | Web pages (mock-ups first) | built (mock-ups chosen: Settings row, one-page split) |

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
- **Migrations are per phase** (`c8e0a2b4d6f3`, `d9f1b3c5e7a4`, `e0a2c4d6f8b5`), `obligation_settlements` and `contact_requests` come with the obligations.
- **Shared expenses** also store `category_id`, `date` and the owner's payment accounts (rows of `expense_contributions` with `account_id`), which the plan's tables lack; there is no `currency` column (one currency) and no `payment_transaction_id`. **No `cancelled` status:** cancelling deletes (no history); a confirmed expense is cancelled and entered again, never edited.
- **No `adjustment` obligations** and no `other` transfer purpose: nothing needed them. An over-payment names what the rest is (`excess_as`: loan/borrowing/advance/gift); "unrelated transfer" is simply not recorded as a settlement.
- **The user's own payments** go in `payments` (an account each), a contact's in `contributions`; the owner's share of contributions is derived, never stored twice.
- **Idempotency** is a small table (`contact_requests`: key → entry), not a column on the entries.
- **Concurrency:** obligations and expenses are locked with `SELECT … FOR UPDATE` (a no-op on SQLite, so the tests check the re-read rule, not the lock itself).
- **Reversal** (`DELETE /transfers/{id}`, `DELETE /settlements/{id}`, `POST /shared-expenses/{id}/cancel`) deletes for good.
- **Backup** is version 6 from phase 1; every later table is added to it and to `tests/test_backup.py`.

- **Phase 6:** the forms are pages instead of the mock-ups' sheets (a sheet opened from a sheet is fragile); no drafts in the UI; no search or sort controls on the list (the owner removed search boxes before; the API has `q` and `sort`); advance is in the transfer kinds, an excess gift has no category choice (Uncategorised).

## Rules for the next phases

- Contacts' money moves only through `TransactionService.create`; the contact services never write postings.
- No history tables: reversals are ordinary entries or deletions, as everywhere else.

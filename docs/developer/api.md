# The JSON API

Everything the web app and the assistants can do with your books can be done through the JSON API under `/api`. It is for scripts, tools and future clients; the web app and the MCP server call the same services directly. Interactive documentation (`/docs`) is off unless `FINODE_API_DOCS=true`.

## Using it

- **Sign in with a Supabase access token**: `Authorization: Bearer <token>`. The API never reads cookies. An assistant's personal access token or an OAuth app's token is refused here (they work only on `/mcp`).
- **Everything is yours alone.** Every request is scoped to the signed-in person; another person's ids answer 404 (or 400 when they are named inside a request). `tests/test_isolation.py` checks this for every route.
- **Amounts** are decimal strings or numbers in the person's one currency (no other currency exists); more decimals than the currency keeps are refused. **Dates** are `YYYY-MM-DD`, between 1900 and 2999. Money moves as a list of **postings** (`account`, `side` debit or credit, `amount`) whose debits equal their credits.
- **Errors** are JSON `{"detail": ...}`: 400 for a refused change (with the reason), 404 for an unknown id, 409 when something is in use, 422 for a malformed request.
- Routes with a trailing slash (`/accounts/`) are the collection; `/accounts/closed`, `/transactions/deleted` and the like are fixed words, not ids.

## What is not in the API, on purpose

| Not here | Why |
|---|---|
| Signing in, signing up, passwords, the OAuth consent page | Identity belongs to Supabase; these are web pages. |
| Creating or revoking assistant tokens and connected apps | A token must never be able to manage tokens, and an app's token never acts as a full sign-in. |
| **Erase my books** and **Delete my account** | They need the person to type their email on the settings pages; a leaked bearer token must not be able to wipe a ledger. |
| Payee suggestions that carry accounts ("payee chips") | A convenience of the Add screen; `GET /transactions/payee-defaults`, `GET /transactions/payees` and `GET /transactions/?payee=` give the same facts. |

## Accounts and categories

| Method | Path | What it does |
|---|---|---|
| `POST` | `/accounts/` | Create an account or category (an Expenses/Income account); `balance` sets an opening balance on an asset or liability. |
| `GET` | `/accounts/closed` | Accounts that were closed (and categories "deleted" while they had a history): the outermost of each closed |
| `GET` | `/accounts/deleted` | Accounts and categories deleted for good that can still be restored, newest first. |
| `POST` | `/accounts/deleted/{did}/restore` | Bring back a deleted account or category (with its old id, plan and payment links). |
| `GET` | `/accounts/{aid}` | The account with its balance as of a day (today by default: later entries do not count yet). |
| `GET` | `/accounts/` | Accounts with their balances as of a day (today by default: later entries do not count yet). |
| `PATCH` | `/accounts/{aid}` | Change an account: name, note, place (`parent_id`), budget flag or payment category. |
| `DELETE` | `/accounts/{aid}` | Delete an account for good; refused when it has entries, sub-accounts or a recurring rule (close it instead). |
| `POST` | `/accounts/{aid}/close` | Close an account (and everything inside it): its history stays, nothing more can be posted to it. |
| `POST` | `/accounts/{aid}/reopen` | Reopen a closed account with everything inside it, and the groups above it. |
| `GET` | `/accounts/{aid}/check-balance` | Set a statement's balance (`statement_balance`) against the books on the same day (`as_of`, today by default): the books' balance, the difference and the entries of the last `days` days, with those exactly as large as the difference. Nothing is changed. A card's or loan's balance is what is owed, as the app shows it. |
| `GET` | `/accounts/{aid}/register` | The account's entries, oldest first, each with what it changed and the running balance. `own_only` leaves out |

## Transactions

| Method | Path | What it does |
|---|---|---|
| `POST` | `/transactions/` | Record a transaction: postings whose debits equal their credits (at least two), a date (today by default), payee, note and optional `related_id`. `source`, `external_id` and `source_url` say where it came from (a bank, a mail); a source's reference is used once, so sending the same one again with the same date and rows answers 200 with the entry already recorded and creates nothing; the same reference with a different date or rows is a 400. With `dry_run=true` every check runs but nothing is saved: the answer (200) is the entry as it would be saved (`dry_run: true`, and `already_recorded` when the reference is already there). |
| `POST` | `/transactions/batch` | Record up to 50 transactions as one: all are saved or none. An entry whose `source` and `external_id` are already recorded with the same date and rows is skipped (status `already_recorded`), so a batch can be sent again safely. Any problem refuses the whole batch (400) naming the entries at fault. With `dry_run=true` nothing is saved and the answer (200) shows what would be. |
| `GET` | `/transactions/payees` | Who you have paid or been paid by, most used first (the opening-balance entries are left out). |
| `GET` | `/transactions/payee-defaults` | How payees are usually booked, most used first: the accounts of the newest entry with one account on each side (so a repeat can be filled in), and the other routes seen. `payee` narrows to those that match what is typed. |
| `GET` | `/transactions/deleted` | Entries that were deleted and are not back, newest deletion first; `hid` is what to restore. |
| `POST` | `/transactions/deleted/{hid}/restore` | Bring a deleted entry back as it was, with its old id (checked again like any new entry). |
| `GET` | `/transactions/{tid}` | One transaction with its postings. |
| `GET` | `/transactions/` | Newest first. `text` matches the payee, the note or the name of an account used; `kind` is told by the accounts used; `payee` is exact; `source` and `external_id` find the entry a source's reference stands for. |
| `PATCH` | `/transactions/{tid}` | Change a transaction; only the fields sent change (`related_id: null` removes the link; `source`, `external_id` and `source_url` can be set or cleared with null). With `dry_run=true` every check runs but nothing is saved: the answer is the entry as it would read afterwards. |
| `DELETE` | `/transactions/{tid}` | Delete a transaction; it waits in /transactions/deleted and can be restored. With `dry_run=true` nothing is deleted: the answer (200) is the entry that would go. |
| `GET` | `/transactions/changes` | The latest steps across all entries (made, edited, deleted), newest first, each with what it changed. `since` is a day; `by` is `assistant` (any), `web`, `api`, `import`, `recurring` or `mcp:<connection name>`. |
| `GET` | `/transactions/{tid}/changes` | What happened to an entry, oldest first, each step with what it changed (works for a deleted one too). |
| `GET` | `/transactions/{tid}/history` | What happened to an entry, oldest first (works for a deleted one too). |
| `GET` | `/transactions/{tid}/related` | The entries that are related to this one (refunds, reversals), oldest first. |

## Recurring transactions

| Method | Path | What it does |
|---|---|---|
| `GET` | `/recurring/` | Every recurring rule (due occurrences are recorded first). |
| `POST` | `/recurring/` | Create a rule: a simple one (from/to/amount) or a split (`postings`), on a schedule. |
| `GET` | `/recurring/{rid}` | One recurring rule. |
| `PUT` | `/recurring/{rid}` | Replace a rule's details; it continues after the last recorded or skipped day. |
| `POST` | `/recurring/{rid}/pause` | Stop recording a rule until it is resumed. What it already recorded is kept. |
| `POST` | `/recurring/{rid}/resume` | Start a paused rule again. What fell due while it was paused is skipped, not recorded late. |
| `POST` | `/recurring/{rid}/skip` | Leave the next occurrence out (nothing is recorded for it); the rule carries on with the one after. |
| `DELETE` | `/recurring/{rid}` | Delete a rule; the transactions it recorded are kept. |

## Budget and goals

| Method | Path | What it does |
|---|---|---|
| `GET` | `/budget/` | The month's budget (the current month by default): what is left to assign and each category's figures. |
| `PUT` | `/budget/categories/{aid}` | Set how much of the month a category gets (an expense account); 0 removes it. |
| `POST` | `/budget/move` | Move assigned money from one category to another (at most what is available); Ready to assign does not change. |
| `POST` | `/budget/copy` | Assign a month what each category got the month before, where nothing is assigned yet (nothing is overwritten). |
| `PUT` | `/budget/groups/{aid}` | Set a group's budget for a month: at least what its subcategories add up to; the rest is the group's own money. |
| `POST` | `/budget/accounts/{aid}/include` | Make an account part of the budget (its money and its spending count from now on). |
| `POST` | `/budget/goals` | A savings goal: an amount by a month. `set_aside_now` also sets aside this month's share. |
| `PUT` | `/budget/goals/{goal_id}` | Change a goal's name, amount or month. What is saved in it stays. |
| `DELETE` | `/budget/goals/{goal_id}` | Delete a goal for good: what was saved in it goes back to Ready to assign. |
| `PUT` | `/budget/goals/{goal_id}/month` | Set what is set aside for a goal in a month (0 clears it; negative takes back what was saved before). |
| `POST` | `/budget/goals/{goal_id}/use` | Hand money a goal saved to the category that paid for something; Ready to assign does not change. |

## Reports

| Method | Path | What it does |
|---|---|---|
| `GET` | `/reports/trial-balance` | Every account's debits and credits, plus a check that the books are sound. |
| `GET` | `/reports/summary` | Net worth now, plus income and expenses for a period (the current month so far by default). |
| `GET` | `/reports/breakdown` | Where the money went (or came from) in a period, per account `depth` levels below the top-level account. |

## Profile

| Method | Path | What it does |
|---|---|---|
| `GET` | `/profile/` |  |
| `PATCH` | `/profile/` |  |
| `GET` | `/profile/currencies` | The currencies you can choose for your books (changing it relabels, never converts). |

## Backup, restore, import and export

| Method | Path | What it does |
|---|---|---|
| `GET` | `/export` |  |
| `POST` | `/import` |  |
| `GET` | `/backup` | A complete backup: settings, accounts, transactions, recurring rules and the budget. |
| `POST` | `/restore` | Restore a backup into an empty ledger, all or nothing (`dry_run` shows what would happen). |

## Adding a route

See [Conventions and how-tos](conventions.md): a handler in `app/routers/`, a schema in `app/schemas/`, a test, the classification in the isolation audit, and a row here (this table is the list of what exists: regenerate it from `app.routes` when routes change).

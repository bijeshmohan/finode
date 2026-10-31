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
| `POST` | `/accounts/` | Create an account (under Assets, Liabilities or Equity; Expenses and Income hold categories: use `/categories/`); `balance` sets an opening balance on an asset or liability. |
| `GET` | `/accounts/closed` | Accounts that were closed (and categories "deleted" while they had a history): the outermost of each closed |
| `GET` | `/accounts/deleted` | Accounts and categories deleted for good that can still be restored, newest first. |
| `POST` | `/accounts/deleted/{did}/restore` | Bring back a deleted account or category (with its old id, plan and payment links). |
| `GET` | `/accounts/{aid}` | The account with its balance as of a day (today by default: later entries do not count yet). |
| `GET` | `/accounts/` | Accounts with their balances as of a day (today by default: later entries do not count yet). |
| `PATCH` | `/accounts/{aid}` | Change an account: name, note, place (`parent_id`), budget flag or payment category. |
| `DELETE` | `/accounts/{aid}` | Delete an account for good; refused when it has entries, sub-accounts or a recurring rule (close it instead). |
| `POST` | `/accounts/{aid}/close` | Close an account (and everything inside it): its history stays, nothing more can be posted to it. |
| `POST` | `/accounts/{aid}/reopen` | Reopen a closed account with everything inside it, and the groups above it. |
| `GET` | `/accounts/changes` | The latest steps across all accounts and categories (made, renamed, moved, closed, reopened, deleted), newest first, each with what it changed. `since` is a day; `by` is `assistant` (any), `web`, `api` or `mcp:<name>`. |
| `POST` | `/accounts/{aid}/merge` | Make this account part of another (`into`): its entries, planned amounts, recurring rules and payment links become the other's and it is deleted, all or nothing. Both must be plain accounts of the same top-level account (this one without sub-accounts, the other open and able to take entries). Refused when an entry or rule has both on opposite sides, or only one is part of the budget. With `dry_run=true` nothing changes and the answer says what would move. |
| `GET` | `/accounts/{aid}/changes` | What happened to an account or category, oldest first, each step with what it changed and who did it (works for a deleted one too). |
| `GET` | `/accounts/{aid}/check-balance` | Set a statement's balance (`statement_balance`) against the books on the same day (`as_of`, today by default): the books' balance, the difference and the entries of the last `days` days, with those exactly as large as the difference. Nothing is changed. A card's or loan's balance is what is owed, as the app shows it. |
| `GET` | `/accounts/{aid}/register` | The account's entries, oldest first, each with what it changed and the running balance. `own_only` leaves out |

## Categories

A category is what money was for (Groceries, EMI, Salary), apart from the accounts. **Spending** categories are what the budget plans against; **earning** ones label income. A group has no parent; a category inside it names it as `parent_id`; two levels at most. An Income or Expenses account has a category of the same id (`category_id` on the account), so existing ids keep working. A category's `bcid` is also the id of its books account.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/categories/` | Your categories with their `path` ("Food:Groceries") and kind. `kind` narrows to `spending` or `earning`; `include_closed` adds closed ones. |
| `POST` | `/categories/` | Make a category (or a group: leave out `parent_id`). Names are unique inside a group, capitals aside; a group holds categories of its own kind only. |
| `GET` | `/categories/{bcid}` | One category. |
| `PATCH` | `/categories/{bcid}` | Rename it, change its note or move it into another group (`parent_id`; null takes it out of its group). |
| `POST` | `/categories/{bcid}/close` | Close it (and what is inside a group): history stays, nothing more can be labelled with it. |
| `POST` | `/categories/{bcid}/reopen` | Reopen it. |
| `POST` | `/categories/{bcid}/delete` | Remove an unused category for good. One with history is closed instead; the answer's `outcome` says `deleted` or `closed`. |
| `GET` | `/categories/{bcid}/register` | The entries that have a line labelled with the category (and its subcategories, unless `own_only=true`), oldest first, with what each changed and the running total. |
| `POST` | `/categories/{bcid}/merge` | Fold it into another category (`into`): entries, labelled lines, planned amounts and recurring rules become the other's. `dry_run=true` only says what would move. |

**On a transaction line** (`postings[]` of `/transactions/`, and the rows of a recurring split) `category` says what the line was for. Leave it out and the account decides: an Income or Expenses account stands for its category, and a payment into a loan or fund that has a payment category takes that one. A line may carry **only** its category (no `account`): it then posts to that category's books account. A category on a line to an Income or Expenses account must be that account's own; on any other account it must be a spending category, and not on an account that is part of the budget (the category goes on the other side). A simple recurring rule takes one `category`.

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
| `GET` | `/transactions/` | Newest first. `text` matches the payee, the note or the name of an account used; `kind` is told by the accounts used; `payee` is exact; `source` and `external_id` find the entry a source's reference stands for; `tag` finds the entries that carry that tag (every entry reads back its `tags`; create and update take `tags`). |
| `PATCH` | `/transactions/{tid}` | Change a transaction; only the fields sent change (`related_id: null` removes the link; `source`, `external_id` and `source_url` can be set or cleared with null). With `dry_run=true` every check runs but nothing is saved: the answer is the entry as it would read afterwards. |
| `DELETE` | `/transactions/{tid}` | Delete a transaction; it waits in /transactions/deleted and can be restored. With `dry_run=true` nothing is deleted: the answer (200) is the entry that would go. |
| `GET` | `/transactions/changes` | The latest steps across all entries (made, edited, deleted), newest first, each with what it changed. `since` is a day; `by` is `assistant` (any), `web`, `api`, `import`, `recurring` or `mcp:<connection name>`. |
| `GET` | `/transactions/{tid}/changes` | What happened to an entry, oldest first, each step with what it changed (works for a deleted one too). |
| `GET` | `/transactions/{tid}/history` | What happened to an entry, oldest first (works for a deleted one too). |
| `GET` | `/transactions/{tid}/related` | The entries that are related to this one (refunds, reversals), oldest first. |

## Tags

| Method | Path | What it does |
|---|---|---|
| `GET` | `/tags/` | Your tags, the most used first, each with how many entries carry it and the day of the latest. |
| `PATCH` | `/tags/{name}` | Rename a tag (`{"name": "new"}`); when the new name is another of your tags the two become one. |
| `DELETE` | `/tags/{name}` | Take a tag off every entry and remove it. The entries stay as they are. |

## Recurring transactions

| Method | Path | What it does |
|---|---|---|
| `GET` | `/recurring/` | Every recurring rule (due occurrences are recorded first). |
| `POST` | `/recurring/` | Create a rule: a simple one (from/to/amount) or a split (`postings`), on a schedule; `tags` (up to 10) go on every entry it records. |
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
| `GET` | `/todo/` | What needs a decision now: payments no category took, accounts left out of the budget, failing recurring rules, and a count. |
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
| `GET` | `/reports/summary` | Net worth now, plus for a period (the current month so far by default) `income` and `expenses` as the books see them (paying into a loan is no expense) and `spent`, what the budget calls spending (everything labelled with a spending category, a payment into a loan included). |
| `GET` | `/reports/breakdown` | Where the money went (or came from) in a period, `depth` levels down. It is what the money was for, as the budget counts it (by category). |

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

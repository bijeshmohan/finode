# The JSON API

Everything the web app and the assistants can do with your books can be done through the JSON API under `/api`. It is for scripts, tools and future clients; the web app and the MCP server call the same services directly. Interactive documentation (`/docs`) is off unless `FINODE_API_DOCS=true`.

## Using it

- **Sign in with a Supabase access token**: `Authorization: Bearer <token>`. The API never reads cookies. An assistant's personal access token or an OAuth app's token is refused here (they work only on `/mcp`).
- **Everything is yours alone.** Every request is scoped to the signed-in person; another person's ids answer 404 (or 400 when they are named inside a request). `tests/test_isolation.py` checks this for every route.
- **Amounts** are decimal strings or numbers in the person's one currency (no other currency exists); more decimals than the currency keeps are refused. **Dates** are `YYYY-MM-DD`, between 1900 and 2999. Money moves as a list of **postings** (`account`, `side` debit or credit, `amount`) whose debits equal their credits.
- **Errors** are JSON `{"detail": ...}`: 400 for a refused change (with the reason), 404 for an unknown id, 409 when something is in use, 422 for a malformed request.
- Routes with a trailing slash (`/accounts/`) are the collection; `/accounts/closed`, `/transactions/payees` and the like are fixed words, not ids.

## What is not in the API, on purpose

| Not here | Why |
|---|---|
| Signing in, signing up, passwords, the OAuth consent page | Identity belongs to Supabase; these are web pages. |
| Creating or revoking assistant tokens and connected apps | A token must never be able to manage tokens, and an app's token never acts as a full sign-in. |
| **Erase my books** and **Delete my account** | They need the person to type their email on the settings pages; a leaked bearer token must not be able to wipe a ledger. |
| The Add screen's payee chips (names only) | A convenience of the Add screen; `GET /transactions/payees` gives the same names, and `GET /transactions/payee-defaults` how a payee is usually booked. |

## Accounts and categories

| Method | Path | What it does |
|---|---|---|
| `POST` | `/accounts/` | Create an account (under Assets, Liabilities or Equity; Expenses and Income hold categories: use `/categories/`); `balance` sets an opening balance on an asset or liability. |
| `GET` | `/accounts/closed` | Accounts that were closed (and categories "deleted" while they had a history): the outermost of each closed |
| `GET` | `/accounts/{account_id}` | The account with its balance as of a day (today by default: later entries do not count yet). |
| `GET` | `/accounts/` | Accounts with their balances as of a day (today by default: later entries do not count yet). |
| `PATCH` | `/accounts/{account_id}` | Change an account: name, note, place (`parent_id`) or budget flag. |
| `DELETE` | `/accounts/{account_id}` | Delete an account for good; refused when it has entries, sub-accounts or a recurring rule (close it instead). |
| `POST` | `/accounts/{account_id}/close` | Close an account (and everything inside it): its history stays, nothing more can be posted to it. |
| `POST` | `/accounts/{account_id}/reopen` | Reopen a closed account with everything inside it, and the groups above it. |
| `POST` | `/accounts/{account_id}/merge` | Make this account part of another (`into`): its entries, planned amounts, recurring rules become the other's and it is deleted, all or nothing. Both must be plain accounts of the same top-level account (this one without sub-accounts, the other open and able to take entries). Refused when an entry or rule has both on opposite sides, or only one is part of the budget. With `dry_run=true` nothing changes and the answer says what would move. |
| `GET` | `/accounts/{account_id}/bill` | A card's or loan's bill, worked out from its `statement_day`, `due_day` and `bill_rounding` (`none`, `nearest`, `up`) and from each line's `posted_on` (the day the account posts it, when not the entry's date): what was owed when the latest statement closed (`statement_balance`, and `statement_due` after the rounding, `rounded_by`), the payments and refunds since (`paid_since`), what is left to pay (`bill`), when it is due (`due_date`, `days_to_due`, negative once overdue), what was spent since and what is owed in all. Nothing is stored. 400 while the account has no days. |
| `GET` | `/accounts/{account_id}/check-balance` | Set a statement's balance (`statement_balance`) against the books on the same day (`as_of`, today by default): the books' balance, the difference and the entries of the last `days` days, with those exactly as large as the difference. Nothing is changed. A card's or loan's balance is what is owed, as the app shows it. |
| `GET` | `/accounts/{account_id}/register` | The account's entries, oldest first, each with what it changed and the running balance. `own_only` leaves out |

## Categories

A category is what money was for (Groceries, EMI, Salary), apart from the accounts. **Spending** categories are what the budget plans against; **earning** ones label income. A group has no parent; a category inside it names it as `parent_id`; two levels at most. A category is not an account: nothing is made under Expenses or Income, and a category's id is never accepted where an account id goes.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/categories/` | Your categories with their `path` ("Food:Groceries") and kind. `kind` narrows to `spending` or `earning`; `include_closed` adds closed ones. |
| `POST` | `/categories/` | Make a category (or a group: leave out `parent_id`). Names are unique inside a group, capitals aside; a group holds categories of its own kind only. |
| `GET` | `/categories/{category_id}` | One category. |
| `PATCH` | `/categories/{category_id}` | Rename it, change its note or move it into another group (`parent_id`; null takes it out of its group). |
| `POST` | `/categories/{category_id}/close` | Close it (and what is inside a group): history stays, nothing more can be labelled with it. |
| `POST` | `/categories/{category_id}/reopen` | Reopen it. |
| `POST` | `/categories/{category_id}/delete` | Remove an unused category for good. One with history is closed instead; the answer's `outcome` says `deleted` or `closed`. |
| `GET` | `/categories/{category_id}/register` | The entries that have a line labelled with the category (and its subcategories, unless `own_only=true`), oldest first, with what each changed and the running total. |
| `POST` | `/categories/{category_id}/merge` | Fold it into another category (`into`): entries, labelled lines, planned amounts and recurring rules become the other's. `dry_run=true` only says what would move. |

## Shared expenses

An expense split with contacts. A **draft** is only the plan; **confirming** records one ordinary ledger entry (your own share spent under the expense's `category_id`, what you paid out of your accounts) and, for each contact, what they owe you or you owe them, worked out from what they paid against their share. Only your own share counts against your budget. `split_method` is `equal`, `exact` (the `value` of each participant is an amount), `percentage` (values make 100) or `shares` (weights); leftover units of the smallest coin go to the first participants. `payments` are what *you* paid (an account each), `contributions` what contacts paid; together they must make the total before it can be confirmed. A confirmed expense can't be edited: cancel it (which removes its entry and what it left owed, refused once something was settled) and enter it again.

| Method | Path | What it does |
|---|---|---|
| `POST` | `/shared-expenses/preview` | Each person's share, who owes whom, the ledger lines and how much is still unpaid for, saving nothing. |
| `POST` | `/shared-expenses/` | Save a draft, or with `confirm=true` record it at once. `Idempotency-Key` makes a retry safe (with `confirm`). |
| `GET` | `/shared-expenses/` | Your shared expenses, newest first (`status=draft|confirmed`). |
| `GET` | `/shared-expenses/{expense_id}` | One expense with its shares, payments, ledger lines and what is owed. |
| `PATCH` | `/shared-expenses/{expense_id}` | Change a draft; only what is sent changes (409 once confirmed). |
| `POST` | `/shared-expenses/{expense_id}/confirm` | Record a draft (409 if already confirmed; `Idempotency-Key` returns the first result on a retry). |
| `POST` | `/shared-expenses/{expense_id}/cancel` | Remove a draft, or reverse a confirmed expense for good. |

## Contacts

A contact is a person you lend to, borrow from or share costs with. It is not an account: its ledger side is two ordinary accounts made with it, **Due from X** (an asset: X owes you) and **Due to X** (a liability: you owe X), both outside the budget. They follow the contact (account responses carry `contact_account: true` for them) and can't be renamed, closed, deleted, merged or given sub-accounts on their own, and **nothing can be posted to them except through the contact routes** (the ordinary transaction routes answer 400): that keeps every debt tied to an obligation. An entry made through a contact can't be edited or deleted on the ordinary routes either; reverse it from the contact. Names are unique (capitals aside) and at most 30 characters.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/contacts/` | Your contacts, each with the ids of its two accounts, what each holds (`receivable`, `payable`, `net`: entries dated ahead included) and the day of the latest activity. `q` searches name, email, phone and notes; `owing=receivable|payable` filters; `sort=name|balance` (the biggest outstanding first); `include_archived=true` adds archived ones. |
| `POST` | `/contacts/` | Add a contact (`name`, optional `email`, `phone`, `notes`); its two accounts are made with it. |
| `GET` | `/contacts/{contact_id}` | One contact. |
| `PATCH` | `/contacts/{contact_id}` | Change the name (both accounts are renamed) or details; null clears email, phone or notes. |
| `DELETE` | `/contacts/{contact_id}` | Remove a contact no money moved with, for good. One with entries is archived instead (refused while anything is owed); `outcome` says `deleted` or `archived`. |
| `POST` | `/contacts/{contact_id}/archive` | Hide a contact from new entries; history stays. Refused while anything is owed either way. |
| `POST` | `/contacts/{contact_id}/restore` | Bring an archived contact back. |
| `GET` | `/contacts/{contact_id}/summary` | The ledger's figures (`total_receivable`, `total_payable`, `net_balance`), what you lent and borrowed, the expenses you shared, the settlements, how many obligations are open and the latest activity. |
| `GET` | `/contacts/{contact_id}/activity` | Everything done with the contact, newest first, with `total` for paging (`purpose`, `limit`, `offset`). |
| `GET` | `/contacts/{contact_id}/obligations` | What the contact owes you and what you owe them, one row per amount, oldest first, with `settled_amount`, `outstanding_amount` and `status`. `direction` and `open_only` narrow it. |
| `POST` | `/contacts/{contact_id}/transfers` | Money sent to a contact (`loan`, `advance`, `gift`) or received from one (`borrowing`, `advance`, `gift`) with `amount`, `account_id` (yours), `date`, `description` and, for a gift, `category_id`. A loan or advance leaves a receivable, a borrowing or received advance a payable, a gift nothing. Send an `Idempotency-Key` header and a retry returns the first result. |
| `POST` | `/contacts/{contact_id}/opening-balance` | What the contact already owed you (`receivable`) or you owed them (`payable`) before finode, with `amount`, `date` and a note. Recorded against Opening Balances, so none of your accounts or budgets move; settled like any other amount. Undo it with `DELETE /transfers/{transaction_id}`. `Idempotency-Key` makes a retry safe. |
| `GET` | `/contacts/{contact_id}/transfers` | A contact's transfers, newest first. |
| `GET` | `/transfers/{transaction_id}` | One transfer (its id is the id of its ledger entry). |
| `POST` | `/contacts/{contact_id}/settlements/preview` | What a settlement would clear: which obligations, how much of each, what is left over and what is still owed. Saves nothing. |
| `POST` | `/contacts/{contact_id}/settlements` | Settle up: `received` (they pay back what they owe you) or `sent` (you pay back what you owe them), `amount`, `account_id` (yours), `allocation_method` `fifo` (oldest first) or `manual` (`allocations`: `obligation_id` and `amount`). Never beyond what is owed: more needs `excess_as` (received: `borrowing`, `advance`, `gift`; sent: `loan`, `advance`, `gift`; a gift may name `excess_category_id`). `Idempotency-Key` makes a retry safe. |
| `GET` | `/contacts/{contact_id}/settlements` | A contact's settlements, newest first. |
| `GET` | `/settlements/{transaction_id}` | One settlement with what it cleared. |
| `DELETE` | `/settlements/{transaction_id}` | Undo a settlement for good: what it cleared is owed again. Refused (409) once what its excess left owed has been settled in turn. |
| `DELETE` | `/transfers/{transaction_id}` | Undo a transfer for good: its entry, what it left owed and its activity go. Refused (409) once anything was settled against it. |

**A transaction line** (`postings[]`) may also carry `posted_on`: the day its account posts it when that is not the entry's `date` (never before it); a card's bill counts the line by that day and nothing else reads it. **On a transaction line** (`postings[]` of `/transactions/`, and the rows of a recurring split) `category` says what the line was for. Leave it out and a line on Expenses or Income is Uncategorised; a payment into a loan or fund stays without one (nothing is filled in). A line may carry **only** its category (no `account`): it then posts to the root Expenses account (a spending category) or Income (an earning one). A category on a line to Expenses or Income must be a spending or earning one to match; on any other account it must be a spending category, and not on an account that is part of the budget (the category goes on the other side). A simple recurring rule takes one `category`.

## Transactions

| Method | Path | What it does |
|---|---|---|
| `POST` | `/transactions/` | Record a transaction: postings whose debits equal their credits (at least two), a date (today by default), payee, note and optional `related_id`. `source`, `external_id` and `source_url` say where it came from (a bank, a mail); a source's reference is used once, so sending the same one again with the same date and rows answers 200 with the entry already recorded and creates nothing; the same reference with a different date or rows is a 400. With `dry_run=true` every check runs but nothing is saved: the answer (200) is the entry as it would be saved (`dry_run: true`, and `already_recorded` when the reference is already there). |
| `POST` | `/transactions/batch` | Record up to 50 transactions as one: all are saved or none. An entry whose `source` and `external_id` are already recorded with the same date and rows is skipped (status `already_recorded`), so a batch can be sent again safely. Any problem refuses the whole batch (400) naming the entries at fault. With `dry_run=true` nothing is saved and the answer (200) shows what would be. |
| `GET` | `/transactions/payees` | Who you have paid or been paid by, most used first (the opening-balance entries are left out). |
| `GET` | `/transactions/payee-defaults` | How payees are usually booked, most used first: the accounts of the newest entry with one account on each side (so a repeat can be filled in), and the other routes seen. `payee` narrows to those that match what is typed. |
| `GET` | `/transactions/{transaction_id}` | One transaction with its postings. |
| `GET` | `/transactions/` | Newest first. `text` matches the payee, the note or the name of an account used; `kind` is told by the accounts used; `payee` is exact; `source` and `external_id` find the entry a source's reference stands for; `tag` finds the entries that carry that tag (every entry reads back its `tags`; create and update take `tags`). |
| `PATCH` | `/transactions/{transaction_id}` | Change a transaction; only the fields sent change (`related_id: null` removes the link; `source`, `external_id` and `source_url` can be set or cleared with null). With `dry_run=true` every check runs but nothing is saved: the answer is the entry as it would read afterwards. |
| `DELETE` | `/transactions/{transaction_id}` | Delete a transaction for good (finode keeps no history). With `dry_run=true` nothing is deleted: the answer (200) is the entry that would go. |
| `GET` | `/transactions/{transaction_id}/related` | The entries that are related to this one (refunds, reversals), oldest first. |

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
| `GET` | `/recurring/{recurring_id}` | One recurring rule. |
| `PUT` | `/recurring/{recurring_id}` | Replace a rule's details; it continues after the last recorded or skipped day. |
| `POST` | `/recurring/{recurring_id}/pause` | Stop recording a rule until it is resumed. What it already recorded is kept. |
| `POST` | `/recurring/{recurring_id}/resume` | Start a paused rule again. What fell due while it was paused is skipped, not recorded late. |
| `POST` | `/recurring/{recurring_id}/skip` | Leave the next occurrence out (nothing is recorded for it); the rule carries on with the one after. |
| `DELETE` | `/recurring/{recurring_id}` | Delete a rule; the transactions it recorded are kept. |

## Budget

| Method | Path | What it does |
|---|---|---|
| `GET` | `/budget/` | The month's budget (the current month by default): what is left to assign and each category's figures. |
| `GET` | `/todo/` | What needs a decision now: payments no category took, accounts left out of the budget, failing recurring rules, card bills due within 5 days or overdue (`card_bills`), and a count. |
| `GET` | `/budget/coming-up` | What is coming up after today, to the end of this month (or to `through`, at most a year ahead): entries dated ahead and what recurring rules will record, those that touch an account of the budget, soonest first. |
| `PUT` | `/budget/categories/{category_id}` | Set how much of the month a category gets (an expense account); 0 removes it. |
| `POST` | `/budget/move` | Move assigned money from one category to another (at most what is available); Ready to assign does not change. |
| `POST` | `/budget/copy` | Assign a month what each category got the month before, where nothing is assigned yet (nothing is overwritten). |
| `PUT` | `/budget/groups/{category_id}` | Set a group's budget for a month: at least what its subcategories add up to; the rest is the group's own money. |
| `POST` | `/budget/accounts/{account_id}/include` | Make an account part of the budget (its money and its spending count from now on). |

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

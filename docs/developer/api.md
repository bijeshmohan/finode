# The JSON API

Everything the app and the assistants can do can be done through the JSON API under `/api`. It is for the finode app (the only UI), scripts and tools; the MCP server calls the same services directly. Interactive documentation (`/docs`) is off unless `FINODE_API_DOCS=true`.

## Using it

- **Sign in with a Supabase access token**: `Authorization: Bearer <token>`. An assistant's personal access token or an OAuth app's token is refused here (they work only on `/mcp`).
- **The finode app** signs in through `/auth/sign-in` and then uses the HttpOnly session cookies it sets. A cookie request that changes anything must send `X-Finode: 1` and an `Origin` equal to the address it came in on: the app and the API share one address, and there is no CORS (see `docs/architecture/mcp-and-auth.md`).
- **Everything is yours alone.** Every request is scoped to the signed-in person; another person's ids answer 404 (or 400 when they are named inside a request). `backend/tests/guards/test_isolation.py` checks this for every route.
- **Amounts** are decimal strings or numbers in the person's one currency (no other currency exists); more decimals than the currency keeps are refused. **Dates** are `YYYY-MM-DD`, between 1900 and 2999. Money moves as a list of **postings** (`account`, `side` debit or credit, `amount`) whose debits equal their credits.
- **Errors** are JSON `{"detail": ...}`: 400 for a refused change (with the reason), 404 for an unknown id, 409 when something is in use, 422 for a malformed request.
- Routes with a trailing slash (`/accounts/`) are the collection; `/accounts/closed`, `/transactions/payees` and the like are fixed words, not ids.

## Sign-in

Every `POST` here needs the finode app's header and origin; errors are `{"detail": {"message", "code"}}`, with `Retry-After` on 429.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/auth/options` | What the sign-in screens offer on this server: `signup_enabled`, `reset_enabled`, `test_notice`. No sign-in needed. |
| `GET` | `/auth/session` | Who is signed in (`email`), `today` as finode counts it (`FINODE_TIMEZONE`), the feedback link and whether Delete my account can remove the login. |
| `POST` | `/auth/sign-in` | `email`, `password`: sets the session cookies (204); 401 for a wrong password, 429 after too many tries. |
| `POST` | `/auth/sign-up` | Invite-only (404 when off): `email`, `password`, `confirm_password`, `invite_code`, `accept` (the test notice); 201 `{signed_in}`, with the cookies when signed in. |
| `POST` | `/auth/forgot` | `email`: emails a reset link (404 when reset is off); 202 whether or not the address has an account. |
| `POST` | `/auth/reset` | `token_hash` (from the emailed link), `password`, `confirm_password`: sets the password and signs in (204); a spent or expired link answers `code: link-invalid`. |
| `POST` | `/auth/sign-out` | Clears the session cookies (204). |

## Assistants

Only for someone signed in to the finode app itself (the session cookie): a bearer token is refused, so a token can never mint tokens or let an app in.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/assistants/` | The address assistants connect to (`mcp_url`), your tokens and the apps you connected (revoked ones left out). |
| `POST` | `/assistants/tokens` | A new personal access token: `name`, `scope` (`read`, `write` or `manage`). Its `secret` is in this answer only. |
| `POST` | `/assistants/tokens/{token_id}/access` | Change what a token may do: `scope`. |
| `POST` | `/assistants/tokens/{token_id}/revoke` | Revoke a token; it stops working at once. |
| `POST` | `/assistants/apps/{grant_id}/access` | Change what a connected app may do: `scope`. |
| `POST` | `/assistants/apps/{grant_id}/disconnect` | Take a connected app's access back and ask Supabase to stop issuing it tokens. |
| `GET` | `/oauth/consent/{authorization_id}` | The app asking to connect, as Supabase describes it (`client_name`, `client_uri`, `redirect_uri`: where it sends you after, `scopes`); `redirect_url` is set when you already decided. |
| `POST` | `/oauth/consent/{authorization_id}` | `decision` (`allow` or `deny`) and `access` (`read`, `write`, `manage`); answers the `redirect_url` that sends you back to the app. The app recorded is whatever Supabase says the request is for. |

## Accounts and categories

| Method | Path | What it does |
|---|---|---|
| `POST` | `/accounts/` | Create an account of one of the four types (`type`: `assets.bank` Bank Account, `assets.cash` Cash, `liabilities.cards` Credit Card, `assets.wallet` Prepaid Wallet); it is part of the budget. `balance` sets an opening balance (on a Credit Card: what is owed). Spending and income are categories: use `/categories/`. |
| `GET` | `/accounts/closed` | Accounts that were closed: the outermost of each closed branch, newest first. |
| `GET` | `/accounts/{account_id}` | The account with its balance as of a day (today by default: later entries do not count yet). |
| `GET` | `/accounts/` | Accounts with their balances as of a day (today by default: later entries do not count yet). |
| `PATCH` | `/accounts/{account_id}` | Change an account: name, note, balance (recorded as an adjustment), a card's bill days and rounding, or `pinned` (true pins an open account; the Accounts page lists it again in a Pinned row). It keeps its type. |
| `DELETE` | `/accounts/{account_id}` | Delete an account for good; refused when it has entries or a recurring rule (close it instead). |
| `POST` | `/accounts/{account_id}/close` | Close an account (and everything inside it): its history stays, nothing more can be posted to it. |
| `POST` | `/accounts/{account_id}/reopen` | Reopen a closed account. |
| `POST` | `/accounts/{account_id}/merge` | Make this account part of another (`into`): its entries, recurring rules and shared bills become the other's and it is deleted, all or nothing. Both must be accounts of the same top-level account (assets into assets; the other open). Refused when an entry or rule has both on opposite sides. With `dry_run=true` nothing changes and the answer says what would move. |
| `GET` | `/accounts/{account_id}/bill` | A card's or loan's bill, worked out from its `statement_day`, `due_day` and `bill_rounding` (`none`, `nearest`, `up`) and from each line's `posted_on` (the day the account posts it, when not the entry's date): what was owed when the latest statement closed (`statement_balance`, and `statement_due` after the rounding, `rounded_by`), the payments and refunds since (`paid_since`), what is left to pay (`bill`), when it is due (`due_date`, `days_to_due`, negative once overdue), what was spent since and what is owed in all. Nothing is stored. 400 while the account has no days. |
| `GET` | `/accounts/{account_id}/check-balance` | Set a statement's balance (`statement_balance`) against the books on the same day (`as_of`, today by default): the books' balance, the difference and the entries of the last `days` days, with those exactly as large as the difference. Nothing is changed. A card's or loan's balance is what is owed, as the app shows it. |
| `GET` | `/accounts/{account_id}/register` | The account's entries, oldest first, each with what it changed and the running balance. `own_only` leaves out |

## Categories

A category is what money was for (Groceries, EMI, Salary), apart from the accounts. **Spending** categories are what the budget plans against; **earning** ones label income. Categories are one flat list (since 2026-11-23; a `parent_id` sent by an old client is ignored). A category is not an account: nothing is made under Expenses or Income, and a category's id is never accepted where an account id goes.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/categories/` | Your categories with their name, kind and `icon`. `kind` narrows to `spending` or `earning`; `include_closed` adds closed ones. |
| `POST` | `/categories/` | Make a category with its `icon` (required: a name from `finode/category_icons.py`; unknown names and the system marks are a 422). Names are unique per kind, capitals aside. |
| `GET` | `/categories/{category_id}` | One category. |
| `PATCH` | `/categories/{category_id}` | Rename it, or change its note or its `icon` (the built-in Uncategorised keeps its own). |
| `POST` | `/categories/{category_id}/close` | Close it: history stays, nothing more can be labelled with it. |
| `POST` | `/categories/{category_id}/reopen` | Reopen it. |
| `POST` | `/categories/{category_id}/delete` | Remove an unused category for good. One with history is closed instead; the answer's `outcome` says `deleted` or `closed`. |
| `GET` | `/categories/{category_id}/register` | The entries that have a line labelled with the category, oldest first, with what each changed and the running total. |
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

## Shared income

Money that came in, part of it not yours: rent collected for a co-owner, a refund for the whole group. One ordinary ledger entry records it: only your own part is income (under `category_id`, an income category). `theirs` are the parts that belong to contacts (you hold the money for them, so you owe them that much), `received_by` is money a contact received for you (they owe you), and `deposits` is what landed in your accounts. Your part is the total less `theirs`; `deposits` and `received_by` must add up to the total, a contact is on one side only, and at least one contact is named. There is no draft: it is recorded when sent. It is changed by sending it again (`PUT`), until anything was paid back against it.

| Method | Path | What it does |
|---|---|---|
| `POST` | `/shared-incomes/preview` | Your income, what you hold for others and who received it for you, saving nothing. |
| `POST` | `/shared-incomes/` | Record it. `Idempotency-Key` makes a retry safe. |
| `GET` | `/shared-incomes/{transaction_id}` | One shared income as recorded (404 for any other entry). |
| `PUT` | `/shared-incomes/{transaction_id}` | Record it again with new parts; the entry keeps its id. An ordinary income entry can be turned into shared income this way. 409 once anything was paid back. |
| `POST` | `/shared-incomes/{transaction_id}/cancel` | Reverse it for good: the entry and what it left owed go too (409 once something was settled). |

## Contacts

A contact is a person you lend to, borrow from or share costs with. It is not an account: its ledger side is two ordinary accounts made with it, **Due from X** (an asset: X owes you) and **Due to X** (a liability: you owe X), both outside the budget. They follow the contact (account responses carry `contact_account: true` for them) and can't be renamed, closed, deleted, merged or given sub-accounts on their own, and **nothing can be posted to them except through the contact routes** (the ordinary transaction routes answer 400): that keeps every debt tied to an obligation. An entry made through a contact can't be edited or deleted on the ordinary routes either; reverse it from the contact. Names are unique (capitals aside) and at most 30 characters.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/contacts/` | Your contacts, each with the ids of its two accounts, what each holds (`receivable`, `payable`, `net`: entries dated ahead included) and the day of the latest activity. `q` searches name, email, phone and notes; `owing=receivable|payable` filters; `sort=name|balance` (the biggest outstanding first); `include_archived=true` adds archived ones. |
| `POST` | `/contacts/` | Add a contact (`name`, optional `email`, `phone`, `notes`); its two accounts are made with it. With `opening` (`direction`, `amount`, `date`, `description`, as `/opening-balance` takes it) what they already owed is recorded with them: both or neither. |
| `GET` | `/contacts/{contact_id}` | One contact. |
| `PATCH` | `/contacts/{contact_id}` | Change the name (both accounts are renamed) or details; null clears email, phone or notes. |
| `DELETE` | `/contacts/{contact_id}` | Remove a contact no money moved with, for good. One with entries is archived instead (refused while anything is owed); `outcome` says `deleted` or `archived`. |
| `POST` | `/contacts/{contact_id}/archive` | Hide a contact from new entries; history stays. Refused while anything is owed either way. |
| `POST` | `/contacts/{contact_id}/restore` | Bring an archived contact back. |
| `GET` | `/contacts/{contact_id}/summary` | The ledger's figures (`total_receivable`, `total_payable`, `net_balance`), what you lent and borrowed, the expenses you shared, the settlements, how many obligations are open and the latest activity. |
| `GET` | `/contacts/{contact_id}/activity` | Everything done with the contact, newest first, with `total` for paging (`purpose`, `limit`, `offset`). |
| `GET` | `/contacts/{contact_id}/obligations` | What the contact owes you and what you owe them, one row per amount, oldest first, with `settled_amount`, `outstanding_amount` and `status`. `direction` and `open_only` narrow it. |
| `POST` | `/contacts/{contact_id}/transfers` | (A person is never owed both ways: whatever saves an amount owed evens it out against the other side at once, with one entry between "Due to" and "Due from" that touches none of your accounts or budgets. There are no net-off routes.) Money sent to a contact (`loan`, `advance`, `gift`) or received from one (`borrowing`, `advance`, `gift`) with `amount`, `account_id` (yours), `date`, `description` and, for a gift, `category_id`. A loan or advance leaves a receivable, a borrowing or received advance a payable, a gift nothing. Send an `Idempotency-Key` header and a retry returns the first result. |
| `POST` | `/contacts/{contact_id}/opening-balance` | What the contact already owed you (`receivable`) or you owed them (`payable`) before finode, with `amount`, `date` and a note. Recorded against Opening Balances, so none of your accounts or budgets move; settled like any other amount. Undo it with `DELETE /transfers/{transaction_id}`. `Idempotency-Key` makes a retry safe. |
| `GET` | `/contacts/{contact_id}/transfers` | A contact's transfers, newest first. |
| `GET` | `/transfers/{transaction_id}` | One transfer (its id is the id of its ledger entry). |
| `POST` | `/contacts/{contact_id}/settlements/preview` | What a settlement would clear: which obligations, how much of each, what is left over and what is still owed. Saves nothing. |
| `POST` | `/contacts/{contact_id}/settlements` | Settle up: `received` (they pay back what they owe you) or `sent` (you pay back what you owe them), `amount`, `account_id` (yours), `allocation_method` `fifo` (oldest first) or `manual` (`allocations`: `obligation_id` and `amount`). Never beyond what is owed: more needs `excess_as` (received: `borrowing`, `advance`, `gift`; sent: `loan`, `advance`, `gift`; a gift may name `excess_category_id`). `Idempotency-Key` makes a retry safe. |
| `GET` | `/contacts/{contact_id}/settlements` | A contact's settlements, newest first. |
| `POST` | `/contacts/{contact_id}/entries/{transaction_id}/reverse` | Undo an entry done with the contact for good, the way its kind is undone (a settlement, a shared bill, a shared income, a transfer or an opening balance). 204; 404 for an entry that is not this contact's; 409 while something was paid back against it; 400 for an evened-out entry (it goes by itself when one of the two is undone). Reversing a shared bill cancels it for everyone on it. |
| `GET` | `/settlements/{transaction_id}` | One settlement with what it cleared. |
| `DELETE` | `/settlements/{transaction_id}` | Undo a settlement for good: what it cleared is owed again. Refused (409) once what its excess left owed has been settled in turn. |
| `PATCH` | `/transfers/{transaction_id}` | Change an **opening balance** (`amount`, `date`, `description`, `direction`; only what is sent changes). Once part of it was paid back, the amount can't go below that (400) and who owes whom can't change (409). Any other transfer is reversed and recorded again. |
| `DELETE` | `/transfers/{transaction_id}` | Undo a transfer for good: its entry, what it left owed and its activity go. Refused (409) once anything was settled against it. |

**A transaction line** (`postings[]`) may also carry `posted_on`: the day its account posts it when that is not the entry's `date` (never before it); a card's bill counts the line by that day and nothing else reads it. **On a transaction line** (`postings[]` of `/transactions/`, and the rows of a recurring split) `category` says what the line was for. Leave it out and a line on Expenses or Income is Uncategorised; a payment into a loan or fund stays without one (nothing is filled in). A line may carry **only** its category (no `account`): it then posts to the root Expenses account (a spending category) or Income (an earning one). A category on a line to Expenses or Income must be a spending or earning one to match; on any other account it must be a spending category, and not on an account that is part of the budget (the category goes on the other side). A simple recurring rule takes one `category`.

## Transactions

| Method | Path | What it does |
|---|---|---|
| `POST` | `/transactions/` | Record a transaction: postings whose debits equal their credits (at least two), a date (today by default), payee, note and optional `related_id`. `source`, `external_id` and `source_url` say where it came from (a bank, a mail); a source's reference is used once, so sending the same one again with the same date and rows answers 200 with the entry already recorded and creates nothing; the same reference with a different date or rows is a 400. With `dry_run=true` every check runs but nothing is saved: the answer (200) is the entry as it would be saved (`dry_run: true`, and `already_recorded` when the reference is already there). |
| `POST` | `/transactions/batch` | Record up to 50 transactions as one: all are saved or none. An entry whose `source` and `external_id` are already recorded with the same date and rows is skipped (status `already_recorded`), so a batch can be sent again safely. Any problem refuses the whole batch (400) naming the entries at fault. With `dry_run=true` nothing is saved and the answer (200) shows what would be. |
| `GET` | `/transactions/payees` | Who you have paid or been paid by, most used first (the opening-balance entries are left out). |
| `GET` | `/transactions/payee-defaults` | How payees are usually booked, most used first: the accounts of the newest entry with one account on each side (so a repeat can be filled in), and the other routes seen. `payee` narrows to those that match what is typed. |
| `GET` | `/transactions/payee-suggestions` | The Add screen's chips: names of people you pay that match `payee` (most paid first, six at most), or after an `@` your people (`people`, with ids); `only=people` offers people only. Names only, never accounts. |
| `GET` | `/transactions/{transaction_id}` | One transaction with its postings. |
| `GET` | `/transactions/` | Newest first. `text` matches the payee, the note or the name of an account used; `kind` is told by the accounts used; `payee` is exact; `source` and `external_id` find the entry a source's reference stands for; `tag` finds the entries that carry that tag (every entry reads back its `tags`; create and update take `tags`). |
| `PATCH` | `/transactions/{transaction_id}` | Change a transaction; only the fields sent change (`related_id: null` removes the link; `source`, `external_id` and `source_url` can be set or cleared with null). With `dry_run=true` every check runs but nothing is saved: the answer is the entry as it would read afterwards. |
| `DELETE` | `/transactions/{transaction_id}` | Delete a transaction for good (finode keeps no history). With `dry_run=true` nothing is deleted: the answer (200) is the entry that would go. |
| `GET` | `/transactions/{transaction_id}/related` | The entries that are related to this one (refunds, reversals), oldest first. |

## Entries

What the finode app's Add screen saves: the entry as the person chose it, rows naming an account, a category or a person.
The server decides what that records (`services/entry.py`). `/transactions` stays the
ledger's own, line by line, for scripts and tools.

| Method | Path | What it does |
|---|---|---|
| `POST` | `/entries` | Record an entry: `kind`, `date`, `payee`, `comment`, `tags`, `related_id`, `payee_contact` (a person named after `@`: a gift, nothing owed) and `rows` (`choice`, `side`, `amount`, `category_id` for a payment into a loan or fund, `posted_on`). A category posts on Expenses or Income with it; a person on a transfer is a loan or a borrowing, paying back what is owed first (`recorded: transfer`). With `total` and `share` (and no rows) it records a bill (`share.kind: expense`: `category_id`, `account_id` you paid from, `method` `equal`/`exact`/`percentage`/`shares`, `self_value`, `self_paid` (blank: whatever the others did not pay), `people` with `contact_id`, `value`, `paid`) or an income (`share.kind: income`: `category_id`, `account_id` it was paid into, `people` with `theirs` and `received`) shared with people (`recorded: expense-shared` / `income-shared`). 400 with the reason when refused, 404 for a person, account or entry that is not the caller's, 409 for a clash with what was already done (a bill something was paid back against). |
| `PUT` | `/entries/{transaction_id}` | Change an entry into what the form now says (rows, or a `share`), releasing what it was first (a loan, a gift, a shared bill or income), all of it or nothing. Without a `date` it keeps its own. |

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
| `POST` | `/recurring/form` | Create a rule from the recurring form's rows, the Add screen's (`choice`: an account or a category; `side`, `amount`, `category_id`; never `posted_on`), with `payee`, `comment`, `tags`, `frequency`, `every`, `start_date` and `end_date`. One account on each side with the same amount is saved as a plain rule, anything else as a split; a start date in the past is recorded straight away. |
| `PUT` | `/recurring/{recurring_id}/form` | Replace a rule with what the recurring form's rows say, as `POST /recurring/form`; it continues after the last recorded or skipped day. |

## Budget

| Method | Path | What it does |
|---|---|---|
| `GET` | `/budget/` | The month's budget (the current month by default): what is left to assign and each category's figures. |
| `GET` | `/todo/` | What needs a decision now: payments no category took, accounts left out of the budget, failing recurring rules, card bills due within 5 days or overdue (`card_bills`), and a count. |
| `GET` | `/budget/coming-up` | What is coming up after today, to the end of this month (or to `through`, at most a year ahead): entries dated ahead and what recurring rules will record, those that touch an account of the budget, soonest first. |
| `PUT` | `/budget/categories/{category_id}` | Set how much of the month a spending category gets; 0 removes it. |
| `POST` | `/budget/move` | Move assigned money from one category to another (at most what is available); Ready to assign does not change. |
| `POST` | `/budget/copy` | Assign a month what each category got the month before, where nothing is assigned yet (nothing is overwritten). |

## Reports

| Method | Path | What it does |
|---|---|---|
| `GET` | `/reports/trial-balance` | Every account's debits and credits, plus a check that the books are sound. |
| `GET` | `/reports/summary` | `cash_on_hand` now (the four types' balances, Credit Cards taken off), plus for a period (the current month so far by default) `income`, `expenses` (the Expenses account) and `spent` (what the budget calls spending, by category), and `net_income`. |
| `GET` | `/reports/breakdown` | Where the money went (or came from) in a period, by category. It is what the money was for, as the budget counts it (by category). |

## Profile

| Method | Path | What it does |
|---|---|---|
| `GET` | `/profile/` | Your name, the currency (`default_currency`) and the order of the four account types (`account_type_order`). |
| `PATCH` | `/profile/` | Change any of them; `account_type_order` must name each of the four types once. |
| `GET` | `/profile/currencies` | The currencies you can choose for your books (changing it relabels, never converts). |

## Backup, restore, import and export

| Method | Path | What it does |
|---|---|---|
| `GET` | `/export` |  |
| `POST` | `/import` |  |
| `GET` | `/backup` | A complete backup: settings, accounts, transactions, recurring rules and the budget. |
| `POST` | `/restore` | Restore a backup into an empty ledger, all or nothing (`dry_run` shows what would happen). |
| `GET` | `/data-options` | What the data page offers: `can_import`, `can_restore` (both need empty books), `confirm_word` (what Erase and Delete ask you to type), `can_delete_login`. Signed in to the finode app only. |
| `POST` | `/erase` | Erase my books: everything you recorded goes, the profile and sign-in stay. `confirm` must be your email (or `DELETE`); signed in to the finode app only, never a bearer token. |
| `POST` | `/delete-account` | Delete my account: everything, then the sign-in (503 when the server cannot remove logins). Same `confirm` and the same rule; clears the session cookies. |

## Views

What one screen of the finode app shows, in one call. A view is built by the server's own services
(`services/transaction_rows.py` and the `*_view.py` modules), so the app formats nothing the server already works out (a
row's name and second line, which way the money went, a month's totals); `backend/tests/guards/test_query_counts.py` holds each under a
ceiling. Every row of entries (Transactions, upcoming, an account's entries, Coming up), every Budgets line, every
Categories row and every category option in the pickers carries `icon`, the icon it leads with (`services/row_icon.py`;
a category's own entries carry none).
Add a view only for a screen that would otherwise need several calls or would have to repeat a rule of the server.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/views/home` | Home for a month (`month` as `YYYY-MM`, never ahead): the budget at a glance (`left`, `spent`, `assigned`, `carried`, `of`, `percent` spent, `pace` through the month), the month's `spent` for someone with no budget, and the first steps (`key` account, spend or budget) while some are left. The month's entries come from `/views/transactions` (8 first, then 10 at a time). |
| `GET` | `/views/transactions` | A page of one month's entries for the Transactions screen (`month` as `YYYY-MM`, never ahead; `account`, `category`, `merchant`, `tag`, `q`, `kind`; `offset`, `limit` up to 100). Newest first up to today; a day is never split between pages, so the next page starts at `offset + len(rows)`. Each row has its `title`, `sub`, `amount`, `kind` and markers. With an account, category, merchant or tag filter, `summary` adds up all it matches; on the first page of the current month, `upcoming` lists what is dated ahead. A filter that does not parse answers `error`. |
| `GET` | `/views/transaction-filters` | The Filter sheet's choices: accounts (no Expenses or Income), categories with their parent, payees most used first. |
| `GET` | `/views/entry-form` | Where the Add screen starts and what its pickers offer. `transaction_id` edits an entry; otherwise blank, or from an `account` or a `category`, a `repeat` (dated today), `related` to an entry, `pay` a card with `amount`, `move` (`lend`, `borrow`, `settle`) money `with` a person, or `mode=split` to share a bill `with` a person. Answers the `kind`, `date`, `total`, payee and note, tags, `related`, the rows of each side (`choice`: an account, a category or a person; `amount`, `posted_on`), `mode` (`split`: a bill or income shared with people), the active `people`, the starting `expense_share` and `income_share`, `person_page` (an entry their page looks after), the picker `groups` (one per account type in the person's order, with balance and budget flag; People; Income and Expenses categories), what a new account can be (`account_types`: `key`, `name`, `icon`, `root`). An account option's `icon` is its type's. |
| `POST` | `/views/entry-share-preview` | What the Split would do, as typed so far, with nothing saved: `total`, `date`, `payee` and the `share` as `/entries` takes it. Answers `kind` and the `expense` preview (each share, what is owed, what is unpaid) or the `income` one. 400 with the reason while it cannot be saved yet, 404 for a person, account or category that is not the caller's. |
| `GET` | `/views/related-entries` | Earlier entries a new one can be related to: the newest 30 up to today, narrowed by `q`, without `exclude` and the opening balances. |
| `GET` | `/views/accounts` | The Accounts page: `account_count`, the `pinned` accounts, and `kinds` (a list of accounts per type, in the person's order: `type`, `name`, `icon`) with `total`, `owed`, `open_count`, `all_closed` and `add_url` (`/accounts/new?type=…`). Each account (`cards`, a name kept from when they were drawn as cards) has its type's `icon`, its balance, `closed`, `pinned` and its one quiet `note` (`overdue` / `due` on a day, `soon` when near; `empty`: no entries yet; `stale`: none since a day). Closed accounts are listed too (`has_closed`), for Load more. |
| `GET` | `/views/accounts/{account_id}` | An account's (or a root's) own page: its type's `icon` (null for Opening Balances), balance, the `sub` line, `badge`, a card's `bill` (or `can_set_days`), a group's open accounts as `cards`, `direct`, what is dated ahead (`upcoming`, `upcoming_total`, `balance_after`), the menu's flags (`can_pin`, `can_edit`, `postable`, `has_children`), and its `entries` newest first with the running balance and `inflow`, a chunk at a time (`offset` = the previous chunk's `next_offset`, while `has_more`). |
| `GET` | `/views/categories` | The Categories page for a `month` (`YYYY-MM`; this month for anything else, never one that has not started) and a `tab` (`expense` or `income`): `grand`, and `rows` biggest first, each a category with its `icon`, its `total` and its `share` of the month. |
| `GET` | `/views/categories/{category_id}` | A category's own page for a `month`: `total`, `built_in`, `closed_on`, `can_delete`, and its `entries` newest first. |
| `GET` | `/views/account-form` | Where the account form starts: `account_id` edits one the person made (it keeps its type: `types` is empty); otherwise a new account, opened for a `type` or not. Answers the name, `details`, `balance`, `type`, the four `types` in the person's order (`key`, `name`, `icon`), a card's days and rounding. 404 for an account that is not the person's or not theirs to edit. |
| `GET` | `/views/category-form` | Where the category form starts: `category_id` edits one; otherwise a new one (`root` = `expense` / `income`). Answers `kind`, name, `details`, `icon` (none for a new one) and `icon_fixed` (the built-in Uncategorised). |
| `GET` | `/views/budget` | The Budgets page for a `month` (this month for anything else): `ready_to_assign` and the `sum` behind it (`money_in_accounts`, `reserved_for_cards`, `available`, `assigned_to_later_months`), `copyable` (what copying last month would assign), `show_intro`, `has_budget_accounts`, `overspent`, `pace` (the current month only), and `rows` biggest budget first: each with `assigned`, `activity`, `available`, how it reads (`of` or none for nothing assigned, `state` `overspent` / `all_spent`, `hint`), its bar (`percent`, `over`). |
| `GET` | `/views/budget-move` | The categories money can move between in a `month` (`name`, `available`), with the `source` it moves from (404 when not one of them). |
| `GET` | `/views/todo` | The to-do bell's sheet: `count`, the card bills due soon or overdue (`name`: the card's own name, `days_to_due`) and the failing rules. |
| `GET` | `/views/coming-up` | Coming up (to the end of this month, or `through`) by day: each row's `title`, `sub` (where the money comes from → goes), `amount`, `income`, and the `recurring_id` of a rule or the `transaction_id` of an entry dated ahead. A day's `total` is set only when every row goes one way and there is more than one. |
| `GET` | `/views/recurring` | The Recurring list (what has fallen due is recorded first): `live` (active, or `error` when the last one could not be recorded) and `stopped` (`paused`, `ended`), each with `title` (the payee, else where the money goes), `amount` (a split: what leaves), `schedule`, `status`, `next_date` and `last_error`. |
| `GET` | `/views/recurring-form` | Where the recurring form starts: blank (an expense, every month, starting today) or a rule's (`recurring_id`) `kind`, `total`, payee, note, tags and `from_rows` / `to_rows` as the Add screen shows them; the pickers' `groups` (no People), `account_types`; `frequency`, `every`, `start_date`, `end_date`, the `frequencies`; and for a rule being edited its `status`, `schedule`, `active`, `next_date`, `last_date`, `skipped_date` and `last_error`. 404 for a rule that is not the caller's. |
| `GET` | `/views/people` | The People list (`show`: `all`, `owed`, `owe`, `archived`; `all` for anything else): `rows` with each person's `net` (above zero they owe you) and quiet line (`sub`: "Nothing yet", "Settled up", "Even · ₹50.00 each way", "Last 2 Nov", "Archived"), `owed_total`, `owe_total`, the two apart (`difference`, unsigned) and what the head says (`label`), `everyone` (anyone not archived), `has_archived` and the `shows`. |
| `GET` | `/views/people/{contact_id}` | A person's page: their details, `receivable`, `payable`, `net`, the `open` amounts (`name`, `date`, `who`: which way, only when they are owed both ways; `settled` of `original` when part is paid; `outstanding`) and the newest 30 entries done with them (`title`, `date`, `sub`, `amount`, `income`), with `more_activity`. |
| `GET` | `/views/people/{contact_id}/entries/{transaction_id}` | One entry done with a person as its sheet shows it: `title`, `date`, `amount`, the `notes` under it, `can_edit` (an opening balance) and `can_reverse` (all but an evened-out entry). 404 for an entry that is not theirs. |
| `GET` | `/views/opening-form` | Where the opening balance form starts for a `contact_id`: blank (they owe you, today) or their opening balance `transaction_id` (`direction`, `amount`, `date`, `description`) with what was already `paid` back. 404 for a person or entry that is not the caller's, or an entry that is not this person's opening balance. |
| `GET` | `/views/transactions/{transaction_id}` | One entry as its details sheet shows it: the row, the From and To labels and lines (an amount each, `posted_on` when it differs), note, tags, what it is related to and what is related to it, the person it was made through, its source and the assistant that added or changed it. |

## Adding a route

See [Conventions and how-tos](conventions.md): a handler in `backend/finode/routers/`, a schema in `backend/finode/schemas/`, a test, the classification in the isolation audit, and a row here (this table is the list of what exists: regenerate it from `app.routes` when routes change).

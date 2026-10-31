# Why it is built this way

The decisions that look odd until you know the reason. Each entry says what was decided, why, and what it costs. Where the reason is inferred from the code and its history rather than written down by the owner at the time, it says so with *(inferred)*.

## Balances and the budget are derived, never stored

**Decision.** No balance, no "available", no "Ready to assign" is a column. They are computed from postings and the plan.
**Why.** Editing, deleting or restoring a transaction can never leave a stored number stale or wrong. There is one source of truth, and `trial_balance` can re-check it.
**Cost.** Pages must compute from many postings. This is why queries are bulk (one query for all postings, not one per account) and why `tests/test_query_counts.py` exists.

## One currency per person

**Decision.** `profiles.currency` labels every amount. There are no conversions, prices, shares or coins; the `commodities` and `prices` tables were dropped.
**Why (inferred).** The goal is a small, correct, fast core. Multi-currency and own assets multiply the bookkeeping rules (what is a balanced transaction across currencies?) for little benefit to the intended users.
**Cost.** Changing the currency relabels, it does not convert. The migration that did this cannot be undone; restore a backup instead. Importing a file in another currency is refused with a pointer to Settings.

## Accounts go two levels deep, for everybody

**Decision.** `Expenses › Food › Groceries` is the deepest there is (`MAX_ACCOUNT_DEPTH = 2`). It is not a setting.
**Why (inferred).** Deep trees make every list, picker and budget screen harder to read, especially on a phone. Templates and the budget only ever nest a group once, which keeps the UI simple. (An earlier version had a per-person depth limit; it was removed.)
**Cost.** People who want finer detail use notes or more categories.

## Categories are labels, not accounts (2026-10-31)

**Decision.** The books are pure: an expense debits the root `Expenses` account and an income credits `Income`; the line carries a budget category (`postings.category_id`). Nothing is made under Expenses or Income, and there is no "books accounts" feature. This replaced "a category is an Expenses or Income account" (and the interim pairing of each category with an account of the same id).
**Why.** The pairing left ghost accounts (`Expenses:EMI:Loans`) with a zero balance next to transactions, and two trees to keep in step. The budget layer already stood on its own; the books only need one place for spending to land. Category ids equal the old account ids, so links, API clients and exports keep working, and the journal export still writes `Expenses:Food:Groceries`.

## Postings have positive amounts and a side

**Decision.** `amount > 0` and `side` is `DEBIT` or `CREDIT`, enforced by database `CHECK`s.
**Why.** There is no ambiguity about direction, no negative-amount tricks, and the database itself refuses garbage even if a bug slipped past the service.

## The transaction service is the only writer

**Decision.** The web form, the JSON API, imports, recurring rules and assistants all create transactions through `TransactionService`.
**Why.** Balancing, ownership of accounts, closed accounts and limits then exist once. The exceptions (imports and restores fill an empty ledger through repositories) are documented and tested.

## History is append-only and has no foreign key

**Decision.** `transaction_history` and `account_deletions` only ever get new rows.
**Why.** A deleted transaction's trace survives it, which is what makes *Recently deleted* possible with no extra storage. Restoring recreates the entry with its old id.

## The budget sits on top of the ledger

**Decision.** The ledger knows nothing about budgeting. The budget stores only the plan, the targets and an `on_budget` flag.
**Why.** The ledger stays correct and simple whatever the budget does, and the budget can never corrupt it.
**Cost.** The Budget counts only what budget money paid, while the reports (Categories, breakdown, overview) count every posting to an expense account. They agree on an EMI (a payment into a loan with a payment category is spending in that category everywhere), and differ only where that is the point: interest the lender charges to a loan is an expense in the reports but touches no budget account, so it is not in the Budget.

## The session remembers repeated reads

**Decision.** `repositories/cache.py` keeps the account list, postings, profile and budget targets for the length of one session, and forgets on every write.
**Why.** Services are written independently, so one page asked for the same accounts and postings four times; at 15 ms a query that was most of the page's time. Remembering is safe because every write path passes through the session (flush, commit, rollback, any non-SELECT), and the memory is not used while the session holds unwritten changes.
**Cost.** Cached lists are shared objects (copy before sorting), and the test suite has to forget between requests to imitate one session per request.

## An overspent category starts the next month at zero

**Decision.** The deficit is taken out of Ready to assign from then on (the YNAB way), instead of the category carrying a negative.
**Why.** The money was spent from real cash, so the shortfall must come out of what is unassigned. A negative carry would hide it.

## Budgeting starts with the first month anything was assigned

**Why.** Cash is the balance *now*; past spending already left it. Counting earlier spending as overspending would deduct it twice.

## Entries dated in the future are not history

**Decision.** Home's Transactions list and the Transactions page show only entries up to today. Future entries sit in one collapsed "upcoming" card, on the Transactions page and on account pages.
**Why.** People enter EMI schedules and bills ahead of time; mixing them into the recent list buried what actually happened. Balances also count only up to today, so the list and the numbers agree.

## Server-rendered HTML with htmx, no JavaScript build

**Decision.** Jinja2 templates, vendored htmx, one `app.js`.
**Why (inferred).** One developer, a small app, and no build pipeline to maintain. Pages work without scripts where they can. (This is the documented intent; the project guidance says not to add a build step.)

## A complete JSON API next to the web app and MCP

**Decision.** The JSON API was once cut down to a small core; on 2026-10-25 the owner decided to keep it for good and asked for it to cover everything the application does (reopening, registers, restoring deleted things, history, related entries, moving and copying budget money, groups, goals, reports). It leaves out only sign-in, token management and the two destructive account actions; see [The JSON API](api.md).
**Why.** It will be useful in future (scripts, other clients). The cost is more routes to secure, so each is covered by the isolation audit and a parity test, and the web app and assistants still call the services directly.

## Supabase for identity, finode for data

**Decision.** Passwords, sessions and the OAuth server belong to Supabase; the ledger is in the same Postgres. App tokens and OAuth grants are finode's own tables.
**Why (inferred).** Authentication is hard to get right and not what this project is for. Supabase gives sign-in, token refresh and an OAuth 2.1 server for AI connectors.
**Cost.** finode depends on Supabase being up for sign-in. Read/write scope for connectors is stored by finode because Supabase has no such scope.

## Stateless MCP with JSON responses

**Decision.** Any worker can answer any `/mcp` request.
**Why (inferred).** With two or more workers behind a proxy, session affinity would be a failure mode. Tools are plain calls into the services, so they do not need a session.

## Tokens and app tokens are walled off from each other

**Decision.** A personal access token or an OAuth app token only works on `/mcp`; a normal sign-in token is refused there; an app's token is refused by the JSON API and web UI.
**Why.** Connecting an assistant must never hand it the ability to act as a full sign-in (changing the password, minting tokens, deleting the account).

## No Advanced switch (removed 2026-10-24)

**Decision.** There was a switch (`profiles.advanced`) that hid rarely used features. It is gone: the features it hid (budget targets, since removed too, move up/down, the period lock) are removed; closing accounts is always available in the place they belong.
**Why.** With targets gone only two small features were left behind a whole page and a setting. A rarely used feature should live in a menu or a row, not behind a switch.

## Typed columns for settings

**Decision.** A setting is a column on `profiles`, not a JSON blob or Supabase `user_metadata`.
**Why.** A column has a type, a default and a migration. `user_metadata` is writable by users directly and is copied into every token.

## One backup file format, restore only into an empty ledger

**Decision.** The JSON backup restores only into an empty ledger, all or nothing, with new ids.
**Why.** Merging two ledgers safely is a hard problem with little payoff. An empty target means the restore either fully works or changes nothing.

## Amounts use the Indian lakh and crore grouping for INR only

**Decision.** `12,34,567.00` for rupees; thousands grouping for every other currency, even where lakh-style is also used (PKR, BDT), unless asked.
**Why (inferred).** The first users are Indian. Doing it for one currency was cheap and safe; extending it is one line per currency.

## Feature freeze and the MVP scope

The owner froze new features on 2026-10-14 and defined the MVP on 2026-10-18: correct double entry, monthly budgets (future-proofed for weekly and yearly), a minimal web UI, an MCP server, removing unused code, speed, and documentation. Splitting expenses with friends is a good idea explicitly *not* in the MVP. A review of what to keep or cut is planned for about 2026-11-04.

## A reference on the entry, not an idempotency-key table

**Decision.** Retrying a write safely is done with `source` + `external_id` on the transaction (unique per person), not with a separate table of request keys. Recording the same pair with the same date and rows returns the entry already there; with different content it is an error.
**Why.** The reference is also what an assistant needs later to reconcile or find an entry ("the bank message this came from"), so one field serves both. A key table would need expiry and would still not say where an entry came from. (Asked for by the owner as part of making finode friendly to AI assistants, 2026-10-25; plan in `agent-friendly-plan.md`.)
**Cost.** A write without a reference is not protected from being repeated. The assistants' instructions tell them to pass one for anything that comes from outside.

## Budget categories are their own table, a label on each line

**Decision.** The budget plans against `budget_categories` (spending or earning, two levels), not against Expenses accounts. A category is a label on each line of a transaction (`postings.category_id`), so one entry can be split over several categories and a payment into a loan can carry "EMI" without any expense account being made up for it. An Income or Expenses account stands for a category (`accounts.category_id`; by default its own, with the same id), and extra books accounts may feed a category (Interest under EMI).
**Why.** The old design made "ghost" accounts such as `Expenses:EMI:Loans` just to hang a plan on, repeated the loan-payment rule in five places, and mixed what money was for with what the books record. The owner asked for a budgeting layer on top of the books (2026-10-28), flexible for a person who only wants to budget an EMI and for one who wants interest as a real expense.
**Cost.** The books lose the per-account expense view (the journal export recreates it from the labels). A line may name a category in place of an account (`PostingCreate`), which keeps old API clients working.

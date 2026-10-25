# Making finode friendlier to AI assistants: evaluation and plan

Branch: `feature/agent-friendly`. **Status: phases 1 and 2, and 3a (change history) 3b (payee defaults), 3c (statement check) and 3d (tags) done: phase 3 is complete. Phase 4: 4a (the `manage` access level), 4b (account history), 4c (the account tools) and 4d (merge) done: **all four phases are complete**.** Source: a week of real use over MCP, where Claude proposed 14 improvements. This page
checks each against what the code does today, decides, and orders the work. Nothing here is built yet.

## Verdicts at a glance

| # | Suggestion | Verdict | Why |
|---|---|---|---|
| 1 | Source / external id on transactions | **Build** (phase 2) | Real gap. Also gives idempotency (#4). |
| 2 | Stable account ids | **Build** (phase 1) | Ids already exist and `AccountIndex.find` already accepts them; the tools just never print them. |
| 3 | Dry-run for writes | **Build** (phase 2) | `TransactionService.validate` exists (recurring uses it). |
| 4 | Idempotency keys | **Fold into #1** | A unique `(user, source, external_id)` is the key. No separate table. |
| 5 | Account metadata | **Build** (phase 1), small | `details` and the root type exist; `on_budget`, payment category and built-in group key are not in the tool output. |
| 6 | Payee rules | **Partly** (phase 3) | The web's payee chips already derive "payee -> accounts" from history. Expose that read-only; defer stored rules. |
| 7 | Tags, receivables | **Tags: build as #hashtags in the note** (phase 3d). **Receivables: document the account pattern** | No schema, no screen. |
| 8 | Better search | **Build** (phase 1) | Today it filters in Python after loading everything and has no count or sum. |
| 9 | Safer edits, bulk | **Batch: build** (phase 2). **"Replace X with Y": fold into merge** (phase 4) | |
| 10 | Account rename, re-parent, merge, close | **Build behind a new `manage` access level** (phase 4) | Owner: only with the right permissions. |
| 11 | Loan / EMI templates | **Decline** | A split recurring rule or a batch of entries with external ids covers it without a new concept. |
| 12 | Revalue, depreciate, statement check | **Statement check: build** (phase 3). **Revalue: defer. Depreciate: decline** | One currency, no assets of one's own, so depreciation is just an expense entry. |
| 13 | Capabilities / status call | **Build** (phase 1) | Cheap, removes mid-task surprises. |
| 14 | Audit log with diffs | **Transactions: build** (phase 3). **Accounts: defer** | `transaction_history` already stores a snapshot per change; accounts have no history. |

The owner has been removing features for a calm, minimal product (targets, Advanced, quick amounts). So everything
below is **API/MCP-first with at most a quiet line in the web UI**, and nothing adds a screen.

## Phase 1: make what exists visible (no migration) — done

**1a. Ids everywhere (#2).** Add `id` to `list_accounts`, `get_account`, `create_account`, the budget's categories and
each posting in `_transaction`. Keep paths as the label. Document in `INSTRUCTIONS` that an id survives renames and
re-parenting and a path does not. `find()` needs no change.

**1b. Account facts (#5).** `list_accounts` also returns `type` (the root), `on_budget`, `payment_category`, `group`
(the `system_key`), and always `details` (a missing one is `null`, so an assistant can tell "empty" from "not shown").
Let `create_account` take `on_budget` and `payment_category` (the service already does).

**1c. `get_status` (#13).** One read tool: access level (`read` or `read & write`) and the token or app name, the
person's currency, today's date in `FINODE_TIMEZONE`, counts (accounts, transactions), the **last change** (newest
`updated_at` over transactions), the person's limits and what is left of today's new-transaction allowance
(`limits`), and the app version. The tool list already tells the assistant what exists, so do not repeat it.

**1d. Search (#8).** Push filtering into `TransactionRepository.list` (it already takes `text`, `payee`, `account`,
dates) and add amount bounds there. `search_transactions` gains `payee` (exact, capitals aside), `offset`,
`kind`, `external_id` (phase 2), and returns `count` (all matches) and `total`. Define `total` so it is not a
meaningless mix: with `account` it is that account's net change, otherwise the sum of the matching transactions'
totals plus `spent` and `earned` split by the rules the Transactions page uses (`KIND_FILTERS`). Page size stays
capped at 200. Keep `truncated` for compatibility.

## Phase 2: safe writes

**2a. External reference (#1, #4) — done.** Migration adds to `transactions`:
`source` (varchar 40, e.g. `gmail`, `upi`, `bank-sms`), `external_id` (varchar 120) and `source_url` (varchar 500),
all nullable, with a partial unique index on `(user, source, external_id)` where `external_id IS NOT NULL`.
- `TransactionCreate` / `TransactionUpdate` / `TransactionRead` carry them (JSON API and MCP: `record_transaction`,
  `record_split`, `update_transaction`; `search_transactions` and `get_transaction` return and filter by them).
- **Idempotent create:** `TransactionService.create` with an `external_id` that already exists for the same source
  returns the existing entry with `already_recorded: true` and writes nothing. Different content under the same key
  is reported (amount or accounts differ) instead of silently ignored. On the web form there is no field.
- Add them to the history snapshot and `_comparable`, to the backup (`schemas/backup.py`, `tests/test_backup.py`) and
  to the details sheet as one quiet line ("Source: gmail") only when set. A restore maps them as-is.
- Restoring a deleted entry keeps its key; a deleted entry's key is free again only after the deletion is the
  latest event (it already is: the live row is gone).

**2b. Dry run (#3) — done.** `dry_run: bool = False` on `record_transaction`, `record_split`, `update_transaction`,
`delete_transaction`. The service runs the same `validate` / resolve path with no flush, so every rule (limits,
closed accounts, direction, decimals) applies, and returns the transaction it would produce, plus the duplicate
check from 2a (`would_duplicate: <id>`). JSON API: `?dry_run=true`, as import does. Dry runs are allowed on **read-only** connections (decided: they change nothing, and an assistant can prepare a
confirmation before the person grants write access).

**2c. Batch (#9) — done.** `record_transactions(items: list, dry_run=False)` for up to 50 entries, **all or nothing in one
database transaction**, each item shaped like `record_split` (with `external_id`). Counts once toward limits per
entry, not once per call. One approval for the person. The result lists each entry's id or the item number and the
reason it failed. This also covers EMI schedules (#11): one item per instalment with `external_id="emi-2026-11"`.

## Phase 3: knowledge and trust

**3a. Change history (#14) — done.** `get_transaction_history(transaction_id)` returns the snapshots from
`transaction_history` as a list of changes: who (`created_via` / `updated_via`, so web, API, `mcp:<name>`), when, and a
field-level diff computed between consecutive snapshots (date, payee, note, postings by account, links). Also
`recent_changes(since, via=None, limit)` across entries, so an assistant can ask "what did I change this week".
Read-only, no schema change. Accounts have no history table; see phase 4.

**3b. Payee defaults (#6, derived) — done.** `payee_defaults(payee)` returns how that payee was booked, from the same logic
as `payee_habits` (move it out of `routers/web/transactions.py` into a service so both use it): the newest
one-account-each-side entry, plus a count and the other accounts seen. Nothing stored, so nothing to go stale.
Stored rules are deferred until the owner wants a person to edit them in the app.

**3c. Statement check (#12) — done.** `check_balance(account, statement_balance, as_of)` returns the book balance at the
date, the difference, and the entries from the last N days so the gap can be found. Read-only. Revalue is not built:
finode already posts a balance change against Opening Balances when an account's balance is edited, and a
valuation in a one-currency ledger is rare enough to wait for a real need.

## Phase 4: account management and permissions (decided)

Order: **4a** the access level (done), **4b** account history (done, origin on `AccountRepository`), **4c** `update_account`, `close_account`, `reopen_account`, **4d** merge (done).

Owner's answers: assistants may manage accounts **only with the right permissions**; tags are wanted, as #hashtags;
dry runs are allowed on read-only connections.

- **A third access level (#10).** Today a token or app grant is `read` or `write`. Add `manage`: read & write plus
  changing accounts. `write` keeps today's behaviour (create accounts, never edit), so nobody gains power by an
  upgrade. Touches `api_tokens.scope` and `oauth_grants.scope` (values only, check the column type and any CHECK in a
  migration), `partials/access.html` (a third `level` card in plain words), the token form, the consent page
  (`allow-manage`), the connections list ("Allow changes" / "Make read only" gain "Allow account changes"),
  `transport.py` (the server per scope) and `_refused` (the message names the level that is needed).
- **Tools on `manage` tokens:** `update_account` (rename, details, re-parent, budget flag, payment category),
  `close_account`, `reopen_account`. Never delete. All service rules apply (depth, cycles, fixed groups, unique names).
  `write` and `read` connections get the tools listed but refusing, like the write tools do today.
- **`merge_accounts(from, into)`, also `manage`:** moves postings, plan rows, recurring rules and payment-category
  links, then closes the source. New service operation: tests, the fuzz test and the isolation audit come with it.
- **`account_history`:** append-only, written by every account change from any path (like `account_deletions`), so an
  assistant's rename is recorded with who did it. Read through `recent_changes`.
- **Receivables:** no feature; document `Assets:Owed to me:<Person>` and a transfer to settle in `INSTRUCTIONS`.
- Still deferred until missed: stored payee rules, revalue.

## Tags as #hashtags (decided; added to phase 3)

**3d. Tags (#7) — done.** A tag is a `#word` in a transaction's note (`#reimbursable`, `#goa-trip`). Nothing new is stored:
the note is the one place, so tags work the same on the web form, the API, imports, backups and for assistants.
- A small parser (`app/tags.py`): `#` followed by letters, digits, `-` or `_`, case-insensitive, at the start of the
  note or after a space; at most 30 characters; `#1` alone or a colour like `#fff` inside text is the price of the
  simple rule and is accepted.
- Reading: `search_transactions` gains `tag`, `list_tags` returns each tag with its count and last use (one pass over
  notes). The JSON API gets `tag` on the list and `GET /api/transactions/tags`. The Transactions page's Filter sheet
  can gain a Tag row later, only if the owner asks.
- Writing: assistants add a tag by writing it into the note (`update_transaction`, `record_*`); `INSTRUCTIONS` says
  so and to keep the person's own words.
- If tags later need rename or a limit on notes' length, move them to a `transaction_tags` table then; the parser makes
  that migration a backfill.

## Cross-cutting rules for every item

- Each new MCP tool gets an annotation (`READ`, `WRITE`, `IDEMPOTENT_WRITE`, `DESTRUCTIVE`), a `_refused` twin for
  read-only tokens (except dry runs, if approved), and a line in `INSTRUCTIONS`.
- **Parity:** anything with a `/api` shape needs the route, a test in `tests/test_api_parity.py` and a row in
  `docs/developer/api.md`. The MCP-only ones (status, history, payee defaults) stay MCP-only, which the API doc says.
- Migrations: one per phase that changes the schema (only 2a), a downgrade, and the migration test.
- Tests: MCP tests with `tests/mcputil.py`; `tests/test_isolation.py` (a new route or parameter must be classified;
  other people's keys must not collide: the unique index is per `user`); backup round trip; `trial_balance().balanced`
  after every new write path; `tests/test_query_counts.py` ceilings for search and status.
- Docs: update `CLAUDE.md` (MCP section), `docs/developer/api.md`, `docs/guide` (Assistants page: what the keys and
  dry runs mean in plain words) and add a `decisions.md` entry for "references, not a separate idempotency table".

## Order of work and size

1. Phase 1 (1a, 1b, 1c, 1d): about a day, no migration. Ship first; it is all read-side and low risk.
2. Phase 2a, then 2b, then 2c: 2a is the only migration and the riskiest (backup, history, unique index on both
   SQLite and Postgres); 2b and 2c build on its service changes.
3. Phase 3: independent, small, any order.
4. Phase 4: the access level first (it is a prerequisite for the tools), then the tools, then merge.

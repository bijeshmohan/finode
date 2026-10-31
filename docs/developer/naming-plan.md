# Naming cleanup: plan

Branch `feature/naming-cleanup`. Agreed with the owner 2026-10-31: **everything in one go** (database, code, JSON API, URL
parameters, assistants' output) and **the industry convention** for keys.

## Why

The tables grew bespoke key codes (`aid`, `tid`, `pid`, `bcid`, `bid`, `gid`, `gaid`, `rid`, `rpid`, `hid`, `did`, `tkid`,
`tgid`). A foreign key does not read like the key it points at (`account_id` -> `aid`), `gid` means two things (a goal and an
OAuth grant, which is why the isolation audit says `goal_id`), and every table's owner column is `user`, a reserved word in
Postgres. Each new table adds to the cost, and the FastAPI Cloud move is a natural moment to pay it.

## The rules

1. **A table's primary key is `id`.** (`account.id`, `transaction.id`; JSON `{"id": ...}`.)
2. **A column that points at another table is `<entity>_id`**: `account_id`, `transaction_id`, `category_id`, `parent_id`,
   `recurring_id`, `related_id`, `from_account_id`, `to_account_id`, `user_id`.
3. **Every id in a URL, a form or a tool is named for what it is**: `{account_id}`, `{transaction_id}`, `{category_id}`,
   `{recurring_id}`, `{goal_id}`, `{grant_id}` (was `gid`), `{token_id}`, `{tag_id}`, `{history_id}`, `{deletion_id}`.
4. **Python variables follow the column**: `account_id`, never `aid`. A bare `id` is only for the object's own key.

## Table by table

| Table | Key | Other columns renamed |
|---|---|---|
| `accounts` | `aid` -> `id` | `user` -> `user_id` |
| `transactions` | `tid` -> `id` | `user` -> `user_id` |
| `postings` | `pid` -> `id` | `user` -> `user_id`, `transaction` -> `transaction_id`, `account` -> `account_id` |
| `budget_categories` | `bcid` -> `id` | `user` -> `user_id` |
| `budget_allocations` | `bid` -> `id` | `user` -> `user_id` |
| `goals` | `gid` -> `id` | `user` -> `user_id` |
| `goal_allocations` | `gaid` -> `id` | `user` -> `user_id` |
| `recurring_transactions` | `rid` -> `id` | `user` -> `user_id`, `from_account` -> `from_account_id`, `to_account` -> `to_account_id` |
| `recurring_postings` | `rpid` -> `id` | `user` -> `user_id`, `rid` -> `recurring_id`, `account` -> `account_id` |
| `tags` | `tgid` -> `id` | `user` -> `user_id` |
| `transaction_tags` | (`transaction_id`, `tag_id`) | `user` -> `user_id` |
| `transaction_history`, `account_history` | `hid` -> `id` | `user` -> `user_id` |
| `account_deletions` | `did` -> `id` | `user` -> `user_id` |
| `api_tokens` | `tkid` -> `id` | `user` -> `user_id` |
| `oauth_grants` | `gid` -> `id` | `user` -> `user_id` |
| `profiles` | `user` -> `user_id` (also the key) | |

Index, unique-index and foreign-key names are renamed with their columns (the migration lists them, the autogenerate diff
must come out empty afterwards). Pure renames, so the migration **can be undone**, unlike the pure-books one.

## What stays as it is (on purpose)

- **Stored logs.** The JSON `snapshot` in `transaction_history`, `account_history` and `account_deletions` keeps its keys
  (`account`, `category`, `recurring_id`...). They are readable words, not codes, and the logs are append-only: rewriting
  them would break the rule that history is never edited. The readers already tolerate the shape.
- **Tool arguments that take a name.** The assistants' `from_account`, `to_account` take an account path or name, not an id.
  Tool *output* that prints ids follows the rules above.
- **The backup file** (`version` 5) already uses `id` / `account` / `category` inside the file; whether its reference keys
  become `account_id` / `category_id` (version 6, the old versions upgraded on read as today) is decided in phase 4.

## Phases (each ends green: unit tests, ruff, format, pyrefly; browsers at the end of 3 and 5)

1. **`user` -> `user_id`** in the models, repositories, services, the erase walk, the audit. Type-checker guided.
2. **Primary keys -> `id`, foreign keys -> `<entity>_id`** in the models, repositories, services, MCP, web routers.
3. **Schemas, URL parameters, forms, templates, `app.js` and the JSON API** (`aid` -> `id` in responses, `{aid}` ->
   `{account_id}`, `gid` -> `grant_id`). `docs/developer/api.md` and the isolation audit's id names follow.
4. **Assistants' output and the backup keys** (decision above).
5. **The migration**, written last and proved three ways: autogenerate shows no difference from the models; upgrade then
   downgrade then upgrade on SQLite in the test suite; rehearsal on a restored production dump (row counts and every
   balance equal before and after; the app boots on it and `/login` answers).
6. **Docs and CLAUDE.md**, memory, then deploy with a backup first.

## Risks and how they are handled

- **A missed rename fails loudly** (a type error, a 422, a test), because code and tests are driven from the type checker and
  the isolation audit; a silent miss would only be a dict key or a template attribute, so phase 3 greps templates and
  `app.js` for every old code.
- **API clients break.** Only the owner's own use and connected assistants exist today; the assistants read ids from tool
  output, which changes with the code. No compatibility layer is kept (a layer would be the debt this removes).
- **Deploy order.** The migration and the new code ship together (`migrate` runs before the app starts).

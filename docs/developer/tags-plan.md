# Plan: tags apart from notes

**Status: built (2026-10-26), see "Tags are their own thing" in `CLAUDE.md` and the ledger page for what exists.** Decisions taken: assistants with read & write may tag entries; rename, merge and delete need the "manage" level; the ledger export writes a `; tags: a, b` comment line; renames, merges and deletes are not undoable; limits 200 tags per person and 10 per entry. One addition to the plan: a tag that is part of a sentence ("paid through #UPI") keeps its word in the note when it is moved out. The mock-ups are in the owner's artifacts ("Tags Apart From Notes"). Today a tag is a `#word` written inside an entry's note (`app/tags.py`); nothing is stored for it. This plan makes a tag its own thing on an entry, chosen from a list, and gives the note back to being plain words.

## 1. Why

| Today (a #word in the note) | After |
|---|---|
| The sentence and the tag are tangled; an assistant that edits a note can overwrite the tags | The note is exactly what was written; tags are changed on their own |
| A typo (`#goatrip`) is a different tag, fixed by editing every entry | One tag, one spelling; rename and merge are one action |
| Finding the tags scans every note that has a `#` | A real table with counts, joins and indexes |
| The Add screen needs a popover over the other fields (which took two fixes for phones) | A Tags sheet, the same searchable-list pattern as Filter and Related |
| Nothing can say "this tag exists" without an entry | The tag list is data: management, counts, limits, export |

Non-goals: tag colours or nesting, per-tag budgets or reports, tags on accounts, a tag filter that combines several tags (the mock-ups keep one tag at a time, as today).

## 2. The data

Two tables, both per person (`user` column, so erasing the books, the isolation audit and backups pick them up like every table):

- `tags`: `tgid` (uuid), `user`, `name` (lower case, 1 to 30 characters: letters, digits, `-`, `_`; starts and ends with a letter or digit; at least one letter), `created`. Unique on `(user, name)`.
- `transaction_tags`: `user`, `transaction_id` → `transactions.tid` (on delete cascade in the code, as for postings: the repository removes them), `tag_id` → `tags.tgid`. Primary key `(transaction_id, tag_id)`; index on `(user, tag_id)`.

A tag exists only while an entry carries it: removing the last use deletes the row (so there are no stray tags to look after, and "Create" in the sheet writes nothing until the entry is saved).

Considered and rejected:

- **A JSON list on `transactions`** (`tags: ["goa-trip"]`). Simplest to read, but rename and merge become a rewrite of every entry's JSON, counts and "which entries" need JSON queries that differ between SQLite (tests) and Postgres, and there is no place for a limit or an index.
- **Postgres arrays.** Not available on the SQLite the tests run on.

Limits (new settings, `0` = none, in `config.py`): `FINODE_MAX_TAGS` (default 200 per person) and a fixed 10 tags per entry.

## 3. Rules

- A tag name is cleaned as typed or sent: leading `#` and spaces removed, lower case. `#EMI`, `emi` and ` Emi ` are one tag (this stays true).
- An entry has each tag once, at most 10.
- The note keeps any `#word` as ordinary text; it is no longer read as a tag. The helper `tags_in` stays only for the migration and for old backups (section 5).
- Rename: to a name that does not exist → the same tag with a new name. To a name that exists → it is a merge.
- Merge: every entry of the first tag gets the second (once); the first tag is deleted.
- Delete: the tag comes off its entries and the row goes; the entries and their notes are untouched.
- Renames, merges and deletes are written to the entries' history as ordinary changes (see 4.5).

## 4. Changes, layer by layer

### 4.1 Models and migration

- New `models/tag.py` (`Tag`, `TransactionTag`), exported in `models/__init__.py`.
- One Alembic migration, `tags_apart_from_notes`: creates the two tables, then **moves the existing tags**: for every entry whose note has tags (`tags_in`), create the tags (per person, lower case), link them, and take them out of the note (`without_tags`; a note that becomes empty becomes NULL). Tags longer than the limit or beyond 10 per entry are left in the note as text and counted in the migration's output (none today).
- **Downgrade** puts each entry's tags back on the end of its note (` #a #b`) and drops the tables, so the step can be undone.
- Rehearsal before any deploy: restore the latest backup into a scratch Postgres (as done for the last three migrations), upgrade, compare the number of tagged entries before and after, downgrade, upgrade again.
- A backup is taken before the deploy as always. The owner's data has very few tags (the feature is days old), so the risk is small.

### 4.2 Repository and service

- `TransactionRepository`: `tags_for_transactions(tids)` (one query, like `postings_for_transactions`), `set_tags(tid, names)`, tag listing with counts and last day in SQL (`GROUP BY`), `rename_tag`, `merge_tags`, `delete_tag`, orphan clean-up. `list(tag=...)` becomes a join on `transaction_tags` (no scan of notes, and the paging by tag is done in SQL; the Python post-filter `_with_tag` goes).
- `TransactionService`: `create` and `update` take `tags` (a list of names; `None` leaves them, `[]` clears them), validate (names, 10 per entry, the per-person limit) and keep the history. `_to_read` fills `TransactionRead.tags` from the table (the property that parses the note goes). Lists load tags for all rows with one query.
- **Query counts:** Home and Transactions pages gain one query (the tags of the rows shown). `tests/test_query_counts.py` ceilings are raised by one for those pages, with the reason.

### 4.3 Schemas and the JSON API

- `TransactionCreate` / `TransactionUpdate` / `TransactionRead` get `tags: list[str]`.
- `GET /api/tags` (name, uses, last day), `PATCH /api/tags/{name}` (rename; merges when the new name exists), `DELETE /api/tags/{name}`. The existing `GET /api/transactions/tags` is replaced by `GET /api/tags`; the `tag` filter on the list stays.
- Documented in `docs/developer/api.md` (a test keeps it complete); the isolation audit classifies the new routes.

### 4.4 The web app (the mock-ups)

- **Add and Edit:** under the note, chosen tags as chips with ✕ and a dashed "＋ Tags" row (same markup and CSS as "Related transaction"). It opens a `<dialog class="sheet">` with a search field, the person's tags with a tick each and their counts, and "＋ Create “word”" when the search matches nothing; "Done" returns the choice to hidden inputs (`name="tags"`, one per tag). The `#` suggestions popover, its JS and its two phone bugs go away.
- **Rows, details sheet, Filter sheet:** as built last week (tags on the quiet line, a Tags row of links, the Tag list in Filter), reading from the table. The note shows whole.
- **Settings › Your data › Tags** (new row with the count): a page listing tags (uses, last day) with a sheet per tag: Rename, Merge into…, Delete (red). Uses the existing tile, row and sheet parts.
- The recurring-rule form has a note but no tags: rules can carry tags later (out of scope here).

### 4.5 History, restore, Recently deleted

- The history snapshot gets `tags` (names). Restoring a deleted entry recreates its tags by name (creating the tag row if the tag no longer exists), exactly as related links are restored now.
- A rename or merge touches many entries; the entries' history is **not** written for that (one tag action, not N changes); the tag actions are not undoable in the first version (a merge can be rebuilt from a backup). Open decision 3.

### 4.6 Backup, restore, import and export

- **Backup** `version` 3: each transaction gets `tags: [names]`. Version 1 and 2 files are still read. **A file older than version 3 has its notes' `#tags` moved into tags on restore**, by the same function as the migration, so an old backup restores into the new shape.
- Restore creates tags per person with the limits, all or nothing as before; the restore preview counts them.
- **Ledger import/export:** the journal format keeps tags in comments. The first version writes an entry's tags as a trailing comment `; tags: a, b` and reads that comment back on import (other comments stay ignored, as now). A test round-trips it. The exact spelling is open decision 2.
- CSV export gets a `tags` column (seven columns; documented).

### 4.7 Assistants (MCP)

- `record_transaction`, `record_split`, `record_transactions` and `update_transaction` get `tags` (a list; `update_transaction` replaces the entry's tags only when given) and, for races between two assistants, `add_tags` / `remove_tags` on `update_transaction`.
- `list_tags` keeps its shape. `search_transactions(tag=)` keeps working. `get_transaction` already returns `tags`.
- New tools: `rename_tag`, `merge_tags`, `delete_tag`. **Access:** an assistant with read & write may tag entries; rename, merge and delete change many entries at once and need the "manage" level (open decision 1).
- **A note with a `#word` written by an assistant is just text now.** To make the old habit harmless: the instructions and tool descriptions say "tags are a separate field", and a write whose note contains a `#word` answers with a `notice` ("tags are not read from notes; pass them in `tags`"). No magic conversion.
- `INSTRUCTIONS`, `docs/guide/mcp.md` and `docs/architecture/mcp-and-auth.md` are updated; the tool-count assertions in the tests change.

### 4.8 Everything else

- `services/erase.py` already walks every table with a `user` column: nothing to add, but a test proves the tag tables are erased with the books.
- `tests/test_isolation.py`: new routes, and a test that one person cannot attach or see another's tags.
- Docs: user guide (Transactions, MCP), `CLAUDE.md`, `docs/architecture/ledger.md` and `design.md` if a part changes.

## 5. Order of work, each step deployable

1. **Data and service (no screen change).** Models, migration with rehearsal, repository and service, schemas, the JSON API, the rows/sheet/Filter reading from the table, backup version 3 with the old-file conversion, history. The note becomes whole; the Add screen's `#` popover is removed and replaced in step 2, so in between tags are changed only through the API and assistants. To avoid that gap, steps 1 and 2 are **deployed together** (one release).
2. **Add and Edit screens.** The Tags sheet and chips, browser tests with a finger on WebKit and Chromium (the lesson from the two fixes).
3. **Settings › Tags.** List, rename, merge, delete.
4. **Assistants.** The `tags` fields, the three tools, the notice, the docs.
5. **Import/export of tags.**

Effort: about two days of work, most of it in step 1 and the tests; the migration rehearsal on real data is the gate before step 1 goes live.

## 6. Risks

| Risk | Answer |
|---|---|
| The migration mangles a note | Rehearsed on a copy of real data; the note without tags is compared with the note before for every entry in the rehearsal; a backup is taken first; the downgrade is tested |
| An assistant keeps writing `#words` into notes | The notice in the reply, the updated instructions, and the owner can ask it to retry with `tags` |
| One more query per list page | Counted and accepted (about 16 ms); the tags are loaded once per page, never per row |
| The Tags sheet is fiddlier than typing | It is the Filter sheet's list again, and has its own phone tests; the Create row makes a new tag two taps |
| An old backup restores with `#words` left in notes | Files before version 3 are converted on restore, by the migration's function, tested with a fixture |
| Tags lost on a delete and restore | The snapshot carries the tag names (4.5), tested |

## 7. Decisions needed

1. Rename, merge and delete for assistants: the "manage" level (suggested) or plain read & write?
2. The ledger-format spelling of tags in export (4.6): a trailing `; tags: a, b` comment (suggested) or none in the first version?
3. Should rename, merge and delete be undoable? The suggestion is no in the first version (the history is per entry and a merge is easy to redo by hand).
4. The limits: 200 tags per person and 10 per entry are suggestions.
5. A tag filter that takes several tags at once: later, if wanted.

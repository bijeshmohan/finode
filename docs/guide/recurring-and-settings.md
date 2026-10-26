# Recurring transactions, settings and your data

## Recurring transactions

A recurring transaction is a rule that records itself on a schedule: rent, a salary, a subscription. Open it from **Settings › Your data › Recurring transactions**.

A rule has:

- the accounts and amount (one account on each side, or several for a split, built the same way as in the transaction form),
- a payee, a note and **tags** (the **#** button in the note field, as on New transaction: every entry the rule records gets them),
- how often: **daily, weekly, monthly or yearly**, every N of them,
- a **start date** and an optional **end date**.

The New recurring transaction page is the same page as New transaction (kind, amount, payee, From and To, the note with its **#** button), with one row for how often (*Every 1 month*) and two chips for the dates (*Starts* and *Ends*, which reads *never* until you pick a day; ✕ clears it).

What to know:

- finode records every occurrence that is due, even if you never open the app. It also catches up when you open Home, Transactions or Recurring. Each day is recorded **once**, however many times that happens.
- A monthly rule starting on the 31st falls on the last day of short months.
- **Skip next**: leave one occurrence out (nothing is recorded for it) and carry on. Skipping the last occurrence before the end date ends the rule.
- **Pause** and **Resume**: what falls due while paused is skipped, not made up later.
- Renaming, merging or deleting a tag on the **Tags** page changes the rules that use it too, so a rule never brings an old tag back.
- **Delete** a rule and the transactions it already recorded stay.
- If a rule cannot be recorded (an account was closed, for example), it keeps the reason and retries.
- Entries a rule records are marked *Recurring* in blue, and are not linked back after a restore from *Recently deleted*.

For a fixed set of future payments such as an **EMI schedule**, you can also enter the future-dated transactions directly: they wait in the *upcoming* card until their date.

## Settings

Settings is about how the application works (your name and your data are on Profile).

| Setting | What it does |
|---|---|
| **Preferences › Currency** | the one currency of your ledger. Changing it relabels; nothing is converted |
| **Preferences › Appearance** | match the device, light or dark (kept per browser) |
| **Your data** | backup, export and import, **Recurring transactions**, **Recently deleted** and **AI assistants** (connect Claude or another assistant, see [the MCP guide](mcp.md)) |
| **About** | *Send feedback* (when the installation has an address for it), *About this test*, and *Sign out* (the red row at the end) |

## Profile and your data

There is no separate Profile page: the header of Settings is you (tap it to change your name), and the same page holds **AI assistants** (see [the MCP guide](mcp.md)), **Your data** and sign out.

### Your data

- **Export**: a plain-text ledger file (readable by ledger and hledger) or a CSV for spreadsheets. Always available.
- **Import**: bring in a ledger file. Only possible while you have **no transactions** yet. You see a preview first, and it is all-or-nothing. Anything finode cannot represent (another currency, prices, conversions) is refused with the line number.
- **Full backup**: one JSON file with everything you recorded (settings, accounts, transactions, recurring rules, budget plan and goals). **Restore** puts it back, but only into an empty ledger. Access tokens and connected apps are not included; set those up again.
- **Erase my books**: removes every account, transaction, rule and budget but keeps your profile, tokens and connections. You type your email to confirm.
- **Delete my account**: removes everything including your sign-in (offered only when the installation allows it).

Keep a backup file safe from time to time, especially before experiments.

## If you are running finode yourself

Nightly database dumps, deployment and configuration are described in [Data and operations](../architecture/data-and-ops.md).

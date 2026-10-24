# Transactions

A transaction is money moving from one or more places to one or more places. Every one is recorded in a way that always balances.

## Adding one

Tap **+** (phone) or **New transaction** (wide screen).

1. **Amount**: type it at the top. The amount field cleans itself as you type: only digits, one decimal point and a leading minus are kept, so `42.00.00` cannot happen. On a phone, tap the amount to open the keyboard.
2. **Kind**: **Expense** (the default), **Income** or **Transfer**. The kind only narrows the account lists:
   - Expense: from an account or card, to a category.
   - Income: from an income category, to an account.
   - Transfer: between your own accounts (including paying a card or a loan).
   - Tap the selected kind again to select *none*: every account is offered. Use this for anything unusual.
3. **From** and **To**: pick the accounts. Choose *+ New account…* to create one without leaving the form.
4. **Payee**, **note** and **date** (today by default).
5. **Save**, or **Save & add another** to keep entering.

### Payee chips

Under the payee field, finode suggests the payees you use most. Tapping one fills the payee, the kind and the accounts you used last time for that payee and moves you to the amount. Typing a payee in full does the same quietly. Under the amount, a chip such as **₹597 as last time** puts that payee's last amount in with one tap, and a row of chips builds any amount without opening the keyboard: **+0.01, +0.1, +1, +10** add to whatever is there, the **+ / −** switch turns them into subtractions (₹9.99 is +10, then −0.01), **×2, ×5, ×10** scale it, and the arrow undoes the last tap. Typing in the amount still works and starts over.

### Splitting across accounts

When you need more than one account on a side (a bill paid half by cash and half by card, or a shop receipt with Food and Household), add rows. Each side starts with one row; when you type a different amount in a row, a new row appears with the remainder suggested, until the side adds up to the total. Both sides must add up to the same total. The same account cannot be on both sides of one entry (money cannot move from an account to itself); it can appear on several rows of the same side.

### Repeat

Open a transaction and tap the **Repeat** circle (two overlapping squares) to start a new one pre-filled with the same accounts, payee and note, dated today.

### Related entries

A refund, a reversal or a cash-back belongs with the purchase it follows. Open the original and tap the **Related** circle (a chain link): a new, empty entry opens with a "Related to…" line above Save, and you fill it in as usual. From any form you can also tap **+ Related to an earlier entry** and pick one from a searchable list, which is how to link something you have already recorded (the ✕ on the line takes the link off, on a new entry or when editing).

Both entries show the link in their details sheet: the new one says "Related to" the original, the original lists what is related to it, and tapping either opens the other. A link is only a link: it changes no amounts, balances or budget, and deleting the original simply drops it.

## The Transactions page

**View all** on Home (or the sidebar) opens the full list, grouped by day.

- The **month pill** at the top right (the same place as on Budgets and Categories) picks the month: the arrows go back or forward, and tapping the month opens a month and year picker. Entries dated ahead wait in the *upcoming* card on the current month.
- **Filter** (the word at the right of the line under the title): opens a sheet with **Account**, **Category** and **Merchant**; each opens a searchable list, **Show transactions** applies them (a field left on Any is not sent). What is set shows under the line with a ✕ to remove it, and the line says how many entries match and what they come to when they all go one way ("3 transactions · ₹2,338 spent"). The filters apply to the month in the pill. Recurring transactions and Recently deleted are in Settings › Your data.
- **Tap a row** (on this page, Home, and on an account's or a category's own page) to see its details in a sheet: the accounts (*Paid from* and *Spent on* for an expense), the note (only when there is one), the entries related to it, a quiet line above the buttons when an assistant added it (*Added by Claude*, with a sparkle) or a recurring rule did (*Recurring*; nothing is said for what you entered yourself), the **Edit** button, two round icon buttons (**Repeat** and **Related**, named for screen readers and as a hover tip) and **Delete**.

<img src="img/transaction-sheet.png" alt="A transaction's details sheet with Edit, Repeat, Related and Delete" width="300">
- A month starts with its newest 25 entries (a day is never cut in two); **Show 25 more** at the bottom of the list adds the next ones in place, with how many are left beside it, until the whole month is on the page. **Home** does the same, starting with the newest 8 and adding 10 at a time.

### Upcoming entries

An entry dated in the future (a loan instalment, a bill you entered ahead) is **not history**. It does not appear in the Transactions list on Home, and it does not change balances until its date. On the Transactions page, and on an account's page, all of them sit in **one collapsed card**: *N upcoming · X in all*. Open it for a statement of dates, payees and amounts, soonest first.

## Editing and deleting

Open a row and tap **Edit**. The edit page also shows the entry's history. **Delete** removes it at once and the toast offers **Undo** for a few seconds (the entry also waits in Recently deleted).

If you used **Period lock** (Settings › Advanced), entries on or before the locked day cannot be added, changed or deleted.

### Recently deleted

Deleted by accident? Open **Settings › Your data › Recently deleted** (it also lists accounts and categories): it lists what was deleted, newest first, each with **Restore**. A restored entry comes back with its old details (it is checked again, so a locked period or a closed account will stop it, and tell you why). Only the latest deletion of an entry can be restored, and a restored entry is no longer linked to the recurring rule that made it.

## How amounts look

- Ordinary spending shows no minus sign, so a long list is not a column of signs. Income is `+` and green. Transfers are plain.
- A real negative (an overdrawn account, an overspent category, a debt) keeps its `−` and red.
- In **INR** amounts are grouped the Indian way (`12,34,567.00`), with `₹` in front of large figures. Other currencies are grouped in thousands.
- Text coloured **blue** under a row (*Recurring*, *Added by Claude*) was added automatically.

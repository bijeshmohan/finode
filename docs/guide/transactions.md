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

Under the payee field, finode suggests the payees you use most. Tapping one fills the payee, the kind and the accounts you used last time for that payee and moves you to the amount. Typing a payee in full does the same quietly.

### Splitting across accounts

When you need more than one account on a side (a bill paid half by cash and half by card, or a shop receipt with Food and Household), add rows. Each side starts with one row; when you type a different amount in a row, a new row appears with the remainder suggested, until the side adds up to the total. Both sides must add up to the same total. The same account cannot be on both sides of one entry (money cannot move from an account to itself); it can appear on several rows of the same side.

### Add again

Open a transaction and tap **Add again** to start a new one pre-filled with the same accounts, payee and note, dated today.

## The Transactions page

**View all** on Home (or the sidebar) opens the full list, grouped by day.

- **Search** by payee, note, or the name of any account involved.
- **Kind chips** (Expense, Income, Transfer) filter the list; **More filters** adds account and date filters.
- **Tap a row** to see its details in a sheet: the accounts (*Paid from* and *Spent on* for an expense), the note, who added it (*By the app* for what you entered, or *Recurring* or the assistant's name), and the buttons **Edit**, **Add again** and **Delete**.

<img src="img/transaction-sheet.png" alt="A transaction's details sheet with Edit, Add again and Delete" width="300">
- The list shows 25 entries a page; use *Older →* and *← Newer* at the bottom to move between pages.

### Upcoming entries

An entry dated in the future (a loan instalment, a bill you entered ahead) is **not history**. It does not appear in Recent on Home, and it does not change balances until its date. On the Transactions page, and on an account's page, all of them sit in **one collapsed card**: *N upcoming · X in all*. Open it for a statement of dates, payees and amounts, soonest first.

## Editing and deleting

Open a row and tap **Edit**. The edit page also shows the entry's history. **Delete** asks for confirmation.

If you used **Period lock** (Settings › Advanced), entries on or before the locked day cannot be added, changed or deleted.

### Recently deleted

Deleted by accident? On the Transactions page, tap the **bin** icon: **Recently deleted** lists what was deleted, newest first, each with **Restore**. A restored entry comes back with its old details (it is checked again, so a locked period or a closed account will stop it, and tell you why). Only the latest deletion of an entry can be restored, and a restored entry is no longer linked to the recurring rule that made it.

## How amounts look

- Ordinary spending shows no minus sign, so a long list is not a column of signs. Income is `+` and green. Transfers are plain.
- A real negative (an overdrawn account, an overspent category, a debt) keeps its `−` and red.
- In **INR** amounts are grouped the Indian way (`12,34,567.00`), with `₹` in front of large figures. Other currencies are grouped in thousands.
- Text coloured **blue** under a row (*Recurring*, *Added by Claude*) was added automatically.

# Accounts and categories

## The idea

Money is always *somewhere* and always *for something*. finode keeps both as accounts in one tree:

- **Accounts** are where money is: Assets (bank, cash, wallet, investments) and Liabilities (credit cards, loans). Equity holds the system's *Opening Balances* and is folded away.
- **Categories** are what money is for: Expenses (Food, Rent) and Income (Salary).

Every transaction moves an amount *from* one place *to* another, and the books stay balanced because both sides are recorded. You never have to think about debits and credits to use it.

## Accounts page

**Accounts** has three chips, **Assets**, **Liabilities** and **Equity**, in that order, like Expense and Income on Categories. The chosen one shows its total as a large figure, then its accounts: each group (for example *Bank*) has a heading with its subtotal and its accounts under it; plain accounts share one tile. Things to know:

- Every open account is listed, used or not. Closed ones are tucked behind one **Load more** button at the bottom (they carry a *closed* badge).
- Accounts go **two levels** deep, at most: a group and the accounts in it.

### Add an account

Tap the round **+** (*Add account*) on the Accounts page. The form asks for a **Name**, **Belongs under** (Assets for banks, cash and wallets; Liabilities for cards and loans; or a group you already made), an optional **Current balance** and optional **Notes**. The balance is recorded as an *Opening balance* entry against the system's Opening Balances account, and you will see it in your transactions.

<img src="img/accounts.png" alt="The Accounts page: groups with subtotals, accounts in tiles" width="300">

An account page shows its balance, an **Add transaction** button, a pencil for Edit, a small **i** beside the name when you wrote a description for the account (tap it to read the note), a **…** menu when there is something in it (to add a sub-account, or, with Advanced on, to reorder or close the account), and its transactions (the newest 30, then **Load more**). Entries dated in the future are in one **upcoming** card at the top of that list.

An account that has sub-accounts (such as a *Banks* group) is not posted to itself, so its page shows a **Sub-accounts** list with each balance instead; open one to see its transactions. The **+** beside the heading adds another.

<img src="img/account-page.png" alt="An account page: balance, Add transaction, upcoming card, transactions" width="300">

### Colours and signs on an account's page

- **Green with a `+`** is money that raises an asset account, or a **payment into a card or loan** (it lowers what you owe).
- A **charge on a card** is plain, with no sign; the running balance beside each row shows which way it went.

### Credit cards and loans

A card or loan is a **liability**: its balance is what you owe. Paying the bill is a *transfer* from your bank account to the card. To have the budget count a card's purchases as spending, turn on **Part of the budget** when you add it (or later in its edit page). A card or loan outside the budget can name a **payment category**, chosen in the same form, so an EMI counts as spending in that category.

### Closing and deleting

An account that holds a balance cannot be closed. A closed account keeps its history but disappears from pickers; **Reopen** it any time. Closing is under **Advanced** (see [Settings](recurring-and-settings.md)). An unused account can be deleted for good. Both can be brought back from **Recently deleted** (the bin icon on the Accounts page).

## Categories page

**Categories** shows one month at a time (never a future one; the month pill sits at the right of the title, as on Budget: the arrows go back or forward, and tapping the month lets you pick any past month and year). Pick **Expense** or **Income** (the bin and the round **+** are at the right of the chips). The big figure is the month's total up to today (the whole month for a past one); it has no label, the Expense and Income chips say which it is. Below it is a ranked list, biggest first, each row with its three biggest subcategories and its share of the month (0% for one with nothing in it; every row is the same height). Tap a row to see the category's page: its subcategories and the month's transactions that were posted to that category itself (a subcategory's transactions are on its own page; the big figure still counts everything inside). On a category's page the month pill sits beside the back link; the round **+** on the *Subcategories* heading adds a subcategory and the one on *Transactions* adds a transaction in this category (a category with no subcategories has no such heading: use **…** › *Add subcategory*). Use the arrows on the month pill to move between months.

<img src="img/categories.png" alt="The Categories page: the month, Expense and Income, ranked categories" width="300">

To add one, tap the round **+**. A category can have subcategories one level down (Food › Groceries), no further.

**Deleting a category:** if it has never been used it is removed. If it has history it is *closed* instead: it leaves your lists and pickers but stays in the months where it has amounts. **Restore category** brings it back. Both are under the **…** menu and in **Recently deleted** (the bin icon).

## Notes

Names can be up to 40 characters, must be visible and on one line, cannot contain a colon (`:`), and must differ from the other accounts or categories in the same place (capitals do not count: `Food` and `food` are the same). Dates you can enter run from 1900 to 2999. A category can carry a short note, shown on the Budget.

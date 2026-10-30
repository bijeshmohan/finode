# Budgeting and Budgets

The tab is called **Budgets**. It has two chips: **Spend** (the categories you spend from) and **Save** (your goals).

finode uses **envelope budgeting**: you give every rupee in your budget accounts a job (a category), and you spend from the category. When a category is empty you either move money in from another one or you overspend, and the app shows it.

Budgets are **monthly**.

## The words

| Word | Meaning |
|---|---|
| **Budget accounts** | The bank, cash and card accounts whose money you budget. When you add an account under Assets or Liabilities the form asks **Part of the budget**: it is on by default for a bank or cash account and off for a card or loan (turn it on for a card whose purchases you want counted). You can change it later on the account's edit page. |
| **Tracking accounts** | Accounts outside the budget (say, a long-term investment or a loan). They count in net worth but their money is not yours to assign. |
| **Assigned** | How much you gave a category this month. |
| **Spent** (activity) | What you spent in the category this month, from budget accounts. |
| **Left** (available) | What you can still spend: last month's leftover (if any) + assigned − spent. |
| **Ready to assign** | Money in budget accounts that has no job yet. |

The page opens with one figure: **Ready to assign** (tap the **i** beside it for the sum). Your aim is to bring it to zero: *every ₹ has a job*. *Left to spend* and its bar are on Home, not here.

Tap the **i** beside the figure (on the Budgets page, and on Home's *Left to spend*) to see how it is worked out with your own numbers: for example, money in your accounts, minus what is set aside for card bills, minus what is left in your categories, minus what you assigned to later months.

<img src="img/budget.png" alt="The Budgets page: Ready to assign, and the categories ranked with a bar and a tick for today" width="300">

## A worked example

You have ₹50,000 in your bank account, and no budget yet.

1. Ready to assign: **₹50,000**.
2. You assign Rent ₹20,000, Groceries ₹8,000 and Transport ₹2,000. Ready to assign: **₹20,000**.
3. You spend ₹3,000 on groceries. Groceries shows **₹5,000 left**; Ready to assign is unchanged.
4. Next month, the unspent ₹5,000 stays in Groceries (it carries over), and you assign fresh money on top.

## The warnings

- **Amber "Over-assigned by X"** (under the figure): you assigned more than you have. Ready to assign shows ₹0.00. Lower an assignment.
- **Red "Overspent by X"**: you spent more than there was to spend across *all* categories together. A single overspent category is not a warning; its own bar shows it in red.
- **Overspending carries a cost**: an overspent category starts next month at zero and the deficit is taken out of Ready to assign from then on. Cover it by moving money from another category.

## Using the page

- Use the arrows around the month at the top (**‹ Oct 2026 ›**) to look at the next or previous month, including future ones, or tap the month itself to pick any month and year.
- The list is ranked, **biggest budget first**. Each row has a bar showing how much is spent, with a small **notch marking how far through the month today is**: a bar ahead of the tick means you are spending faster than the month passes.
- A **group** (like Food) shows the total of its subcategories; tap it to open its own page. A plain category, or a row on a group's page, opens a **sheet** with **Assigned this month** (type the amount and **Save**), what was **Spent**, and **Move money** to another category. On a group's page, tap the figure at the top to set the group's own budget: it starts at what its subcategories add up to, you can raise it, and a lower amount is refused (the field turns red).

<img src="img/budget-sheet.png" alt="The category sheet: Assigned this month, Spent, Save, Move money" width="300">
- Budgets looks at the **whole month**, so an entry dated later this month already counts as spent in its category, while Home's Transactions list, account balances count up to today.
- **Move money** never changes Ready to assign; it limits you to what the source category has left. Typing a smaller (even negative) amount in a category's *Assign* field takes money back to Ready to assign, but never more than the category has left.
- What needs a decision is under the **bell** at the top of every page (a number beside it when something is waiting): payments no category took, accounts left out of the budget, and recurring transactions that could not be recorded. Each item has its fix on the spot. On a month with nothing assigned yet, a quiet **Copy last month's amounts** link sits under the figure.
- **Copy last month's amounts** assigns each category what it got last month, but only where nothing is assigned yet.

### Credit cards, loans and EMIs

- Purchases on a **budget credit card** count in their category as you buy. Paying the card is a transfer and is not "spending" again.
- A card that is *not* part of the budget: purchases on it are not counted; Budgets offers *Add to budget* for it.
- A **loan** outside the budget needs no account made up for it. When you pay it from a budget account, the Add screen shows a **Category** line: pick *EMI* and the payment counts as spending in that category. The loan can name a *usual category* on its edit page so the line fills itself in. A payment saved without a category is listed under *Needs you* on Budgets, where you can pick one. Interest the lender charges is not part of the budget.

## Home vs Budgets

Home shows one number, *Left to spend in <month>*, with a thin bar: the total left across your categories. A month picker sits at the top right (any past month; never a future one); a small notch under the bar marks how far through the month today is. Before you have assigned anything it shows what you have spent this month and a link to set up the budget. Under it Home shows, once you have recorded something: a line when a category is overspent, and last your latest transactions. The Plan page is for *deciding*, Home is for *glancing*.

## If numbers disagree

**Budgets** and the **Categories** page count a loan payment the same way: as spending in the category you gave it. The overview's *expenses* are the books' view, where paying into a loan is not an expense (only the interest the lender charges is), and its *spent* matches Budgets. The Budget leaves out on purpose what no budget account paid, so interest a lender adds to a loan shows up as an expense in the books but not in the Budget.

## Saving for a goal and paying a fund or a loan

A goal ("save ₹1,00,000 by March for a trip") has its own chip: **Budgets › Save**. Tap **New goal**, say what it is for, how much you need and by which month. The form shows what it asks of each month (the amount spread evenly over this month and the ones left, rounded up) before you create it, and by default sets this month's share aside at once.

Each goal is a row with what is saved of what you need, a bar, and what this month still asks ("This month done", or "₹10,333 to go this month"). Tap it for its sheet: **Set aside** this month's share, **Use it for…**, **Change amount or month**, or **Delete goal**. Money set aside for goals is not money to spend: it is left out of *Left to spend* (here and on Home), and the Spend chip says how much is set aside ("₹80,000 in goals ›"). It still has a job, so it is out of *Ready to assign*. The money stays in your bank account.

A goal is not a category, and you never record spending on it. When the time comes, pay as usual and record the spending on an ordinary category (the hospital bill on *Health › Hospital*, the laptop on *Shopping › Gadgets*). Then open the goal and tap **Use it for…**: pick that category and an amount, and the goal hands that much of its saved money to the category, so the spending is covered and the category is no longer over. Ready to assign does not change. Deleting a goal gives what is saved in it back to Ready to assign.

Money you put into a mutual fund each month, or an EMI you pay on a loan, is not an expense in the ledger, but you can still plan it. Make a category such as *Investing* or *EMI* and plan it like any other. When you pay the fund or loan from a budget account, pick that category on the **Category** line; open the fund or loan (outside the budget) and set a *usual category for payments* under *Budget options* to have it filled in. The payment then counts as spending in the category, so Ready to assign falls when you plan it and the category shows what you have paid.

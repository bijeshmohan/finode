# The budget

finode uses **envelope budgeting** (the YNAB idea): every unit of money in your budget accounts gets a job. The budget sits **on top of the ledger without changing it**.

All of it lives in `app/services/budget.py` (`BudgetService`).

## What is stored, and what is not

Only these things are stored:

| Stored | Where |
|---|---|
| The plan: how much each expense category is *assigned* in each month | `budget_allocations` (user, month = first day, expense account, amount; unique per month and account) |
| Which asset or liability accounts are part of the budget | the flag `accounts.on_budget` |

Everything else is **derived on demand** from postings and the plan, so editing a transaction can never leave the budget stale.

## The four numbers

For a month and an expense category:

- **Assigned** — what you gave the category this month.
- **Activity** — postings to the category in transactions that touch a budget account. Spending paid from an account outside the budget is ignored (and reported as "left out").
- **Available** — what you can still spend:
  `max(0, last month's available) + assigned − activity`
- **Ready to assign** — money in budget accounts that has no job yet:
  `ready to assign = money in accounts − reserved for cards − Σ available − Σ goal available − assigned to later months`

A **goal** is not a category: it has its own table `goals` (name, amount, month) and `goal_allocations` (what was set aside, month by month, negative when taken back or handed over), and **goal available** is the sum of its allocations up to the month's end. Nothing is posted to a goal: spending is recorded on an ordinary category, and `BudgetService.use_goal` moves the goal's money across (a negative goal allocation and an equal positive category allocation in the same month), so Ready to assign does not change. A goal never holds less than nothing in any month (`_check_saved`). The by-date rule that funds a goal is the same `funding()` function the category targets use.

`BudgetRead` always satisfies that sum, and the page and the `get_budget` tool show it.

```mermaid
flowchart LR
    CASH["Money in budget accounts<br/>(debits − credits, to month end)"] --> RTA
    CARDS["Owed on budget credit cards"] -->|subtract| RTA
    AV["Σ available of every category"] -->|subtract| RTA
    LATER["Assigned to later months"] -->|subtract| RTA
    RTA(["Ready to assign"])
```

### Rolling month to month

`BudgetService._roll` carries the figures forward:

- Leftover money **carries into the next month**.
- An **overspent** category (negative at the end of a month) starts the next month at **zero**, and the deficit is taken out of *Ready to assign* from then on. In its own month an overspent category just shows negative and Ready to assign is unchanged. `overspent_last_month` reports what was deducted.
- Budgeting **starts with the first month anything was assigned**. Earlier spending is ignored, because cash is the balance *now* and past spending already left it; counting it would deduct it twice.
- Money assigned to **later months** is subtracted from Ready to assign in every earlier month, so assigning ahead uses up what is ready now, and the same money reads the same from either month.
- **Moving money** between categories (`move`, limited to what is available) never changes Ready to assign.
- A month's **assigned amount may be negative** to take back what an earlier month left in the category (Move money writes the same), but not by more than the category has left. Otherwise the category would show as overspent with nothing spent and Ready to assign would exceed the money there is.

## What Budgets is not

The Budgets page (then Plans) was once three sections, Spend, Build (money moved into funds and loans paid down) and Earn (expected income). Build and Earn were removed on 2026-10-22: moving money between accounts does not change net worth, only income does, and the envelopes already covered the rest. Migration `c4e6a8b0d2f4` dropped `accounts.saving` and the profile's section switches and deleted the plan rows of funds, loans and income accounts (the ledger was not touched). A fund or loan payment is budgeted as spending through the account's **payment category**. A savings goal is its own record (the `goals` and `goal_allocations` tables, not an account). It has its own chip (**Goals**) and is kept out of the Budgets figures: `BudgetRead.goals`, `goal_assigned`, `goal_available`, with the identity `ready_to_assign = money_in_accounts − reserved_for_cards − Σ available − Σ goal available − assigned to later months`. It is made in one step by the **New goal** form (`BudgetService.create_goal`; the monthly share is `funding()` for a by-date target, so the form and the target agree).

## Budget accounts, tracking accounts and liabilities

| Kind of account | In the budget? | Effect |
|---|---|---|
| Asset (bank, cash, wallet) flagged `on_budget` | Yes (default for new asset accounts holding a currency) | Its balance is the cash you can assign. |
| Asset **not** flagged | Tracking only | Appears in net worth, not in the budget. |
| Credit card (liability) flagged `on_budget` | Yes, opted in | Purchases count as category spending; the debt is subtracted from cash and shown under **Cards to pay**. |
| Loan or other liability **not** in the budget | Tracking | A payment into it carries a **category** on its line (EMI, SIP): in a transaction touching a budget account it counts as spending in that category. The account can name a *usual category* that fills the line in; credits, such as the loan paying out, carry none. |

Reports speak two languages. **By category** (the Categories page, the breakdown by default, the overview's `spent`) counts a payment into a loan as spending in its category, as the Budget does. **By account** (the breakdown with `by=account`, the overview's `expenses`) is the books' view: paying into a loan is no expense, and only the interest the lender charges is (it touches no budget account, so the Budget does not count it).

Spending on an unflagged card is not counted in a category; it is reported as `left_out` and the page offers "Add to budget" for that account.

Credit cards need no assigning. The collapsible credit-accounts row on Home shows what is owed at the month's end (`BudgetCard.owed`), with the month's charged and paid; it is the same arithmetic, made visible.

## Groups

Two-level categories (`Food › Groceries`) show **the sum of their children**. A group's own budget (tapping the figure on its page) starts at that sum and may be raised but never lowered below it (`BudgetService.assign_group`); the extra is kept on the group's own account in `budget_allocations`, so a group's total always adds up its own money and its categories'. The page shows no separate row for it.

## Targets and notes (removed)

Budget targets (monthly, weekly, refill, by-date and yearly wishes per category, "Assign what is needed", the week-by-week view) and a category's short note on the budget were taken out on 2026-10-24: nobody used them. Migration `f2c4e6a8b0d1` drops `budget_targets`; the API's target routes, the web target page and the assistants' `set_budget_target` and `fund_budget_targets` went with them. A goal still spreads what it needs evenly over the months left (`funding` in `services/budget.py`). Older backups that carry `targets` are read and the targets ignored.

## Setting up a month

`copy_previous` assigns each open category what it got last month, only where nothing is assigned yet. `assign` and `move` refuse a month that ends inside the locked period.

## Where it surfaces

- **Web:** `/budget` (Ready to assign, categories ranked by size, sheets for assigning), a group's page, `/budget/move`.
- **Home:** one number, *Left to spend*, taken from the same `view()`.
- **API:** `GET /api/budget/`, `PUT /api/budget/categories/{aid}`.
- **MCP:** `get_budget`, `assign_to_category`, `move_budget_money`, `copy_budget_from_previous_month`.

Next: [The web UI](web-ui.md).

## Categories apart from the books (2026-10-29)

The plan is kept against **budget categories** (`budget_categories`: spending or earning, two levels), not against Expenses accounts. A category is a label on the lines of a transaction (`postings.category_id`); the budget's activity is the lines that carry a spending category in entries that touch a budget account, where the line's own account is not part of the budget. An Income or Expenses account has a category (`accounts.category_id`; for most accounts a category of its own, with the same id), so an expense still needs no extra step. A payment into a loan or fund carries the category it was labelled with, which is how an EMI or a SIP is budgeted without an account made up for it. Several books accounts may feed one category (Interest under EMI): the Budget counts them together and the books keep them apart. A payment saved without a category is listed in the bell's To do sheet. The identity `ready_to_assign = money_in_accounts − reserved_for_cards − Σ available − Σ goal available − assigned to later months` is unchanged.

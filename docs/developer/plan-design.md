# Plan: design proposal

**Status: design agreed 2026-10-20 (page arrangement P2, the five decisions below as recommended); building phase by phase.** Written at the owner's request. The feature freeze (since 2026-10-14) is lifted for this feature only; everything else stays frozen. The scope below is introduced in phases, one merge at a time, and each phase is shown to the owner (mock-ups, then real screenshots) before it is merged.

## The idea

The Budget today plans one thing: money going from the budget accounts to **Expenses**. finode's Plan plans the month as a whole:

| Section | What it plans | Account type | Plan means | Actual comes from |
|---|---|---|---|---|
| **Spend** | money you will use up | Expenses (today's Budget) | set aside to spend | postings to the category |
| **Save** | money you will keep | Assets outside the budget (funds, FDs, RDs) | to move into the account | transfers into it from budget accounts |
| **Earn** (optional) | money you expect | Income | expected to arrive | postings to the income category |

One sentence ties the page together:

> **Expected income − planned saving − budgeted spending = unplanned.**

The name: the page is **Plan**; its three sections are **Spend**, **Save** and **Earn**. "Budget" stays as the word for the Spend section's envelopes ("budget" as a verb is still fine).

## Why this is not three features

A plan line is *an amount planned for an account in a month*. That is exactly what `budget_allocations` stores (user, month, account, amount). Nothing says the account has to be an Expenses account except one check in `BudgetService`. The meaning of a line comes from where its account sits:

- under **Expenses** → Spend
- an **Asset outside the budget** that the person switched on for saving → Save
- under **Income** → Earn

Actuals are derived from the ledger as they are today, so a plan can never go stale and the ledger rules are untouched.

## The arithmetic (the part to get right)

The budget's identity is the contract (`tests/test_ledger_fuzz.py` checks it):

`ready_to_assign = money_in_accounts − reserved_for_cards − Σ available − assigned_to_later_months`

**Spend** is unchanged.

**Save behaves, in arithmetic, exactly like a Spend line.** Take a Save line with 5,000 assigned. When 5,000 is moved from a budget account to the fund, cash falls by 5,000 and the line's *activity* is 5,000, so its *available* is `assigned − activity = 0`. Ready to assign does not move, which is right: the money had a job and did it. Before the transfer, assigning 5,000 to the line lowers Ready to assign by 5,000, which is also right: that money is spoken for. So the identity needs **no change**, only a second source of "activity": debits into the Save account in transactions that touch a budget account. That is precisely the rule the payment category already uses for loans (`AccountService.payments_into_loans`), applied to the account itself instead of a category. This keeps phase 1 small and keeps the fuzz identity valid.

**Earn is informational.** Expected income is not money yet, so it never changes Ready to assign (YNAB's rule too). A line shows *expected* and *received so far* (credits to the income account in the month). The overview sentence uses the expected amounts. Nothing in the identity reads them.

## What is stored

| Need | Stored as | Migration |
|---|---|---|
| The amounts | `budget_allocations` as today, now also for Save and Earn accounts | none (the table already fits; relax the Expenses-only check) |
| Which off-budget assets are Save lines | **one new column** `accounts.saving` (bool, default false), set on the account's edit page ("Plan for saving") | yes, additive, and the backup carries it |
| Targets on Save lines ("₹5 lakh by March", "₹5,000 a month") | `budget_targets` as today (kinds `monthly`, `by_date`, `yearly` already fit) | none |
| Earn lines | allocations on Income accounts | none |

Nothing else is stored. The table keeps its name for now (`budget_allocations`); a rename is a later, separate cleanup because it buys nothing for users.

## Reports and the owner's complaint

Today a SIP is made to look like spending by giving the fund a payment category (an Expenses account). With Save lines:

- A Save account's transfers are **Saved**, never spending: Categories, the breakdown, Home's Spent and "you kept X%" stop counting them. (The reports already count a payment into a loan once, as spending in its payment category; a Save account is simply never given one.)
- The owner's two live links (Mutual Funds → category "Mutual Funds"; Recurring → "Recurring Deposits") need a **conversion step**, because the existing category would keep counting: the account is switched to Save, its payment category is cleared, and the category's past months keep their history. This is the main migration risk, and it is a decision for the owner (see below).
- Home gains no new number in phase 1. A "Saved" figure beside Earned / Assigned / Spent is a later question.

## The page

**Arrangement P2 (chosen by the owner so the page is built like Accounts and Categories):** a title row with the month pill at the right, then one row of chips **Spend · Save · Earn** (Spend is the default, `?tab=spend|save|earn`), then Ready to assign and the one-line sum, then the chosen section's list. The hero and the sum stay on top whichever chip is chosen. Earn's chip is only there when Advanced is on. `/plan` replaces `/budget` in phase 3 (the old path redirects); until then the page is still `/budget` and still titled Budget, and the chips appear as the sections arrive: **Save in phase 1**, Earn in phase 2. The JSON API stays at `/api/budget` and the assistants' tools keep their names; new tools come with the phases (`get_plan`).

## Phases

Every phase ends with: unit and browser tests green (Chromium and WebKit), the docs (`CLAUDE.md`, guide, architecture) updated, mock-ups then screenshots shown, and "Merge and deploy" from the owner.

1. **Save.** `accounts.saving`, Save lines in the plan (assign, activity, targets), reports exclude them from spending, backup, the conversion step for the two existing accounts, tests (the fuzz identity includes Save lines). No page rename yet: the Budget page gets the chips (Spend, Save) and Save is the second chip.
2. **Earn.** Allocations on Income accounts, expected versus received, behind **Advanced** (the owner said "optionally"). The overview sentence.
3. **Plan.** The rename (page, tab, route redirect, docs, tools), the overview, copy last month for all three sections.

Each phase is shippable on its own; stopping after phase 1 still fixes the complaint.

## Risks and how they are handled

- **The budget identity.** Save reuses Spend's arithmetic; the fuzz test is extended to random Save lines and transfers before the feature is switched on.
- **Two meanings of "assigned to an asset".** A Save account must be off-budget and open; joining the budget or closing it removes the line (as a closed category is handled).
- **Reports disagreeing.** One shared definition of "spending" (a test already compares Categories, the breakdown, the overview and the Budget); Save moves out of all of them together.
- **Query counts.** The plan page is under a ceiling (`tests/test_query_counts.py`); Save lines come from the same single pass over postings.
- **Isolation, backup and erase.** `accounts.saving` is a column on a table that is already user-scoped, backed up and erased; `tests/test_backup.py` and `tests/test_isolation.py` cover it.
- **Scope creep.** Goals with photos, interest calculations, projections and a savings rate are **not** part of this. Targets reuse the ones that exist.

## Decisions (owner, 2026-10-20)

1. **Page arrangement:** P2, chips Spend · Save · Earn.
2. **Earn behind Advanced:** yes.
3. **Earn never feeds Ready to assign:** agreed.
4. **Existing links** (Mutual Funds, Recurring): switched to Save by a conversion step, payment category cleared, old categories keep their history.
5. **Saving is a switch on the account, never automatic.**
6. **The tab is renamed to Plan in phase 3.**

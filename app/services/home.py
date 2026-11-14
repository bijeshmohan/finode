"""Home's numbers, for the web page and the finode app alike: a month's budget at a glance, the month's first entries,
and a new person's first steps."""

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from ..clock import local_today, month_progress
from ..schemas.report import SummaryRead
from .account import AccountService
from .budget import BudgetService
from .category import CategoryService
from .report import ReportService
from .transaction import TransactionService
from .transaction_rows import HOME_FIRST, AccountIndex, TransactionRow, list_rows, to_row

RECENT_LIMIT = 8
StepKey = Literal["account", "spend", "budget"]


@dataclass
class Glance:
    has_budget: bool  # spending with no plan at all is not "over budget"
    left: Decimal
    spent: Decimal
    assigned: Decimal
    carried: Decimal  # what earlier months left in the categories
    of: Decimal  # what there was to spend
    percent: int
    pace: int | None  # how far through the month today is: the tick on the bar (none for a past month)


@dataclass
class Step:
    key: StepKey
    title: str
    done: bool
    hint: str | None = None


@dataclass
class Home:
    when: date
    is_current: bool
    summary: SummaryRead
    has_recorded: bool
    glance: Glance
    steps: list[Step]  # all of them; the page shows them only while some are left
    rows: list[TransactionRow]
    total: int  # the month's entries in all (the rows are the first few)
    roots: dict[str, UUID]

    @property
    def steps_left(self) -> bool:
        return not all(step.done for step in self.steps)


def home_view(
    when: date,
    accounts: AccountService,
    categories: CategoryService,
    reports: ReportService,
    transactions: TransactionService,
    budget: BudgetService,
) -> Home:
    """Home for the month beginning `when` (never one that has not started)."""
    this_month = local_today().replace(day=1)
    when = min(when, this_month)
    is_current = when == this_month
    month_end = when.replace(day=calendar.monthrange(when.year, when.month)[1])
    summary = reports.summary() if is_current else reports.summary(when, month_end)
    all_accounts = accounts.list()
    index = AccountIndex.build(all_accounts, categories.list(include_closed=True))
    # The chosen month's own entries, newest first (this month up to today), a few at first and "Show more" for the rest.
    chunk, total = transactions.page(0, HOME_FIRST, date_from=when, date_to=min(month_end, local_today()))
    recent = list_rows(chunk, index, transactions)
    roots = {a.name: a.id for a in all_accounts if a.parent_id is None}
    system_ids = {a.id for a in all_accounts if AccountService.is_opening_balances(a, all_accounts)}
    used_roots = {index.roots[a.id] for a in all_accounts if a.parent_id is not None and a.id not in system_ids}

    # Opening balances are bookkeeping, not a transaction the person recorded.
    def recorded(rows: list[TransactionRow]) -> bool:
        return any(not any(p.account_id in system_ids for p in row.transaction.postings) for row in rows)

    has_recorded = recorded(recent)
    if (
        not has_recorded
    ):  # a month with nothing yet: look at the latest entries of any month (dated ahead is not recent)
        has_recorded = recorded(
            [to_row(t, index) for t in transactions.list(date_to=local_today(), limit=RECENT_LIMIT)]
        )
    steps = [
        Step("account", "Add a bank account, cash or card", bool(used_roots & {"Assets", "Liabilities"})),
        Step("spend", "Record your first spend", has_recorded, "Takes about ten seconds"),
        Step("budget", "Give your money a job", budget.started(), "Set aside rent and food"),
    ]
    plan = budget.view(when)
    # What is left of this month's budget: the money still to spend, out of what there was to spend.
    to_spend = plan.activity + max(plan.available, Decimal(0))
    glance = Glance(
        has_budget=plan.assigned > 0 or plan.available > 0,
        left=plan.available,
        spent=plan.activity,
        assigned=plan.assigned,
        carried=plan.available - plan.assigned + plan.activity,
        of=to_spend,
        percent=int(min(max(plan.activity / to_spend, Decimal(0)), Decimal(1)) * 100) if to_spend > 0 else 0,
        pace=month_progress() if is_current else None,
    )
    return Home(when, is_current, summary, has_recorded, glance, steps, recent, total, dict(roots))

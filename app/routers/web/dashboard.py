import calendar
from decimal import Decimal

from fastapi import APIRouter, Request

from ...dependencies import Accounts, Budget, Recurring, Reports, Transactions
from ...services.account import AccountService
from ...clock import local_today, month_progress
from ...templating import templates
from .budget import shift
from .transactions import AccountIndex, to_row


router = APIRouter()

RECENT_LIMIT = 8


def _versus(now: Decimal, before: Decimal, name: str) -> tuple[str, Decimal, str] | None:
    """How the month so far compares with the same days of the month before: (more than / less than / same as, by
    how much, that month's name); None when there is nothing to compare."""
    if not before:
        return None
    return ("same as" if now == before else "more than" if now > before else "less than"), abs(now - before), name



def _catch_up(recurring: Recurring) -> None:
    """Record what has fallen due; a problem here must never stop the page from opening."""
    try:
        recurring.process_due()
    except Exception:
        recurring.repo.db.rollback()


@router.get("/")
def dashboard(
    request: Request,
    accounts: Accounts,
    reports: Reports,
    transactions: Transactions,
    recurring: Recurring,
    budget: Budget,
):
    _catch_up(recurring)
    summary = reports.summary()
    all_accounts = accounts.list()
    index = AccountIndex.build(all_accounts)
    recent = [to_row(t, index) for t in transactions.list(date_to=local_today(), limit=RECENT_LIMIT)]  # entries dated ahead are not recent

    roots = {a.name: a.aid for a in all_accounts if a.parent_id is None}
    system_ids = {a.aid for a in all_accounts if AccountService.is_opening_balances(a, all_accounts)}
    used_roots = {
        index.roots[a.aid] for a in all_accounts if a.parent_id is not None and a.aid not in system_ids
    }
    # Opening balances are bookkeeping, not a transaction the user recorded.
    has_recorded = any(
        not any(p.account in system_ids for p in row.transaction.postings) for row in recent
    )
    steps = [
        {
            "done": bool(used_roots & {"Assets", "Liabilities"}),
            "title": "Add a bank account, cash or card",
            "href": f"/accounts/new?parent={roots['Assets']}",
        },
        {
            "done": "Expenses" in used_roots,
            "title": "Add an expense category, like Groceries",
            "href": f"/accounts/new?parent={roots['Expenses']}",
        },
        {
            "done": has_recorded,
            "title": "Record your first transaction",
            "href": "/transactions/new",
        },
    ]
    month = budget.view(None)
    # What is left of this month's budget: the money still to spend, out of what there was to spend.
    to_spend = month.activity + max(month.available, Decimal(0))
    glance = {
        "has_budget": month.assigned > 0 or month.available > 0,  # spending with no plan at all is not "over budget"
        "left": month.available,
        "spent": month.activity,
        "assigned": month.assigned,
        "carried": month.available - month.assigned + month.activity,  # what earlier months left in the categories
        "of": to_spend,
        "percent": int(min(max(month.activity / to_spend, Decimal(0)), Decimal(1)) * 100) if to_spend > 0 else 0,
        "pace": month_progress(),  # how far through the month today is: the tick on the bar
    }
    # The month so far against the same days of the month before.
    today = local_today()
    before_start = shift(month.month, -1)
    before_end = before_start.replace(day=min(today.day, calendar.monthrange(before_start.year, before_start.month)[1]))
    before = reports.summary(before_start, before_end) if has_recorded else None
    previous_name = calendar.month_abbr[before_start.month]
    overspent = sorted(
        (l for l in month.lines if not l.group and l.available < 0), key=lambda l: l.available
    )
    tiles = {
        "money": month.money_in_accounts,
        "cards": month.reserved_for_cards,
        "has_cards": bool(month.cards),
        "ready": month.ready_to_assign,
        "income": summary.income,
        "expenses": summary.expenses,
        "income_vs": _versus(summary.income, before.income, previous_name) if before else None,
        "expenses_vs": _versus(summary.expenses, before.expenses, previous_name) if before else None,
        "cards_n": len(month.cards),
    }
    warning = (
        {"name": overspent[0].name, "n": len(overspent), "over": -sum((l.available for l in overspent), Decimal(0)), "first": -overspent[0].available}
        if overspent
        else None
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active": "dashboard",
            "summary": summary,
            "currency": summary.currency,
            "month_name": calendar.month_name[month.month.month],
            "glance": glance,
            "tiles": tiles,
            "warning": warning,
            "month_short": calendar.month_abbr[month.month.month],
            "has_recorded": has_recorded,
            "recent": recent,
            "steps": steps if not all(step["done"] for step in steps) else None,
            "steps_done": sum(1 for step in steps if step["done"]),
            "steps_total": len(steps),
        },
    )

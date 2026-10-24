import calendar
from decimal import Decimal

from fastapi import APIRouter, Request

from ...clock import local_today, month_progress
from ...dependencies import Accounts, Budget, Profiles, Recurring, Reports, Transactions
from ...services.account import AccountService
from ...templating import templates
from .budget import parse_month
from .categories import _month_context
from .transactions import HOME_FIRST, HOME_MORE, AccountIndex, _more, to_row

router = APIRouter()

RECENT_LIMIT = 8


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
    profiles: Profiles,
    month: str = "",
):
    _catch_up(recurring)
    this_month = local_today().replace(day=1)
    when = min(parse_month(month), this_month)  # never a month that has not started
    is_current = when == this_month
    summary = (
        reports.summary()
        if is_current
        else reports.summary(when, when.replace(day=calendar.monthrange(when.year, when.month)[1]))
    )
    all_accounts = accounts.list()
    index = AccountIndex.build(all_accounts)
    # The chosen month's own entries, newest first (this month up to today), a few at first and "Show more" for the rest.
    month_end = when.replace(day=calendar.monthrange(when.year, when.month)[1])
    chunk, month_total = transactions.page(0, HOME_FIRST, date_from=when, date_to=min(month_end, local_today()))
    recent = [to_row(t, index) for t in chunk]
    more = _more({"scope": "home", "month": when.strftime("%Y-%m")}, len(recent), month_total, HOME_MORE, HOME_MORE)
    roots = {a.name: a.aid for a in all_accounts if a.parent_id is None}
    system_ids = {a.aid for a in all_accounts if AccountService.is_opening_balances(a, all_accounts)}
    used_roots = {index.roots[a.aid] for a in all_accounts if a.parent_id is not None and a.aid not in system_ids}

    # Opening balances are bookkeeping, not a transaction the user recorded.
    def recorded(rows):
        return any(not any(p.account in system_ids for p in row.transaction.postings) for row in rows)

    has_recorded = recorded(recent)
    if (
        not has_recorded
    ):  # a month with nothing yet: look at the latest entries of any month (dated ahead is not recent)
        has_recorded = recorded(
            [to_row(t, index) for t in transactions.list(date_to=local_today(), limit=RECENT_LIMIT)]
        )
    planned = bool(budget.br.list())  # anything ever assigned in the Plan
    steps = [
        {
            "done": bool(used_roots & {"Assets", "Liabilities"}),
            "title": "Add a bank account, cash or card",
            "href": f"/accounts/new?parent={roots['Assets']}",
        },
        {
            "done": has_recorded,
            "title": "Record your first spend",
            "href": "/transactions/new",
            "hint": "Takes about ten seconds",
        },
        {
            "done": planned,
            "title": "Give your money a job",
            "href": "/budget",
            "hint": "Open Budgets and set aside rent and food",
        },
    ]
    plan = budget.view(when)
    # What is left of this month's budget: the money still to spend, out of what there was to spend.
    to_spend = plan.activity + max(plan.available, Decimal(0))
    glance = {
        "has_budget": plan.assigned > 0 or plan.available > 0,  # spending with no plan at all is not "over budget"
        "left": plan.available,
        "spent": plan.activity,
        "assigned": plan.assigned,
        "carried": plan.available - plan.assigned + plan.activity,  # what earlier months left in the categories
        "of": to_spend,
        "percent": int(min(max(plan.activity / to_spend, Decimal(0)), Decimal(1)) * 100) if to_spend > 0 else 0,
        "pace": month_progress()
        if is_current
        else None,  # how far through the month today is: the tick on the bar (none for a past month)
    }
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active": "dashboard",
            "summary": summary,
            "currency": summary.currency,
            **_month_context(when, is_current),
            "glance": glance,
            "has_recorded": has_recorded,
            "recent": recent,
            "more": more,
            "steps": steps if not all(step["done"] for step in steps) else None,
            "steps_done": sum(1 for step in steps if step["done"]),
            "steps_total": len(steps),
        },
    )

import calendar
from decimal import Decimal

from fastapi import APIRouter, Request

from ...dependencies import Accounts, Budget, Profiles, Recurring, Reports, Transactions
from ...services.account import AccountService
from ...clock import local_today, month_progress
from ...templating import templates
from .budget import parse_month
from .categories import _month_context
from .transactions import AccountIndex, to_row


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
    summary = reports.summary() if is_current else reports.summary(when, when.replace(day=calendar.monthrange(when.year, when.month)[1]))
    all_accounts = accounts.list()
    index = AccountIndex.build(all_accounts)
    latest = [to_row(t, index) for t in transactions.list(date_to=local_today(), limit=RECENT_LIMIT)]  # entries dated ahead are not recent
    # An older month lists its own entries, newest first; this month lists the latest ones.
    recent = latest if is_current else [
        to_row(t, index)
        for t in transactions.list(date_from=when, date_to=when.replace(day=calendar.monthrange(when.year, when.month)[1]), limit=RECENT_LIMIT)
    ]

    roots = {a.name: a.aid for a in all_accounts if a.parent_id is None}
    system_ids = {a.aid for a in all_accounts if AccountService.is_opening_balances(a, all_accounts)}
    used_roots = {
        index.roots[a.aid] for a in all_accounts if a.parent_id is not None and a.aid not in system_ids
    }
    # Opening balances are bookkeeping, not a transaction the user recorded.
    has_recorded = any(
        not any(p.account in system_ids for p in row.transaction.postings) for row in latest
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
            "href": "/plan",
            "hint": "Open Plan and set aside rent and food",
        },
    ]
    month = budget.view(when)
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
        "pace": month_progress() if is_current else None,  # how far through the month today is: the tick on the bar (none for a past month)
    }
    overspent = sorted(
        (l for l in month.lines if not l.group and l.available < 0), key=lambda l: l.available
    )
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
            **_month_context(when, is_current),
            "glance": glance,
            "warning": warning,
            "cards": month.cards,
            "cards_owed": month.reserved_for_cards,
            "has_recorded": has_recorded,
            "recent": recent,
            "steps": steps if not all(step["done"] for step in steps) else None,
            "show_steps_card": not profiles.pr.advanced(),  # people on Advanced know their way around; the card is for new profiles
            "steps_done": sum(1 for step in steps if step["done"]),
            "steps_total": len(steps),
        },
    )

"""Home: a month's money in and out, the budget at a glance, the month's entries, and a new person's first steps.
The numbers come from services/home.py, shared with the finode app (/api/views/home)."""

from fastapi import APIRouter, Request

from ...dependencies import Accounts, Budget, Categories, Recurring, Reports, Transactions
from ...services.home import home_view
from ...services.transaction_rows import HOME_MORE
from ...templating import templates
from .budget import parse_month
from .categories import _month_context
from .transactions import _more

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request,
    accounts: Accounts,
    categories: Categories,
    reports: Reports,
    transactions: Transactions,
    recurring: Recurring,
    budget: Budget,
    month: str = "",
):
    recurring.catch_up()  # record what has fallen due; it never stops the page from opening
    found = home_view(parse_month(month), accounts, categories, reports, transactions, budget)
    month_key = found.when.strftime("%Y-%m")
    links = {
        "account": f"/accounts/new?parent={found.roots['Assets']}",
        "spend": "/transactions/new",
        "budget": "/budget",
    }
    steps = [
        {"done": s.done, "title": s.title, "href": links[s.key], **({"hint": s.hint} if s.hint else {})}
        for s in found.steps
    ]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active": "dashboard",
            "summary": found.summary,
            "currency": found.summary.currency,
            **_month_context(found.when, found.is_current),
            "glance": found.glance,
            "has_recorded": found.has_recorded,
            "recent": found.rows,
            "more": _more({"scope": "home", "month": month_key}, len(found.rows), found.total, HOME_MORE, HOME_MORE),
            "steps": steps if found.steps_left else None,
            "steps_done": sum(1 for s in found.steps if s.done),
            "steps_total": len(found.steps),
        },
    )

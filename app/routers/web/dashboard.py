import calendar
from decimal import Decimal

from fastapi import APIRouter, Request

from ...dependencies import Accounts, Budget, Recurring, Reports, Transactions
from ...services.account import AccountService
from ...templating import templates
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
):
    _catch_up(recurring)
    summary = reports.summary()
    all_accounts = accounts.list()
    index = AccountIndex.build(all_accounts)
    recent = [to_row(t, index) for t in transactions.list(limit=RECENT_LIMIT)]

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
        "of": to_spend,
        "percent": int(min(max(month.activity / to_spend, Decimal(0)), Decimal(1)) * 100) if to_spend > 0 else 0,
    }
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active": "dashboard",
            "summary": summary,
            "currency": summary.currency,
            "month_name": calendar.month_name[month.month.month],
            "glance": glance,
            "has_recorded": has_recorded,
            "recent": recent,
            "steps": steps if not all(step["done"] for step in steps) else None,
            "steps_done": sum(1 for step in steps if step["done"]),
            "steps_total": len(steps),
        },
    )

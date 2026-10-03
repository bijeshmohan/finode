from fastapi import APIRouter, Request

from ...dependencies import Accounts, Reports, Transactions
from ...services.account import AccountService
from ...templating import templates
from .transactions import AccountIndex, to_row


router = APIRouter()

RECENT_LIMIT = 8


@router.get("/")
def dashboard(
    request: Request,
    accounts: Accounts,
    reports: Reports,
    transactions: Transactions,
):
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
            "href": f"/app/accounts/new?parent={roots['Assets']}",
        },
        {
            "done": "Expenses" in used_roots,
            "title": "Add an expense category, like Groceries",
            "href": f"/app/accounts/new?parent={roots['Expenses']}",
        },
        {
            "done": has_recorded,
            "title": "Record your first transaction",
            "href": "/app/transactions/new",
        },
    ]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active": "dashboard",
            "summary": summary,
            "recent": recent,
            "steps": steps if not all(step["done"] for step in steps) else None,
        },
    )

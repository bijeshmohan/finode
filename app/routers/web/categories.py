"""Categories: where money goes and comes from (the Expenses and Income accounts), one month at a time.

The Accounts page is where the money is. A category is an Expenses or Income account shown for a month,
because the lifetime total of an expense account says nothing."""

import calendar
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from ...clock import local_today
from ...dependencies import Accounts, Profiles, Reports
from ...templating import templates
from .accounts import CATEGORY_ROOTS, Node, _load, _root_of, account_context, build_tree, new_account_page
from .budget import parse_month, shift


router = APIRouter(prefix="/categories")

TABS = {"expense": "Expenses", "income": "Income"}
OLD_TABS = {"spending": "expense"}  # the earlier spelling of the tab keeps working in saved links
ZERO = Decimal("0.00")


def _period(month: str):
    """The month asked for (never one that has not started) and the days it counts: up to today for this month."""
    this_month = local_today().replace(day=1)
    when = parse_month(month)
    if when > this_month:
        return None, None, None
    last = when.replace(day=calendar.monthrange(when.year, when.month)[1])
    return when, min(last, local_today()), when == this_month


def _month_context(when, is_current: bool) -> dict:
    return {
        "month": when,
        "month_key": when.strftime("%Y-%m"),
        "month_name": f"{calendar.month_name[when.month]} {when.year}",
        "is_current": is_current,
        "previous": shift(when, -1).strftime("%Y-%m"),
        "next": shift(when, 1).strftime("%Y-%m"),
    }


@router.get("")
def categories_page(request: Request, accounts: Accounts, reports: Reports, month: str = "", tab: str = "expense"):
    when, end, is_current = _period(month)
    if when is None:
        return RedirectResponse(f"/categories?tab={tab}", status_code=303)
    tab = OLD_TABS.get(tab, tab)
    tab = tab if tab in TABS else "expense"
    root_name = TABS[tab]
    own = reports.account_totals(root_name, when, end)
    roots = build_tree(accounts.list())
    root = next(r for r in roots if r.account.name == root_name)

    totals: dict[UUID, Decimal] = {}

    def walk(node: Node) -> Decimal:
        total = own.get(node.account.aid, ZERO) + sum((walk(child) for child in node.children), ZERO)
        totals[node.account.aid] = total
        return total

    # A deleted (closed) category with nothing in the month is not listed, at either level.
    def shown(n: Node) -> bool:
        return n.account.closed_on is None or any(own.get(m.account.aid) for m in n.walk())

    for n in root.children:
        n.children = [c for c in n.children if shown(c)]
    top = [n for n in root.children if shown(n)]
    grand = sum((walk(n) for n in top), ZERO)
    # Top-level groups and categories with nothing in the month are tucked away once anything has something.
    quiet = [n for n in top if totals[n.account.aid] == 0] if any(totals[n.account.aid] for n in top) else []
    return templates.TemplateResponse(
        request,
        "categories.html",
        {
            "active": "categories",
            "tab": tab,
            "root_name": root_name,
            "tree": top,
            "totals": totals,
            "own": own,
            "grand": grand,
            "quiet_ids": {n.account.aid for n in quiet},
            "quiet_count": len(quiet),
            "currency": accounts.currency().code,
            **_month_context(when, is_current),
        },
    )


@router.get("/new")
def new_category_page(request: Request, accounts: Accounts, profiles: Profiles, parent: UUID | None = None):
    """The form for a new category is the account form, set to categories (see accounts.new_account_page)."""
    return new_account_page(request, accounts, profiles, parent=parent, kind="category")


@router.get("/{aid}")
def category_page(request: Request, aid: UUID, accounts: Accounts, profiles: Profiles, month: str = ""):
    roots, node = _load(accounts, aid)
    root = _root_of(roots, node)
    if root.account.name not in CATEGORY_ROOTS or node.kind == "root":
        raise HTTPException(status_code=404, detail="category not found")
    when, end, is_current = _period(month)
    if when is None:
        return RedirectResponse(f"/categories/{aid}", status_code=303)
    entries = [e for e in (accounts.register(aid) or []) if when <= e.date <= end]
    context = account_context(accounts, profiles, aid, entries)
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            **context,
            "category": True,
            "active": "categories",
            "total": sum((e.change for e in entries), ZERO),
            "tab": "income" if root.account.name == "Income" else "expense",
            **_month_context(when, is_current),
        },
    )

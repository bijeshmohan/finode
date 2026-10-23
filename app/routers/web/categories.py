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
from .accounts import CATEGORY_ROOTS, Node, _load, _root_of, account_context, build_tree, deleted_page, new_account_page
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
        "this_month": local_today().strftime("%Y-%m"),
        "previous": shift(when, -1).strftime("%Y-%m"),
        "next": shift(when, 1).strftime("%Y-%m"),
    }


def _figures(accounts, reports, root_name: str, when, end):
    """The month's amounts for one type: (the type's tree with closed empty categories left out, what was posted to
    each account itself, what each account and everything inside it came to)."""
    own = reports.account_totals(root_name, when, end)
    root = next(r for r in build_tree(accounts.list()) if r.account.name == root_name)
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
    for n in top:
        walk(n)
    return top, own, totals


def _share(total: Decimal, grand: Decimal) -> str:
    """What part of the month's total a category is: '34%', '<1%', '0%' for one with nothing in the month (so every row
    has one), or nothing when the categories cancel out to no total at all."""
    if not total:
        return "0%"
    if not grand:
        return ""
    percent = abs(total) / abs(grand) * 100
    return "<1%" if percent < 1 else f"{round(percent)}%"


def _by_amount(nodes: list[Node], totals: dict[UUID, Decimal]) -> list[Node]:
    return sorted(nodes, key=lambda n: (-abs(totals[n.account.aid]), n.account.name.lower()))


@router.get("")
def categories_page(request: Request, accounts: Accounts, reports: Reports, month: str = "", tab: str = "expense"):
    when, end, is_current = _period(month)
    if when is None:
        return RedirectResponse(f"/categories?tab={tab}", status_code=303)
    tab = OLD_TABS.get(tab, tab)
    tab = tab if tab in TABS else "expense"
    root_name = TABS[tab]
    top, own, totals = _figures(accounts, reports, root_name, when, end)
    grand = sum((totals[n.account.aid] for n in top), ZERO)
    rows = []
    for n in _by_amount(top, totals):
        total = totals[n.account.aid]
        inside = [c.account.name for c in _by_amount(n.children, totals) if totals[c.account.aid]]
        hint = " · ".join(inside[:3] + ([f"+{len(inside) - 3}"] if len(inside) > 3 else []))
        rows.append({"node": n, "total": total, "share": _share(total, grand), "hint": hint})
    # Categories with nothing in the month are tucked away once anything has something.
    quiet = [r for r in rows if r["total"] == 0] if any(r["total"] for r in rows) else []
    return templates.TemplateResponse(
        request,
        "categories.html",
        {
            "active": "categories",
            "tab": tab,
            "root_name": root_name,
            "rows": rows,
            "grand": grand,
            "quiet_ids": {r["node"].account.aid for r in quiet},
            "quiet_count": len(quiet),
            "currency": accounts.currency().code,
            **_month_context(when, is_current),
        },
    )


@router.get("/new")
def new_category_page(request: Request, accounts: Accounts, profiles: Profiles, parent: UUID | None = None, root: str = ""):
    """The form for a new category is the account form, set to categories (see accounts.new_account_page)."""
    return new_account_page(request, accounts, profiles, parent=parent, kind="category", root=root)


@router.get("/deleted")
def deleted_categories_page(request: Request, accounts: Accounts):
    return deleted_page(request, accounts, "categories")


@router.get("/{aid}")
def category_page(request: Request, aid: UUID, accounts: Accounts, profiles: Profiles, reports: Reports, month: str = ""):
    roots, node = _load(accounts, aid)
    root = _root_of(roots, node)
    if root.account.name not in CATEGORY_ROOTS or node.kind == "root":
        raise HTTPException(status_code=404, detail="category not found")
    when, end, is_current = _period(month)
    if when is None:
        return RedirectResponse(f"/categories/{aid}", status_code=303)
    # The figure is the whole category's month; the list is what was posted to this category itself (each
    # subcategory's entries are on its own page).
    in_month = lambda rows: [e for e in (rows or []) if when <= e.date <= end]
    everything = in_month(accounts.register(aid))
    entries = in_month(accounts.register(aid, own_only=True))
    context = account_context(accounts, profiles, aid, entries)
    # What its subcategories came to in the month, biggest first, and what was posted to it itself.
    top, own, totals = _figures(accounts, reports, root.account.name, when, end)
    shown = next((n for t in top for n in t.walk() if n.account.aid == aid), None)
    subs = [(c, totals[c.account.aid]) for c in _by_amount(shown.children, totals)] if shown is not None else []
    own_here = own.get(aid, ZERO) if subs else ZERO
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            **context,
            "category": True,
            "active": "categories",
            "total": sum((e.change for e in everything), ZERO),
            "subs": subs,
            "own_here": own_here,
            "tab": "income" if root.account.name == "Income" else "expense",
            **_month_context(when, is_current),
        },
    )

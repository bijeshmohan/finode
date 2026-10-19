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


CHART_COLOURS = 5  # the biggest categories get a colour of their own, the rest share the grey


def share_bar(items: list[tuple[object, str, Decimal]]) -> tuple[list[dict], dict]:
    """The share bar for (key, name, amount) items listed in the order they are shown: the five biggest each get a colour
    (1 to 5, in the order shown), everything else the grey (6), and the bar has one slice per colour. Returns
    (slices, colour_of), where colour_of maps each key with an amount to its colour. Nothing when the bar would say
    nothing: fewer than two things to compare, or money going the other way (a refund) among them."""
    counted = [(key, name, amount) for key, name, amount in items if amount]
    if len(counted) < 2 or any(amount < 0 for _, _, amount in counted):
        return [], {}
    total = sum((amount for _, _, amount in counted), ZERO)
    biggest = {key for key, _, _ in sorted(counted, key=lambda i: -i[2])[:CHART_COLOURS]}
    colour_of: dict = {}
    slices: list[dict] = []
    rest = ZERO
    for key, name, amount in counted:
        if key in biggest:
            colour_of[key] = len(slices) + 1
            slices.append({"name": name, "amount": amount, "colour": colour_of[key]})
        else:
            colour_of[key] = CHART_COLOURS + 1
            rest += amount
    if rest:
        slices.append({"name": "Everything else", "amount": rest, "colour": CHART_COLOURS + 1})
    for s in slices:
        s["percent"] = float(s["amount"] / total * 100)
        s["label"] = f"{s['name']} {_share(s['amount'], total)}"
    return slices, colour_of


def _bar(rows: list[dict]) -> list[dict]:
    """The Categories page's bar (see share_bar); sets row["colour"] on every row (0 = not in the bar)."""
    slices, colour_of = share_bar([(i, r["node"].account.name, r["total"]) for i, r in enumerate(rows)])
    for i, r in enumerate(rows):
        r["colour"] = colour_of.get(i, 0)
    return slices


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
    bar = _bar(rows)
    return templates.TemplateResponse(
        request,
        "categories.html",
        {
            "active": "categories",
            "tab": tab,
            "root_name": root_name,
            "rows": rows,
            "bar": bar,
            "grand": grand,
            "quiet_ids": {r["node"].account.aid for r in quiet},
            "quiet_count": len(quiet),
            "currency": accounts.currency().code,
            **_month_context(when, is_current),
        },
    )


@router.get("/new")
def new_category_page(request: Request, accounts: Accounts, profiles: Profiles, parent: UUID | None = None):
    """The form for a new category is the account form, set to categories (see accounts.new_account_page)."""
    return new_account_page(request, accounts, profiles, parent=parent, kind="category")


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
    bar, colour_of = share_bar([(c.account.aid, c.account.name, amount) for c, amount in subs] + ([("own", "Everything else", own_here)] if own_here else []))
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
            "bar": bar,
            "colour_of": colour_of,
            "tab": "income" if root.account.name == "Income" else "expense",
            **_month_context(when, is_current),
        },
    )

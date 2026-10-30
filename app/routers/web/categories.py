"""Categories: what money was for, one month at a time.

The Accounts page is where the money is. A category is a label on the lines of an entry (Groceries, EMI, Salary), kept
apart from the books' accounts, and this page shows what each one came to in a month, because a lifetime total says
nothing."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from ...clock import local_today
from ...dependencies import Categories, Reports
from ...schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from ...templating import templates
from .budget import parse_month, shift
from .utils import htmx_error, htmx_redirect, htmx_trigger, validation_message

router = APIRouter(prefix="/categories")

# The chips on the Categories page, and the kind each one shows.
TABS = {"expense": "spending", "income": "earning"}
KIND_TABS = {kind: tab for tab, kind in TABS.items()}
ZERO = Decimal("0.00")


@dataclass
class CatNode:
    """A category and the categories inside it (a group holds categories; a category holds none)."""

    category: CategoryRead
    children: list[CatNode] = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def category_tree(categories: Categories, kind: str, include_closed: bool = False) -> list[CatNode]:
    """The categories of one kind as groups with their categories inside, A to Z."""
    found = categories.list(kind, include_closed)
    nodes = {c.bcid: CatNode(c) for c in found}
    top: list[CatNode] = []
    for node in nodes.values():
        parent = nodes.get(node.category.parent_id) if node.category.parent_id else None
        (parent.children if parent is not None else top).append(node)
    for node in nodes.values():
        node.children.sort(key=lambda n: n.category.name.lower())
    top.sort(key=lambda n: n.category.name.lower())
    return top


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


def _figures(categories: Categories, reports: Reports, kind: str, when, end):
    """The month's amounts for one kind: (the tree with closed empty categories left out, what was labelled with each
    category itself, what each category and everything inside it came to)."""
    own = reports.category_totals(kind, when, end)
    top = category_tree(categories, kind, include_closed=True)
    totals: dict[UUID, Decimal] = {}

    def walk(node: CatNode) -> Decimal:
        total = own.get(node.category.bcid, ZERO) + sum((walk(child) for child in node.children), ZERO)
        totals[node.category.bcid] = total
        return total

    # A deleted (closed) category with nothing in the month is not listed, at either level.
    def shown(n: CatNode) -> bool:
        return n.category.closed_on is None or any(own.get(m.category.bcid) for m in n.walk())

    for n in top:
        n.children = [c for c in n.children if shown(c)]
    top = [n for n in top if shown(n)]
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


def _by_amount(nodes: list[CatNode], totals: dict[UUID, Decimal]) -> list[CatNode]:
    return sorted(nodes, key=lambda n: (-abs(totals[n.category.bcid]), n.category.name.lower()))


@router.get("")
def categories_page(request: Request, categories: Categories, reports: Reports, month: str = "", tab: str = "expense"):
    when, end, is_current = _period(month)
    if when is None:
        return RedirectResponse(f"/categories?tab={tab}", status_code=303)
    tab = {"spending": "expense", "earning": "income"}.get(tab, tab)  # the kinds' own names work too
    tab = tab if tab in TABS else "expense"
    top, _own, totals = _figures(categories, reports, TABS[tab], when, end)
    grand = sum((totals[n.category.bcid] for n in top), ZERO)
    rows = []
    for n in _by_amount(top, totals):
        total = totals[n.category.bcid]
        inside = [c.category.name for c in _by_amount(n.children, totals) if totals[c.category.bcid]]
        hint = " · ".join(inside[:3] + ([f"+{len(inside) - 3}"] if len(inside) > 3 else []))
        rows.append({"node": n, "total": total, "share": _share(total, grand), "hint": hint})
    return templates.TemplateResponse(
        request,
        "categories.html",
        {
            "active": "categories",
            "tab": tab,
            "root_name": "Income" if tab == "income" else "Expenses",
            "rows": rows,
            "grand": grand,
            "currency": categories.accounts.currency().code,
            **_month_context(when, is_current),
        },
    )


def _form(request: Request, categories: Categories, current: CategoryRead | None, kind: str, parent: UUID | None):
    groups = [n.category for n in category_tree(categories, kind) if n.category.bcid != (current and current.bcid)]
    # A group that holds categories cannot move into another group (two levels at most).
    if current is not None and any(c.parent_id == current.bcid for c in categories.list(kind, True)):
        groups = []
    return templates.TemplateResponse(
        request,
        "category_form.html",
        {
            "active": "categories",
            "hide_fab": True,
            "category": current,
            "kind": kind,
            "tab": KIND_TABS[kind],
            "parent_id": parent,
            "groups": groups,
        },
    )


@router.get("/new")
def new_category_page(request: Request, categories: Categories, parent: UUID | None = None, root: str = "expense"):
    """The form for a new category: a spending one by default, an earning one from the Earning chip. Opened from a
    group's page ("Add subcategory") it starts inside that group, whose kind it takes."""
    kind = TABS.get(root.lower(), "spending")
    if parent is not None:
        group = categories.read(parent)
        if group is None:
            raise HTTPException(status_code=404, detail="category not found")
        kind = group.kind
    return _form(request, categories, None, kind, parent)


@router.post("")
def create_category(
    categories: Categories,
    name: Annotated[str, Form()] = "",
    kind: Annotated[str, Form()] = "spending",
    parent_id: Annotated[str, Form()] = "",
    details: Annotated[str, Form()] = "",
):
    try:
        made = categories.create(
            CategoryCreate(
                name=name.strip(),
                kind="earning" if kind == "earning" else "spending",
                parent_id=UUID(parent_id) if parent_id else None,
                details=details.strip() or None,
            )
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/categories/{made.bcid}", flash="category-created")


@router.post("/quick")
def quick_create_category(
    categories: Categories,
    name: Annotated[str, Form()] = "",
    kind: Annotated[str, Form()] = "spending",
    parent_id: Annotated[str, Form()] = "",
):
    """The "new category" sheet over the transaction form: tells the form so it can refresh its pickers."""
    try:
        made = categories.create(
            CategoryCreate(
                name=name.strip(),
                kind="earning" if kind == "earning" else "spending",
                parent_id=UUID(parent_id) if parent_id else None,
            )
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#quick-error")
    except ValueError as e:
        return htmx_error(str(e), "#quick-error")
    return htmx_trigger("account-added", {"aid": str(made.bcid), "name": made.name})


@router.get("/deleted")
def deleted_categories_page(request: Request, categories: Categories):
    closed = [c for c in categories.list(include_closed=True) if c.closed_on is not None]
    # Show the outermost of each closed branch: a closed group carries the categories in it.
    shown = [c for c in closed if not any(p.bcid == c.parent_id and p.closed_on for p in closed)]
    entries = sorted(
        (
            {"aid": c.bcid, "name": c.name, "path": c.path, "kind": "closed", "when": c.closed_on}
            for c in shown
            if c.closed_on is not None
        ),
        key=lambda e: e["when"],
        reverse=True,
    )
    return templates.TemplateResponse(
        request, "accounts_deleted.html", {"active": "settings", "area": "categories", "entries": entries}
    )


def _load(categories: Categories, bcid: UUID) -> CategoryRead:
    category = categories.read(bcid)
    if category is None:
        raise HTTPException(status_code=404, detail="category not found")
    return category


@router.get("/{bcid}")
def category_page(request: Request, bcid: UUID, categories: Categories, reports: Reports, month: str = ""):
    category = _load(categories, bcid)
    when, end, is_current = _period(month)
    if when is None:
        return RedirectResponse(f"/categories/{bcid}", status_code=303)

    # The figure is the whole category's month; the list is what was labelled with this category itself (each
    # subcategory's entries are on its own page).
    def in_month(rows):
        return [e for e in (rows or []) if when <= e.date <= end]

    everything = in_month(categories.register(bcid))
    entries = in_month(categories.register(bcid, own_only=True))
    top, own, totals = _figures(categories, reports, category.kind, when, end)
    shown = next((n for t in top for n in t.walk() if n.category.bcid == bcid), None)
    subs = [(c, totals[c.category.bcid]) for c in _by_amount(shown.children, totals)] if shown is not None else []
    own_here = own.get(bcid, ZERO) if subs else ZERO
    group = categories.read(category.parent_id) if category.parent_id else None
    return templates.TemplateResponse(
        request,
        "category.html",
        {
            "active": "categories",
            "category": category,
            "group": group,
            "entries": list(reversed(entries)),
            "currency": categories.accounts.currency().code,
            "total": sum((e.change for e in everything), ZERO),
            "subs": subs,
            "own_here": own_here,
            "can_add_child": category.parent_id is None and category.closed_on is None and category.system_key is None,
            "tab": KIND_TABS[category.kind],
            "earning": category.kind == "earning",
            **_month_context(when, is_current),
        },
    )


@router.get("/{bcid}/edit")
def edit_category_page(request: Request, bcid: UUID, categories: Categories):
    category = _load(categories, bcid)
    if category.system_key is not None:
        raise HTTPException(status_code=404, detail="category not found")
    return _form(request, categories, category, category.kind, category.parent_id)


@router.post("/{bcid}/edit")
def update_category(
    bcid: UUID,
    categories: Categories,
    name: Annotated[str, Form()] = "",
    parent_id: Annotated[str, Form()] = "",
    details: Annotated[str, Form()] = "",
):
    current = _load(categories, bcid)
    try:
        changes: dict = {}
        if name.strip() != current.name:
            changes["name"] = name.strip()
        if (details.strip() or None) != current.details:
            changes["details"] = details.strip() or None
        if (UUID(parent_id) if parent_id else None) != current.parent_id:
            changes["parent_id"] = UUID(parent_id) if parent_id else None
        if changes:
            categories.update(bcid, CategoryUpdate(**changes))
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/categories/{bcid}", flash="category-updated")


@router.post("/{bcid}/delete")
def delete_category(bcid: UUID, categories: Categories):
    current = _load(categories, bcid)
    try:
        categories.delete(bcid)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect(f"/categories?tab={KIND_TABS[current.kind]}", flash="category-deleted")


@router.post("/{bcid}/reopen")
def reopen_category(bcid: UUID, categories: Categories):
    _load(categories, bcid)
    try:
        categories.reopen(bcid)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect(f"/categories/{bcid}", flash="category-restored")

"""Categories: what money was for, one month at a time.

The Accounts page is where the money is. A category is a label on the lines of an entry (Groceries, EMI, Salary), kept
apart from the books' accounts, and this page shows what each one came to in a month, because a lifetime total says
nothing."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from ...clock import local_today
from ...dependencies import Categories, Reports
from ...schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from ...services.categories_view import KIND_TABS, TABS, CategoryForm, categories_page, category_form, category_page
from ...templating import templates
from .budget import parse_month, shift
from .utils import htmx_error, htmx_redirect, htmx_trigger, validation_message

router = APIRouter(prefix="/categories")


def _period(month: str):
    """The month asked for (never one that has not started) and the days it counts: up to today for this month."""
    this_month = local_today().replace(day=1)
    when = parse_month(month)
    if when > this_month:
        return None, None, None
    last = when.replace(day=calendar.monthrange(when.year, when.month)[1])
    return when, min(last, local_today()), when == this_month


def _month_context(when: date, is_current: bool) -> dict:
    return {
        "month": when,
        "month_key": when.strftime("%Y-%m"),
        "month_name": f"{calendar.month_name[when.month]} {when.year}",
        "is_current": is_current,
        "this_month": local_today().strftime("%Y-%m"),
        "previous": shift(when, -1).strftime("%Y-%m"),
        "next": shift(when, 1).strftime("%Y-%m"),
    }


@router.get("")
def categories_list_page(
    request: Request, categories: Categories, reports: Reports, month: str = "", tab: str = "expense"
):
    when, end, is_current = _period(month)
    if when is None or end is None or is_current is None:
        return RedirectResponse(f"/categories?tab={tab}", status_code=303)
    tab = KIND_TABS.get(tab, tab)  # the kinds' own names work too
    tab = tab if tab in TABS else "expense"
    rows, grand = categories_page(categories, reports, TABS[tab], when, end)
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


def _form(request: Request, form: CategoryForm):
    return templates.TemplateResponse(
        request,
        "category_form.html",
        {
            "active": "categories",
            "hide_fab": True,
            "category": form.category,
            "kind": form.kind,
            "tab": KIND_TABS[form.kind],
            "parent_id": form.parent_id,
            "groups": form.groups,
        },
    )


@router.get("/new")
def new_category_page(request: Request, categories: Categories, parent: UUID | None = None, root: str = "expense"):
    """The form for a new category (services/categories_view.category_form)."""
    try:
        return _form(request, category_form(categories, parent=parent, root=root))
    except LookupError:
        raise HTTPException(status_code=404, detail="category not found") from None


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
    return htmx_redirect(f"/categories/{made.id}", flash="category-created")


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
    return htmx_trigger("account-added", {"id": str(made.id), "name": made.name})


def _load(categories: Categories, category_id: UUID) -> CategoryRead:
    category = categories.read(category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="category not found")
    return category


@router.get("/{category_id}")
def category_own_page(request: Request, category_id: UUID, categories: Categories, reports: Reports, month: str = ""):
    _load(categories, category_id)
    when, end, is_current = _period(month)
    if when is None or end is None or is_current is None:
        return RedirectResponse(f"/categories/{category_id}", status_code=303)
    page = category_page(categories, reports, category_id, when, end)
    category = page.category
    return templates.TemplateResponse(
        request,
        "category.html",
        {
            "active": "categories",
            # The "+" in the bar starts an entry for this category and comes back here.
            "new_transaction_url": None
            if category.closed_on
            else f"/transactions/new?category={category_id}&back=/categories/{category_id}",
            "category": category,
            "group": page.group,
            "entries": page.entries,
            "currency": categories.accounts.currency().code,
            "total": page.total,
            "subs": page.subs,
            "own_here": page.own_here,
            "can_add_child": page.can_add_child,
            "tab": KIND_TABS[category.kind],
            "earning": category.kind == "earning",
            **_month_context(when, is_current),
        },
    )


@router.get("/{category_id}/edit")
def edit_category_page(request: Request, category_id: UUID, categories: Categories):
    _load(categories, category_id)
    return _form(request, category_form(categories, category_id))


@router.post("/{category_id}/edit")
def update_category(
    category_id: UUID,
    categories: Categories,
    name: Annotated[str, Form()] = "",
    parent_id: Annotated[str, Form()] = "",
    details: Annotated[str, Form()] = "",
):
    current = _load(categories, category_id)
    try:
        changes: dict = {}
        if name.strip() != current.name:
            changes["name"] = name.strip()
        if (details.strip() or None) != current.details:
            changes["details"] = details.strip() or None
        if (UUID(parent_id) if parent_id else None) != current.parent_id:
            changes["parent_id"] = UUID(parent_id) if parent_id else None
        if changes:
            categories.update(category_id, CategoryUpdate(**changes))
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/categories/{category_id}", flash="category-updated")


@router.post("/{category_id}/delete")
def delete_category(category_id: UUID, categories: Categories):
    current = _load(categories, category_id)
    try:
        categories.delete(category_id)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect("/categories" + ("?tab=income" if current.kind == "earning" else ""), flash="category-deleted")


@router.post("/{category_id}/reopen")
def reopen_category(category_id: UUID, categories: Categories):
    _load(categories, category_id)
    try:
        categories.reopen(category_id)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect(f"/categories/{category_id}", flash="category-restored")

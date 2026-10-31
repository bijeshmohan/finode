"""The to-do bell: a count in the top bar and a sheet of what needs a decision (see TodoService). Each item carries its
fix, so most are done without leaving the sheet."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from ...dependencies import Budget, Todo, Transactions
from ...services.budget import BudgetError
from ...templating import templates
from .utils import htmx_error

router = APIRouter(prefix="/todo")


def _sheet(request: Request, budget: Budget, todo: Todo, status_code: int = 200):
    items = todo.read()
    return templates.TemplateResponse(
        request,
        "partials/todo_sheet.html",
        {
            "todo": items,
            "currency": budget.accounts.currency().code,
            "category_choices": [(c.id, " › ".join(budget.category_path(c))) for c in budget.spending_categories()],
        },
        status_code=status_code,
    )


@router.get("/badge")
def badge(todo: Todo):
    """The bell's count, for both places it is drawn (top bar and sidebar), swapped in out of band."""
    count = todo.read().count
    text = str(count) if count else ""
    hidden = "" if count else " hidden"
    return HTMLResponse(
        f'<span id="todo-count-bar" class="bell-badge"{hidden} hx-swap-oob="true">{text}</span>'
        f'<span id="todo-count-side" class="bell-badge"{hidden} hx-swap-oob="true">{text}</span>'
    )


@router.get("/sheet")
def sheet(request: Request, budget: Budget, todo: Todo):
    return _sheet(request, budget, todo)


@router.post("/payments/{transaction_id}/category")
def label_payment(
    request: Request,
    budget: Budget,
    todo: Todo,
    transactions: Transactions,
    transaction_id: UUID,
    category: Annotated[str, Form()] = "",
):
    try:
        transactions.read(transaction_id) or _missing()
        transactions.label_payment(transaction_id, UUID(category))
    except ValueError as e:
        if "not found" in str(e) and f"'{transaction_id}'" in str(e):
            raise HTTPException(status_code=404, detail="transaction not found") from None
        return htmx_error(str(e), "#todo-error")
    return _sheet(request, budget, todo)


def _missing():
    raise HTTPException(status_code=404, detail="transaction not found")


@router.post("/accounts/{account_id}/include")
def include_account(request: Request, budget: Budget, todo: Todo, account_id: UUID):
    try:
        budget.include_account(account_id)
    except BudgetError as e:
        return htmx_error(str(e), "#todo-error")
    return _sheet(request, budget, todo)

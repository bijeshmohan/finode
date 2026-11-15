"""What is coming up for the budget: entries dated ahead and what recurring rules will record (see services/coming_up.py
and services/coming_up_view.py)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...dependencies import Accounts, Categories, ComingUp
from ...services.coming_up_view import coming_days
from ...templating import templates

router = APIRouter(prefix="/budget/coming-up")


@router.get("")
def coming_up_page(request: Request, service: ComingUp, accounts: Accounts, categories: Categories):
    found = coming_days(service, accounts, categories)
    return templates.TemplateResponse(
        request,
        "coming_up.html",
        {"data": found.data, "days": found.days, "active": "budget", "currency": accounts.currency().code},
    )


@router.get("/note")
def coming_up_note(request: Request, service: ComingUp):
    """The line in the sum behind Ready to assign: how many payments are coming up this month. Loaded after the page."""
    data = service.view()
    if not data.count:
        return HTMLResponse("")
    return templates.TemplateResponse(request, "partials/coming_note.html", {"data": data})

"""What is coming up for the budget: entries dated ahead and what recurring rules will record (see services/coming_up.py)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...dependencies import Accounts, Categories, ComingUp
from ...schemas.coming_up import ComingUpItem, ComingUpLine
from ...services.transaction_rows import AccountIndex
from ...templating import templates

router = APIRouter(prefix="/budget/coming-up")


@router.get("")
def coming_up_page(request: Request, service: ComingUp, accounts: Accounts, categories: Categories):
    data = service.view()
    index = AccountIndex.build(accounts.list(), categories.list(include_closed=True))

    def names(lines: list[ComingUpLine]) -> list[str]:
        found: list[str] = []
        for line in lines:
            name = index.line_name(line)
            if name not in found:
                found.append(name)
        return found

    def row(item: ComingUpItem) -> dict:
        debits, credits = names(item.debits), names(item.credits)
        return {
            "item": item,
            "title": item.payee or ", ".join(debits),
            "sub": f"{', '.join(credits)} → {', '.join(debits)}" if item.payee else ", ".join(credits),
        }

    days: list[dict] = []
    for item in data.items:
        if not days or days[-1]["date"] != item.date:
            days.append({"date": item.date, "rows": []})
        days[-1]["rows"].append(row(item))
    for day in days:
        directions = {r["item"].income for r in day["rows"]}
        day["total"] = sum((r["item"].amount for r in day["rows"]), 0) if len(directions) == 1 else None
    return templates.TemplateResponse(
        request,
        "coming_up.html",
        {"data": data, "days": days, "active": "budget", "currency": accounts.currency().code},
    )


@router.get("/note")
def coming_up_note(request: Request, service: ComingUp):
    """The line in the sum behind Ready to assign: how many payments are coming up this month. Loaded after the page."""
    data = service.view()
    if not data.count:
        return HTMLResponse("")
    return templates.TemplateResponse(request, "partials/coming_note.html", {"data": data})

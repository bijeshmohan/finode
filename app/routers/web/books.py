"""Books accounts (Settings › Your data): the Income and Expenses accounts the books keep behind the categories.

Most people never open this. An account that stands for a category (it has the category's name and id) is shown as
information; an extra account that feeds a category (Interest under EMI) can be made, renamed, moved to another
category, closed or deleted here."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request

from ...dependencies import Accounts, Categories
from ...schemas.account import AccountCreate, AccountRead, AccountUpdate
from ...services.account import AccountInUseError
from ...templating import templates
from .accounts import build_tree, is_extra
from .utils import htmx_error, htmx_redirect

router = APIRouter(prefix="/books")

KINDS = (("Expenses", "Spending", "spending"), ("Income", "Earning", "earning"))


def _books_accounts(accounts: Accounts) -> list[AccountRead]:
    """Every Income and Expenses account below the roots."""
    return [
        n.account
        for r in build_tree(accounts.list(), books=True)
        if r.account.name in ("Expenses", "Income")
        for n in r.walk()
        if n.kind != "root"
    ]


def _found(accounts: Accounts, aid: UUID) -> AccountRead:
    found = next((a for a in _books_accounts(accounts) if a.aid == aid), None)
    if found is None:
        raise HTTPException(status_code=404, detail="account not found")
    return found


@router.get("")
def books_page(request: Request, accounts: Accounts, categories: Categories):
    names = {c.bcid: c for c in categories.list(include_closed=True)}
    tree = build_tree(accounts.list(), books=True)
    groups = []
    for root_name, title, _kind in KINDS:
        root = next((r for r in tree if r.account.name == root_name), None)
        rows = []
        for n in root.walk() if root else []:
            if n.kind == "root":
                continue
            a = n.account
            category = names.get(a.category_id) if a.category_id else None
            rows.append(
                {
                    "account": a,
                    "path": n.path.replace(" › ", ":"),
                    "feeds": category.path if category is not None and is_extra(a) else "",
                }
            )
        rows.sort(key=lambda r: r["path"].casefold())
        groups.append({"title": title, "kind": _kind, "rows": rows})
    return templates.TemplateResponse(request, "books.html", {"active": "settings", "groups": groups})


@router.get("/new")
def new_books_account(request: Request, categories: Categories, category: UUID | None = None):
    every = categories.list()
    return templates.TemplateResponse(
        request, "partials/books_new.html", {"categories": every, "chosen": category, "kinds": KINDS}
    )


@router.post("")
def create_books_account(
    accounts: Accounts,
    categories: Categories,
    name: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "",
):
    try:
        feeds = categories.read(UUID(category)) if category else None
        if feeds is None:
            return htmx_error("choose the category this account feeds!", "#books-sheet-error")
        parent = next(
            a.aid
            for a in accounts.ensure_roots()
            if a.parent_id is None and a.name == ("Expenses" if feeds.kind == "spending" else "Income")
        )
        accounts.create(AccountCreate(name=name, parent_id=parent, category_id=feeds.bcid))
    except ValueError as e:
        return htmx_error(str(e), "#books-sheet-error")
    return htmx_redirect("/books", flash="books-saved")


@router.get("/{aid}/sheet")
def books_account_sheet(request: Request, aid: UUID, accounts: Accounts, categories: Categories):
    account = _found(accounts, aid)
    own = account.category_id == account.aid
    mine = categories.read(account.category_id) if account.category_id else None
    options = categories.list(kind=mine.kind) if mine is not None else []
    return templates.TemplateResponse(
        request, "partials/books_sheet.html", {"account": account, "own": own, "category": mine, "options": options}
    )


def _extra(accounts: Accounts, aid: UUID) -> AccountRead:
    account = _found(accounts, aid)
    if not is_extra(account):
        raise ValueError("this account stands for its category: change the category itself instead!")
    return account


@router.post("/{aid}")
def update_books_account(
    aid: UUID,
    accounts: Accounts,
    name: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "",
):
    try:
        _found(accounts, aid)
        account = _extra(accounts, aid)
        fields: dict = {"name": name or account.name}
        if category and UUID(category) != account.category_id:
            fields["category_id"] = UUID(category)
        accounts.update(aid, AccountUpdate(**fields))
    except ValueError as e:
        return htmx_error(str(e), "#books-sheet-error")
    return htmx_redirect("/books", flash="books-saved")


def _act(accounts: Accounts, aid: UUID, action, flash: str):
    try:
        _extra(accounts, aid)
        action(aid)
    except (ValueError, AccountInUseError) as e:
        return htmx_error(str(e), "#books-sheet-error")
    return htmx_redirect("/books", flash=flash)


@router.post("/{aid}/close")
def close_books_account(aid: UUID, accounts: Accounts):
    _found(accounts, aid)
    return _act(accounts, aid, accounts.close, "books-closed")


@router.post("/{aid}/reopen")
def reopen_books_account(aid: UUID, accounts: Accounts):
    _found(accounts, aid)
    return _act(accounts, aid, accounts.reopen, "books-reopened")


@router.post("/{aid}/delete")
def delete_books_account(aid: UUID, accounts: Accounts):
    _found(accounts, aid)
    return _act(accounts, aid, accounts.delete, "books-deleted")

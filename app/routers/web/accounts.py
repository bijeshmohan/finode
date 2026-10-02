from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import ValidationError

from ...dependencies import Accounts
from ...schemas import AccountCreate, AccountRead, AccountUpdate
from ...services.account import AccountService
from ...templating import templates
from .utils import htmx_error, htmx_redirect, parse_amount, validation_message


router = APIRouter(prefix="/accounts")

ROOT_ORDER = ("Assets", "Liabilities", "Equity", "Income", "Expenses")


@dataclass
class Node:
    account: AccountRead
    depth: int = 0
    kind: str = "user"  # root | system | user
    children: list["Node"] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def build_tree(accounts: list[AccountRead]) -> list[Node]:
    nodes = {a.aid: Node(a) for a in accounts}
    roots: list[Node] = []
    for node in nodes.values():
        parent = nodes.get(node.account.parent_id) if node.account.parent_id else None
        if parent is None:
            node.kind = "root"
            roots.append(node)
        else:
            parent.children.append(node)
            if AccountService.is_opening_balances(node.account, accounts):
                node.kind = "system"

    def finish(node: Node, depth: int) -> None:
        node.depth = depth
        node.children.sort(key=lambda n: n.account.name.lower())
        for child in node.children:
            finish(child, depth + 1)

    roots.sort(key=lambda n: ROOT_ORDER.index(n.account.name) if n.account.name in ROOT_ORDER else len(ROOT_ORDER))
    for root in roots:
        finish(root, 0)
    return roots


def _find(roots: list[Node], aid: UUID) -> Node | None:
    return next((n for root in roots for n in root.walk() if n.account.aid == aid), None)


def _parent_options(roots: list[Node], exclude: Node | None = None) -> list[Node]:
    """Accounts that may become a parent; system accounts are leaves by design."""
    excluded = {n.account.aid for n in exclude.walk()} if exclude else set()
    return [
        n
        for root in roots
        for n in root.walk()
        if n.kind != "system" and n.account.aid not in excluded
    ]


@router.get("")
def accounts_page(request: Request, accounts: Accounts):
    roots = build_tree(accounts.list())
    return templates.TemplateResponse(
        request,
        "accounts.html",
        {"active": "accounts", "roots": roots, "parent_options": _parent_options(roots)},
    )


@router.post("")
def create_account(
    accounts: Accounts,
    name: Annotated[str, Form()],
    parent_id: Annotated[UUID, Form()],
    details: Annotated[str, Form()] = "",
    balance: Annotated[str, Form()] = "",
):
    try:
        data = AccountCreate(
            name=name.strip(),
            details=details.strip() or None,
            parent_id=parent_id,
            balance=parse_amount(balance, Decimal("0.00")),
        )
        accounts.create(data)
    except ValidationError as e:
        return htmx_error(validation_message(e), "#create-error")
    except ValueError as e:
        return htmx_error(str(e), "#create-error")
    return htmx_redirect("/app/accounts")


@router.get("/{aid}/register")
def account_register(request: Request, aid: UUID, accounts: Accounts):
    account = accounts.read(aid)
    entries = accounts.register(aid)
    if account is None or entries is None:
        raise HTTPException(status_code=404, detail="account not found")
    return templates.TemplateResponse(
        request,
        "register.html",
        {"active": "accounts", "account": account, "entries": list(reversed(entries))},
    )


def _row_response(request: Request, accounts: AccountService, aid: UUID, template: str):
    roots = build_tree(accounts.list())
    node = _find(roots, aid)
    if node is None:
        raise HTTPException(status_code=404, detail="account not found")
    context = {"node": node}
    if template == "partials/account_edit.html":
        root_of = next(r for r in roots if node in list(r.walk()))
        context["parent_options"] = [
            n for n in _parent_options(roots, exclude=node) if n in list(root_of.walk())
        ]
    return templates.TemplateResponse(request, template, context)


@router.get("/{aid}/row")
def account_row(request: Request, aid: UUID, accounts: Accounts):
    return _row_response(request, accounts, aid, "partials/account_row.html")


@router.get("/{aid}/edit")
def account_edit_form(request: Request, aid: UUID, accounts: Accounts):
    return _row_response(request, accounts, aid, "partials/account_edit.html")


@router.post("/{aid}/edit")
def update_account(
    aid: UUID,
    accounts: Accounts,
    name: Annotated[str, Form()],
    parent_id: Annotated[UUID, Form()],
    details: Annotated[str, Form()] = "",
    balance: Annotated[str | None, Form()] = None,
):
    error_target = f"#edit-error-{aid}"
    current = accounts.read(aid)
    if current is None:
        raise HTTPException(status_code=404, detail="account not found")

    changes: dict = {}
    if name.strip() != current.name:
        changes["name"] = name.strip()
    if (details.strip() or None) != current.details:
        changes["details"] = details.strip() or None
    if parent_id != current.parent_id:
        changes["parent_id"] = parent_id
    try:
        if balance is not None and balance.strip():
            new_balance = parse_amount(balance)
            if new_balance != current.balance:
                changes["balance"] = new_balance
        if changes:
            accounts.update(aid, AccountUpdate(**changes))
    except ValidationError as e:
        return htmx_error(validation_message(e), error_target)
    except ValueError as e:
        return htmx_error(str(e), error_target)
    return htmx_redirect("/app/accounts")


@router.post("/{aid}/delete")
def delete_account(aid: UUID, accounts: Accounts):
    try:
        accounts.delete(aid)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect("/app/accounts")

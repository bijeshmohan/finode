from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from ...dependencies import Accounts
from ...schemas import AccountCreate, AccountRead, AccountUpdate
from ...services.account import AccountService
from ...templating import templates
from .utils import htmx_error, htmx_redirect, htmx_trigger, parse_amount, validation_message


router = APIRouter(prefix="/accounts")

ROOT_ORDER = ("Assets", "Liabilities", "Equity", "Income", "Expenses")

# Only these hold money the user already has (or owes) when an account is first added.
OPENING_BALANCE_ROOTS = ("Assets", "Liabilities")


@dataclass
class Node:
    account: AccountRead
    depth: int = 0
    kind: str = "user"  # root | system | user
    path: str = ""
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

    def finish(node: Node, depth: int, parent_path: str = "") -> None:
        node.depth = depth
        node.path = f"{parent_path} › {node.account.name}" if parent_path else node.account.name
        node.children.sort(key=lambda n: n.account.name.lower())
        for child in node.children:
            finish(child, depth + 1, node.path)

    roots.sort(key=lambda n: ROOT_ORDER.index(n.account.name) if n.account.name in ROOT_ORDER else len(ROOT_ORDER))
    for root in roots:
        finish(root, 0)
    return roots


def posting_groups(roots: list[Node]) -> list[tuple[str, list[Node]]]:
    """Accounts that transactions may post to (leaf, non-root), grouped by root."""
    groups = []
    for root in roots:
        leaves = [n for n in root.walk() if n.kind != "root" and n.is_leaf]
        if leaves:
            groups.append((root.account.name, leaves))
    return groups


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


def _load(accounts: AccountService, aid: UUID) -> tuple[list[Node], Node]:
    roots = build_tree(accounts.list())
    node = _find(roots, aid)
    if node is None:
        raise HTTPException(status_code=404, detail="account not found")
    return roots, node


def _root_of(roots: list[Node], node: Node) -> Node:
    return next(r for r in roots if any(n is node for n in r.walk()))


@router.get("")
def accounts_page(request: Request, accounts: Accounts):
    return templates.TemplateResponse(
        request, "accounts.html", {"active": "accounts", "roots": build_tree(accounts.list())}
    )


@router.get("/new")
def new_account_page(request: Request, accounts: Accounts, parent: UUID | None = None):
    roots = build_tree(accounts.list())
    return templates.TemplateResponse(
        request,
        "account_form.html",
        {
            "active": "accounts",
            "hide_fab": True,
            "node": None,
            "parent_id": parent,
            "parent_options": _parent_options(roots),
        },
    )


@router.get("/quick")
def quick_account_sheet(request: Request, accounts: Accounts, hint: str = ""):
    """The "new account" sheet shown over the transaction form."""
    roots = build_tree(accounts.list())
    suggested = next((r.account.aid for r in roots if r.account.name == hint), None)
    return templates.TemplateResponse(
        request,
        "partials/quick_account.html",
        {
            "parent_id": suggested,
            "parent_options": _parent_options(roots),
            "roots_by_id": {n.account.aid: r.account.name for r in roots for n in r.walk()},
        },
    )


@router.get("/options")
def account_options_list(request: Request, accounts: Accounts):
    """Fresh <option>s for the transaction form's account pickers."""
    return templates.TemplateResponse(
        request,
        "partials/account_options_list.html",
        {"groups": posting_groups(build_tree(accounts.list()))},
    )


@router.post("/quick")
def quick_create_account(
    accounts: Accounts,
    name: Annotated[str, Form()] = "",
    parent_id: Annotated[str, Form()] = "",
    balance: Annotated[str, Form()] = "",
):
    try:
        roots = build_tree(accounts.list())
        parent = _find(roots, UUID(parent_id)) if parent_id else None
        if parent is None:
            raise ValueError("choose where the account belongs!")
        name = name.strip()
        if any(child.account.name.casefold() == name.casefold() for child in parent.children):
            raise ValueError(f"'{parent.account.name}' already has an account named '{name}'. Pick it from the list instead!")
        root = _root_of(roots, parent)
        opening = parse_amount(balance, Decimal("0.00")) if root.account.name in OPENING_BALANCE_ROOTS else Decimal("0.00")
        created = accounts.create(AccountCreate(name=name, parent_id=parent.account.aid, balance=opening))
    except ValidationError as e:
        return htmx_error(validation_message(e), "#quick-error")
    except ValueError as e:
        return htmx_error(str(e), "#quick-error")
    return htmx_trigger("account-added", {"aid": str(created.aid), "name": created.name})


@router.post("")
def create_account(
    accounts: Accounts,
    name: Annotated[str, Form()] = "",
    parent_id: Annotated[str, Form()] = "",
    details: Annotated[str, Form()] = "",
    balance: Annotated[str, Form()] = "",
):
    try:
        if not parent_id:
            raise ValueError("choose where the account belongs!")
        data = AccountCreate(
            name=name.strip(),
            details=details.strip() or None,
            parent_id=UUID(parent_id),
            balance=parse_amount(balance, Decimal("0.00")),
        )
        created = accounts.create(data)
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/app/accounts/{created.aid}", flash="account-created")


@router.get("/{aid}")
def account_page(request: Request, aid: UUID, accounts: Accounts):
    roots, node = _load(accounts, aid)
    entries = accounts.register(aid) or []
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "active": "accounts",
            "node": node,
            "root": _root_of(roots, node),
            "entries": list(reversed(entries)),
            # Accounts with their own postings cannot gain sub-accounts.
            "can_add_child": node.kind != "system" and not (node.is_leaf and entries and node.kind != "root"),
        },
    )


@router.get("/{aid}/register")
def account_register(aid: UUID):
    return RedirectResponse(f"/app/accounts/{aid}", status_code=301)


@router.get("/{aid}/edit")
def edit_account_page(request: Request, aid: UUID, accounts: Accounts):
    roots, node = _load(accounts, aid)
    if node.kind != "user":
        raise HTTPException(status_code=404, detail="account not found")
    root = _root_of(roots, node)
    return templates.TemplateResponse(
        request,
        "account_form.html",
        {
            "active": "accounts",
            "hide_fab": True,
            "node": node,
            "parent_id": node.account.parent_id,
            "parent_options": [
                n for n in _parent_options(roots, exclude=node) if any(n is m for m in root.walk())
            ],
        },
    )


@router.post("/{aid}/edit")
def update_account(
    aid: UUID,
    accounts: Accounts,
    name: Annotated[str, Form()] = "",
    parent_id: Annotated[str, Form()] = "",
    details: Annotated[str, Form()] = "",
    balance: Annotated[str | None, Form()] = None,
):
    current = accounts.read(aid)
    if current is None:
        raise HTTPException(status_code=404, detail="account not found")

    try:
        changes: dict = {}
        if name.strip() != current.name:
            changes["name"] = name.strip()
        if (details.strip() or None) != current.details:
            changes["details"] = details.strip() or None
        if parent_id and UUID(parent_id) != current.parent_id:
            changes["parent_id"] = UUID(parent_id)
        if balance is not None and balance.strip():
            new_balance = parse_amount(balance)
            if new_balance != current.balance:
                changes["balance"] = new_balance
        if changes:
            accounts.update(aid, AccountUpdate(**changes))
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/app/accounts/{aid}", flash="account-updated")


@router.post("/{aid}/delete")
def delete_account(aid: UUID, accounts: Accounts):
    try:
        accounts.delete(aid)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect("/app/accounts", flash="account-deleted")

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from ...dependencies import Accounts, Profiles
from ...schemas import AccountCreate, AccountRead, AccountUpdate
from ...services.account import GROUP_POSTING_ROOT_NAMES, AccountService
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
    postable: bool = False
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

    def finish(node: Node, depth: int, parent_path: str = "", root_name: str = "") -> None:
        node.depth = depth
        node.postable = node.kind != "root" and (node.is_leaf or root_name in GROUP_POSTING_ROOT_NAMES)
        node.path = f"{parent_path} › {node.account.name}" if parent_path else node.account.name
        node.children.sort(key=lambda n: n.account.name.lower())
        for child in node.children:
            finish(child, depth + 1, node.path, root_name)

    roots.sort(key=lambda n: ROOT_ORDER.index(n.account.name) if n.account.name in ROOT_ORDER else len(ROOT_ORDER))
    for root in roots:
        finish(root, 0, root_name=root.account.name)
    return roots


def posting_groups(roots: list[Node]) -> list[tuple[str, list[Node]]]:
    """Accounts that transactions may post to, grouped by root."""
    groups = []
    for root in roots:
        postable = [n for n in root.walk() if n.postable]
        if postable:
            groups.append((root.account.name, postable))
    return groups


def _optional_amount(text: str) -> Decimal | None:
    return parse_amount(text) if text.strip() else None


def _find(roots: list[Node], aid: UUID) -> Node | None:
    return next((n for root in roots for n in root.walk() if n.account.aid == aid), None)


def _parent_options(
    roots: list[Node],
    limits: dict[str, int],
    exclude: Node | None = None,
    keep: UUID | None = None,
) -> list[Node]:
    """Accounts that may become a parent: system accounts are leaves by design and a
    parent must leave room for the new (or moved) subtree within the depth limit."""
    excluded = {n.account.aid for n in exclude.walk()} if exclude else set()
    below = (max(n.depth for n in exclude.walk()) - exclude.depth) if exclude else 0
    return [
        n
        for root in roots
        for n in root.walk()
        if n.kind != "system"
        and n.account.aid not in excluded
        and (n.depth + 1 + below <= limits.get(root.account.name, 0) or n.account.aid == keep)
    ]


def _load(accounts: AccountService, aid: UUID) -> tuple[list[Node], Node]:
    roots = build_tree(accounts.list())
    node = _find(roots, aid)
    if node is None:
        raise HTTPException(status_code=404, detail="account not found")
    return roots, node


def root_of_node(roots: list[Node], node: Node) -> str:
    return _root_of(roots, node).account.name


def _root_of(roots: list[Node], node: Node) -> Node:
    return next(r for r in roots if any(n is node for n in r.walk()))


@router.get("")
def accounts_page(request: Request, accounts: Accounts):
    return templates.TemplateResponse(
        request,
        "accounts.html",
        {"active": "accounts", "roots": build_tree(accounts.list()), "currency": accounts.default_currency().code},
    )


@router.get("/new")
def new_account_page(request: Request, accounts: Accounts, profiles: Profiles, parent: UUID | None = None):
    roots = build_tree(accounts.list())
    return templates.TemplateResponse(
        request,
        "account_form.html",
        {
            "active": "accounts",
            "hide_fab": True,
            "node": None,
            "parent_id": parent,
            "parent_options": _parent_options(roots, profiles.depth_limits()),
            "currency": accounts.default_currency().code,
            "opening_currency": accounts.opening_currency().code,
            "commodity_choices": accounts.commodity_choices(),
            "can_change_commodity": True,
        },
    )


@router.get("/quick")
def quick_account_sheet(request: Request, accounts: Accounts, profiles: Profiles, hint: str = ""):
    """The "new account" sheet shown over the transaction form."""
    roots = build_tree(accounts.list())
    suggested = next((r.account.aid for r in roots if r.account.name == hint), None)
    return templates.TemplateResponse(
        request,
        "partials/quick_account.html",
        {
            "parent_id": suggested,
            "parent_options": _parent_options(roots, profiles.depth_limits()),
            "roots_by_id": {n.account.aid: r.account.name for r in roots for n in r.walk()},
            "currency": accounts.default_currency().code,
            "opening_currency": accounts.opening_currency().code,
            "commodity_choices": accounts.commodity_choices(),
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
    commodity: Annotated[str, Form()] = "",
    balance_value: Annotated[str, Form()] = "",
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
        created = accounts.create(
            AccountCreate(
                name=name,
                parent_id=parent.account.aid,
                commodity=commodity.strip() or None,
                balance=opening,
                balance_value=_optional_amount(balance_value),
            )
        )
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
    commodity: Annotated[str, Form()] = "",
    balance_value: Annotated[str, Form()] = "",
):
    try:
        if not parent_id:
            raise ValueError("choose where the account belongs!")
        data = AccountCreate(
            name=name.strip(),
            details=details.strip() or None,
            parent_id=UUID(parent_id),
            commodity=commodity.strip() or None,
            balance=parse_amount(balance, Decimal("0.00")),
            balance_value=_optional_amount(balance_value),
        )
        created = accounts.create(data)
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/accounts/{created.aid}", flash="account-created")


@router.get("/{aid}")
def account_page(request: Request, aid: UUID, accounts: Accounts, profiles: Profiles):
    roots, node = _load(accounts, aid)
    entries = accounts.register(aid) or []
    root = _root_of(roots, node)
    limit = profiles.depth_limits()[root.account.name]
    at_limit = node.kind != "system" and node.depth >= limit
    # Asset and liability accounts with their own postings cannot gain sub-accounts.
    has_own_postings = node.is_leaf and bool(entries) and node.kind != "root"
    can_add_child = (
        node.kind != "system"
        and not at_limit
        and (not has_own_postings or root.account.name in GROUP_POSTING_ROOT_NAMES)
    )
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "active": "accounts",
            "node": node,
            "root": root,
            "entries": list(reversed(entries)),
            "currency": accounts.default_currency().code,
            "holding": accounts.holding(aid),
            "at_limit": at_limit,
            "depth_limit": limit,
            "can_add_child": can_add_child,
            # Part of a group's balance that was posted to the group itself.
            "direct": node.account.balance - sum((c.account.balance for c in node.children), Decimal("0.00"))
            if node.postable and node.children
            else None,
        },
    )


@router.get("/{aid}/register")
def account_register(aid: UUID):
    return RedirectResponse(f"/accounts/{aid}", status_code=301)


@router.get("/{aid}/edit")
def edit_account_page(request: Request, aid: UUID, accounts: Accounts, profiles: Profiles):
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
            "currency": accounts.default_currency().code,
            "opening_currency": accounts.opening_currency().code,
            "commodity_choices": accounts.commodity_choices(),
            "can_change_commodity": not accounts.has_postings(aid),
            "root_name": root.account.name,
            "can_budget": root.account.name in ("Assets", "Liabilities") and node.is_leaf,
            "on_budget": node.account.on_budget,
            "parent_options": [
                n
                for n in _parent_options(roots, profiles.depth_limits(), exclude=node, keep=node.account.parent_id)
                if any(n is m for m in root.walk())
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
    commodity: Annotated[str, Form()] = "",
    balance_value: Annotated[str, Form()] = "",
    on_budget: Annotated[str | None, Form()] = None,
    budget_choice: Annotated[str | None, Form()] = None,
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
        if commodity.strip() and commodity.strip().upper() != current.commodity:
            changes["commodity"] = commodity.strip()
        if balance is not None and balance.strip():
            new_balance = parse_amount(balance)
            if new_balance != current.balance:
                changes["balance"] = new_balance
                changes["balance_value"] = _optional_amount(balance_value)
        if budget_choice is not None and (on_budget is not None) != current.on_budget:
            changes["on_budget"] = on_budget is not None
        if changes:
            accounts.update(aid, AccountUpdate(**changes))
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/accounts/{aid}", flash="account-updated")


@router.post("/{aid}/delete")
def delete_account(aid: UUID, accounts: Accounts):
    try:
        accounts.delete(aid)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect("/accounts", flash="account-deleted")

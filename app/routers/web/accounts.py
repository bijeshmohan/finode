"""The Accounts page, an account's own page, and the forms that make, change, close, pin and delete accounts."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import ValidationError

from ...clock import local_today
from ...dependencies import Accounts, Categories
from ...schemas import AccountCreate, AccountUpdate
from ...schemas.account import GroupCreate
from ...services import cards
from ...services.account import (
    AccountService,
)
from ...services.account_tree import Node, build_tree, without_contacts
from ...services.accounts_view import account_page as account_page_view
from ...services.accounts_view import accounts_page, kind_groups, load
from ...services.accounts_view import find as find_node
from ...services.accounts_view import root_of as root_node
from ...services.accounts_view import starts as group_starts
from ...services.pickers import ACCOUNT_ROOTS, OPENING_BALANCE_ROOTS, category_groups, parent_options, posting_groups
from ...templating import templates
from .utils import htmx_error, htmx_redirect, htmx_trigger, parse_amount, validation_message

router = APIRouter(prefix="/accounts")

# Only these hold money the user already has (or owes) when an account is first added.


def _load(accounts: AccountService, account_id: UUID) -> tuple[list[Node], Node]:
    try:
        return load(accounts, account_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="account not found") from None


# Where the money is (the Accounts page); where it goes and comes from is a category (the Categories page).


# What a new group can hold, as the form words it, and the type it sits under.
HOLDS: dict[str, Literal["Assets", "Liabilities"]] = {"own": "Assets", "owe": "Liabilities"}


@router.get("")
def accounts_list_page(request: Request, accounts: Accounts):
    page = accounts_page(accounts, local_today())
    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "active": "accounts",
            "kinds": page.kinds,
            "pinned": page.pinned,
            "net_worth": page.net_worth,
            "notes": page.notes,
            "currency": accounts.currency().code,
            "closed": page.has_closed,
            "account_count": page.account_count,
            "has_budget_accounts": page.has_budget_accounts,
        },
    )


@router.get("/new-group")
def new_group_page(request: Request):
    """The form for a new group: a name, whether it holds money the person owns or owes, and what the accounts made in it
    start as. Nothing is chosen until the person does."""
    return templates.TemplateResponse(request, "group_form.html", {"active": "accounts", "hide_fab": True})


@router.post("/new-group")
def create_group(
    accounts: Accounts,
    name: Annotated[str, Form()] = "",
    holds: Annotated[str, Form()] = "",
    new_accounts_in_budget: Annotated[str | None, Form()] = None,
):
    try:
        root = HOLDS.get(holds)
        if root is None:
            raise ValueError("choose whether it holds money you own or money you owe!")
        accounts.create_group(
            GroupCreate(name=name, root=root, new_accounts_in_budget=new_accounts_in_budget is not None)
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect("/accounts", flash="group-created")


@router.get("/new")
def new_account_page(
    request: Request,
    accounts: Accounts,
    parent: UUID | None = None,
    root: str = "",
):
    """The form for a new account. It asks what kind it is (a built-in group or one the person made); nothing is chosen
    until the person does, unless the link says (a kind's own "Add account", or a type's)."""
    everything = without_contacts(build_tree(accounts.list()))
    roots = [r for r in everything if r.account.name in ACCOUNT_ROOTS]
    root_of = {n.account.id: r.account.name for r in roots for n in r.walk()}
    only = next((r.account.name for r in roots if r.account.name.lower() == root.lower()), None)
    if only and (parent is None or root_of.get(parent) != only):
        # Opened for plain accounts under a type: they sit directly under that type.
        parent = next(r.account.id for r in roots if r.account.name == only)
    groups = [g for g in kind_groups(roots) if g.account.closed_on is None]
    starts = group_starts(everything)
    chosen_root = root_of.get(parent) if parent else None
    return templates.TemplateResponse(
        request,
        "account_form.html",
        {
            "active": "accounts",
            "hide_fab": True,
            "starts": starts,
            "node": None,
            "parent_id": parent,
            "kinds": groups,
            "placed": _placed(groups, next((n for r in roots for n in r.walk() if n.account.id == parent), None)),
            "parent_options": _with_parent(groups, roots, parent),
            "currency": accounts.currency().code,
            "root_name": chosen_root,
            "root_of": root_of,
            "back_list": "/accounts",
            "can_budget": chosen_root in ("Assets", "Liabilities"),
            "can_bill": chosen_root == "Liabilities",
            # an asset starts in the budget; a card or loan, outside it; under a built-in group, as that group says
            "on_budget": (starts.get(parent) == "budget") if parent in starts else chosen_root == "Assets",
        },
    )


def _with_parent(groups: list[Node], roots: list[Node], parent: UUID | None) -> list[Node]:
    """The form's choices of where an account sits: the kinds, and the account's current parent when that is not a kind
    (a type itself, or an account it is being made inside), so saving never moves it by accident."""
    if parent is None or any(g.account.id == parent for g in groups):
        return groups
    found = next((n for r in roots for n in r.walk() if n.account.id == parent), None)
    return [*groups, *([found] if found else [])]


def _placed(groups: list[Node], parent: Node | None) -> tuple[str, str] | None:
    """When a new account is opened for somewhere that is not a kind, what the form says instead of the kind chips: "Other"
    for the plain accounts of a type, or the account it is made inside."""
    if parent is None or any(g.account.id == parent.account.id for g in groups):
        return None
    if parent.kind == "root":
        return ("Kind", "Other" if parent.account.name == "Assets" else "Other you owe")
    return ("Inside", parent.account.name)


@router.get("/quick")
def quick_account_sheet(request: Request, accounts: Accounts, categories: Categories, hint: str = ""):
    """The "new account" sheet shown over the transaction form (a "new category" sheet where the picker lists
    categories: the Expenses and Income kinds)."""
    if hint in ("Expenses", "Income"):
        kind = "spending" if hint == "Expenses" else "earning"
        groups = [c for c in categories.list(kind) if c.parent_id is None]
        return templates.TemplateResponse(request, "partials/quick_category.html", {"kind": kind, "groups": groups})
    roots = [r for r in without_contacts(build_tree(accounts.list())) if r.account.name in ACCOUNT_ROOTS]
    suggested = next((r.account.id for r in roots if r.account.name == hint), None)
    return templates.TemplateResponse(
        request,
        "partials/quick_account.html",
        {
            "parent_id": suggested,
            "parent_options": parent_options(roots),
            "roots_by_id": {n.account.id: r.account.name for r in roots for n in r.walk()},
            "currency": accounts.currency().code,
        },
    )


@router.get("/options")
def account_options_list(request: Request, accounts: Accounts, categories: Categories):
    """Fresh <option>s for the transaction form's account pickers (and the categories among them)."""
    return templates.TemplateResponse(
        request,
        "partials/account_options_list.html",
        {
            "groups": [
                *posting_groups(build_tree(accounts.list())),
                *category_groups(categories.list(include_closed=True)),
            ]
        },
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
        parent = find_node(roots, UUID(parent_id)) if parent_id else None
        if parent is None:
            raise ValueError("choose where the account belongs!")
        name = name.strip()
        if any(child.account.name.casefold() == name.casefold() for child in parent.children):
            raise ValueError(
                f"'{parent.account.name}' already has an account named '{name}'. Pick it from the list instead!"
            )
        root = root_node(roots, parent)
        opening = (
            parse_amount(balance, Decimal("0.00")) if root.account.name in OPENING_BALANCE_ROOTS else Decimal("0.00")
        )
        created = accounts.create(
            AccountCreate(
                name=name,
                parent_id=parent.account.id,
                balance=opening,
            )
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#quick-error")
    except ValueError as e:
        return htmx_error(str(e), "#quick-error")
    return htmx_trigger("account-added", {"id": str(created.id), "name": created.name})


def _bill_days(statement_day: str, due_day: str, bill_rounding: str = "none") -> dict:
    """The form's two days as numbers (both empty means none) and how the bill is rounded. Anything else is refused."""
    try:
        days = [int(v) if v.strip() else None for v in (statement_day, due_day)]
    except ValueError:
        raise ValueError("the statement day and the due day are numbers from 1 to 31!") from None
    return {"statement_day": days[0], "due_day": days[1], "bill_rounding": bill_rounding or "none"}


@router.post("")
def create_account(
    accounts: Accounts,
    name: Annotated[str, Form()] = "",
    parent_id: Annotated[str, Form()] = "",
    details: Annotated[str, Form()] = "",
    balance: Annotated[str, Form()] = "",
    on_budget: Annotated[str | None, Form()] = None,
    budget_choice: Annotated[str | None, Form()] = None,
    bill_choice: Annotated[str | None, Form()] = None,
    statement_day: Annotated[str, Form()] = "",
    due_day: Annotated[str, Form()] = "",
    bill_rounding: Annotated[str, Form()] = "none",
):
    try:
        if not parent_id:
            raise ValueError("choose what kind of account it is!")
        data = AccountCreate(
            name=name.strip(),
            details=details.strip() or None,
            parent_id=UUID(parent_id),
            balance=parse_amount(balance, Decimal("0.00")),
            # The form asked (budget_choice): its box says yes or no. Without it the default applies (an asset: yes).
            on_budget=None if budget_choice is None else on_budget is not None,
            **(_bill_days(statement_day, due_day, bill_rounding) if bill_choice is not None else {}),
        )
        created = accounts.create(data)
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/accounts/{created.id}", flash="account-created")


def account_context(accounts: AccountService, account_id: UUID, offset: int = 0) -> dict:
    """What the account page needs (services/accounts_view.account_page), as the templates read it."""
    try:
        page = account_page_view(accounts, account_id, local_today(), offset)
    except LookupError:
        raise HTTPException(status_code=404, detail="account not found") from None
    return {
        "active": "accounts",
        "notes": page.notes,
        "cards": page.cards,
        "bill": page.bill,
        "due_soon_days": cards.DUE_SOON_DAYS,
        "can_set_days": page.can_set_days,
        "new_transaction_url": page.new_transaction_url,
        "node": page.node,
        "root": page.root,
        "sub": page.sub,
        "entries": page.entries,
        "has_more": page.has_more,
        "next_offset": page.next_offset,
        "upcoming": page.upcoming,
        "upcoming_total": page.upcoming_total,
        "balance_after": page.balance_after,
        "currency": accounts.currency().code,
        "can_add_child": page.can_add_child,
        "can_pin": page.can_pin,
        "direct": page.direct,
    }


@router.get("/{account_id}")
def account_page(request: Request, account_id: UUID, accounts: Accounts):
    return templates.TemplateResponse(request, "account.html", account_context(accounts, account_id))


@router.post("/{account_id}/close")
def close_account(account_id: UUID, accounts: Accounts):
    try:
        accounts.close(account_id)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect("/accounts", flash="account-closed")


@router.post("/{account_id}/pin")
def pin_account(account_id: UUID, accounts: Accounts):
    try:
        accounts.update(account_id, AccountUpdate(pinned=True))
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect(f"/accounts/{account_id}", flash="account-pinned")


@router.post("/{account_id}/unpin")
def unpin_account(account_id: UUID, accounts: Accounts):
    try:
        accounts.update(account_id, AccountUpdate(pinned=False))
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect(f"/accounts/{account_id}", flash="account-unpinned")


@router.post("/{account_id}/reopen")
def reopen_account(account_id: UUID, accounts: Accounts):
    try:
        accounts.reopen(account_id)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect(f"/accounts/{account_id}", flash="account-reopened")


@router.get("/{account_id}/more")
def account_more(request: Request, account_id: UUID, accounts: Accounts, offset: int = 0):
    """The next chunk of an account's transactions (htmx replaces the "Load more" button with it)."""
    context = account_context(accounts, account_id, offset=max(offset, 0))
    return templates.TemplateResponse(request, "partials/account_entries.html", {**context, "area": "/accounts"})


@router.get("/{account_id}/edit")
def edit_account_page(request: Request, account_id: UUID, accounts: Accounts):
    roots, node = _load(accounts, account_id)
    if node.kind != "user":
        raise HTTPException(status_code=404, detail="account not found")
    root = root_node(roots, node)
    mine = [g for g in kind_groups([root]) if not node.is_group and g.account.closed_on is None]
    return templates.TemplateResponse(
        request,
        "account_form.html",
        {
            "active": "accounts",
            "hide_fab": True,
            "node": node,
            "parent_id": node.account.parent_id,
            "currency": accounts.currency().code,
            "root_name": root.account.name,
            "can_budget": root.account.name in ("Assets", "Liabilities") and not node.is_group,
            "can_bill": root.account.name == "Liabilities" and not node.is_group,
            "on_budget": node.account.on_budget,
            "starts": group_starts(roots),
            # Where it sits is a kind; a group (an account with accounts inside) stays where it is.
            "kinds": mine,
            "parent_options": [] if node.is_group else _with_parent(mine, [root], node.account.parent_id),
        },
    )


@router.post("/{account_id}/edit")
def update_account(
    account_id: UUID,
    accounts: Accounts,
    name: Annotated[str, Form()] = "",
    parent_id: Annotated[str, Form()] = "",
    details: Annotated[str, Form()] = "",
    balance: Annotated[str | None, Form()] = None,
    on_budget: Annotated[str | None, Form()] = None,
    budget_choice: Annotated[str | None, Form()] = None,
    bill_choice: Annotated[str | None, Form()] = None,
    statement_day: Annotated[str, Form()] = "",
    due_day: Annotated[str, Form()] = "",
    bill_rounding: Annotated[str, Form()] = "none",
    group_choice: Annotated[str | None, Form()] = None,
    new_accounts_in_budget: Annotated[str | None, Form()] = None,
):
    current = accounts.read(account_id)
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
        if budget_choice is not None and (on_budget is not None) != current.on_budget:
            changes["on_budget"] = on_budget is not None
        if group_choice is not None and (new_accounts_in_budget is not None) != current.new_accounts_in_budget:
            changes["new_accounts_in_budget"] = new_accounts_in_budget is not None
        if bill_choice is not None:
            days = _bill_days(statement_day, due_day, bill_rounding)
            if days != {
                "statement_day": current.statement_day,
                "due_day": current.due_day,
                "bill_rounding": current.bill_rounding,
            }:
                changes.update(days)
        if changes:
            accounts.update(account_id, AccountUpdate(**changes))
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/accounts/{account_id}", flash="account-updated")


@router.post("/{account_id}/delete")
def delete_account(account_id: UUID, accounts: Accounts):
    try:
        accounts.delete(account_id)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect("/accounts", flash="account-deleted")

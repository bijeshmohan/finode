from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from ...dependencies import Accounts, Profiles
from ...schemas import AccountCreate, AccountRead, AccountUpdate
from ...services.account import FIXED_DEFAULTS, GROUP_POSTING_ROOT_NAMES, MAX_ACCOUNT_DEPTH, AccountInUseError, AccountService, RegisterPage
from ...templating import templates
from .utils import UpcomingItem, htmx_error, htmx_redirect, htmx_trigger, parse_amount, validation_message
from ...clock import local_day, local_today


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
    # For the accounts page: whether the account is closed (closed ones wait behind "Load more").
    closed: bool = False

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
            elif node.account.system_key:
                node.kind = "fixed"  # a built-in group (Bank Accounts, Cash, Investments, Credit Cards, Loans)

    def finish(node: Node, depth: int, parent_path: str = "", root_name: str = "") -> None:
        node.depth = depth
        node.postable = node.kind not in ("root", "fixed") and (node.is_leaf or root_name in GROUP_POSTING_ROOT_NAMES)
        node.path = f"{parent_path} › {node.account.name}" if parent_path else node.account.name
        node.children.sort(key=lambda n: AccountService.order_key(n.account))
        for child in node.children:
            finish(child, depth + 1, node.path, root_name)

    roots.sort(key=lambda n: ROOT_ORDER.index(n.account.name) if n.account.name in ROOT_ORDER else len(ROOT_ORDER))
    for root in roots:
        finish(root, 0, root_name=root.account.name)
    return roots


def posting_groups(roots: list[Node], keep: set[UUID] = frozenset()) -> list[tuple[str, list[Node]]]:
    """Accounts that transactions may post to, grouped by root. Closed accounts are left out, except those in
    `keep` (what an entry being edited already uses)."""
    groups = []
    for root in roots:
        postable = [n for n in root.walk() if n.postable and (n.account.closed_on is None or n.account.aid in keep)]
        if postable:
            groups.append((root.account.name, postable))
    return groups


def _find(roots: list[Node], aid: UUID) -> Node | None:
    return next((n for root in roots for n in root.walk() if n.account.aid == aid), None)


CATEGORY_TABS = {"expense": "Expenses", "income": "Income"}


def _parent_options(
    roots: list[Node],
    exclude: Node | None = None,
    keep: UUID | None = None,
) -> list[Node]:
    """Accounts that may become a parent: system accounts are leaves by design and a
    parent must leave room for the new (or moved) subtree within two levels."""
    excluded = {n.account.aid for n in exclude.walk()} if exclude else set()
    below = (max(n.depth for n in exclude.walk()) - exclude.depth) if exclude else 0
    return [
        n
        for root in roots
        for n in root.walk()
        if n.kind != "system"
        and n.account.aid not in excluded
        and (n.depth + 1 + below <= MAX_ACCOUNT_DEPTH or n.account.aid == keep)
    ]


def _starts(roots: list[Node]) -> dict[UUID, str]:
    """For each built-in group, how an account made under it starts: "budget" (part of the budget) or "outside" it."""
    return {n.account.aid: FIXED_DEFAULTS[n.account.system_key] for r in roots for n in r.walk() if n.account.system_key in FIXED_DEFAULTS}


def _load(accounts: AccountService, aid: UUID) -> tuple[list[Node], Node]:
    roots = build_tree(accounts.list())
    node = _find(roots, aid)
    if node is None:
        raise HTTPException(status_code=404, detail="account not found")
    return roots, node


def _category_options(roots: list[Node]) -> list[tuple[UUID, str]]:
    """The expense categories a payment-category choice may name: (aid, path below Expenses)."""
    return [
        (n.account.aid, n.path.split(" › ", 1)[1])
        for r in roots
        if r.account.name == "Expenses"
        for n in r.walk()
        if n.account.parent_id is not None
    ]


def _root_of(roots: list[Node], node: Node) -> Node:
    return next(r for r in roots if any(n is node for n in r.walk()))


# Where the money is (the Accounts page) and where it goes and comes from (the Categories page).
ACCOUNT_ROOTS = ("Assets", "Liabilities", "Equity")
CATEGORY_ROOTS = ("Expenses", "Income")


# The chips on the accounts page, in this order (?tab=): each shows one type of account.
ACCOUNT_TABS = {"assets": "Assets", "liabilities": "Liabilities", "equity": "Equity"}
# What the chips say: one kind of account, in the singular (the roots themselves keep their names).
ACCOUNT_CHIP_NAMES = {"assets": "Asset", "liabilities": "Liability", "equity": "Equity"}


@router.get("")
def accounts_page(request: Request, accounts: Accounts, tab: str = "assets"):
    tab = tab.lower() if tab.lower() in ACCOUNT_TABS else "assets"
    roots = [r for r in build_tree(accounts.list()) if r.account.name in ACCOUNT_ROOTS]
    mark_closed(roots)
    root = next(r for r in roots if r.account.name == ACCOUNT_TABS[tab])
    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "active": "accounts",
            "tab": tab,
            "tabs": ACCOUNT_TABS,
            "chip_names": ACCOUNT_CHIP_NAMES,
            "root": root,
            "blocks": page_blocks(root),
            "currency": accounts.currency().code,
            "closed": closed_count([root]),
            # What the quiet line under the figure counts: the open accounts of the type (groups are only headings).
            "account_count": sum(1 for n in root.walk() if n.account.closed_on is None and n.depth > 0 and not n.children),
        },
    )


def page_blocks(root: Node) -> list[tuple[Node | None, list[Node]]]:
    """A type's accounts as the page lists them: each group is a heading with its accounts under it, then **all** the plain
    accounts that sit directly under the type together in one block without a heading, at the end. Accounts only go two
    levels deep. A built-in group with nothing in it is not shown (the page offers "Add account" instead)."""
    blocks: list[tuple[Node | None, list[Node]]] = []
    plain: list[Node] = []
    for child in root.children:
        if child.children:
            blocks.append((child, child.children))
        elif child.kind != "fixed":
            plain.append(child)
    if plain:
        blocks.append((None, plain))
    return blocks


def mark_closed(roots: list[Node]) -> None:
    """Flag the closed accounts: the accounts page lists every open account, and keeps the closed ones behind "Load more"."""
    for root in roots:
        for node in root.walk():
            node.closed = node.account.closed_on is not None


def closed_count(roots: list[Node]) -> int:
    return sum(1 for root in roots for n in root.walk() if n.closed)


@router.get("/new")
def new_account_page(request: Request, accounts: Accounts, profiles: Profiles, parent: UUID | None = None, kind: str = "account", root: str = ""):
    """The form for a new account (under Assets or Liabilities), or with kind=category for a new category
    (under Expenses or Income, reached from the Categories page)."""
    kind = "category" if kind == "category" else "account"
    allowed = CATEGORY_ROOTS if kind == "category" else ACCOUNT_ROOTS
    everything = build_tree(accounts.list())
    roots = [r for r in everything if r.account.name in allowed]
    root_of = {n.account.aid: r.account.name for r in roots for n in r.walk()}
    only = (ACCOUNT_TABS if kind == "account" else CATEGORY_TABS).get(root.lower())
    if only:
        # Opened from a type's tab on the Accounts or Categories page: only that type's accounts can be made.
        parent_roots = [r for r in roots if r.account.name == only]
        if parent is None or root_of.get(parent) != only:
            parent = parent_roots[0].account.aid if parent_roots else None
            first_group = next((c for c in parent_roots[0].children if c.kind == "fixed"), None) if parent_roots else None
            if first_group is not None:
                parent = first_group.account.aid  # the "+" on a type starts on its first built-in group (Bank Accounts, Credit Cards)
    else:
        parent_roots = roots
    starts = _starts(everything)
    return templates.TemplateResponse(
        request,
        "account_form.html",
        {
            "active": "categories" if kind == "category" else "accounts",
            "kind": kind,
            "hide_fab": True,
            "starts": starts,
            "node": None,
            "parent_id": parent,
            "parent_options": _parent_options(parent_roots),
            "currency": accounts.currency().code,
            "root_name": root_of.get(parent),
            "root_of": root_of,
            "back_list": _list_for_root(root_of.get(parent)),
            "can_budget": root_of.get(parent) in ("Assets", "Liabilities"),
            # an asset starts in the budget; a card or loan, outside it; under a built-in group, as that group says
            "on_budget": (starts.get(parent) == "budget") if parent in starts else root_of.get(parent) == "Assets",
            "category_options": _category_options(everything),
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
            "parent_options": _parent_options(roots),
            "roots_by_id": {n.account.aid: r.account.name for r in roots for n in r.walk()},
            "currency": accounts.currency().code,
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
        created = accounts.create(
            AccountCreate(
                name=name,
                parent_id=parent.account.aid,
                balance=opening,
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
    on_budget: Annotated[str | None, Form()] = None,
    budget_choice: Annotated[str | None, Form()] = None,
    payment_category: Annotated[str, Form()] = "",
):
    try:
        if not parent_id:
            raise ValueError("choose where the account belongs!")
        data = AccountCreate(
            name=name.strip(),
            details=details.strip() or None,
            parent_id=UUID(parent_id),
            balance=parse_amount(balance, Decimal("0.00")),
            # The form asked (budget_choice): its box says yes or no. Without it the default applies (an asset: yes).
            on_budget=None if budget_choice is None else on_budget is not None,
            payment_category_id=None if on_budget is not None or not payment_category.strip() else UUID(payment_category.strip()),
        )
        created = accounts.create(data)
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/accounts/{created.aid}", flash="account-created")


def _is_inflow(root_name: str, change: Decimal) -> bool:
    """Money coming in, as an account's page marks it (green, "+"): what raises an asset account, and a payment into a
    liability (a card or loan), which lowers what is owed. A charge on a card is plain."""
    return (root_name == "Assets" and change > 0) or (root_name == "Liabilities" and change < 0)


def account_context(accounts: AccountService, profiles, aid: UUID, entries=None, offset: int = 0) -> dict:
    """What the account page needs; the category page (categories.py) reuses it with its month's entries."""
    roots, node = _load(accounts, aid)
    root = _root_of(roots, node)
    today = local_today()
    page = None
    if entries is None and (node.children or node.kind == "fixed"):
        # An account with sub-accounts cannot be posted to: its page lists the sub-accounts, whose entries are on their own pages.
        history, ahead, has_any = [], [], False
    elif entries is None:
        # An account's own page reads only its newest entries (and what is dated ahead); a category passes its month's.
        page = accounts.register_page(aid, today, offset) or RegisterPage([], [], 0, 0, False, False)
        history, ahead, has_any = page.entries, page.upcoming, page.has_any
    else:
        history = list(reversed([e for e in entries if e.date <= today]))
        ahead = [e for e in sorted((e for e in entries if e.date > today), key=lambda e: e.date)]
        has_any = bool(entries)
    # What is dated ahead is not history: it waits in its own card, soonest first, and out of the running list.
    upcoming = [
        UpcomingItem(e.tid, e.date, e.payee or ", ".join(e.counter_accounts), (", ".join(e.counter_accounts) if e.payee else "") + (f" \u00b7 {e.comment}" if e.comment and e.payee else e.comment or ""), abs(e.change), _is_inflow(root.account.name, e.change))
        for e in ahead
    ]
    signs = {e.change > 0 for e in ahead}
    upcoming_total = sum((u.amount for u in upcoming), Decimal("0.00")) if upcoming and len(signs) == 1 else None
    at_limit = node.kind != "system" and node.depth >= MAX_ACCOUNT_DEPTH
    # Asset and liability accounts with their own postings cannot gain sub-accounts.
    has_own_postings = node.is_leaf and has_any and node.kind != "root"
    can_add_child = (
        node.kind != "system"
        and not at_limit
        and (not has_own_postings or root.account.name in GROUP_POSTING_ROOT_NAMES)
    )
    return {
        "active": "accounts",
        "node": node,
        "root": root,
        "entries": history,
        "has_more": page.has_more if page else False,
        "next_offset": page.next_offset if page else 0,
        "upcoming": upcoming,
        "upcoming_total": upcoming_total,
        "is_inflow": lambda change: _is_inflow(root.account.name, change),
        "currency": accounts.currency().code,
        "can_add_child": can_add_child,
        # Part of a group's balance that was posted to the group itself.
        "direct": node.account.balance - sum((c.account.balance for c in node.children), Decimal("0.00"))
        if node.postable and node.children
        else None,
    }


def deleted_page(request: Request, accounts: Accounts, area: str):
    """Closed and deleted accounts (`area` "accounts") or categories ("categories"), newest first, each with Restore."""
    roots = ACCOUNT_ROOTS if area == "accounts" else CATEGORY_ROOTS
    closed = [dict(c, kind="closed", when=c["closed_on"]) for c in accounts.closed() if c["root"] in roots]
    gone = [dict(d, kind="deleted", when=local_day(d["at"])) for d in accounts.restorable() if d["root"] in roots]
    entries = sorted(closed + gone, key=lambda e: e["when"], reverse=True)
    return templates.TemplateResponse(
        request,
        "accounts_deleted.html",
        {"active": "settings", "area": area, "entries": entries},
    )


@router.get("/deleted")
def deleted_accounts_page(request: Request, accounts: Accounts):
    return deleted_page(request, accounts, "accounts")


@router.post("/deleted/{did}/restore")
def restore_deleted_account(did: UUID, accounts: Accounts):
    try:
        restored = accounts.restore_deleted(did)
    except LookupError:
        return htmx_error("That deleted account is not there any more.", "#restore-error", status_code=404)
    except ValueError as e:
        return htmx_error(str(e), "#restore-error")
    category = area_of(accounts, restored.aid) == "/categories"
    return htmx_redirect(f"/accounts/{restored.aid}", flash="category-restored" if category else "account-restored")


@router.get("/{aid}")
def account_page(request: Request, aid: UUID, accounts: Accounts, profiles: Profiles):
    roots, node = _load(accounts, aid)
    root = _root_of(roots, node)
    if root.account.name in CATEGORY_ROOTS and node.kind != "root":
        return RedirectResponse(f"/categories/{aid}", status_code=303)
    return templates.TemplateResponse(request, "account.html", account_context(accounts, profiles, aid))


def area_of(accounts: AccountService, aid: UUID) -> str:
    """Where an account's pages live: categories (Expenses, Income) have their own tab."""
    roots = build_tree(accounts.list())
    node = _find(roots, aid)
    return "/categories" if node is not None and _root_of(roots, node).account.name in CATEGORY_ROOTS else "/accounts"


def _list_for_root(root: str | None) -> str:
    """The list a root's accounts are on, on the chip they are under (so going back lands where the person came from)."""
    if root in CATEGORY_ROOTS:
        return "/categories" + ("?tab=income" if root == "Income" else "")
    return f"/accounts?tab={root.lower()}" if root in ACCOUNT_TABS.values() else "/accounts"


def list_url(accounts: AccountService, aid: UUID) -> str:
    roots = build_tree(accounts.list())
    node = _find(roots, aid)
    return _list_for_root(_root_of(roots, node).account.name if node is not None else None)


@router.post("/{aid}/close")
def close_account(aid: UUID, accounts: Accounts):
    area = list_url(accounts, aid)
    try:
        accounts.close(aid)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect(area, flash="account-closed")


@router.post("/{aid}/reopen")
def reopen_account(aid: UUID, accounts: Accounts):
    category = area_of(accounts, aid) == "/categories"
    try:
        accounts.reopen(aid)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect(f"/accounts/{aid}", flash="category-restored" if category else "account-reopened")


@router.get("/{aid}/more")
def account_more(request: Request, aid: UUID, accounts: Accounts, profiles: Profiles, offset: int = 0):
    """The next chunk of an account's transactions (htmx replaces the "Load more" button with it)."""
    context = account_context(accounts, profiles, aid, None, offset=max(offset, 0))
    return templates.TemplateResponse(request, "partials/account_entries.html", {**context, "category": False, "area": "/accounts"})


@router.get("/{aid}/edit")
def edit_account_page(request: Request, aid: UUID, accounts: Accounts, profiles: Profiles):
    roots, node = _load(accounts, aid)
    if node.kind != "user":
        raise HTTPException(status_code=404, detail="account not found")
    root = _root_of(roots, node)
    kind = "category" if root.account.name in CATEGORY_ROOTS else "account"
    return templates.TemplateResponse(
        request,
        "account_form.html",
        {
            "active": "categories" if kind == "category" else "accounts",
            "kind": kind,
            "hide_fab": True,
            "node": node,
            "parent_id": node.account.parent_id,
            "currency": accounts.currency().code,
            "root_name": root.account.name,
            "can_budget": root.account.name in ("Assets", "Liabilities") and node.is_leaf,
            "on_budget": node.account.on_budget,
            "payment_category_id": node.account.payment_category_id,
            "starts": _starts(roots),
            "category_options": _category_options(roots),
            "parent_options": [
                n
                for n in _parent_options(roots, exclude=node, keep=node.account.parent_id)
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
    on_budget: Annotated[str | None, Form()] = None,
    budget_choice: Annotated[str | None, Form()] = None,
    payment_category: Annotated[str, Form()] = "",
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
        if budget_choice is not None and (on_budget is not None) != current.on_budget:
            changes["on_budget"] = on_budget is not None
        if budget_choice is not None:
            wanted = None if on_budget is not None or not payment_category.strip() else UUID(payment_category.strip())
            if wanted != current.payment_category_id:
                changes["payment_category_id"] = wanted
        if changes:
            accounts.update(aid, AccountUpdate(**changes))
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/accounts/{aid}", flash="account-updated")


@router.post("/{aid}/delete")
def delete_account(aid: UUID, accounts: Accounts):
    area = area_of(accounts, aid)
    where = list_url(accounts, aid)
    try:
        accounts.delete(aid)
    except ValueError as e:
        if area != "/categories" or not isinstance(e, AccountInUseError):
            return htmx_error(str(e), "#page-error")
        # A category with entries (or subcategories) cannot vanish from the history: it leaves every list and
        # picker instead, and its past stays in the reports.
        try:
            accounts.close(aid)
        except ValueError as closing:
            return htmx_error(str(closing), "#page-error")
    return htmx_redirect(where, flash="category-deleted" if area == "/categories" else "account-deleted")

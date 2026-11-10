from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import ValidationError

from ...clock import local_today
from ...dependencies import Accounts, Categories
from ...schemas import AccountCreate, AccountRead, AccountUpdate
from ...schemas.account import GroupCreate, RegisterEntry
from ...schemas.category import CategoryRead
from ...services import cards
from ...services.account import (
    GROUP_POSTING_ROOT_NAMES,
    MAX_ACCOUNT_DEPTH,
    AccountService,
    RegisterPage,
)
from ...templating import templates
from .utils import UpcomingItem, htmx_error, htmx_redirect, htmx_trigger, parse_amount, validation_message

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
    children: list[Node] = field(default_factory=list)
    # For the accounts page: whether the account is closed (closed ones wait behind "Load more").
    closed: bool = False

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def is_group(self) -> bool:
        """A shelf for accounts: a built-in group or one the person made (even empty), or an account with accounts in it."""
        return self.account.new_accounts_in_budget is not None or bool(self.children)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def build_tree(accounts: list[AccountRead]) -> list[Node]:
    """The accounts as a tree."""
    nodes = {a.id: Node(a) for a in accounts}
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
        node.postable = (
            node.kind not in ("root", "fixed")
            and node.account.new_accounts_in_budget is None
            and (node.is_leaf or root_name in GROUP_POSTING_ROOT_NAMES)
        )
        node.path = f"{parent_path} › {node.account.name}" if parent_path else node.account.name
        node.children.sort(key=lambda n: AccountService.order_key(n.account))
        for child in node.children:
            finish(child, depth + 1, node.path, root_name)

    roots.sort(key=lambda n: ROOT_ORDER.index(n.account.name) if n.account.name in ROOT_ORDER else len(ROOT_ORDER))
    for root in roots:
        finish(root, 0, root_name=root.account.name)
    return roots


@dataclass
class PickOption:
    """One choice in an account or category picker: what it is called (below its type: "Banks › HDFC",
    "Food › Groceries"), and for an account its budget flag and balance."""

    id: UUID
    label: str
    budget: bool = False
    balance: Decimal | None = None


PickGroups = list[tuple[str, list[PickOption]]]


def without_contacts(roots: list[Node]) -> list[Node]:
    """The tree without a contact's "Due from" and "Due to" accounts: they belong to the People pages, not to the Accounts
    page or the pickers."""
    for node in roots:
        node.children = [c for c in node.children if not c.account.contact_account]
        without_contacts(node.children)
    return roots


def posting_groups(roots: list[Node], keep: Collection[UUID] = frozenset()) -> PickGroups:
    """Accounts that transactions may post to, grouped by root. Closed accounts are left out, except those in
    `keep` (what an entry being edited already uses)."""
    groups: PickGroups = []
    for root in roots:
        options = [
            PickOption(
                n.account.id,
                n.path.split(" › ", 1)[1] if " › " in n.path else n.path,
                budget=n.account.on_budget,
                balance=n.account.balance,
            )
            for n in root.walk()
            if n.postable and not n.account.contact_account and (n.account.closed_on is None or n.account.id in keep)
        ]
        if options:
            groups.append((root.account.name, options))
    return groups


def _category_options(
    category: CategoryRead, by_parent: dict[UUID | None, list[CategoryRead]], label: str
) -> list[PickOption]:
    options = [PickOption(category.id, label)]
    for child in by_parent.get(category.id, []):
        options += _category_options(child, by_parent, f"{label} › {child.name}")
    return options


def category_groups(categories: list[CategoryRead], keep: Collection[UUID] = frozenset()) -> PickGroups:
    """The categories an entry's lines may be labelled with, grouped as Income and Expenses (each with its categories
    and subcategories), for the same pickers as the accounts. Closed categories are left out, except those in `keep`
    (what an entry being edited already uses)."""
    found: PickGroups = []
    for root, kind in (("Income", "earning"), ("Expenses", "spending")):
        mine = [c for c in categories if c.kind == kind and (c.closed_on is None or c.id in keep)]
        by_parent: dict[UUID | None, list[CategoryRead]] = {}
        for c in sorted(mine, key=lambda c: c.name.lower()):
            by_parent.setdefault(c.parent_id, []).append(c)
        options: list[PickOption] = []
        for top in by_parent.get(None, []):
            options += _category_options(top, by_parent, top.name)
        if options:
            found.append((root, options))
    return found


def _find(roots: list[Node], account_id: UUID) -> Node | None:
    return next((n for root in roots for n in root.walk() if n.account.id == account_id), None)


def _parent_options(
    roots: list[Node],
    exclude: Node | None = None,
    keep: UUID | None = None,
) -> list[Node]:
    """Accounts that may become a parent: system accounts are leaves by design and a
    parent must leave room for the new (or moved) subtree within two levels."""
    excluded = {n.account.id for n in exclude.walk()} if exclude else set()
    below = (max(n.depth for n in exclude.walk()) - exclude.depth) if exclude else 0
    return [
        n
        for root in roots
        for n in root.walk()
        if n.kind != "system"
        and n.account.id not in excluded
        and (n.depth + 1 + below <= MAX_ACCOUNT_DEPTH or n.account.id == keep)
    ]


def _starts(roots: list[Node]) -> dict[UUID, str]:
    """For each group, how an account made in it starts: "budget" (part of the budget) or "outside" it."""
    return {
        n.account.id: "budget" if n.account.new_accounts_in_budget else "outside"
        for r in roots
        for n in r.walk()
        if n.account.new_accounts_in_budget is not None
    }


def _load(accounts: AccountService, account_id: UUID) -> tuple[list[Node], Node]:
    roots = build_tree(accounts.list())
    node = _find(roots, account_id)
    if node is None:
        raise HTTPException(status_code=404, detail="account not found")
    return roots, node


def _root_of(roots: list[Node], node: Node) -> Node:
    return next(r for r in roots if any(n is node for n in r.walk()))


# Where the money is (the Accounts page); where it goes and comes from is a category (the Categories page).
ACCOUNT_ROOTS = ("Assets", "Liabilities", "Equity")


# What a new group can hold, as the form words it, and the type it sits under.
HOLDS: dict[str, Literal["Assets", "Liabilities"]] = {"own": "Assets", "owe": "Liabilities"}

# An account whose newest entry is older than this says so on its card; a newer one has nothing to add.
STALE_DAYS = 30

# The kinds the Accounts page lists, in this order; a group the person made follows them, then the plain accounts.
KIND_ORDER = ("assets.bank", "assets.cash", "liabilities.cards", "assets.investments", "liabilities.loans")


@dataclass
class Kind:
    """One row of cards on the Accounts page: a kind of account (Bank Accounts, Credit Cards...) and its accounts."""

    name: str
    root: str  # Assets or Liabilities: a liability reads "owed"
    items: list[Node]
    total: Decimal
    group_id: UUID | None = None  # the group; none for the plain accounts that sit directly under a type
    closed: bool = False  # the group itself was closed

    @property
    def owed(self) -> bool:
        return self.root == "Liabilities"

    @property
    def add_url(self) -> str:
        return f"/accounts/new?parent={self.group_id}" if self.group_id else f"/accounts/new?root={self.root.lower()}"


def kind_groups(roots: list[Node]) -> list[Node]:
    """The groups an account can be made under (the form's Kind chips, the page's rows): the built-in ones in the page's
    order, then the ones the person made."""
    found = [
        child
        for root in roots
        if root.account.name in ("Assets", "Liabilities")
        for child in root.children
        if child.is_group
    ]
    place = {key: i for i, key in enumerate(KIND_ORDER)}
    return sorted(found, key=lambda n: (place.get(n.account.system_key or "", len(place)), n.account.name.lower()))


def kinds(roots: list[Node]) -> list[Kind]:
    """The accounts as the page lists them: a kind per group (an empty one too), then the plain accounts that sit
    directly under Assets or Liabilities."""
    root_of = {id(n): r.account.name for r in roots for n in r.walk()}
    found = [
        Kind(
            g.account.name, root_of[id(g)], g.children, g.account.balance, g.account.id, g.account.closed_on is not None
        )
        for g in kind_groups(roots)
    ]
    for root in roots:
        loose = [c for c in root.children if c.kind != "fixed" and not c.children]
        if loose and root.account.name in ("Assets", "Liabilities"):
            name = "Other" if root.account.name == "Assets" else "Other you owe"
            found.append(Kind(name, root.account.name, loose, sum((n.account.balance for n in loose), Decimal("0.00"))))
    return found


@router.get("")
def accounts_page(request: Request, accounts: Accounts):
    roots = without_contacts(build_tree(accounts.list()))
    mark_closed(roots)
    shown = [r for r in roots if r.account.name in ("Assets", "Liabilities")]
    balance = {r.account.name: r.account.balance for r in shown}
    leaves = [n for r in shown for n in r.walk() if n.depth > 0 and not n.is_group]
    last, bills = accounts.glance(local_today())
    rows = kinds(shown)
    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "active": "accounts",
            "kinds": rows,
            # The accounts the person pinned, in the order of the rows below (the same cards again, no totals).
            "pinned": [n for k in rows for n in k.items if n.account.pinned and not n.closed],
            "net_worth": balance.get("Assets", Decimal("0.00")) - balance.get("Liabilities", Decimal("0.00")),
            "last_entry": last,
            "bills": bills,
            "due_soon_days": cards.DUE_SOON_DAYS,
            "stale_before": local_today() - timedelta(days=STALE_DAYS),
            "currency": accounts.currency().code,
            "closed": any(n.closed for n in leaves),
            # What the quiet line under the figure counts: the open accounts.
            "account_count": sum(1 for n in leaves if not n.closed),
            # Whether any open account feeds the budget: the line under the figure then explains the dot beside them.
            "has_budget_accounts": any(n.account.on_budget and not n.closed for n in leaves),
        },
    )


def mark_closed(roots: list[Node]) -> None:
    """Flag the closed accounts: the accounts page lists every open account, and keeps the closed ones behind "Load more"."""
    for root in roots:
        for node in root.walk():
            node.closed = node.account.closed_on is not None


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
    starts = _starts(everything)
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
            "parent_options": _parent_options(roots),
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
        parent = _find(roots, UUID(parent_id)) if parent_id else None
        if parent is None:
            raise ValueError("choose where the account belongs!")
        name = name.strip()
        if any(child.account.name.casefold() == name.casefold() for child in parent.children):
            raise ValueError(
                f"'{parent.account.name}' already has an account named '{name}'. Pick it from the list instead!"
            )
        root = _root_of(roots, parent)
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


def _is_inflow(root_name: str, change: Decimal) -> bool:
    """Money coming in, as an account's page marks it (green, "+"): what raises an asset account, and a payment into a
    liability (a card or loan), which lowers what is owed. A charge on a card is plain."""
    return (root_name == "Assets" and change > 0) or (root_name == "Liabilities" and change < 0)


def account_context(
    accounts: AccountService, account_id: UUID, entries: Sequence[RegisterEntry] | None = None, offset: int = 0
) -> dict:
    """What the account page needs; the category page (categories.py) reuses it with its month's entries."""
    roots, node = _load(accounts, account_id)
    root = _root_of(roots, node)
    today = local_today()
    page = None
    if entries is None:
        # An account's own page reads only its newest entries (and what is dated ahead); a category passes its month's.
        # A group's page does the same over every account in it.
        page = accounts.register_page(account_id, today, offset) or RegisterPage([], [], 0, 0, False, False)
        history, ahead, has_any = page.entries, page.upcoming, page.has_any
    else:
        history = list(reversed([e for e in entries if e.date <= today]))
        ahead = sorted((e for e in entries if e.date > today), key=lambda e: e.date)
        has_any = bool(entries)
    # What is dated ahead is not history: it waits in its own card, soonest first, and out of the running list.
    upcoming = [
        UpcomingItem(
            e.transaction_id,
            e.date,
            e.payee or ", ".join(e.counter_accounts),
            (", ".join(e.counter_accounts) if e.payee else "")
            + (f" \u00b7 {e.comment}" if e.comment and e.payee else e.comment or ""),
            abs(e.change),
            _is_inflow(root.account.name, e.change),
        )
        for e in ahead
    ]
    signs = {e.change > 0 for e in ahead}
    upcoming_total = sum((u.amount for u in upcoming), Decimal("0.00")) if upcoming and len(signs) == 1 else None
    # With entries dated ahead, the balance they leave (the running balance of the last one); a category has its own month.
    balance_after = ahead[-1].balance if ahead and page is not None else None
    at_limit = node.kind != "system" and node.depth >= MAX_ACCOUNT_DEPTH
    # Asset and liability accounts with their own postings cannot gain sub-accounts.
    has_own_postings = node.is_leaf and has_any and node.kind != "root"
    can_add_child = (
        node.kind != "system"
        and not at_limit
        and (not has_own_postings or root.account.name in GROUP_POSTING_ROOT_NAMES)
    )
    bill = None
    can_set_days = False
    if entries is None and root.account.name == "Liabilities" and node.kind == "user" and node.postable:
        if not node.account.closed_on and node.account.statement_day is not None:
            bill = accounts.bill(account_id, today)
        can_set_days = node.account.statement_day is None and not node.account.closed_on
    # A group's page shows its open accounts as the Accounts page does: cards, with a bill or an idle account noted.
    last, bills = accounts.glance(today) if node.is_group and entries is None else ({}, {})
    return {
        "active": "accounts",
        "last_entry": last,
        "bills": bills,
        "stale_before": today - timedelta(days=STALE_DAYS),
        "bill": bill,
        "due_soon_days": cards.DUE_SOON_DAYS,
        "can_set_days": can_set_days,
        # The "+" in the bar starts an entry for this account and comes back here (a group, a closed account: the usual one).
        "new_transaction_url": f"/transactions/new?account={account_id}&back=/accounts/{account_id}"
        if node.postable and not node.account.closed_on
        else None,
        "node": node,
        "root": root,
        "entries": history,
        "has_more": page.has_more if page else False,
        "next_offset": page.next_offset if page else 0,
        "upcoming": upcoming,
        "upcoming_total": upcoming_total,
        "balance_after": balance_after,
        "is_inflow": lambda change: _is_inflow(root.account.name, change),
        "currency": accounts.currency().code,
        "can_add_child": can_add_child,
        # Pin or Unpin sits in the menu of an open account that holds entries; a group, a root or a closed account has none.
        "can_pin": node.kind == "user"
        and not node.is_group
        and not node.account.closed_on
        and not node.account.contact_account
        and root.account.name in ("Assets", "Liabilities"),
        # Part of a group's balance that was posted to the group itself.
        "direct": node.account.balance - sum((c.account.balance for c in node.children), Decimal("0.00"))
        if node.postable and node.children
        else None,
    }


@router.get("/{account_id}")
def account_page(request: Request, account_id: UUID, accounts: Accounts):
    return templates.TemplateResponse(request, "account.html", account_context(accounts, account_id))


@router.post("/{account_id}/close")
def close_account(account_id: UUID, accounts: Accounts):
    area = "/accounts"
    try:
        accounts.close(account_id)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect(area, flash="account-closed")


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
    context = account_context(accounts, account_id, None, offset=max(offset, 0))
    return templates.TemplateResponse(request, "partials/account_entries.html", {**context, "area": "/accounts"})


@router.get("/{account_id}/edit")
def edit_account_page(request: Request, account_id: UUID, accounts: Accounts):
    roots, node = _load(accounts, account_id)
    if node.kind != "user":
        raise HTTPException(status_code=404, detail="account not found")
    root = _root_of(roots, node)
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
            "starts": _starts(roots),
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
    where = "/accounts"
    try:
        accounts.delete(account_id)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect(where, flash="account-deleted")

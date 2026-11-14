"""What the Accounts page and an account's own page show: the kinds of account as rows of cards, each card's quiet line,
net worth, and an account's balance, bill, coming-up entries and register. The web pages (routers/web/accounts.py) and
the finode app's views (/api/views/accounts) both read from here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from ..schemas.account import CardBill
from . import cards
from .account import MAX_ACCOUNT_DEPTH, AccountService, RegisterPage
from .account_tree import Node, build_tree, without_contacts
from .transaction_rows import RegisterRow, UpcomingItem, account_register_row, is_inflow

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

    @property
    def open_count(self) -> int:
        return sum(1 for n in self.items if not n.closed)

    @property
    def all_closed(self) -> bool:
        """A kind whose accounts are all closed (or that was closed itself) hides whole until closed ones are shown."""
        return self.closed or (bool(self.items) and all(n.closed for n in self.items))


@dataclass
class CardNote:
    """The one quiet line under a card's balance, when there is something to say: a card's bill ("Bill overdue",
    "Bill due 5 Dec", `soon` when within cards.DUE_SOON_DAYS), an account with no entries, or one untouched for a
    month ("No entry since 2 Oct")."""

    kind: Literal["overdue", "due", "empty", "stale"]
    on: date | None = None
    soon: bool = False


def find(roots: list[Node], account_id: UUID) -> Node | None:
    return next((n for root in roots for n in root.walk() if n.account.id == account_id), None)


def root_of(roots: list[Node], node: Node) -> Node:
    return next(r for r in roots if any(n is node for n in r.walk()))


def starts(roots: list[Node]) -> dict[UUID, str]:
    """For each group, how an account made in it starts: "budget" (part of the budget) or "outside" it."""
    return {
        n.account.id: "budget" if n.account.new_accounts_in_budget else "outside"
        for r in roots
        for n in r.walk()
        if n.account.new_accounts_in_budget is not None
    }


def load(accounts: AccountService, account_id: UUID) -> tuple[list[Node], Node]:
    """The person's accounts as a tree, and the one asked for; LookupError when it is not theirs."""
    roots = build_tree(accounts.list())
    node = find(roots, account_id)
    if node is None:
        raise LookupError("account not found")
    return roots, node


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
    root_name = {id(n): r.account.name for r in roots for n in r.walk()}
    found = [
        Kind(
            g.account.name,
            root_name[id(g)],
            g.children,
            g.account.balance,
            g.account.id,
            g.account.closed_on is not None,
        )
        for g in kind_groups(roots)
    ]
    for root in roots:
        loose = [c for c in root.children if c.kind != "fixed" and not c.children]
        if loose and root.account.name in ("Assets", "Liabilities"):
            name = "Other" if root.account.name == "Assets" else "Other you owe"
            found.append(Kind(name, root.account.name, loose, sum((n.account.balance for n in loose), Decimal("0.00"))))
    return found


def mark_closed(roots: list[Node]) -> None:
    """Flag the closed accounts: the accounts page lists every open account, and keeps the closed ones behind "Load more"."""
    for root in roots:
        for node in root.walk():
            node.closed = node.account.closed_on is not None


def card_notes(
    nodes: list[Node], last: dict[UUID, date], bills: dict[UUID, CardBill], today: date
) -> dict[UUID, CardNote]:
    """Each open card's quiet line, when it has one."""
    stale_before = today - timedelta(days=STALE_DAYS)
    notes: dict[UUID, CardNote] = {}
    for node in nodes:
        account_id = node.account.id
        if node.account.closed_on is not None:
            continue
        bill, seen = bills.get(account_id), last.get(account_id)
        if bill and bill.bill > 0:
            overdue = bill.days_to_due < 0
            notes[account_id] = CardNote(
                "overdue" if overdue else "due",
                None if overdue else bill.due_date,
                bill.days_to_due <= cards.DUE_SOON_DAYS,
            )
        elif not seen:
            notes[account_id] = CardNote("empty")
        elif seen < stale_before:
            notes[account_id] = CardNote("stale", seen)
    return notes


@dataclass
class AccountsPage:
    kinds: list[Kind]
    # The accounts the person pinned, in the order of the rows below (the same cards again, no totals).
    pinned: list[Node]
    net_worth: Decimal
    notes: dict[UUID, CardNote]
    # Whether any account is closed: "Load more" then shows them.
    has_closed: bool
    # What the quiet line under the figure counts: the open accounts.
    account_count: int
    # Whether any open account feeds the budget: the line under the figure then explains the dot beside them.
    has_budget_accounts: bool


def accounts_page(accounts: AccountService, today: date) -> AccountsPage:
    roots = without_contacts(build_tree(accounts.list()))
    mark_closed(roots)
    shown = [r for r in roots if r.account.name in ("Assets", "Liabilities")]
    balance = {r.account.name: r.account.balance for r in shown}
    leaves = [n for r in shown for n in r.walk() if n.depth > 0 and not n.is_group]
    last, bills = accounts.glance(today)
    rows = kinds(shown)
    return AccountsPage(
        kinds=rows,
        pinned=[n for k in rows for n in k.items if n.account.pinned and not n.closed],
        net_worth=balance.get("Assets", Decimal("0.00")) - balance.get("Liabilities", Decimal("0.00")),
        notes=card_notes([n for k in rows for n in k.items], last, bills, today),
        has_closed=any(n.closed for n in leaves),
        account_count=sum(1 for n in leaves if not n.closed),
        has_budget_accounts=any(n.account.on_budget and not n.closed for n in leaves),
    )


def sub_line(node: Node, root: Node) -> str:
    """What an account's page says under its name: the kind it sits in (Bank Accounts, Credit Cards...), never the type's
    own name; for a group, whether it is built in and what it holds."""
    trail = node.path.split(" › ")
    owed = root.account.name == "Liabilities"
    if len(trail) > 2:
        return trail[1]
    if not node.is_group:
        return "Other you owe" if owed else "Other"
    return f"{'Built in' if node.kind == 'fixed' else 'Group'} · {'money I owe' if owed else 'money I own'}"


@dataclass
class AccountPage:
    node: Node
    root: Node
    sub: str
    entries: list[RegisterRow]
    has_more: bool
    next_offset: int
    upcoming: list[UpcomingItem]
    upcoming_total: Decimal | None
    # With entries dated ahead, the balance they leave.
    balance_after: Decimal | None
    bill: CardBill | None
    can_set_days: bool
    can_add_child: bool
    # The pin button in the header: an open account that holds entries; a group, a root or a closed account has none.
    can_pin: bool
    # Part of a group's balance that was posted to the group itself.
    direct: Decimal | None
    # A group's open accounts, as cards, and their quiet lines.
    cards: list[Node] = field(default_factory=list)
    notes: dict[UUID, CardNote] = field(default_factory=dict)

    @property
    def new_transaction_url(self) -> str | None:
        """The "+" in the bar starts an entry for this account and comes back here (a group, a closed account: none)."""
        account = self.node.account
        if not self.node.postable or account.closed_on:
            return None
        return f"/transactions/new?account={account.id}&back=/accounts/{account.id}"


def account_page(accounts: AccountService, account_id: UUID, today: date, offset: int = 0) -> AccountPage:
    """An account's (or a group's) own page: its newest entries from `offset`, what is dated ahead, its bill. LookupError
    for an account that is not the person's."""
    roots, node = load(accounts, account_id)
    root = root_of(roots, node)
    page = accounts.register_page(account_id, today, offset) or RegisterPage([], [], 0, 0, False, False)
    # What is dated ahead is not history: it waits in its own card, soonest first, and out of the running list.
    upcoming = [
        UpcomingItem(
            e.transaction_id,
            e.date,
            e.payee or ", ".join(e.counter_accounts),
            (", ".join(e.counter_accounts) if e.payee else "")
            + (f" · {e.comment}" if e.comment and e.payee else e.comment or ""),
            abs(e.change),
            is_inflow(root.account.name, e.change),
        )
        for e in page.upcoming
    ]
    signs = {e.change > 0 for e in page.upcoming}
    at_limit = node.kind != "system" and node.depth >= MAX_ACCOUNT_DEPTH
    # Asset and liability accounts with their own postings cannot gain sub-accounts.
    has_own_postings = node.is_leaf and page.has_any and node.kind != "root"
    bill = None
    can_set_days = False
    if root.account.name == "Liabilities" and node.kind == "user" and node.postable:
        if not node.account.closed_on and node.account.statement_day is not None:
            bill = accounts.bill(account_id, today)
        can_set_days = node.account.statement_day is None and not node.account.closed_on
    shown_cards = [c for c in node.children if not c.account.closed_on] if node.is_group else []
    notes = card_notes(shown_cards, *accounts.glance(today), today) if shown_cards else {}
    return AccountPage(
        node=node,
        root=root,
        sub=sub_line(node, root),
        entries=[account_register_row(e, root.account.name) for e in page.entries],
        has_more=page.has_more,
        next_offset=page.next_offset,
        upcoming=upcoming,
        upcoming_total=sum((u.amount for u in upcoming), Decimal("0.00")) if upcoming and len(signs) == 1 else None,
        balance_after=page.upcoming[-1].balance if page.upcoming else None,
        bill=bill,
        can_set_days=can_set_days,
        can_add_child=node.kind != "system" and not at_limit and not has_own_postings,
        can_pin=node.kind == "user"
        and not node.is_group
        and not node.account.closed_on
        and not node.account.contact_account
        and root.account.name in ("Assets", "Liabilities"),
        direct=node.account.balance - sum((c.account.balance for c in node.children), Decimal("0.00"))
        if node.postable and node.children
        else None,
        cards=shown_cards,
        notes=notes,
    )


# ---- the account form ---------------------------------------------------------------------------------------------

ACCOUNT_ROOTS = ("Assets", "Liabilities", "Equity")


def with_parent(groups: list[Node], roots: list[Node], parent: UUID | None) -> list[Node]:
    """The form's choices of where an account sits: the kinds, and the account's current parent when that is not a kind
    (a type itself, or an account it is being made inside), so saving never moves it by accident."""
    if parent is None or any(g.account.id == parent for g in groups):
        return groups
    found = find(roots, parent)
    return [*groups, *([found] if found else [])]


def placed(groups: list[Node], parent: Node | None) -> tuple[str, str] | None:
    """When a new account is opened for somewhere that is not a kind, what the form says instead of the kind chips: "Other"
    for the plain accounts of a type, or the account it is made inside."""
    if parent is None or any(g.account.id == parent.account.id for g in groups):
        return None
    if parent.kind == "root":
        return ("Kind", "Other" if parent.account.name == "Assets" else "Other you owe")
    return ("Inside", parent.account.name)


@dataclass
class KindChoice:
    """One place a new account can go, with what the form then asks: whether it can be part of the budget, whether it
    takes a card's statement and due days, and whether the budget box starts ticked (an asset starts in the budget, a
    card or loan outside it, and under a built-in group as that group says)."""

    node: Node
    root: str
    can_budget: bool
    can_bill: bool
    budget_default: bool


@dataclass
class AccountForm:
    node: Node | None  # the account being edited
    parent_id: UUID | None
    kinds: list[KindChoice]
    placed: tuple[str, str] | None
    parent_options: list[KindChoice]
    root_name: str | None
    can_budget: bool
    can_bill: bool
    on_budget: bool
    starts: dict[UUID, str]
    root_of: dict[UUID, str]


def _choice(node: Node, root_of: dict[UUID, str], group_starts: dict[UUID, str]) -> KindChoice:
    root = root_of.get(node.account.id, "")
    start = group_starts.get(node.account.id)
    return KindChoice(
        node=node,
        root=root,
        can_budget=root in ("Assets", "Liabilities"),
        can_bill=root == "Liabilities",
        budget_default=start == "budget" if start is not None else root == "Assets",
    )


def new_account_form(accounts: AccountService, parent: UUID | None, root: str = "") -> AccountForm:
    """The form for a new account. It asks what kind it is (a built-in group or one the person made); nothing is chosen
    until the person does, unless the link says (a kind's own "Add account", or a type's)."""
    everything = without_contacts(build_tree(accounts.list()))
    roots = [r for r in everything if r.account.name in ACCOUNT_ROOTS]
    root_names = {n.account.id: r.account.name for r in roots for n in r.walk()}
    only = next((r.account.name for r in roots if r.account.name.lower() == root.lower()), None)
    if only and (parent is None or root_names.get(parent) != only):
        # Opened for plain accounts under a type: they sit directly under that type.
        parent = next(r.account.id for r in roots if r.account.name == only)
    groups = [g for g in kind_groups(roots) if g.account.closed_on is None]
    group_starts = starts(everything)
    chosen_root = root_names.get(parent) if parent else None
    return AccountForm(
        node=None,
        parent_id=parent,
        kinds=[_choice(g, root_names, group_starts) for g in groups],
        placed=placed(groups, find(roots, parent) if parent else None),
        parent_options=[_choice(n, root_names, group_starts) for n in with_parent(groups, roots, parent)],
        root_name=chosen_root,
        can_budget=chosen_root in ("Assets", "Liabilities"),
        can_bill=chosen_root == "Liabilities",
        on_budget=(group_starts.get(parent) == "budget")
        if parent is not None and parent in group_starts
        else chosen_root == "Assets",
        starts=group_starts,
        root_of=root_names,
    )


def edit_account_form(accounts: AccountService, account_id: UUID) -> AccountForm:
    """The form for an account the person made. Where it sits is a kind; a group (an account with accounts inside) stays
    where it is. LookupError for one that is not theirs or not theirs to edit (a type, a built-in group)."""
    roots, node = load(accounts, account_id)
    if node.kind != "user":
        raise LookupError("account not found")
    root = root_of(roots, node)
    root_names = {n.account.id: root.account.name for n in root.walk()}
    group_starts = starts(roots)
    mine = [g for g in kind_groups([root]) if not node.is_group and g.account.closed_on is None]
    return AccountForm(
        node=node,
        parent_id=node.account.parent_id,
        kinds=[_choice(g, root_names, group_starts) for g in mine],
        placed=None,
        parent_options=[]
        if node.is_group
        else [_choice(n, root_names, group_starts) for n in with_parent(mine, [root], node.account.parent_id)],
        root_name=root.account.name,
        can_budget=root.account.name in ("Assets", "Liabilities") and not node.is_group,
        can_bill=root.account.name == "Liabilities" and not node.is_group,
        on_budget=node.account.on_budget,
        starts=group_starts,
        root_of=root_names,
    )

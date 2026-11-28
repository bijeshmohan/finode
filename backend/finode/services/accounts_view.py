"""What the Accounts page and an account's own page show: the four types as rows of cards, each card's quiet line,
and an account's balance, bill, coming-up entries and register. The finode app's views
(/api/views/accounts) read from here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from ..schemas.account import CardBill
from . import cards
from .account import AccountService, RegisterPage
from .account_tree import Node, build_tree, without_contacts
from .account_types import TYPE_KEYS, TYPE_NAMES, TYPE_ROOTS
from .transaction_rows import RegisterRow, UpcomingItem, account_register_row, is_inflow

# An account whose newest entry is older than this says so on its card; a newer one has nothing to add.
STALE_DAYS = 30


@dataclass
class Kind:
    """One row of cards on the Accounts page: one of the four types (Bank Account, Cash...) and its accounts."""

    name: str
    root: str  # Assets or Liabilities: a liability reads "owed"
    items: list[Node]
    total: Decimal
    type: str

    @property
    def owed(self) -> bool:
        return self.root == "Liabilities"

    @property
    def add_url(self) -> str:
        return f"/accounts/new?type={self.type}"

    @property
    def all_closed(self) -> bool:
        """A kind whose accounts are all closed hides whole until closed ones are shown."""
        return bool(self.items) and all(n.closed for n in self.items)


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


def load(accounts: AccountService, account_id: UUID) -> tuple[list[Node], Node]:
    """The person's accounts as a tree, and the one asked for; LookupError when it is not theirs."""
    roots = build_tree(accounts.list())
    node = find(roots, account_id)
    if node is None:
        raise LookupError("account not found")
    return roots, node


def kinds(roots: list[Node], order: list[str] | None = None) -> list[Kind]:
    """The accounts as the page lists them: a row per type in the person's order (an empty one too), its total what
    its accounts hold (or, for Credit Card, owe)."""
    typed = [n for r in roots for n in r.children if n.account.type in TYPE_KEYS]
    rows = []
    for key in order or list(TYPE_KEYS):
        items = [n for n in typed if n.account.type == key]
        total = sum((n.account.balance for n in items), Decimal("0.00"))
        rows.append(Kind(TYPE_NAMES[key], TYPE_ROOTS[key], items, total, key))
    return rows


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
    notes: dict[UUID, CardNote]
    # Whether any account is closed: "Load more" then shows them.
    has_closed: bool
    # What the quiet line under the title counts: the open accounts.
    account_count: int
    # The hero card: what the Bank, Cash and Prepaid Wallet accounts hold, and what is owed on the cards, apart (never
    # one net figure: finode counts cash flow, not worth).
    in_accounts: Decimal
    owed_on_cards: Decimal


def accounts_page(accounts: AccountService, today: date) -> AccountsPage:
    roots = without_contacts(build_tree(accounts.list()))
    mark_closed(roots)
    shown = [r for r in roots if r.account.name in ("Assets", "Liabilities")]
    leaves = [n for r in shown for n in r.walk() if n.depth > 0 and not n.is_group]
    last, bills = accounts.glance(today)
    rows = kinds(shown, accounts.type_order())
    return AccountsPage(
        kinds=rows,
        pinned=[n for k in rows for n in k.items if n.account.pinned and not n.closed],
        notes=card_notes([n for k in rows for n in k.items], last, bills, today),
        has_closed=any(n.closed for n in leaves),
        account_count=sum(1 for n in leaves if not n.closed),
        in_accounts=sum((k.total for k in rows if not k.owed), Decimal("0.00")),
        owed_on_cards=sum((k.total for k in rows if k.owed), Decimal("0.00")),
    )


def sub_line(node: Node, root: Node) -> str:
    """What an account's page says under its name: the type it is (Bank Account, Credit Card...); for a root, what it
    holds."""
    owed = root.account.name == "Liabilities"
    if node.account.type in TYPE_NAMES:
        return TYPE_NAMES[node.account.type]
    if not node.is_group:
        return "Other you owe" if owed else "Other"
    return "money I owe" if owed else "money I own"


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
            e.icon,
        )
        for e in page.upcoming
    ]
    signs = {e.change > 0 for e in page.upcoming}
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


@dataclass
class AccountForm:
    """Where the account form starts: the account being edited (none for a new one), its type (or the one a new account
    was opened for: a type's own "+ Add account"), and the four types in the person's order for a new account to pick."""

    node: Node | None
    type: str | None
    types: list[tuple[str, str]]  # (key, name)


def _types(order: list[str]) -> list[tuple[str, str]]:
    return [(key, TYPE_NAMES[key]) for key in order]


def new_account_form(accounts: AccountService, type: str | None, order: list[str] | None = None) -> AccountForm:
    """The form for a new account: nothing is chosen until the person picks a type, unless the link says."""
    return AccountForm(
        node=None, type=type if type in TYPE_KEYS else None, types=_types(order or accounts.type_order())
    )


def edit_account_form(accounts: AccountService, account_id: UUID) -> AccountForm:
    """The form for an account the person made; it keeps its type. LookupError for one that is not theirs or not theirs to
    edit (a type itself, a root, Opening Balances, a person's account)."""
    _, node = load(accounts, account_id)
    if node.kind != "user" or node.account.type is None:
        raise LookupError("account not found")
    return AccountForm(node=node, type=node.account.type, types=[])

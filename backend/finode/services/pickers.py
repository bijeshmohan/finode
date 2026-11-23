"""What the Add screen's pickers offer: accounts grouped by their type, the people, and the categories; for the finode
app's form view."""

from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ..schemas.category import CategoryRead
from .account_tree import Node
from .account_types import TYPE_KEYS, TYPE_NAMES
from .contact import ContactService


@dataclass
class PickOption:
    """One choice in an account or category picker: what it is called (below its type: "Banks › HDFC",
    "Groceries"), and for an account its budget flag and balance."""

    id: UUID
    label: str
    budget: bool = False
    balance: Decimal | None = None


PickGroups = list[tuple[str, list[PickOption]]]


def posting_groups(
    roots: list[Node], keep: Collection[UUID] = frozenset(), order: list[str] | None = None
) -> PickGroups:
    """Accounts that transactions may post to: a group per type in the person's `order` (Bank Account, Cash...),
    then what else can be posted to by its root (Equity's Opening Balances). Closed accounts are left out, except those
    in `keep` (what an entry being edited already uses)."""
    groups: PickGroups = []

    def shown(n: Node) -> bool:
        return n.postable and not n.account.contact_account and (n.account.closed_on is None or n.account.id in keep)

    def option(n: Node) -> PickOption:
        return PickOption(n.account.id, n.account.name, budget=n.account.type is not None, balance=n.account.balance)

    typed = [n for r in roots for n in r.children if n.account.type in TYPE_KEYS and shown(n)]
    for key in order or list(TYPE_KEYS):
        options = [option(n) for n in typed if n.account.type == key]
        if options:
            groups.append((TYPE_NAMES[key], options))
    for root in roots:
        if root.account.name in ("Assets", "Liabilities"):
            continue
        options = [option(n) for n in root.walk() if shown(n)]
        if options:
            groups.append((root.account.name, options))
    return groups


def category_groups(categories: list[CategoryRead], keep: Collection[UUID] = frozenset()) -> PickGroups:
    """The categories an entry's lines may be labelled with, grouped as Income and Expenses, A to Z, for the same pickers
    as the accounts. Closed categories are left out, except those in `keep` (what an entry being edited already uses)."""
    found: PickGroups = []
    for root, kind in (("Income", "earning"), ("Expenses", "spending")):
        mine = [c for c in categories if c.kind == kind and (c.closed_on is None or c.id in keep)]
        options = [PickOption(c.id, c.name) for c in sorted(mine, key=lambda c: c.name.lower())]
        if options:
            found.append((root, options))
    return found


def people_group(contacts: ContactService | None, keep: Collection[UUID] = frozenset()) -> PickGroups:
    """The people a transfer can go to or come from, as one more group in the pickers. Nobody with no contacts pays a
    query for it: the contact accounts are known from the account list."""
    if contacts is None or not contacts.has_people():
        return []
    # The balance of a person is what they owe you (a negative one: what you owe them); the form says what a transfer does.
    people = [
        PickOption(c.id, c.name, balance=c.net)
        for c in contacts.list(include_archived=True)
        if not c.archived or c.id in keep
    ]
    return [("People", sorted(people, key=lambda o: o.label.casefold()))] if people else []

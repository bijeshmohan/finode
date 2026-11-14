"""What the Add screen's pickers offer: accounts grouped by their type, the people, and the categories; for the web form
and the finode app's form view alike."""

from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ..schemas.category import CategoryRead
from .account_tree import Node
from .contact import ContactService


@dataclass
class PickOption:
    """One choice in an account or category picker: what it is called (below its type: "Banks › HDFC",
    "Food › Groceries"), and for an account its budget flag and balance."""

    id: UUID
    label: str
    budget: bool = False
    balance: Decimal | None = None


PickGroups = list[tuple[str, list[PickOption]]]


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

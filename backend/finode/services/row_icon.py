"""Which icon a row leads with: the one place this is decided (the app only draws it).

An opening balance or an adjustment is a flag. Otherwise the lines on Expenses or Income decide: one category is that
category's icon; several (an uncategorised line counts as one) is the "several" mark; only uncategorised lines are the
Uncategorised mark. An entry with no such lines and a person's account in it (a loan, a settlement) is a person;
anything else is a transfer. A shared bill (a category plus a person's share) therefore shows its category."""

from collections.abc import Collection, Mapping, Sequence
from typing import Protocol
from uuid import UUID

from ..category_icons import DEFAULT, OPENING, PERSON, SEVERAL, TRANSFER, UNCATEGORISED

CATEGORY_ROOTS = ("Expenses", "Income")


class IconLine(Protocol):
    @property
    def account_id(self) -> UUID: ...

    @property
    def category_id(self) -> UUID | None: ...


def row_icon(
    lines: Sequence[IconLine],
    roots: Mapping[UUID, str],
    icons: Mapping[UUID, str],
    contacts: Collection[UUID],
    opening: UUID | None,
) -> str:
    """`roots` names every account's root (a root names itself), `icons` the categories' icons by id, `contacts` the
    people's accounts and `opening` the Opening Balances account."""
    if opening is not None and any(line.account_id == opening for line in lines):
        return OPENING
    labels = {line.category_id for line in lines if roots.get(line.account_id) in CATEGORY_ROOTS}
    if len(labels) > 1:
        return SEVERAL
    if labels:
        (only,) = labels
        return UNCATEGORISED if only is None else icons.get(only, DEFAULT)
    if any(line.account_id in contacts for line in lines):
        return PERSON
    return TRANSFER

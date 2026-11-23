"""What the Recurring list shows: every rule with the names on its two sides, what leaves each time (a split: its
total), its schedule in words and its status. The finode app's view (/api/views/recurring) reads from
here."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

from ..models.transaction import PostingSide
from ..schemas.recurring import RecurringRead
from .account import AccountService
from .account_tree import build_tree
from .category import CategoryService
from .recurring import RecurringService
from .schedule import describe

Status = Literal["active", "paused", "ended", "error"]


@dataclass
class RuleRow:
    rule: RecurringRead
    to_name: str
    amount: Decimal  # what leaves (a split: its total)
    schedule: str
    status: Status


@dataclass
class RuleRows:
    rows: list[RuleRow]

    @property
    def live(self) -> list[RuleRow]:
        return [r for r in self.rows if r.status in ("active", "error")]

    @property
    def stopped(self) -> list[RuleRow]:
        return [r for r in self.rows if r.status in ("paused", "ended")]


def status(rule: RecurringRead) -> Status:
    if rule.active:
        return "error" if rule.last_error else "active"
    return "ended" if rule.end_date is not None and rule.next_date > rule.end_date else "paused"


def paths(accounts: AccountService, categories: CategoryService) -> dict[UUID, str]:
    """A name for every account and every category, by id (a category reads "Expenses › Groceries")."""
    names = {n.account.id: n.path for root in build_tree(accounts.list()) for n in root.walk()}
    for c in categories.list(include_closed=True):
        names[c.id] = ("Expenses" if c.kind == "spending" else "Income") + " › " + c.name
    return names


def side_name(names: dict[UUID, str], account: UUID | None, category: UUID | None) -> str:
    """What a rule's side is called: the category when the money goes to Expenses or Income, else the account."""
    if account is None:
        return "?"
    path = names.get(account, "?")
    if path in ("Expenses", "Income") and category is not None:
        return names.get(category, path)
    return path


def rule_row(rule: RecurringRead, names: dict[UUID, str]) -> RuleRow:
    if rule.postings:

        def on(side: PostingSide) -> str:
            return ", ".join(
                dict.fromkeys(
                    side_name(names, p.account_id, p.category_id).split(" › ")[-1]
                    for p in rule.postings
                    if p.side == side
                )
            )

        total = sum((p.amount for p in rule.postings if p.side == PostingSide.DEBIT), Decimal(0))
        return RuleRow(
            rule,
            on(PostingSide.DEBIT),
            total,
            describe(rule.frequency, rule.every),
            status(rule),
        )
    return RuleRow(
        rule=rule,
        to_name=side_name(names, rule.to_account_id, rule.category_id),
        amount=rule.amount or Decimal(0),
        schedule=describe(rule.frequency, rule.every),
        status=status(rule),
    )


def rule_rows(recurring: RecurringService, accounts: AccountService, categories: CategoryService) -> RuleRows:
    recurring.catch_up()  # record what has fallen due; it never stops the page from opening
    names = paths(accounts, categories)
    return RuleRows([rule_row(r, names) for r in recurring.list()])

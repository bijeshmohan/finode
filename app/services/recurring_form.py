"""The recurring form: where it starts (a rule's rows as the Add screen shows them) and what its rows save as (a plain
rule, one account each side with the same amount, or a split). The web form (routers/web/recurring.py) and the finode
app (/api/recurring/form, /api/views/recurring-form) both go through here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from ..models.transaction import PostingSide
from ..schemas.entry import EntryRow
from ..schemas.recurring import RecurringPostingData, RecurringRead
from .account import AccountService
from .account_tree import roots_by_id
from .entry import infer_kind, postings_of
from .entry_form import form_rows
from .recurring import RecurringService

# How often a rule repeats, and what one of each is called ("Every 2 months").
FREQUENCIES = [("daily", "day"), ("weekly", "week"), ("monthly", "month"), ("yearly", "year")]


def rule_fields(
    rows: list[EntryRow],
    places: Mapping[UUID, UUID],
    *,
    payee: str,
    comment: str,
    tags: list[str],
    frequency: str,
    every: int,
    start_date: date,
    end_date: date | None,
) -> dict:
    """What RecurringCreate / RecurringUpdate take for the rows (a category row posts on Expenses or Income with it):
    one debit and one credit of the same amount is a plain rule, anything else a split."""
    if any(r.posted_on is not None for r in rows):
        raise ValueError("a recurring rule has no posting day of its own for a line!")
    postings = postings_of(rows, places)
    if len(postings) < 2:
        raise ValueError("choose where the money comes from and where it goes!")
    common = {
        "payee": payee,
        "comment": comment,
        "tags": tags,
        "frequency": frequency,
        "every": every,
        "start_date": start_date,
        "end_date": end_date,
    }
    debit = [p for p in postings if p.side == PostingSide.DEBIT]
    credit = [p for p in postings if p.side == PostingSide.CREDIT]
    if len(postings) == 2 and len(debit) == 1 and len(credit) == 1 and debit[0].amount == credit[0].amount:
        return {
            "from_account_id": credit[0].account_id,
            "to_account_id": debit[0].account_id,
            "amount": credit[0].amount,
            "category_id": debit[0].category_id or credit[0].category_id,
            **common,
        }
    return {
        "postings": [
            RecurringPostingData(account_id=p.target, side=p.side, amount=p.amount, category_id=p.category_id)
            for p in postings
        ],
        **common,
    }


@dataclass
class RuleStart:
    kind: str = "expense"
    total: Decimal | str = ""
    from_rows: list[dict] = field(default_factory=lambda: form_rows([], PostingSide.CREDIT))
    to_rows: list[dict] = field(default_factory=lambda: form_rows([], PostingSide.DEBIT))
    # The accounts the rule uses, offered in the pickers even if they were closed since.
    keep: set[UUID] = field(default_factory=set)


def form_start(recurring: RecurringService, accounts: AccountService, rule: RecurringRead | None) -> RuleStart:
    """The form's rows filled from the rule (simple and split alike), or blank for a new one."""
    if rule is None:
        return RuleStart()
    recorded = recurring.as_transaction(rule)
    roots = roots_by_id(accounts)
    return RuleStart(
        kind=infer_kind(recorded.postings, roots),
        total=sum((p.amount for p in recorded.postings if p.side == PostingSide.DEBIT), Decimal(0)),
        from_rows=form_rows(recorded.postings, PostingSide.CREDIT, roots=roots),
        to_rows=form_rows(recorded.postings, PostingSide.DEBIT, roots=roots),
        keep={p.target for p in recorded.postings},
    )

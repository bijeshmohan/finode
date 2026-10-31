"""The two postings of a plain money-moves-from-here-to-there transaction, shared by the web form's simple case, recurring rules and the assistants."""

from decimal import Decimal
from uuid import UUID

from ..models.account import Account
from ..models.transaction import PostingSide
from ..schemas.transaction import PostingCreate


def simple_postings(paid: Decimal, from_id: UUID, to_id: UUID) -> list[PostingCreate]:
    """The two postings of a money-moves-from-here-to-there transaction."""
    if from_id == to_id:
        raise ValueError("the from and to accounts must differ!")
    return [
        PostingCreate(account=to_id, side=PostingSide.DEBIT, amount=paid),
        PostingCreate(account=from_id, side=PostingSide.CREDIT, amount=paid),
    ]


def label_simple(accounts: dict[UUID, Account], postings: list[PostingCreate], category: UUID) -> None:
    """Put a category on a simple entry: on the side that is not in the budget and does not stand for a category itself
    (the loan or fund being paid), the one place a label says anything. If there is none, it goes on the first line
    and the entry's checks name the problem."""
    for posting in postings:
        account = accounts.get(posting.target)
        if account is not None and not account.on_budget:
            posting.category = category
            return
    postings[0].category = category

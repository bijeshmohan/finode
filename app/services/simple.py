from decimal import Decimal
from uuid import UUID

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

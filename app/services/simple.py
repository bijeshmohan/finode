from decimal import Decimal
from uuid import UUID

from ..models.transaction import PostingSide
from ..schemas.transaction import PostingCreate
from .account import AccountService


def simple_postings(
    accounts: AccountService, paid: Decimal, received: Decimal | None, from_id: UUID, to_id: UUID
) -> tuple[str, list[PostingCreate]]:
    """The two postings of a money-moves-from-here-to-there transaction, and the currency it is in
    (always explicit, so an edit that moves a transaction between accounts does not keep a stale currency).

    Between accounts holding the same thing one amount is enough. Otherwise `received` says how
    much arrives; the transaction is in the default currency when it is one of the two, else in
    whichever of them is a currency, and the other side is worth what the currency side is.
    """
    if from_id == to_id:
        raise ValueError("the from and to accounts must differ!")
    source, target = accounts.commodity_of(from_id), accounts.commodity_of(to_id)
    if source is None or target is None:
        raise ValueError("account not found!")
    if source.cid == target.cid:
        if received is not None and received != paid:
            raise ValueError(f"both accounts hold {source.code}, so the amount that arrives is the amount that leaves!")
        return source.code, [
            PostingCreate(account=to_id, side=PostingSide.DEBIT, amount=paid),
            PostingCreate(account=from_id, side=PostingSide.CREDIT, amount=paid),
        ]
    if received is None:
        raise ValueError(
            f"these accounts hold different things ({source.code} and {target.code}): say how much {target.code} arrives!"
        )
    default = accounts.default_currency()
    if default.cid in (source.cid, target.cid):
        currency = default
    elif source.kind == "currency" or target.kind != "currency":
        currency = source
    else:
        currency = target
    from_posting = PostingCreate(
        account=from_id, side=PostingSide.CREDIT, amount=paid, value=received if currency.cid == target.cid else None
    )
    to_posting = PostingCreate(
        account=to_id, side=PostingSide.DEBIT, amount=received, value=paid if currency.cid == source.cid else None
    )
    return currency.code, [to_posting, from_posting]

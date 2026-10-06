from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlmodel import Session

from ..repositories import (
    AccountRepository,
    CommodityRepository,
    PriceRepository,
    ProfileRepository,
    RecurringRepository,
    TransactionRepository,
)
from ..services import AccountService, CommodityService, PriceService, RecurringService, ReportService, TransactionService
from ..services.api_token import TokenOwner


# Who is calling: set by the transport for each request after checking the token.
current_owner: ContextVar[TokenOwner | None] = ContextVar("finode_mcp_owner", default=None)


def _default_session() -> AbstractContextManager[Session]:
    from ..dependencies import engine

    return Session(engine)


# Tests replace this to use their own database.
session_factory: Callable[[], AbstractContextManager[Session]] = _default_session


@dataclass
class Services:
    owner: TokenOwner
    accounts: AccountService
    transactions: TransactionService
    reports: ReportService
    prices: PriceService
    commodities: CommodityService
    recurring: RecurringService


@contextmanager
def services() -> Iterator[Services]:
    """The caller's services, scoped to their user like the JSON API's."""
    owner = current_owner.get()
    if owner is None:
        raise PermissionError("not authenticated")
    with session_factory() as db:
        uid = owner.user
        ar, tr = AccountRepository(db, uid), TransactionRepository(db, uid)
        cr, pr = CommodityRepository(db, uid), PriceRepository(db, uid)
        prices = PriceService(pr, tr, cr)
        accounts = AccountService(ar, tr, ProfileRepository(db, uid), cr, prices)
        yield Services(
            owner=owner,
            accounts=accounts,
            transactions=TransactionService(tr, ar, cr, origin=f"mcp:{owner.name}"),
            reports=ReportService(accounts, tr),
            prices=prices,
            commodities=CommodityService(cr),
            recurring=RecurringService(
                RecurringRepository(db, uid), accounts, TransactionService(tr, ar, cr, origin="recurring")
            ),
        )

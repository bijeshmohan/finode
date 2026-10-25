"""Builds the services for the token's user inside a tool call, the way dependencies.py does for a web request."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlmodel import Session

from ..repositories import (
    AccountRepository,
    BudgetRepository,
    ProfileRepository,
    RecurringRepository,
    TransactionRepository,
)
from ..services import AccountService, BudgetService, RecurringService, ReportService, TransactionService
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
    recurring: RecurringService
    budget: BudgetService


@contextmanager
def services() -> Iterator[Services]:
    """The caller's services, scoped to their user like the JSON API's."""
    owner = current_owner.get()
    if owner is None:
        raise PermissionError("not authenticated")
    with session_factory() as db:
        uid = owner.user
        ar = AccountRepository(db, uid, origin=f"mcp:{owner.name}")
        tr, pr = TransactionRepository(db, uid), ProfileRepository(db, uid)
        accounts = AccountService(ar, tr, pr)
        yield Services(
            owner=owner,
            accounts=accounts,
            transactions=TransactionService(tr, ar, pr, origin=f"mcp:{owner.name}"),
            reports=ReportService(accounts, tr),
            budget=BudgetService(accounts, tr, BudgetRepository(db, uid)),
            recurring=RecurringService(
                RecurringRepository(db, uid), accounts, TransactionService(tr, ar, pr, origin="recurring")
            ),
        )

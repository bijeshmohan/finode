"""The services for the test user, for tests that check what the code does without going through a route."""

import json
from types import SimpleNamespace

from app.repositories import AccountRepository, ProfileRepository, TransactionRepository
from app.repositories.budget import BudgetRepository
from app.repositories.recurring import RecurringRepository
from app.services.account import AccountService
from app.services.budget import BudgetService
from app.services.category import CategoryService
from app.services.recurring import RecurringService
from app.services.report import ReportService
from app.services.transaction import TransactionService

from .conftest import TEST_USER_ID


def services(session, user=TEST_USER_ID, origin="api"):
    ar, tr, pr = (
        AccountRepository(session, user),
        TransactionRepository(session, user),
        ProfileRepository(session, user),
    )
    accounts = AccountService(ar, tr, pr)
    return SimpleNamespace(
        accounts=accounts,
        transactions=TransactionService(tr, ar, pr, origin=origin),
        reports=ReportService(accounts, tr),
        categories=CategoryService(accounts),
        budget=BudgetService(accounts, tr, BudgetRepository(session, user)),
        recurring=RecurringService(
            RecurringRepository(session, user), accounts, TransactionService(tr, ar, pr, origin="recurring")
        ),
    )


def plain(model):
    """A response model as the JSON a client would have read (Decimals as strings, dates as text)."""
    if isinstance(model, list):
        return [plain(m) for m in model]
    return json.loads(model.model_dump_json())

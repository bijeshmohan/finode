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


def entries(session, user=TEST_USER_ID, origin="web"):
    """The service that saves an entry from a form (services/entry.py), wired as app/dependencies.py wires it."""
    from app.repositories.obligation import ObligationRepository
    from app.repositories.shared_expense import SharedExpenseRepository
    from app.services.contact import ContactService
    from app.services.entry import EntryService
    from app.services.expense_sharing import ExpenseSharingService
    from app.services.income_sharing import IncomeSharingService
    from app.services.obligation import ObligationService
    from app.services.settlement import SettlementService
    from app.services.transfer import TransferService

    ar, tr, pr = (
        AccountRepository(session, user),
        TransactionRepository(session, user),
        ProfileRepository(session, user),
    )
    accounts = AccountService(ar, tr, pr)
    contacts = ContactService(accounts)
    with_people = TransactionService(tr, ar, pr, origin=origin, contacts=True)
    ob = ObligationRepository(session, user)
    settlements = SettlementService(
        contacts, with_people, ob, ObligationService(tr, ob), SharedExpenseRepository(session, user)
    )
    return EntryService(
        transactions=TransactionService(tr, ar, pr, origin=origin),
        accounts=accounts,
        categories=CategoryService(accounts),
        contacts=contacts,
        transfers=TransferService(contacts, with_people, ob, settlements),
        expenses=ExpenseSharingService(contacts, with_people, ob, SharedExpenseRepository(session, user)),
        incomes=IncomeSharingService(contacts, with_people, ob),
    )

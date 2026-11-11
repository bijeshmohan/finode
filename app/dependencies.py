"""Turns a request into "this user": opens the database session and builds repositories and services bound to the user's id."""

from typing import Annotated

from fastapi import Depends, Request
from sqlmodel import Session, create_engine

from .auth import CurrentUser, require_authenticated_user
from .config import settings
from .repositories import (
    AccountRepository,
    BudgetRepository,
    ProfileRepository,
    RecurringRepository,
    TransactionRepository,
)
from .repositories.api_token import ApiTokenRepository
from .repositories.oauth_grant import OAuthGrantRepository
from .repositories.obligation import ObligationRepository
from .repositories.shared_expense import SharedExpenseRepository
from .services import (
    AccountService,
    BudgetService,
    ComingUpService,
    DataService,
    ProfileService,
    RecurringService,
    ReportService,
    TransactionService,
)
from .services.api_token import ApiTokenService
from .services.backup import BackupService
from .services.category import CategoryService
from .services.contact import ContactService
from .services.contact_summary import ContactSummaryService
from .services.erase import EraseService
from .services.expense_sharing import ExpenseSharingService
from .services.income_sharing import IncomeSharingService
from .services.oauth_grant import OAuthGrantService
from .services.obligation import ObligationService
from .services.settlement import SettlementService
from .services.todo import TodoService
from .services.transfer import TransferService

engine = create_engine(settings.database_url, echo=settings.database_echo)


def get_db_session():
    with Session(engine) as session:
        yield session


def get_account_repository(
    request: Request,
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> AccountRepository:
    origin = "api" if request.url.path.startswith("/api/") else "web"
    return AccountRepository(db, user.id, origin=origin)


def get_transaction_repository(
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> TransactionRepository:
    return TransactionRepository(db, user.id)


def get_profile_repository(
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> ProfileRepository:
    return ProfileRepository(db, user.id)


def load_currency(
    request: Request,
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> None:
    """Note the person's currency for the page being built: amounts are grouped the way it is written (see templating)."""
    request.state.currency = ProfileRepository(db, user.id).currency()


def get_account_service(
    ar: AccountRepository = Depends(get_account_repository),
    tr: TransactionRepository = Depends(get_transaction_repository),
    pr: ProfileRepository = Depends(get_profile_repository),
) -> AccountService:
    return AccountService(ar, tr, pr)


def get_category_service(accounts: AccountService = Depends(get_account_service)) -> CategoryService:
    return CategoryService(accounts)


def get_contact_service(accounts: AccountService = Depends(get_account_service)) -> ContactService:
    return ContactService(accounts)


def get_obligation_repository(
    db: Session = Depends(get_db_session), user: CurrentUser = Depends(require_authenticated_user)
) -> ObligationRepository:
    return ObligationRepository(db, user.id)


def get_obligation_service(
    tr: TransactionRepository = Depends(get_transaction_repository),
    ob: ObligationRepository = Depends(get_obligation_repository),
) -> ObligationService:
    return ObligationService(tr, ob)


def get_contact_transactions(
    request: Request,
    tr: TransactionRepository = Depends(get_transaction_repository),
    ar: AccountRepository = Depends(get_account_repository),
    pr: ProfileRepository = Depends(get_profile_repository),
) -> TransactionService:
    """The transaction service the contact workflows use: the only one that may post to a contact's accounts."""
    origin = "api" if request.url.path.startswith("/api/") else "web"
    return TransactionService(tr, ar, pr, origin=origin, contacts=True)


def get_settlement_service(
    contacts: ContactService = Depends(get_contact_service),
    transactions: TransactionService = Depends(get_contact_transactions),
    ob: ObligationRepository = Depends(get_obligation_repository),
    obligations: ObligationService = Depends(get_obligation_service),
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> SettlementService:
    return SettlementService(contacts, transactions, ob, obligations, SharedExpenseRepository(db, user.id))


def get_transfer_service(
    contacts: ContactService = Depends(get_contact_service),
    transactions: TransactionService = Depends(get_contact_transactions),
    ob: ObligationRepository = Depends(get_obligation_repository),
    settlements: SettlementService = Depends(get_settlement_service),
) -> TransferService:
    return TransferService(contacts, transactions, ob, settlements)


def get_expense_sharing_service(
    contacts: ContactService = Depends(get_contact_service),
    transactions: TransactionService = Depends(get_contact_transactions),
    ob: ObligationRepository = Depends(get_obligation_repository),
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> ExpenseSharingService:
    return ExpenseSharingService(contacts, transactions, ob, SharedExpenseRepository(db, user.id))


def get_income_sharing_service(
    contacts: ContactService = Depends(get_contact_service),
    transactions: TransactionService = Depends(get_contact_transactions),
    ob: ObligationRepository = Depends(get_obligation_repository),
) -> IncomeSharingService:
    return IncomeSharingService(contacts, transactions, ob)


def get_contact_summary_service(
    contacts: ContactService = Depends(get_contact_service),
    tr: TransactionRepository = Depends(get_transaction_repository),
    ob: ObligationRepository = Depends(get_obligation_repository),
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> ContactSummaryService:
    return ContactSummaryService(contacts, tr, ob, SharedExpenseRepository(db, user.id))


def get_profile_service(
    pr: ProfileRepository = Depends(get_profile_repository),
    accounts: AccountService = Depends(get_account_service),
) -> ProfileService:
    return ProfileService(pr, accounts)


def get_data_service(
    accounts: AccountService = Depends(get_account_service),
    ar: AccountRepository = Depends(get_account_repository),
    tr: TransactionRepository = Depends(get_transaction_repository),
    pr: ProfileRepository = Depends(get_profile_repository),
) -> DataService:
    return DataService(accounts, ar, tr, pr)


def get_erase_service(
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> EraseService:
    return EraseService(db, user.id)


def get_backup_service(
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
    accounts: AccountService = Depends(get_account_service),
    ar: AccountRepository = Depends(get_account_repository),
    tr: TransactionRepository = Depends(get_transaction_repository),
    pr: ProfileRepository = Depends(get_profile_repository),
) -> BackupService:
    return BackupService(accounts, ar, tr, pr, RecurringRepository(db, user.id), BudgetRepository(db, user.id))


def get_transaction_service(
    request: Request,
    tr: TransactionRepository = Depends(get_transaction_repository),
    ar: AccountRepository = Depends(get_account_repository),
    pr: ProfileRepository = Depends(get_profile_repository),
) -> TransactionService:
    origin = "api" if request.url.path.startswith("/api/") else "web"
    return TransactionService(tr, ar, pr, origin=origin)


def get_recurring_service(
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
    accounts: AccountService = Depends(get_account_service),
    tr: TransactionRepository = Depends(get_transaction_repository),
    ar: AccountRepository = Depends(get_account_repository),
    pr: ProfileRepository = Depends(get_profile_repository),
) -> RecurringService:
    # What a rule records is marked as made by the rule, not by whoever happened to open the page.
    return RecurringService(
        RecurringRepository(db, user.id), accounts, TransactionService(tr, ar, pr, origin="recurring")
    )


def get_report_service(
    accounts: AccountService = Depends(get_account_service),
    tr: TransactionRepository = Depends(get_transaction_repository),
) -> ReportService:
    return ReportService(accounts, tr)


def get_budget_service(
    accounts: AccountService = Depends(get_account_service),
    tr: TransactionRepository = Depends(get_transaction_repository),
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> BudgetService:
    return BudgetService(accounts, tr, BudgetRepository(db, user.id))


def get_coming_up_service(
    accounts: AccountService = Depends(get_account_service),
    transactions: TransactionService = Depends(get_transaction_service),
    recurring: RecurringService = Depends(get_recurring_service),
) -> ComingUpService:
    return ComingUpService(accounts, transactions, recurring)


def get_todo_service(
    budget: BudgetService = Depends(get_budget_service),
    recurring: RecurringService = Depends(get_recurring_service),
    accounts: AccountService = Depends(get_account_service),
) -> TodoService:
    return TodoService(budget, recurring, accounts)


def get_api_token_service(
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> ApiTokenService:
    return ApiTokenService(ApiTokenRepository(db, user.id))


def get_oauth_grant_service(
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> OAuthGrantService:
    return OAuthGrantService(OAuthGrantRepository(db, user.id))


Accounts = Annotated[AccountService, Depends(get_account_service)]
Categories = Annotated[CategoryService, Depends(get_category_service)]
ContactSummaries = Annotated[ContactSummaryService, Depends(get_contact_summary_service)]
Contacts = Annotated[ContactService, Depends(get_contact_service)]
Obligations = Annotated[ObligationService, Depends(get_obligation_service)]
Settlements = Annotated[SettlementService, Depends(get_settlement_service)]
SharedExpenses = Annotated[ExpenseSharingService, Depends(get_expense_sharing_service)]
SharedIncomes = Annotated[IncomeSharingService, Depends(get_income_sharing_service)]
Transfers = Annotated[TransferService, Depends(get_transfer_service)]
Transactions = Annotated[TransactionService, Depends(get_transaction_service)]
Data = Annotated[DataService, Depends(get_data_service)]
Backup = Annotated[BackupService, Depends(get_backup_service)]
Erase = Annotated[EraseService, Depends(get_erase_service)]
Profiles = Annotated[ProfileService, Depends(get_profile_service)]
Recurring = Annotated[RecurringService, Depends(get_recurring_service)]
Reports = Annotated[ReportService, Depends(get_report_service)]
Budget = Annotated[BudgetService, Depends(get_budget_service)]
ComingUp = Annotated[ComingUpService, Depends(get_coming_up_service)]
Todo = Annotated[TodoService, Depends(get_todo_service)]
ApiTokens = Annotated[ApiTokenService, Depends(get_api_token_service)]
OAuthGrants = Annotated[OAuthGrantService, Depends(get_oauth_grant_service)]

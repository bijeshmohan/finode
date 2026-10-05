from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, create_engine

from .auth import CurrentUser, require_authenticated_user
from .config import settings
from .repositories import AccountRepository, CommodityRepository, ProfileRepository, TransactionRepository
from .services import AccountService, CommodityService, DataService, ProfileService, ReportService, TransactionService


engine = create_engine(settings.database_url, echo=settings.database_echo)


def get_db_session():
    with Session(engine) as session:
        yield session


def get_account_repository(
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> AccountRepository:
    return AccountRepository(db, user.id)


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


def get_commodity_repository(
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> CommodityRepository:
    return CommodityRepository(db, user.id)


def get_commodity_service(
    cr: CommodityRepository = Depends(get_commodity_repository),
) -> CommodityService:
    return CommodityService(cr)


def get_account_service(
    ar: AccountRepository = Depends(get_account_repository),
    tr: TransactionRepository = Depends(get_transaction_repository),
    pr: ProfileRepository = Depends(get_profile_repository),
    cr: CommodityRepository = Depends(get_commodity_repository),
) -> AccountService:
    return AccountService(ar, tr, pr, cr)


def get_profile_service(
    pr: ProfileRepository = Depends(get_profile_repository),
    accounts: AccountService = Depends(get_account_service),
    cr: CommodityRepository = Depends(get_commodity_repository),
) -> ProfileService:
    return ProfileService(pr, accounts, cr)


def get_data_service(
    accounts: AccountService = Depends(get_account_service),
    ar: AccountRepository = Depends(get_account_repository),
    tr: TransactionRepository = Depends(get_transaction_repository),
    pr: ProfileRepository = Depends(get_profile_repository),
) -> DataService:
    return DataService(accounts, ar, tr, pr)


def get_transaction_service(
    tr: TransactionRepository = Depends(get_transaction_repository),
    ar: AccountRepository = Depends(get_account_repository),
    cr: CommodityRepository = Depends(get_commodity_repository),
) -> TransactionService:
    return TransactionService(tr, ar, cr)


def get_report_service(
    accounts: AccountService = Depends(get_account_service),
    tr: TransactionRepository = Depends(get_transaction_repository),
) -> ReportService:
    return ReportService(accounts, tr)


DB = Annotated[Session, Depends(get_db_session)]
AR = Annotated[AccountRepository, Depends(get_account_repository)]
TR = Annotated[TransactionRepository, Depends(get_transaction_repository)]
Commodities = Annotated[CommodityService, Depends(get_commodity_service)]
Accounts = Annotated[AccountService, Depends(get_account_service)]
Transactions = Annotated[TransactionService, Depends(get_transaction_service)]
Data = Annotated[DataService, Depends(get_data_service)]
Profiles = Annotated[ProfileService, Depends(get_profile_service)]
Reports = Annotated[ReportService, Depends(get_report_service)]

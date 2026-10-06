from typing import Annotated

from fastapi import Depends, Request
from sqlmodel import Session, create_engine

from .auth import CurrentUser, require_authenticated_user
from .config import settings
from .repositories.api_token import ApiTokenRepository
from .repositories.oauth_grant import OAuthGrantRepository
from .services.api_token import ApiTokenService
from .services.oauth_grant import OAuthGrantService
from .repositories import (
    AccountRepository,
    CommodityRepository,
    PriceRepository,
    ProfileRepository,
    RecurringRepository,
    TransactionRepository,
)
from .services import (
    AccountService,
    CommodityService,
    DataService,
    PriceService,
    ProfileService,
    RecurringService,
    ReportService,
    TransactionService,
)


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


def get_price_repository(
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> PriceRepository:
    return PriceRepository(db, user.id)


def get_price_service(
    pr: PriceRepository = Depends(get_price_repository),
    tr: TransactionRepository = Depends(get_transaction_repository),
    cr: CommodityRepository = Depends(get_commodity_repository),
) -> PriceService:
    return PriceService(pr, tr, cr)


def get_commodity_service(
    cr: CommodityRepository = Depends(get_commodity_repository),
) -> CommodityService:
    return CommodityService(cr)


def get_account_service(
    ar: AccountRepository = Depends(get_account_repository),
    tr: TransactionRepository = Depends(get_transaction_repository),
    pr: ProfileRepository = Depends(get_profile_repository),
    cr: CommodityRepository = Depends(get_commodity_repository),
    prices: PriceService = Depends(get_price_service),
) -> AccountService:
    return AccountService(ar, tr, pr, cr, prices)


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
    request: Request,
    tr: TransactionRepository = Depends(get_transaction_repository),
    ar: AccountRepository = Depends(get_account_repository),
    cr: CommodityRepository = Depends(get_commodity_repository),
) -> TransactionService:
    origin = "web" if request.url.path.startswith("/app") else "api"
    return TransactionService(tr, ar, cr, origin=origin)


def get_recurring_service(
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
    accounts: AccountService = Depends(get_account_service),
    tr: TransactionRepository = Depends(get_transaction_repository),
    ar: AccountRepository = Depends(get_account_repository),
    cr: CommodityRepository = Depends(get_commodity_repository),
) -> RecurringService:
    # What a rule records is marked as made by the rule, not by whoever happened to open the page.
    return RecurringService(RecurringRepository(db, user.id), accounts, TransactionService(tr, ar, cr, origin="recurring"))


def get_report_service(
    accounts: AccountService = Depends(get_account_service),
    tr: TransactionRepository = Depends(get_transaction_repository),
) -> ReportService:
    return ReportService(accounts, tr)


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


DB = Annotated[Session, Depends(get_db_session)]
AR = Annotated[AccountRepository, Depends(get_account_repository)]
TR = Annotated[TransactionRepository, Depends(get_transaction_repository)]
Prices = Annotated[PriceService, Depends(get_price_service)]
Commodities = Annotated[CommodityService, Depends(get_commodity_service)]
Accounts = Annotated[AccountService, Depends(get_account_service)]
Transactions = Annotated[TransactionService, Depends(get_transaction_service)]
Data = Annotated[DataService, Depends(get_data_service)]
Profiles = Annotated[ProfileService, Depends(get_profile_service)]
Recurring = Annotated[RecurringService, Depends(get_recurring_service)]
Reports = Annotated[ReportService, Depends(get_report_service)]
ApiTokens = Annotated[ApiTokenService, Depends(get_api_token_service)]
OAuthGrants = Annotated[OAuthGrantService, Depends(get_oauth_grant_service)]

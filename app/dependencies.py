from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, create_engine

from .config import settings
from .repositories import AccountRepository, CategoryRepository, TransactionRepository
from .services import AccountService, CategoryService, TransactionService


engine = create_engine(settings.database_url, echo=settings.database_echo)


def get_db_session():
    with Session(engine) as session:
        yield session


def get_account_repository(db: Session = Depends(get_db_session)) -> AccountRepository:
    return AccountRepository(db)


def get_category_repository(db: Session = Depends(get_db_session)) -> CategoryRepository:
    return CategoryRepository(db)


def get_transaction_repository(db: Session = Depends(get_db_session)) -> TransactionRepository:
    return TransactionRepository(db)


def get_account_service(ar: AccountRepository = Depends(get_account_repository), tr: TransactionRepository = Depends(get_transaction_repository)) -> AccountService:
    return AccountService(ar, tr)


def get_category_service(cr: CategoryRepository = Depends(get_category_repository)) -> CategoryService:
    return CategoryService(cr)


def get_transaction_service(tr: TransactionRepository = Depends(get_transaction_repository), ar: AccountRepository = Depends(get_account_repository)) -> TransactionService:
    return TransactionService(tr, ar)


DB = Annotated[Session, Depends(get_db_session)]
AR = Annotated[AccountRepository, Depends(get_account_repository)]
CR = Annotated[CategoryRepository, Depends(get_category_repository)]
TR = Annotated[TransactionRepository, Depends(get_transaction_repository)]
Accounts = Annotated[AccountService, Depends(get_account_service)]
Categories = Annotated[CategoryService, Depends(get_category_service)]
Transactions = Annotated[TransactionService, Depends(get_transaction_service)]

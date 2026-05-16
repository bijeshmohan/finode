from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, create_engine

from .config import settings
from .repositories import AccountRepository, CategoryRepository, TransactionRepository


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


DB = Annotated[Session, Depends(get_db_session)]
AR = Annotated[AccountRepository, Depends(get_account_repository)]
CR = Annotated[CategoryRepository, Depends(get_category_repository)]
TR = Annotated[TransactionRepository, Depends(get_transaction_repository)]

from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, create_engine

from .auth import CurrentUser, require_authenticated_user
from .config import settings
from .repositories import AccountRepository, JournalEntryRepository
from .services import AccountService, JournalEntryService


engine = create_engine(settings.database_url, echo=settings.database_echo)


def get_db_session():
    with Session(engine) as session:
        yield session


def get_account_repository(
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> AccountRepository:
    return AccountRepository(db, user.id)


def get_journal_entry_repository(
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(require_authenticated_user),
) -> JournalEntryRepository:
    return JournalEntryRepository(db, user.id)


def get_account_service(
    ar: AccountRepository = Depends(get_account_repository),
    jr: JournalEntryRepository = Depends(get_journal_entry_repository),
) -> AccountService:
    return AccountService(ar, jr)


def get_journal_entry_service(
    jr: JournalEntryRepository = Depends(get_journal_entry_repository),
    ar: AccountRepository = Depends(get_account_repository),
) -> JournalEntryService:
    return JournalEntryService(jr, ar)


DB = Annotated[Session, Depends(get_db_session)]
AR = Annotated[AccountRepository, Depends(get_account_repository)]
JR = Annotated[JournalEntryRepository, Depends(get_journal_entry_repository)]
Accounts = Annotated[AccountService, Depends(get_account_service)]
JournalEntries = Annotated[JournalEntryService, Depends(get_journal_entry_service)]

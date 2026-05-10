from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, create_engine

from .config import settings

engine = create_engine(settings.database_url, echo=settings.database_echo)


def get_db_session():
    with Session(engine) as session:
        yield session


DBSession = Annotated[Session, Depends(get_db_session)]

from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, create_engine

DATABASE = "sqlite:///./finode.db"
engine = create_engine(DATABASE, echo=True)


def get_db_session():
    with Session(engine) as session:
        yield session


DBSession = Annotated[Session, Depends(get_db_session)]

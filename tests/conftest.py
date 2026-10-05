from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.commodity_seed import seed_rows
from app.auth import CurrentUser, require_authenticated_user
from app.dependencies import get_db_session
from app.main import app
from app.models.commodity import Commodity
from app.models.utils import utc_now
from app.web_auth import web_login_required


TEST_USER_ID = UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # A single shared connection, so the in-memory databases live as long as the engine. The session
    # commits for real: a service that rolls back only undoes its own unfinished work.
    with engine.connect() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS auth")
        connection.commit()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(Commodity(**row) for row in seed_rows(utc_now()))
        session.commit()
        yield session


@pytest.fixture
def client(session: Session) -> Generator[TestClient, None, None]:
    def get_session_override():
        return session

    def auth_override():
        return CurrentUser(id=TEST_USER_ID, email="test@example.com", claims={})

    app.dependency_overrides[get_db_session] = get_session_override
    app.dependency_overrides[require_authenticated_user] = auth_override
    app.dependency_overrides[web_login_required] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def root_accounts(client: TestClient) -> dict[str, str]:
    response = client.get("/accounts/")
    assert response.status_code == 200
    accounts = response.json()
    return {a["name"]: a["aid"] for a in accounts if a["parent_id"] is None}


@pytest.fixture
def account(client: TestClient, root_accounts: dict[str, str]) -> dict:
    response = client.post(
        "/accounts/",
        json={"name": "checking", "details": None, "parent_id": root_accounts["Assets"]},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def other_account(client: TestClient, root_accounts: dict[str, str]) -> dict:
    response = client.post(
        "/accounts/",
        json={"name": "savings", "details": None, "parent_id": root_accounts["Assets"]},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def expense_account(client: TestClient, root_accounts: dict[str, str]) -> dict:
    response = client.post(
        "/accounts/",
        json={"name": "groceries", "details": None, "parent_id": root_accounts["Expenses"]},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def income_account(client: TestClient, root_accounts: dict[str, str]) -> dict:
    response = client.post(
        "/accounts/",
        json={"name": "salary", "details": None, "parent_id": root_accounts["Income"]},
    )
    assert response.status_code == 201
    return response.json()

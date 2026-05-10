from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.dependencies import get_db_session
from app.main import app


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(session: Session) -> Generator[TestClient, None, None]:
    def get_session_override():
        return session

    app.dependency_overrides[get_db_session] = get_session_override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def account(client: TestClient) -> dict:
    response = client.post(
        "/accounts/",
        json={"name": "checking", "details": None, "balance": "100.00"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def other_account(client: TestClient) -> dict:
    response = client.post(
        "/accounts/",
        json={"name": "savings", "details": None, "balance": "500.00"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def expense_category(client: TestClient) -> dict:
    response = client.post(
        "/categories/",
        json={"type": "expense", "name": "groceries"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def income_category(client: TestClient) -> dict:
    response = client.post(
        "/categories/",
        json={"type": "income", "name": "salary"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def transfer_category(client: TestClient) -> dict:
    response = client.post(
        "/categories/",
        json={"type": "transfer", "name": "internal"},
    )
    assert response.status_code == 201
    return response.json()

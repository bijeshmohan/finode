from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.auth import CurrentUser, require_authenticated_user
from app.dependencies import get_db_session
from app.main import app
from app.web_auth import web_login_required


TEST_USER_ID = UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture(autouse=True)
def deployment_settings_off(monkeypatch: pytest.MonkeyPatch):
    """Settings a real deployment switches on in .env must not change what the tests see."""
    from app.config import settings

    for name, value in (
        ("test_notice", False), ("feedback_email", None), ("password_reset", False),
        ("signup_code", None), ("supabase_service_role_key", None), ("max_users", 10), ("timezone", None),
    ):
        monkeypatch.setattr(settings, name, value)


@pytest.fixture(autouse=True)
def advanced_features_on(monkeypatch: pytest.MonkeyPatch):
    """New profiles start with the advanced features hidden; most tests exercise them, so they start with them shown."""
    from app.repositories import profile

    monkeypatch.setattr(profile, "NEW_PROFILE_ADVANCED", True)


@pytest.fixture(autouse=True)
def fresh_attempt_limits():
    """The sign-in and sign-up counters live in memory: every test starts with a clean slate."""
    from app.ratelimit import attempts

    attempts.clear()
    yield
    attempts.clear()


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
    response = client.get("/api/accounts/")
    assert response.status_code == 200
    accounts = response.json()
    return {a["name"]: a["aid"] for a in accounts if a["parent_id"] is None}


@pytest.fixture
def account(client: TestClient, root_accounts: dict[str, str]) -> dict:
    response = client.post(
        "/api/accounts/",
        json={"name": "checking", "details": None, "parent_id": root_accounts["Assets"]},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def other_account(client: TestClient, root_accounts: dict[str, str]) -> dict:
    response = client.post(
        "/api/accounts/",
        json={"name": "savings", "details": None, "parent_id": root_accounts["Assets"]},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def expense_account(client: TestClient, root_accounts: dict[str, str]) -> dict:
    response = client.post(
        "/api/accounts/",
        json={"name": "groceries", "details": None, "parent_id": root_accounts["Expenses"]},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def income_account(client: TestClient, root_accounts: dict[str, str]) -> dict:
    response = client.post(
        "/api/accounts/",
        json={"name": "salary", "details": None, "parent_id": root_accounts["Income"]},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def svc(session):
    """The services for the test user, for checking what the code does without a route (see tests/svc.py)."""
    from .svc import services

    return services(session)

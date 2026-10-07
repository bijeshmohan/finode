from time import time
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.auth import CurrentUser, require_authenticated_user, verify_supabase_jwt
from app.config import settings
from app.dependencies import get_db_session
from app.main import app


USER_A_ID = UUID("00000000-0000-4000-8000-00000000000a")
USER_B_ID = UUID("00000000-0000-4000-8000-00000000000b")


class FakeSigningKey:
    def __init__(self, key):
        self.key = key


class FakeJwksClient:
    def __init__(self, key):
        self.signing_key = FakeSigningKey(key)

    def get_signing_key_from_jwt(self, token: str):
        return self.signing_key


def test_accounts_require_authentication():
    with TestClient(app) as client:
        response = client.get("/api/accounts/")

    assert response.status_code == 401
    assert response.json() == {"detail": "missing authentication token"}


def test_verify_supabase_jwt_accepts_valid_jwks_token(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_audience", "authenticated")
    monkeypatch.setattr(
        "app.auth._get_jwks_client",
        lambda: FakeJwksClient(private_key.public_key()),
    )
    token = jwt.encode(
        {
            "sub": str(USER_A_ID),
            "email": "user@example.com",
            "aud": "authenticated",
            "iss": "https://example.supabase.co/auth/v1",
            "exp": int(time()) + 60,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    claims = verify_supabase_jwt(token)

    assert claims["sub"] == str(USER_A_ID)
    assert claims["email"] == "user@example.com"


def test_users_can_only_access_their_own_data(session: Session):
    def get_session_override():
        return session

    def authenticate_as(user_id: str):
        def auth_override():
            return CurrentUser(id=user_id, email=None, claims={})

        app.dependency_overrides[require_authenticated_user] = auth_override

    app.dependency_overrides[get_db_session] = get_session_override
    try:
        with TestClient(app) as client:
            authenticate_as(USER_A_ID)
            roots = {a["name"]: a["aid"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None}
            account = client.post(
                "/api/accounts/",
                json={"name": "checking", "details": None, "parent_id": roots["Assets"]},
            ).json()
            expense_account = client.post(
                "/api/accounts/",
                json={"name": "groceries", "parent_id": roots["Expenses"]},
            ).json()
            transaction = client.post(
                "/api/transactions/",
                json={
                    "postings": [
                        {
                            "account": expense_account["aid"],
                            "side": "debit",
                            "amount": "10.00",
                        },
                        {
                            "account": account["aid"],
                            "side": "credit",
                            "amount": "10.00",
                        },
                    ],
                },
            ).json()

            authenticate_as(USER_B_ID)
            assert len(client.get("/api/accounts/").json()) == 5
            assert client.get("/api/transactions/").json() == []
            assert client.get(f"/api/accounts/{account['aid']}").status_code == 404
            assert client.get(f"/api/transactions/{transaction['tid']}").status_code == 404
            response = client.post(
                "/api/transactions/",
                json={
                    "postings": [
                        {
                            "account": expense_account["aid"],
                            "side": "debit",
                            "amount": "5.00",
                        },
                        {
                            "account": account["aid"],
                            "side": "credit",
                            "amount": "5.00",
                        },
                    ],
                },
            )
            assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()

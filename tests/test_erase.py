"""Erasing your books, and deleting your account: what goes, what stays, and that nobody else is touched."""

import json
from uuid import UUID

import pytest
from sqlmodel import select

from app.config import settings
from app.models.account import Account
from app.models.account_deletion import AccountDeletion
from app.models.api_token import ApiToken
from app.models.oauth_grant import OAuthGrant
from app.models.profile import Profile
from app.models.tag import Tag, TransactionTag
from app.models.transaction import Posting, Transaction
from app.repositories.api_token import ApiTokenRepository
from app.repositories.oauth_grant import OAuthGrantRepository
from app.routers.web import profile as profile_router
from app.schemas.api_token import ApiTokenCreate
from app.services.api_token import ApiTokenService
from app.services.erase import EraseService
from app.services.oauth_grant import OAuthGrantService
from app.web_auth import ACCESS_COOKIE, AuthUnavailableError

from .books import post_account
from .conftest import TEST_USER_ID
from .test_backup import rich  # noqa: F401
from .test_isolation import B_USER, books_of, signed_in_as


def rows(session, model, user=TEST_USER_ID):
    return session.exec(select(model).where(model.user_id == user)).all()


@pytest.fixture
def both(client, session, rich):
    """A has a full ledger, an assistant token and a connected app; B has a little."""
    ApiTokenService(ApiTokenRepository(session, TEST_USER_ID)).create(ApiTokenCreate(name="Laptop", scope="write"))
    OAuthGrantService(OAuthGrantRepository(session, TEST_USER_ID)).allow("client-a", "A-Assistant", "write")
    client.patch("/api/profile/", json={"first_name": "Ada", "last_name": "L"})
    with signed_in_as(B_USER):
        roots = {a["name"]: a["id"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None}
        mine = post_account(client, {"name": "Mine", "parent_id": roots["Assets"], "balance": "700"}).json()
        client.patch("/api/profile/", json={"first_name": "Bea"})
        ApiTokenService(ApiTokenRepository(session, B_USER)).create(ApiTokenCreate(name="B-Phone"))
    return mine


def test_erasing_the_books_empties_them_and_keeps_the_person(client, session, both):
    before_b = books_of(client, B_USER)
    shelf = post_account(
        client,
        {
            "name": "Shelf",
            "parent_id": next(
                a["id"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None and a["name"] == "Assets"
            ),
        },
    ).json()["id"]
    client.delete(f"/api/accounts/{shelf}")
    assert rows(session, AccountDeletion), "a deleted account leaves a record"
    removed = EraseService(session, TEST_USER_ID).erase_books()
    assert rows(session, AccountDeletion) == [] and "account_deletions" in removed, (
        "erasing the books clears the records too"
    )
    assert {
        "accounts",
        "transactions",
        "postings",
        "recurring_transactions",
        "budget_allocations",
        "transaction_history",
        "tags",
        "transaction_tags",
    } <= set(removed)
    for model in (Account, Transaction, Posting, Tag, TransactionTag):
        assert rows(session, model) == [], model
    # What belongs to the person, not the books, stays.
    [profile] = rows(session, Profile)
    assert profile.first_name == "Ada"
    assert len(rows(session, ApiToken)) == 1 and len(rows(session, OAuthGrant)) == 1
    assert books_of(client, B_USER) == before_b, "nobody else's books were touched"


def test_deleting_everything_leaves_nothing_of_the_person(client, session, both):
    before_b = books_of(client, B_USER)
    EraseService(session, TEST_USER_ID).erase_everything()
    for model in (Account, Transaction, Posting, Tag, TransactionTag, Profile, ApiToken, OAuthGrant):
        assert rows(session, model) == [], model
    assert books_of(client, B_USER) == before_b
    assert len(rows(session, Profile, B_USER)) == 1 and len(rows(session, ApiToken, B_USER)) == 1


def test_after_erasing_a_backup_restores_everything(client, session, both):
    backup = client.get("/api/backup").json()
    EraseService(session, TEST_USER_ID).erase_books()
    assert client.get("/api/backup").json()["transactions"] == []
    done = client.post("/api/restore", files={"file": ("b.json", json.dumps(backup), "application/json")})
    assert done.status_code == 200, done.text
    again = client.get("/api/backup").json()
    assert len(again["transactions"]) == len(backup["transactions"]) and len(again["accounts"]) == len(
        backup["accounts"]
    )
    assert client.get("/api/reports/trial-balance").json()["balanced"]


# ---- the pages -----------------------------------------------------------------------------------------------


def test_the_data_page_offers_both_and_says_what_each_does(client, both, monkeypatch):
    monkeypatch.setattr(settings, "supabase_service_role_key", None)
    page = client.get("/profile/data").text
    assert "Erase my books" in page and "test@example.com" in page
    assert "Deleting your login isn't set up here" in page and "Delete my account</button>" not in page
    monkeypatch.setattr(settings, "supabase_service_role_key", "sb_secret_x")
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    assert "Delete my account</button>" in client.get("/profile/data").text


def test_erasing_needs_the_email_typed(client, session, both):
    wrong = client.post("/profile/data/erase", data={"confirm": "nope"})
    assert wrong.status_code == 400 and wrong.headers["HX-Retarget"] == "#erase-error"
    assert rows(session, Account), "nothing was erased"
    done = client.post("/profile/data/erase", data={"confirm": " Test@Example.com "})
    assert done.headers["HX-Redirect"] == "/" and "books-erased" in done.headers["set-cookie"]
    assert rows(session, Account) == [] and len(rows(session, Profile)) == 1


def test_deleting_the_account_erases_everything_and_signs_out(client, session, both, monkeypatch):
    deleted = []
    monkeypatch.setattr(settings, "supabase_service_role_key", "sb_secret_x")
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(profile_router, "delete_user", lambda user_id: deleted.append(user_id))
    wrong = client.post("/profile/data/delete-account", data={"confirm": "x"})
    assert wrong.status_code == 400 and deleted == [] and rows(session, Account)
    done = client.post("/profile/data/delete-account", data={"confirm": "test@example.com"})
    assert done.headers["HX-Redirect"] == "/login" and "your-account-deleted" in done.headers["set-cookie"]
    assert deleted == [TEST_USER_ID]
    cookies = done.headers.get_list("set-cookie")
    assert any(c.startswith(f"{ACCESS_COOKIE}=") and "Max-Age=0" in c for c in cookies), "the sign-in cookie is cleared"
    for model in (Account, Profile, ApiToken, OAuthGrant):
        assert rows(session, model) == [], model


def test_if_the_login_cannot_be_removed_the_person_is_told(client, session, both, monkeypatch):
    monkeypatch.setattr(settings, "supabase_service_role_key", "sb_secret_x")
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")

    def broken(user_id):
        raise AuthUnavailableError("down")

    monkeypatch.setattr(profile_router, "delete_user", broken)
    response = client.post("/profile/data/delete-account", data={"confirm": "test@example.com"})
    assert response.status_code == 400 and "Your data was erased, but removing your login failed" in response.text
    assert rows(session, Account) == [], "the books are gone; the person can try again"


def test_without_the_service_key_nothing_is_erased_by_the_delete_button(client, session, both, monkeypatch):
    monkeypatch.setattr(settings, "supabase_service_role_key", None)
    response = client.post("/profile/data/delete-account", data={"confirm": "test@example.com"})
    assert response.status_code == 400 and "is not set up here" in response.text
    assert rows(session, Account), "nothing was erased: the option is unavailable"


def test_deleting_an_account_frees_a_place_for_the_next_person(client, session, both, monkeypatch):
    from app.routers.web import auth as web_auth_router  # noqa: F401

    monkeypatch.setattr(settings, "max_users", 2)
    count = lambda: len(session.exec(select(Profile)).all())
    assert count() == 2
    monkeypatch.setattr(settings, "supabase_service_role_key", "sb_secret_x")
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(profile_router, "delete_user", lambda user_id: None)
    client.post("/profile/data/delete-account", data={"confirm": "test@example.com"})
    assert count() == 1


def test_supabase_delete_call(monkeypatch):
    from app import signup

    sent = {}

    class Reply:
        def __init__(self, code):
            self.status_code = code

    def fake(url, headers, timeout):
        sent.update(url=url, headers=headers)
        return Reply(204)

    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co/")
    monkeypatch.setattr(settings, "supabase_service_role_key", "sb_secret_x")
    monkeypatch.setattr(signup.httpx, "delete", fake)
    signup.delete_user(UUID(int=7))
    assert (
        sent["url"] == f"https://proj.supabase.co/auth/v1/admin/users/{UUID(int=7)}"
        and sent["headers"]["apikey"] == "sb_secret_x"
    )
    monkeypatch.setattr(signup.httpx, "delete", lambda *a, **k: Reply(500))
    with pytest.raises(AuthUnavailableError):
        signup.delete_user(UUID(int=7))
    monkeypatch.setattr(settings, "supabase_service_role_key", None)
    with pytest.raises(AuthUnavailableError):
        signup.delete_user(UUID(int=7))

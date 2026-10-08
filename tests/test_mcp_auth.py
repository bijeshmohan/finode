"""Who may use /mcp: personal access tokens, their scope, revocation and the rate limit."""

from uuid import UUID

import httpx2
import pytest

from app.config import settings
from app.mcp_server import transport
from app.main import app
from app.models.api_token import ApiToken
from app.models.transaction import Transaction
from app.repositories.api_token import ApiTokenRepository
from app.schemas.api_token import ApiTokenCreate
from app.services.api_token import ApiTokenService, hash_secret

from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app


pytestmark = pytest.mark.anyio

OTHER_USER = UUID("00000000-0000-4000-8000-000000000002")
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
}


async def raw_post(headers: dict[str, str]):
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://testserver") as http:
        return await http.post(
            "/mcp", json=INITIALIZE, headers={"Accept": "application/json, text/event-stream", **headers}
        )


async def test_requests_without_a_valid_token_are_refused(session):
    async with running_app(session):
        missing = await raw_post({})
        assert missing.status_code == 401 and "Profile, AI assistants" in missing.json()["error"]
        assert missing.headers["www-authenticate"].startswith("Bearer")
        for header in ("Bearer nonsense", "Bearer fin_notarealtoken", "Basic abc"):
            assert (await raw_post({"Authorization": header})).status_code == 401, header


async def test_a_valid_token_is_answered(session):
    secret = make_token(session, TEST_USER_ID)
    async with running_app(session):
        response = await raw_post({"Authorization": f"Bearer {secret}"})
    assert response.status_code == 200 and response.json()["result"]["serverInfo"]["name"] == "finode"


async def test_a_revoked_token_stops_working(session):
    service = ApiTokenService(ApiTokenRepository(session, TEST_USER_ID))
    created = service.create(ApiTokenCreate(name="Laptop", scope="write"))
    async with running_app(session):
        assert (await raw_post({"Authorization": f"Bearer {created.secret}"})).status_code == 200
        service.revoke(created.tkid)
        assert (await raw_post({"Authorization": f"Bearer {created.secret}"})).status_code == 401


async def test_a_read_write_token_is_told_it_can_write(session):
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        assert "record_transaction" in c.instructions and "read-only" not in c.instructions


async def test_a_read_only_token_can_see_but_not_use_write_tools(session, root_accounts):
    secret = make_token(session, TEST_USER_ID, scope="read")
    async with running_app(session), mcp_client(secret) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert "get_overview" in names and "list_accounts" in names
        writers = {"record_transaction", "record_split", "update_transaction", "delete_transaction", "create_account", "set_price", "assign_to_category", "move_budget_money"}
        assert writers <= names, "listed so the assistant can explain, but they only refuse"
        calls = {
            "record_transaction": {"amount": "1", "from_account": "a", "to_account": "b"},
            "record_split": {"postings": [{"account": "a", "side": "debit", "amount": "1"}, {"account": "b", "side": "credit", "amount": "1"}]},
            "update_transaction": {"transaction_id": "00000000-0000-4000-8000-000000000001"},
            "delete_transaction": {"transaction_id": "00000000-0000-4000-8000-000000000001"},
            "create_account": {"name": "X", "parent": "Assets"},
            "set_price": {"commodity": "BTC", "price": "1"},
            "assign_to_category": {"category": "Food", "amount": "1"},
            "move_budget_money": {"from_category": "Food", "to_category": "Rent", "amount": "1"},
        }
        assert set(calls) == writers
        for tool, arguments in calls.items():
            with pytest.raises(ToolFailed, match="read-only.*Profile > AI assistants"):
                payload(await c.call_tool(tool, arguments))
        assert "read-only" in c.instructions and "Profile > AI assistants" in c.instructions
        assert not session.exec(Transaction.__table__.select()).all(), "nothing was written"


async def test_each_token_sees_only_its_own_users_books(session, client, root_accounts):
    client.post("/api/accounts/", json={"name": "Mine", "parent_id": root_accounts["Assets"], "balance": "500"})
    theirs = make_token(session, OTHER_USER, name="Theirs")
    async with running_app(session), mcp_client(theirs) as c:
        accounts = payload(await c.call_tool("list_accounts", {}))["accounts"]
        assert "Assets:Mine" not in {a["path"] for a in accounts}
        assert payload(await c.call_tool("get_overview", {}))["net_worth"] == "0.00"
        with pytest.raises(ToolFailed, match="no account matches"):
            payload(await c.call_tool("get_account", {"account": "Mine"}))


async def test_the_rate_limit_answers_429(session, monkeypatch):
    secret = make_token(session, TEST_USER_ID)
    monkeypatch.setattr(settings, "mcp_rate_limit", 2)
    transport._calls.clear()
    async with running_app(session):
        statuses = [(await raw_post({"Authorization": f"Bearer {secret}"})).status_code for _ in range(3)]
    transport._calls.clear()
    assert statuses == [200, 200, 429]


def test_the_window_slides():
    tkid = UUID(int=7)
    transport._calls.pop(tkid, None)
    limit = settings.mcp_rate_limit
    assert all(transport._allow(tkid, now=100.0) for _ in range(limit))
    assert not transport._allow(tkid, now=110.0)
    assert transport._allow(tkid, now=160.5), "a minute later there is room again"
    transport._calls.pop(tkid, None)


async def test_using_a_token_notes_when(session):
    secret = make_token(session, TEST_USER_ID)
    async with running_app(session):
        await raw_post({"Authorization": f"Bearer {secret}"})
    token = session.exec(ApiToken.__table__.select()).first()
    assert token.last_used is not None


def test_only_a_hash_of_the_secret_is_stored(session):
    created = ApiTokenService(ApiTokenRepository(session, TEST_USER_ID)).create(ApiTokenCreate(name="Desk"))
    stored = session.get(ApiToken, created.tkid)
    assert created.secret.startswith("fin_") and len(created.secret) > 40
    assert stored.token_hash == hash_secret(created.secret) and created.secret not in stored.token_hash
    assert stored.prefix == created.secret[:10] and stored.scope == "read"


def test_token_names_and_limits(session, monkeypatch):
    service = ApiTokenService(ApiTokenRepository(session, TEST_USER_ID))
    service.create(ApiTokenCreate(name="Desk"))
    with pytest.raises(ValueError, match="already have a token named"):
        service.create(ApiTokenCreate(name="desk"))
    with pytest.raises(ValueError):
        ApiTokenCreate(name="  ")
    with pytest.raises(ValueError):
        ApiTokenCreate(name="x", scope="admin")
    monkeypatch.setattr("app.services.api_token.MAX_ACTIVE_TOKENS", 1)
    with pytest.raises(ValueError, match="at most 1"):
        service.create(ApiTokenCreate(name="Another"))


def test_another_users_token_cannot_be_revoked(session):
    theirs = ApiTokenService(ApiTokenRepository(session, OTHER_USER)).create(ApiTokenCreate(name="Theirs"))
    with pytest.raises(LookupError):
        ApiTokenService(ApiTokenRepository(session, TEST_USER_ID)).revoke(theirs.tkid)


def test_tokens_do_not_work_on_the_json_api(session, client):
    secret = make_token(session, TEST_USER_ID)
    from fastapi.testclient import TestClient

    from app.auth import require_authenticated_user

    app.dependency_overrides.pop(require_authenticated_user, None)  # restored by the client fixture's teardown
    with TestClient(app) as plain:
        assert plain.get("/api/accounts/", headers={"Authorization": f"Bearer {secret}"}).status_code == 401

"""The third access level: read, write and manage accounts. Nobody gets it unless they choose it."""

import pytest

from app.models.api_token import TokenScope

from .conftest import TEST_USER_ID
from .mcputil import make_token, mcp_client, payload, running_app


def test_the_scope_helpers():
    assert [TokenScope.can_write(s) for s in ("read", "write", "manage")] == [False, True, True]
    assert [TokenScope.can_manage(s) for s in ("read", "write", "manage")] == [False, False, True]
    assert TokenScope.LABELS["manage"] == "read, write & manage accounts"


def test_a_token_can_be_made_with_and_moved_between_every_level(client):
    made = client.post("/api/assistants/tokens", json={"name": "Boss", "scope": "manage"})
    assert made.status_code == 201 and made.json()["scope"] == "manage", made.text
    token = made.json()["id"]
    for scope in ("write", "read", "manage"):
        moved = client.post(f"/api/assistants/tokens/{token}/access", json={"scope": scope})
        assert moved.status_code == 200, moved.text
        assert [t["scope"] for t in client.get("/api/assistants/").json()["tokens"]] == [scope]
    assert client.post(f"/api/assistants/tokens/{token}/access", json={"scope": "root"}).status_code == 400


@pytest.mark.anyio
async def test_the_status_and_instructions_tell_each_level_what_it_may_do(session):
    expectations = {
        "read": ("read only", False, False, "read-only"),
        "write": ("read & write", True, False, "not manage accounts, categories or tags"),
        "manage": ("read, write & manage accounts", True, True, "may also change accounts, categories and tags"),
    }
    for scope, (label, can_write, can_manage, note) in expectations.items():
        async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, name=scope, scope=scope)) as c:
            status = payload(await c.call_tool("get_status", {}))["connection"]
            assert (status["access"], status["can_change_things"], status["can_change_accounts"]) == (
                label,
                can_write,
                can_manage,
            )
            assert note in c.instructions

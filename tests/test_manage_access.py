"""The third access level: read, write and manage accounts. Nobody gets it unless they choose it."""

import pytest

from app.models.api_token import TokenScope

from .conftest import TEST_USER_ID
from .mcputil import make_token, mcp_client, payload, running_app


def test_the_scope_helpers():
    assert [TokenScope.can_write(s) for s in ("read", "write", "manage")] == [False, True, True]
    assert [TokenScope.can_manage(s) for s in ("read", "write", "manage")] == [False, False, True]
    assert TokenScope.LABELS["manage"] == "read, write & manage accounts"


def test_a_token_can_be_made_with_and_moved_between_every_level(client, session):
    made = client.post("/profile/assistants", data={"name": "Boss", "scope": "manage"})
    assert made.status_code == 200 and "read, write &amp; manage accounts" in made.text
    from app.repositories.api_token import ApiTokenRepository

    token = ApiTokenRepository(session, TEST_USER_ID).list()[0]
    for scope in ("write", "read", "manage"):
        assert client.post(f"/profile/assistants/{token.id}/access", data={"scope": scope}).headers["HX-Redirect"]
        session.expire_all()
        assert ApiTokenRepository(session, TEST_USER_ID).list()[0].scope == scope
    assert client.post(f"/profile/assistants/{token.id}/access", data={"scope": "root"}).status_code == 400


def test_each_level_offers_the_other_two(client, session):
    for scope, offers in (
        ("read", ["Allow changes", "Allow account changes"]),
        ("write", ["Make read only", "Allow account changes"]),
        ("manage", ["Make read only", "Stop account changes"]),
    ):
        client.post("/profile/assistants", data={"name": f"t-{scope}", "scope": scope})
        page = client.get("/profile/assistants").text
        row = page[page.index(f"t-{scope}") :]
        row = row[: row.index("</li>")]
        assert all(label in row for label in offers), (scope, offers)
        client.post(f"/profile/assistants/{_tkid(session, f't-{scope}')}/revoke")


def _tkid(session, name):
    from app.repositories.api_token import ApiTokenRepository

    return next(t.id for t in ApiTokenRepository(session, TEST_USER_ID).list() if t.name == name)


@pytest.mark.anyio
async def test_the_status_and_instructions_tell_each_level_what_it_may_do(session):
    expectations = {
        "read": ("read only", False, False, "read-only"),
        "write": ("read & write", True, False, "not accounts"),
        "manage": ("read, write & manage accounts", True, True, "may also change accounts"),
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

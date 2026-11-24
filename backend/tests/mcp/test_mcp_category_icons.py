"""Assistants and category icons: create_category must name an icon from list_category_icons, update_category can
change it, and list_categories shows it."""

import pytest

from tests.conftest import TEST_USER_ID
from tests.mcputil import ToolFailed, make_token, mcp_client, payload, running_app

pytestmark = pytest.mark.anyio


async def test_create_category_needs_a_known_icon(session):
    token = make_token(session, TEST_USER_ID, scope="manage")
    async with running_app(session), mcp_client(token) as c:
        with pytest.raises(Exception, match="icon"):
            payload(await c.call_tool("create_category", {"name": "Gifts", "kind": "spending"}))
        with pytest.raises(ToolFailed, match="'rocket' is not one of finode's category icons.*list_category_icons"):
            payload(await c.call_tool("create_category", {"name": "Gifts", "kind": "spending", "icon": "rocket"}))
        made = payload(await c.call_tool("create_category", {"name": "Gifts", "kind": "spending", "icon": "gift"}))
        assert made["created"]["icon"] == "gift"
        changed = payload(await c.call_tool("update_category", {"category": "Gifts", "icon": "hand-heart"}))
        assert changed["updated"]["icon"] == "hand-heart"
        listed = payload(await c.call_tool("list_categories", {}))
        assert {r["name"]: r["icon"] for r in listed["categories"]}["Gifts"] == "hand-heart"


async def test_list_category_icons_gives_the_groups(session):
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="read")) as c:
        answer = payload(await c.call_tool("list_category_icons", {}))
    groups = answer["groups"]
    assert [g["name"] for g in groups] == [
        "Food and home",
        "Getting around",
        "Health and family",
        "Fun and shopping",
        "Money",
    ]
    names = {n for g in groups for n in g["icons"]}
    assert "tag" in names and not names & {"layers", "circle-dashed", "arrow-left-right", "user", "flag"}

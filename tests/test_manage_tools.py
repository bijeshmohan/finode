"""Changing accounts through the assistants' tools: only with the manage level, with history and ids that survive."""

import pytest

from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app


@pytest.fixture
def books(client, root_accounts):
    banks = client.post("/api/accounts/", json={"name": "Banks", "parent_id": root_accounts["Assets"]}).json()
    hdfc = client.post("/api/accounts/", json={"name": "HDFC", "parent_id": banks["aid"], "balance": "500"}).json()
    cash = client.post("/api/accounts/", json={"name": "Cash2", "parent_id": root_accounts["Assets"]}).json()
    food = client.post("/api/accounts/", json={"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    return {"banks": banks, "hdfc": hdfc, "cash": cash, "food": food}


async def call(c, tool, **args):
    return payload(await c.call_tool(tool, args))


@pytest.mark.anyio
async def test_a_rename_keeps_the_id_and_the_history(session, client, books):
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, name="Claude", scope="manage")) as c:
        done = await call(c, "update_account", account="Banks", name="Bank Accounts", details="where salary lands")
        assert done["was"] == "Assets:Banks" and done["updated"]["path"] == "Assets:Bank Accounts"
        assert done["updated"]["id"] == books["banks"]["aid"] and done["updated"]["details"] == "where salary lands"
        by_old_id = await call(c, "get_account", account=books["hdfc"]["aid"])
        assert by_old_id["path"] == "Assets:Bank Accounts:HDFC" and by_old_id["balance"] == "500.00"
        history = await call(c, "get_account_history", account=books["banks"]["aid"])
        assert history["history"][-1]["by"] == "assistant (Claude)"
        assert history["history"][-1]["changes"]["name"] == {"from": "Banks", "to": "Bank Accounts"}


@pytest.mark.anyio
async def test_move_budget_flag_and_clearing_a_note(session, client, books):
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="manage")) as c:
        moved = await call(c, "update_account", account="HDFC", parent="Cash2", on_budget=False)
        assert moved["updated"]["path"] == "Assets:Cash2:HDFC" and moved["updated"]["on_budget"] is False
        await call(c, "update_account", account="HDFC", details="x")
        assert (await call(c, "update_account", account="HDFC", details=""))["updated"]["details"] is None
        linked = await call(c, "update_account", account="HDFC", payment_category="Food")
        assert linked["updated"]["payment_category"] == "Expenses:Food"
        assert (
            "payment_category" not in (await call(c, "update_account", account="HDFC", payment_category=""))["updated"]
        )
        with pytest.raises(ToolFailed, match="nothing to change"):
            await call(c, "update_account", account="HDFC")


@pytest.mark.anyio
async def test_the_rules_still_apply(session, client, books):
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="manage")) as c:
        with pytest.raises(ToolFailed, match="different root"):
            await call(c, "update_account", account="HDFC", parent="Expenses")
        with pytest.raises(ToolFailed, match="already|exists"):
            await call(c, "update_account", account="Cash2", name="Banks")
        with pytest.raises(ToolFailed):
            await call(c, "update_account", account="Assets", name="Mine")
        with pytest.raises(ToolFailed, match="holds"):
            await call(c, "close_account", account="HDFC")


@pytest.mark.anyio
async def test_close_and_reopen(session, client, books):
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="manage")) as c:
        closed = await call(c, "close_account", account="Cash2")
        assert closed["closed"]["closed"] and closed["closed"]["can_post"] is False
        reopened = await call(c, "reopen_account", account="Cash2")
        assert "closed" not in reopened["reopened"] and reopened["reopened"]["can_post"] is True
        steps = (await call(c, "get_account_history", account="Cash2"))["history"]
        assert [s["action"] for s in steps] == ["created", "closed", "reopened"]


@pytest.mark.anyio
async def test_lower_levels_see_the_tools_but_they_refuse(session, client, books):
    for scope, message in (("write", "not manage accounts or tags"), ("read", "read-only")):
        async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, name=scope, scope=scope)) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"update_account", "close_account", "reopen_account"} <= names
            with pytest.raises(ToolFailed, match=message):
                await call(c, "update_account", account="Cash2", name="Wallet")
            with pytest.raises(ToolFailed, match=message):
                await call(c, "close_account", account="Cash2")
    assert client.get(f"/api/accounts/{books['cash']['aid']}").json()["name"] == "Cash2"

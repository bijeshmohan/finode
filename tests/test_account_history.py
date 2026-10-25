"""An append-only history of what happened to each account: who, when and what changed."""

import pytest

from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app


def steps(client, aid):
    return client.get(f"/api/accounts/{aid}/changes").json()


def test_an_account_has_a_history_from_the_start(client, root_accounts):
    made = client.post("/api/accounts/", json={"name": "Wallet", "parent_id": root_accounts["Assets"]}).json()
    client.patch(f"/api/accounts/{made['aid']}", json={"name": "Purse", "details": "daily cash"})
    client.post(f"/api/accounts/{made['aid']}/close")
    client.post(f"/api/accounts/{made['aid']}/reopen")
    got = steps(client, made["aid"])
    assert [s["action"] for s in got] == ["created", "updated", "closed", "reopened"]
    assert got[0]["entry"]["path"] == "Assets:Wallet" and got[0]["via"] == "api"
    assert got[1]["changes"] == {
        "name": {"from": "Wallet", "to": "Purse"},
        "path": {"from": "Assets:Wallet", "to": "Assets:Purse"},
        "note": {"from": None, "to": "daily cash"},
    }
    assert got[2]["entry"]["closed_on"] and got[3]["entry"]["closed_on"] is None


def test_moving_and_budget_changes_are_told(client, root_accounts):
    a = client.post("/api/accounts/", json={"name": "Banks", "parent_id": root_accounts["Assets"]}).json()
    b = client.post("/api/accounts/", json={"name": "Cash", "parent_id": root_accounts["Assets"]}).json()
    kid = client.post("/api/accounts/", json={"name": "Purse", "parent_id": a["aid"]}).json()
    client.patch(f"/api/accounts/{kid['aid']}", json={"parent_id": b["aid"], "on_budget": False})
    change = steps(client, kid["aid"])[-1]["changes"]
    assert change["path"] == {"from": "Assets:Banks:Purse", "to": "Assets:Cash:Purse"}
    assert change["on_budget"]["to"] is False


def test_a_save_that_changes_nothing_adds_no_step(client, root_accounts):
    made = client.post("/api/accounts/", json={"name": "Wallet", "parent_id": root_accounts["Assets"]}).json()
    client.patch(f"/api/accounts/{made['aid']}", json={"name": "Wallet"})
    assert len(steps(client, made["aid"])) == 1


def test_a_deleted_account_keeps_its_history(client, root_accounts):
    made = client.post("/api/accounts/", json={"name": "Temp", "parent_id": root_accounts["Expenses"]}).json()
    assert client.delete(f"/api/accounts/{made['aid']}").status_code == 204
    got = steps(client, made["aid"])
    assert [s["action"] for s in got] == ["created", "deleted"] and got[1]["entry"]["name"] == "Temp"
    did = client.get("/api/accounts/deleted").json()[0]["did"]
    client.post(f"/api/accounts/deleted/{did}/restore")
    assert [s["action"] for s in steps(client, made["aid"])] == ["created", "deleted", "restored"]


def test_what_finode_makes_itself_is_not_logged(client, root_accounts, account):
    client.post("/api/accounts/", json={"name": "Bank2", "parent_id": account["parent_id"], "balance": "10"})
    recent = client.get("/api/accounts/changes").json()
    assert "Opening Balances" not in {c["entry"]["name"] for c in recent}
    assert {c["entry"]["name"] for c in recent} >= {"checking", "Bank2"}
    assert not {c["entry"]["name"] for c in recent} & {"Assets", "Liabilities", "Equity", "Income", "Expenses"}


def test_recent_changes_can_be_limited(client, root_accounts):
    for n in range(3):
        client.post("/api/accounts/", json={"name": f"A{n}", "parent_id": root_accounts["Assets"]})
    assert [c["entry"]["name"] for c in client.get("/api/accounts/changes", params={"limit": 2}).json()] == ["A2", "A1"]
    assert client.get("/api/accounts/changes", params={"by": "assistant"}).json() == []
    assert len(client.get("/api/accounts/changes", params={"by": "api"}).json()) == 3
    assert client.get("/api/accounts/00000000-0000-4000-8000-000000000000/changes").status_code == 404


@pytest.mark.anyio
async def test_assistants_changes_carry_their_name(session, client, root_accounts):
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, name="Claude")) as c:
        made = payload(await c.call_tool("create_account", {"name": "Fund", "parent": "Assets"}))["created"]
        history = payload(await c.call_tool("get_account_history", {"account": made["path"]}))
        assert history["exists"] is True and history["history"][0]["by"] == "assistant (Claude)"
        mine = payload(await c.call_tool("recent_changes", {"what": "accounts", "by": "assistant"}))
        assert mine["count"] == 1 and mine["changes"][0]["entry"]["name"] == "Fund"
        client.delete(f"/api/accounts/{made['id']}")
        gone = payload(await c.call_tool("get_account_history", {"account": made["id"]}))
        assert gone["exists"] is False and gone["history"][-1]["action"] == "deleted"
        with pytest.raises(ToolFailed, match="no account matches"):
            payload(await c.call_tool("get_account_history", {"account": "Nowhere"}))

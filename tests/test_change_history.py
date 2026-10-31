"""The history of an entry with what each step changed, and the latest changes across entries."""

from datetime import date, timedelta

import pytest

from .books import leg
from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app
from .test_transaction_references import body


def make(client, account, expense, **extra):
    return client.post("/api/transactions/", json=body(expense, account, **extra)).json()


def test_each_update_says_what_it_changed(client, account, other_account, expense_account):
    made = make(client, account, expense_account, payee="Cafe")
    client.patch(f"/api/transactions/{made['id']}", json={"payee": "Bar", "comment": "late"})
    rows = [
        leg(other_account, "credit", "100"),
        leg(expense_account, "debit", "120"),
        leg(account, "credit", "20"),
    ]
    client.patch(f"/api/transactions/{made['id']}", json={"postings": rows})
    client.patch(f"/api/transactions/{made['id']}", json={"source": "gmail", "external_id": "m1"})
    client.delete(f"/api/transactions/{made['id']}")
    steps = client.get(f"/api/transactions/{made['id']}/changes").json()
    assert [s["action"] for s in steps] == ["created", "updated", "updated", "updated", "deleted"]
    assert steps[0]["changes"] == {} and steps[0]["entry"]["payee"] == "Cafe"
    assert steps[1]["changes"] == {"payee": {"from": "Cafe", "to": "Bar"}, "note": {"from": None, "to": "late"}}
    posting = steps[2]["changes"]["postings"]
    assert [r["account"] for r in posting["added"]] == ["Assets:savings"] and posting["removed"] == []
    assert posting["changed"][0]["from"] == "100.00" and posting["changed"][0]["to"] == "120.00"
    assert steps[3]["changes"]["reference"]["to"]["external_id"] == "m1"
    assert steps[4]["changes"] == {} and steps[4]["entry"]["external_id"] == "m1"


def test_an_unchanged_save_adds_no_step_and_old_snapshots_compare(client, account, expense_account, session):
    made = make(client, account, expense_account)
    client.patch(f"/api/transactions/{made['id']}", json={"payee": made["payee"]})
    assert len(client.get(f"/api/transactions/{made['id']}/changes").json()) == 1
    assert client.get("/api/transactions/00000000-0000-4000-8000-000000000000/changes").status_code == 404


def test_the_latest_changes_can_be_limited_by_day_and_origin(client, account, expense_account):
    first = make(client, account, expense_account, payee="One")
    make(client, account, expense_account, payee="Two", on="2026-10-11")
    client.patch(f"/api/transactions/{first['id']}", json={"payee": "Uno"})
    recent = client.get("/api/transactions/changes").json()
    assert [(c["action"], c["entry"]["payee"]) for c in recent] == [
        ("updated", "Uno"),
        ("created", "Two"),
        ("created", "One"),
    ]
    assert recent[0]["changes"] == {"payee": {"from": "One", "to": "Uno"}}
    assert len(client.get("/api/transactions/changes", params={"limit": 1}).json()) == 1
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert client.get("/api/transactions/changes", params={"since": tomorrow}).json() == []
    assert client.get("/api/transactions/changes", params={"by": "assistant"}).json() == []
    assert len(client.get("/api/transactions/changes", params={"by": "api"}).json()) == 3


@pytest.mark.anyio
async def test_assistants_can_see_who_changed_what(session, client, account, expense_account):
    made = make(client, account, expense_account, payee="Cafe")
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, name="Claude")) as c:
        await c.call_tool("update_transaction", {"transaction_id": made["id"], "payee": "Bar"})
        history = payload(await c.call_tool("get_transaction_history", {"transaction_id": made["id"]}))
        assert history["exists"] is True and [h["action"] for h in history["history"]] == ["created", "updated"]
        assert history["history"][0]["by"] == "api" and history["history"][1]["by"] == "assistant (Claude)"
        assert history["history"][1]["changes"] == {"payee": {"from": "Cafe", "to": "Bar"}}
        assert history["history"][0]["entry"]["total"] == "100.00"
        mine = payload(await c.call_tool("recent_changes", {"by": "assistant"}))
        assert mine["count"] == 1 and mine["changes"][0]["by"] == "assistant (Claude)"
        everything = payload(await c.call_tool("recent_changes", {"since": date.today().isoformat()}))
        assert everything["count"] == 2
        client.delete(f"/api/transactions/{made['id']}")
        gone = payload(await c.call_tool("get_transaction_history", {"transaction_id": made["id"]}))
        assert gone["exists"] is False and gone["history"][-1]["action"] == "deleted"
        with pytest.raises(ToolFailed, match="no history"):
            payload(
                await c.call_tool("get_transaction_history", {"transaction_id": "00000000-0000-4000-8000-000000000000"})
            )

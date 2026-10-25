"""dry_run runs every rule of a write and saves nothing, in the JSON API and for assistants (also read-only ones)."""

import pytest

from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app
from .test_transaction_references import PAY, body


def count(client):
    return len(client.get("/api/transactions/").json())


def test_creating_with_dry_run_saves_nothing(client, account, expense_account):
    answer = client.post("/api/transactions/?dry_run=true", json=body(expense_account, account, **PAY))
    assert answer.status_code == 200
    assert answer.json()["dry_run"] is True and answer.json()["tid"] is None and answer.json()["external_id"] == "msg-1"
    assert count(client) == 0
    # the reference was not taken either
    assert client.post("/api/transactions/", json=body(expense_account, account, **PAY)).status_code == 201


def test_a_dry_run_refuses_what_the_real_call_refuses(client, account, expense_account, root_accounts):
    root = {"aid": root_accounts["Assets"]}
    assert client.post("/api/transactions/?dry_run=true", json=body(root, account)).status_code == 400
    bad = body(expense_account, account, amount="1.005")
    assert client.post("/api/transactions/?dry_run=true", json=bad).status_code == 400
    client.post("/api/transactions/", json=body(expense_account, account, **PAY))
    other = body(expense_account, account, amount="101", **PAY)
    assert client.post("/api/transactions/?dry_run=true", json=other).status_code == 400
    assert count(client) == 1


def test_a_dry_run_of_a_repeat_names_the_entry_already_there(client, account, expense_account):
    first = client.post("/api/transactions/", json=body(expense_account, account, **PAY)).json()
    again = client.post("/api/transactions/?dry_run=true", json=body(expense_account, account, **PAY)).json()
    assert again["already_recorded"] == first["tid"] and again["tid"] == first["tid"]


def test_updating_with_dry_run_shows_the_result_and_changes_nothing(client, account, expense_account):
    made = client.post("/api/transactions/", json=body(expense_account, account, payee="Old")).json()
    patch = {"payee": "New", "postings": body(expense_account, account, amount="40")["postings"]}
    answer = client.patch(f"/api/transactions/{made['tid']}?dry_run=true", json=patch).json()
    assert (
        answer["tid"] == made["tid"] and answer["payee"] == "New" and answer["postings"][0]["amount"] in ("40", "40.00")
    )
    assert client.get(f"/api/transactions/{made['tid']}").json()["payee"] == "Old"
    kept = client.patch(f"/api/transactions/{made['tid']}?dry_run=true", json={"comment": "x"}).json()
    assert kept["payee"] == "Old" and kept["postings"][0]["amount"] == "100.00"
    unbalanced = {"postings": body(expense_account, account)["postings"][:1]}
    assert client.patch(f"/api/transactions/{made['tid']}?dry_run=true", json=unbalanced).status_code == 422


def test_deleting_with_dry_run_keeps_the_entry(client, account, expense_account):
    made = client.post("/api/transactions/", json=body(expense_account, account)).json()
    answer = client.delete(f"/api/transactions/{made['tid']}?dry_run=true")
    assert answer.status_code == 200 and answer.json()["tid"] == made["tid"]
    assert count(client) == 1
    assert client.delete(f"/api/transactions/{made['tid']}").status_code == 204
    assert client.delete(f"/api/transactions/{made['tid']}?dry_run=true").status_code == 404


@pytest.mark.anyio
async def test_assistants_can_check_before_they_write(session, client, account, expense_account):
    args = {"amount": "75", "from_account": account["aid"], "to_account": expense_account["aid"], "payee": "Cafe"}
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        seen = payload(await c.call_tool("record_transaction", args | {"dry_run": True}))
        assert seen["dry_run"] is True and seen["saved"] is False and seen["would_record"]["total"] == "75.00"
        assert count(client) == 0
        made = payload(await c.call_tool("record_transaction", args))["recorded"]["id"]
        change = payload(
            await c.call_tool("update_transaction", {"transaction_id": made, "payee": "Bar", "dry_run": True})
        )
        assert change["would_become"]["payee"] == "Bar" and change["would_become"]["id"] == made
        assert client.get(f"/api/transactions/{made}").json()["payee"] == "Cafe"
        gone = payload(await c.call_tool("delete_transaction", {"transaction_id": made, "dry_run": True}))
        assert gone["would_delete"]["id"] == made and count(client) == 1
        rows = [
            {"account": account["aid"], "side": "credit", "amount": "9"},
            {"account": expense_account["aid"], "side": "debit", "amount": "9"},
        ]
        split = payload(await c.call_tool("record_split", {"postings": rows, "dry_run": True}))
        assert split["would_record"]["total"] == "9.00" and count(client) == 1
        rows[1]["amount"] = "8"
        with pytest.raises(ToolFailed, match="balance"):
            payload(await c.call_tool("record_split", {"postings": rows, "dry_run": True}))


@pytest.mark.anyio
async def test_a_read_only_connection_may_check_but_not_write(session, client, account, expense_account):
    args = {"amount": "75", "from_account": account["aid"], "to_account": expense_account["aid"]}
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="read")) as c:
        seen = payload(await c.call_tool("record_transaction", args | {"dry_run": True}))
        assert seen["would_record"]["total"] == "75.00" and count(client) == 0
        with pytest.raises(ToolFailed, match="read-only"):
            payload(await c.call_tool("record_transaction", args))
        with pytest.raises(ToolFailed, match="read-only"):
            payload(await c.call_tool("record_transaction", args | {"dry_run": False}))
        assert count(client) == 0

"""Closing accounts: what is refused, what stays, where closed accounts disappear from, and reopening."""

import pytest

from .test_budget import assign, budget, line


@pytest.fixture
def books(client, root_accounts):
    def make(name, parent, **extra):
        response = client.post("/api/accounts/", json={"name": name, "parent_id": parent, **extra})
        assert response.status_code == 201, response.text
        return response.json()

    banks = make("Banks", root_accounts["Assets"])
    old = make("Old Savings", banks["aid"])
    hdfc = make("HDFC", banks["aid"], balance="1000")
    food = make("Food", root_accounts["Expenses"])
    groceries = make("Groceries", food["aid"])
    return {"banks": banks, "old": old, "hdfc": hdfc, "food": food, "groceries": groceries}


def spend(client, source, target, amount="10"):
    return client.post("/api/transactions/", json={"postings": [
        {"account": target["aid"], "side": "debit", "amount": amount},
        {"account": source["aid"], "side": "credit", "amount": amount},
    ]})


def close(client, account):
    return client.post(f"/api/accounts/{account['aid']}/close")


def test_an_empty_account_closes_and_keeps_its_history(client, books):
    spend(client, books["hdfc"], books["groceries"], "10")
    client.post("/api/transactions/", json={"postings": [
        {"account": books["old"]["aid"], "side": "debit", "amount": "5"},
        {"account": books["hdfc"]["aid"], "side": "credit", "amount": "5"},
    ]})
    client.post("/api/transactions/", json={"postings": [
        {"account": books["hdfc"]["aid"], "side": "debit", "amount": "5"},
        {"account": books["old"]["aid"], "side": "credit", "amount": "5"},
    ]})
    closed = close(client, books["old"])
    assert closed.status_code == 200 and closed.json()["closed_on"]
    register = client.get(f"/api/accounts/{books['old']['aid']}/register").json()
    assert len(register) == 2, "its history stays"


def test_an_account_with_a_balance_cannot_be_closed(client, books):
    response = close(client, books["hdfc"])
    assert response.status_code == 400 and "still holds 1000" in response.json()["detail"]
    assert client.get(f"/api/accounts/{books['hdfc']['aid']}").json()["closed_on"] is None


def test_a_future_dated_entry_blocks_closing(client, books):
    client.post("/api/transactions/", json={"date": "2999-01-01", "postings": [
        {"account": books["old"]["aid"], "side": "debit", "amount": "5"},
        {"account": books["hdfc"]["aid"], "side": "credit", "amount": "5"},
    ]})
    assert close(client, books["old"]).status_code == 400


def test_closing_a_group_closes_everything_inside_and_all_must_be_empty(client, books):
    assert close(client, books["banks"]).status_code == 400, "HDFC still holds money"
    response = close(client, books["food"])
    assert response.status_code == 200
    for name in ("food", "groceries"):
        assert client.get(f"/api/accounts/{books[name]['aid']}").json()["closed_on"]


def test_roots_and_system_accounts_cannot_be_closed(client, books, root_accounts):
    assert client.post(f"/api/accounts/{root_accounts['Assets']}/close").status_code == 400
    opening = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Opening Balances")
    assert client.post(f"/api/accounts/{opening['aid']}/close").status_code == 400
    assert client.post("/api/accounts/00000000-0000-4000-8000-0000000000aa/close").status_code == 404


def test_nothing_can_be_posted_to_a_closed_account(client, books):
    close(client, books["old"])
    refused = spend(client, books["hdfc"], books["old"])
    assert refused.status_code == 400 and "is closed" in refused.json()["detail"]
    created = client.post("/api/accounts/", json={"name": "Child", "parent_id": books["old"]["aid"]})
    assert created.status_code == 400 and "closed" in created.json()["detail"]
    assert client.patch(f"/api/accounts/{books['old']['aid']}", json={"balance": "5"}).status_code == 400
    moved = client.patch(f"/api/accounts/{books['hdfc']['aid']}", json={"parent_id": books["old"]["aid"]})
    assert moved.status_code == 400


def test_an_old_entry_on_a_closed_account_can_still_be_edited(client, books):
    made = client.post("/api/transactions/", json={"payee": "x", "postings": [
        {"account": books["old"]["aid"], "side": "debit", "amount": "5"},
        {"account": books["hdfc"]["aid"], "side": "credit", "amount": "5"},
    ]}).json()
    client.post("/api/transactions/", json={"postings": [
        {"account": books["hdfc"]["aid"], "side": "debit", "amount": "5"},
        {"account": books["old"]["aid"], "side": "credit", "amount": "5"},
    ]})
    close(client, books["old"])
    edited = client.patch(f"/api/transactions/{made['tid']}", json={"payee": "renamed"})
    assert edited.status_code == 200 and edited.json()["payee"] == "renamed"
    moved = client.patch(f"/api/transactions/{made['tid']}", json={"postings": [
        {"account": books["groceries"]["aid"], "side": "debit", "amount": "5"},
        {"account": books["hdfc"]["aid"], "side": "credit", "amount": "5"},
    ]})
    assert moved.status_code == 200, "moving it off the closed account is fine"


def test_a_running_recurring_rule_blocks_closing(client, books):
    rule = client.post("/api/recurring/", json={
        "from_account": books["old"]["aid"], "to_account": books["groceries"]["aid"], "amount": "1",
        "start_date": "2999-01-01", "payee": "Netflix",
    }).json()
    refused = close(client, books["old"])
    assert refused.status_code == 409 and "Netflix" in refused.json()["detail"]
    paused = client.post(f"/recurring/{rule['rid']}/pause")
    assert paused.status_code == 200
    assert close(client, books["old"]).status_code == 200


def test_reopening_brings_back_the_account_its_groups_and_what_is_inside(client, books):
    close(client, books["food"])
    reopened = client.post(f"/api/accounts/{books['food']['aid']}/reopen")
    assert reopened.status_code == 200 and reopened.json()["closed_on"] is None
    assert client.get(f"/api/accounts/{books['groceries']['aid']}").json()["closed_on"] is None
    close(client, books["food"])
    client.post(f"/api/accounts/{books['groceries']['aid']}/reopen")
    assert client.get(f"/api/accounts/{books['food']['aid']}").json()["closed_on"] is None, "its group opens with it"
    assert spend(client, books["hdfc"], books["groceries"]).status_code == 201


def test_pickers_leave_closed_accounts_out_but_keep_what_an_entry_uses(client, books):
    made = client.post("/api/transactions/", json={"postings": [
        {"account": books["old"]["aid"], "side": "debit", "amount": "5"},
        {"account": books["hdfc"]["aid"], "side": "credit", "amount": "5"},
    ]}).json()
    client.post("/api/transactions/", json={"postings": [
        {"account": books["hdfc"]["aid"], "side": "debit", "amount": "5"},
        {"account": books["old"]["aid"], "side": "credit", "amount": "5"},
    ]})
    close(client, books["old"])
    assert f'<option value="{books["old"]["aid"]}"' not in client.get("/transactions/new").text
    assert f'<option value="{books["old"]["aid"]}"' in client.get(f"/transactions/{made['tid']}/edit").text


def test_the_accounts_page_tucks_closed_accounts_away(client, books):
    close(client, books["old"])
    page = client.get("/accounts").text
    assert "1 closed account · Show" in page and "closed-hidden" in page and '<span class="badge">closed</span>' in page
    detail = client.get(f"/accounts/{books['old']['aid']}").text
    assert "Reopen account" in detail and "Closed on " in detail and f"/transactions/new?account={books['old']['aid']}" not in detail
    open_detail = client.get(f"/accounts/{books['hdfc']['aid']}").text
    assert "Close account" in open_detail and "still holds" in open_detail


def test_the_close_and_reopen_pages_work(client, books):
    refused = client.post(f"/accounts/{books['hdfc']['aid']}/close")
    assert refused.status_code == 400 and refused.headers["HX-Retarget"] == "#page-error"
    done = client.post(f"/accounts/{books['old']['aid']}/close")
    assert done.headers["HX-Redirect"] == "/accounts" and "account-closed" in done.headers["set-cookie"]
    back = client.post(f"/accounts/{books['old']['aid']}/reopen")
    assert back.headers["HX-Redirect"] == f"/accounts/{books['old']['aid']}"


def test_a_closed_category_leaves_the_budget_once_it_is_empty(client, books):
    assign(client, books["groceries"], "50")
    assert close(client, books["groceries"]).status_code == 200
    assert line(budget(client), "Groceries")["assigned"] == "50.00", "it still holds money this month"
    assign(client, books["groceries"], "0")
    names = [l["name"] for l in budget(client)["lines"]]
    assert "Groceries" not in names and names == ["Food"], "its open group stays, now a plain row"


def test_closing_a_category_clears_its_target(client, books):
    client.put(f"/api/budget/categories/{books['groceries']['aid']}/target", json={"kind": "monthly", "amount": "5"})
    close(client, books["groceries"])
    assert budget(client)["underfunded"] == "0.00"


@pytest.mark.anyio
async def test_assistants_do_not_see_or_post_to_closed_accounts(session, client, books):
    from .conftest import TEST_USER_ID
    from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app

    close(client, books["old"])
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        paths = {a["path"] for a in payload(await c.call_tool("list_accounts", {}))["accounts"]}
        assert "Assets:Banks:Old Savings" not in paths
        listed = payload(await c.call_tool("list_accounts", {"include_closed": True}))["accounts"]
        entry = next(a for a in listed if a["path"] == "Assets:Banks:Old Savings")
        assert entry["can_post"] is False and entry["closed"]
        with pytest.raises(ToolFailed, match="is closed"):
            payload(await c.call_tool("record_transaction", {"amount": "1", "from_account": "HDFC", "to_account": "Old Savings"}))

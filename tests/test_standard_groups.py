"""Adding the standard groups to a ledger that already exists (Settings › Standard groups): nothing is moved or renamed."""

import pytest

from .test_budget import account


def keyed(client):
    return {a["system_key"]: a for a in client.get("/api/accounts/").json() if a["system_key"]}



@pytest.fixture
def mine(client, root_accounts):
    """An existing person (no built-in groups) with accounts of their own."""
    banks = account(client, root_accounts, "Banks", "Assets")
    hdfc = client.post("/api/accounts/", json={"name": "HDFC", "parent_id": banks["aid"], "balance": "500"}).json()
    return {"roots": root_accounts, "banks": banks, "hdfc": hdfc}


def sheet(client):
    return client.get("/settings/groups").text


def test_the_row_shows_only_to_people_missing_groups(client, mine):
    assert 'id="groups"' in client.get("/settings").text
    assert "Add 5 groups" in sheet(client)


def test_adding_makes_the_five_groups_and_moves_nothing(client, mine):
    done = client.post("/settings/groups")
    assert done.status_code == 200 and done.headers["HX-Redirect"] == "/settings"
    assert set(keyed(client)) == {"assets.bank", "assets.cash", "assets.investments", "liabilities.cards", "liabilities.loans"}
    accounts = {a["name"]: a for a in client.get("/api/accounts/").json()}
    assert accounts["HDFC"]["parent_id"] == mine["banks"]["aid"] and accounts["HDFC"]["balance"] == "500.00"
    assert accounts["Banks"]["system_key"] is None
    assert 'id="groups"' not in client.get("/settings").text, "nothing left to add: the row goes"
    assert client.post("/settings/groups").status_code == 400


def test_an_account_in_the_way_is_skipped_with_the_reason(client, mine):
    cash = account(client, mine["roots"], "Cash", "Assets", balance="200")
    text = sheet(client)
    assert "Skipped" in text and "you already have an account called Cash under Assets" in text
    assert "Add 4 groups" in text
    client.post("/settings/groups")
    found = keyed(client)
    assert "assets.cash" not in found and len(found) == 4
    assert next(a for a in client.get("/api/accounts/").json() if a["aid"] == cash["aid"])["balance"] == "200.00"
    assert 'id="groups"' in client.get("/settings").text, "the row stays until the skipped one is added"
    client.patch(f"/api/accounts/{cash['aid']}", json={"name": "Wallet cash"})
    client.post("/settings/groups")
    assert "assets.cash" in keyed(client)


def test_a_group_of_theirs_with_exactly_that_name_becomes_the_built_in_one(client, mine):
    inv = account(client, mine["roots"], "Investments", "Assets")
    fund = client.post("/api/accounts/", json={"name": "Mutual Funds", "parent_id": inv["aid"], "on_budget": False}).json()
    text = sheet(client)
    assert "Uses the Investments you already have" in text and "Your group" in text, "told apart from a group made new"
    assert "1 of your own" in text and "4 new" in text and "becomes this group" not in text
    assert "Set up 5 groups" in text and "Add 5 groups" not in text
    client.post("/settings/groups")
    found = keyed(client)
    assert found["assets.investments"]["aid"] == inv["aid"], "the same account, now built in"
    accounts = {a["name"]: a for a in client.get("/api/accounts/").json()}
    assert accounts["Mutual Funds"]["parent_id"] == inv["aid"] and accounts["Mutual Funds"]["on_budget"] is False
    assert client.patch(f"/api/accounts/{inv['aid']}", json={"name": "Funds"}).status_code == 400


def test_a_different_spelling_is_not_taken_over(client, mine):
    account(client, mine["roots"], "investments", "Assets")
    assert "Skipped" in sheet(client)
    client.post("/settings/groups")
    assert "assets.investments" not in keyed(client)


def test_an_empty_account_of_theirs_with_that_name_is_adopted_but_one_with_entries_is_not(client, mine):
    loans = account(client, mine["roots"], "Loans", "Liabilities", on_budget=False)
    account(client, mine["roots"], "Cash", "Assets", balance="10")
    client.post("/settings/groups")
    assert keyed(client)["liabilities.loans"]["aid"] == loans["aid"]
    assert "assets.cash" not in keyed(client)


def test_moving_an_account_into_a_group_keeps_its_settings(client, mine):
    client.post("/settings/groups")
    bank = keyed(client)["assets.bank"]
    too_deep = client.patch(f"/api/accounts/{mine['banks']['aid']}", json={"parent_id": bank["aid"]})
    assert too_deep.status_code == 400, "a group of their own with accounts in it cannot go inside (three levels)"
    moved = client.patch(f"/api/accounts/{mine['hdfc']['aid']}", json={"parent_id": bank["aid"]})
    assert moved.status_code == 200, moved.text
    assert moved.json()["on_budget"] == mine["hdfc"]["on_budget"] and moved.json()["parent_id"] == bank["aid"]

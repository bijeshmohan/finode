"""How a payee is usually booked: the newest simple entry's accounts, for the API and for assistants."""

import pytest

from .conftest import TEST_USER_ID
from .mcputil import make_token, mcp_client, payload, running_app
from .test_transaction_references import body


def post(client, debit, credit, payee, on, amount="10"):
    assert client.post("/api/transactions/", json=body(debit, credit, amount, on=on, payee=payee)).status_code == 201


@pytest.fixture
def habits(client, account, other_account, expense_account, root_accounts):
    other_expense = client.post("/api/accounts/", json={"name": "meat", "parent_id": root_accounts["Expenses"]}).json()
    salary = client.post("/api/accounts/", json={"name": "salary", "parent_id": root_accounts["Income"]}).json()
    post(client, expense_account, account, "Manjunatha", "2026-10-01")
    post(client, other_expense, account, "Manjunatha", "2026-10-05")
    post(client, other_expense, account, "Manjunatha", "2026-10-07")
    post(client, account, salary, "Acme", "2026-10-02", "900")
    post(client, other_account, account, "Own transfer", "2026-10-03")
    return {"meat": other_expense, "groceries": expense_account}


def test_the_newest_route_is_the_usual_one(client, habits):
    found = client.get("/api/transactions/payee-defaults", params={"payee": "manju"}).json()
    assert len(found) == 1
    top = found[0]
    assert (top["payee"], top["uses"], top["kind"], top["exact"]) == ("Manjunatha", 3, "expense", False)
    assert top["to_account"]["path"] == "Expenses:meat" and top["from_account"]["path"] == "Assets:checking"
    assert [(o["to_account"]["path"], o["uses"]) for o in top["other_routes"]] == [("Expenses:groceries", 1)]


def test_kinds_exact_matches_and_order(client, habits):
    everything = client.get("/api/transactions/payee-defaults").json()
    assert [d["payee"] for d in everything] == ["Manjunatha", "Own transfer", "Acme"]
    assert {d["payee"]: d["kind"] for d in everything} == {
        "Manjunatha": "expense",
        "Acme": "income",
        "Own transfer": "transfer",
    }
    assert client.get("/api/transactions/payee-defaults", params={"payee": "ACME"}).json()[0]["exact"] is True
    assert client.get("/api/transactions/payee-defaults", params={"payee": "zzz"}).json() == []
    assert len(client.get("/api/transactions/payee-defaults", params={"limit": 1}).json()) == 1


def test_splits_and_opening_balances_are_not_a_payee(client, account, expense_account):
    client.post("/api/accounts/", json={"name": "bank2", "parent_id": account["parent_id"], "balance": "50"})
    assert client.get("/api/transactions/payee-defaults").json() == []


@pytest.mark.anyio
async def test_assistants_can_ask_how_a_payee_is_booked(session, habits):
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="read")) as c:
        answer = payload(await c.call_tool("payee_defaults", {"payee": "manjunatha"}))
        top = answer["payees"][0]
        assert top["usually"]["to"] == "Expenses:meat" and top["usually"]["to_id"] == habits["meat"]["aid"]
        assert top["uses"] == 3 and top["other_routes"][0]["to"] == "Expenses:groceries"

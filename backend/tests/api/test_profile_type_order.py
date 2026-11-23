"""Each person orders the four account types; Accounts, the pickers and the assistants' list follow that order."""

import pytest

from tests.books import post_account
from tests.mcputil import make_token, mcp_client, payload, running_app

START = ["assets.bank", "assets.cash", "liabilities.cards", "assets.wallet"]


def order(client):
    return client.get("/api/profile/").json()["account_type_order"]


def test_a_new_profile_starts_in_the_starting_order(client):
    assert order(client) == START


def test_a_saved_order_shapes_accounts_and_the_pickers(client):
    post_account(client, {"name": "HDFC", "type": "assets.bank"})
    post_account(client, {"name": "Paytm", "type": "assets.wallet"})
    post_account(client, {"name": "Amex", "type": "liabilities.cards"})
    mine = ["assets.wallet", "liabilities.cards", "assets.bank", "assets.cash"]
    assert client.patch("/api/profile/", json={"account_type_order": mine}).status_code == 200
    assert order(client) == mine
    assert [k["type"] for k in client.get("/api/views/accounts").json()["kinds"]] == mine
    titles = [g["title"] for g in client.get("/api/views/entry-form").json()["groups"]]
    assert titles[:3] == ["Prepaid Wallet", "Credit Card", "Bank Account"], "a type with no account has no heading"
    form = client.get("/api/views/account-form").json()
    assert [t["key"] for t in form["types"]] == mine


@pytest.mark.parametrize(
    "bad",
    [
        ["assets.bank", "assets.cash", "liabilities.cards"],
        ["assets.bank", "assets.bank", "liabilities.cards", "assets.wallet"],
        ["assets.bank", "assets.cash", "liabilities.cards", "assets.investments"],
    ],
)
def test_an_order_that_is_not_the_four_types_once_each_is_refused(client, bad):
    response = client.patch("/api/profile/", json={"account_type_order": bad})
    assert response.status_code == 422, response.text  # a missing or repeated one is named; an unknown one is no type
    assert order(client) == START


@pytest.mark.anyio
async def test_the_assistants_list_follows_the_order(session, client):
    from tests.conftest import TEST_USER_ID

    post_account(client, {"name": "HDFC", "type": "assets.bank"})
    post_account(client, {"name": "Paytm", "type": "assets.wallet"})
    client.patch(
        "/api/profile/",
        json={"account_type_order": ["assets.wallet", "assets.cash", "liabilities.cards", "assets.bank"]},
    )
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        listed = [
            a["path"] for a in payload(await c.call_tool("list_accounts", {}))["accounts"] if a.get("account_kind")
        ]
    assert listed == ["Assets:Paytm", "Assets:HDFC"]

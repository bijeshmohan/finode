"""Each account type's icon (services/account_types.TYPE_ICONS) reaches every view that shows a type or an account."""

import pytest

ICONS = {
    "assets.bank": "landmark",
    "assets.cash": "banknote",
    "liabilities.cards": "credit-card",
    "assets.wallet": "wallet",
}


@pytest.fixture
def books(client, root_accounts):
    made = {}
    for name, kind in (("HDFC", "assets.bank"), ("Purse", "assets.cash"), ("Amex", "liabilities.cards")):
        made[name] = client.post("/api/accounts/", json={"name": name, "type": kind, "balance": "10"}).json()
    pinned = client.patch(f"/api/accounts/{made['Purse']['id']}", json={"pinned": True})
    assert pinned.status_code in (200, 204), pinned.text
    return made


def test_accounts_page_types_and_cards_carry_icons(client, books):
    page = client.get("/api/views/accounts").json()
    assert {k["type"]: k["icon"] for k in page["kinds"]} == {
        k: v for k, v in ICONS.items() if k in {k["type"] for k in page["kinds"]}
    }
    cards = {c["name"]: c["icon"] for k in page["kinds"] for c in k["cards"]}
    assert cards == {"HDFC": "landmark", "Purse": "banknote", "Amex": "credit-card"}
    assert [(c["name"], c["icon"]) for c in page["pinned"]] == [("Purse", "banknote")]


def test_account_page_carries_its_types_icon(client, books):
    assert client.get(f"/api/views/accounts/{books['Amex']['id']}").json()["icon"] == "credit-card"


def test_opening_balances_page_has_no_icon(client, books, root_accounts):
    accounts = client.get("/api/accounts/").json()
    opening = next(a for a in accounts if a["name"] == "Opening Balances")
    assert client.get(f"/api/views/accounts/{opening['id']}").json()["icon"] is None


def test_account_form_types_carry_icons(client, books):
    types = client.get("/api/views/account-form").json()["types"]
    assert {t["key"]: t["icon"] for t in types} == ICONS


def test_new_account_sheet_types_carry_icons(client, books):
    types = client.get("/api/views/entry-form").json()["account_types"]
    assert {t["key"]: t["icon"] for t in types} == ICONS


def test_picker_accounts_carry_their_types_icon(client, books):
    groups = client.get("/api/views/entry-form").json()["groups"]
    options = {o["label"]: o["icon"] for g in groups for o in g["options"]}
    assert options["HDFC"] == "landmark" and options["Purse"] == "banknote" and options["Amex"] == "credit-card"
    assert options["Opening Balances"] is None

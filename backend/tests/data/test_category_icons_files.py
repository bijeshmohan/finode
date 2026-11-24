"""Category icons in the ledger file: the export writes each category's icon as a label on its `account` line
(`account Expenses:Groceries  ; icon: shopping-cart`), the import reads it back; a category without one gets the
generic tag, an unknown name is refused with its line, and a category that already exists keeps its own icon."""

from tests.books import leg
from tests.conftest import TEST_USER_ID
from tests.data.test_backup import OTHER, as_user


def _import(client, text):
    return client.post("/api/import", files={"file": ("a.ledger", text.encode())})


def _icons(client):
    return {c["name"]: c["icon"] for c in client.get("/api/categories/").json()}


def test_export_writes_icons_and_import_reads_them(client):
    hdfc = client.post("/api/accounts/", json={"name": "HDFC", "type": "assets.bank", "balance": "100"}).json()
    food = client.post("/api/categories/", json={"name": "Groceries", "kind": "spending", "icon": "shopping-cart"})
    body = {"postings": [leg(food.json(), "debit", "40"), leg(hdfc, "credit", "40")]}
    assert client.post("/api/transactions/", json=body).status_code == 201
    text = client.get("/api/export", params={"format": "ledger"}).text
    assert "account Expenses:Groceries  ; icon: shopping-cart" in text
    try:
        as_user(OTHER)
        done = _import(client, text)
        assert done.status_code == 200, done.text
        assert _icons(client)["Groceries"] == "shopping-cart"
    finally:
        as_user(TEST_USER_ID)


def test_import_without_icon_gets_tag(client):
    text = "account Expenses:Fuel\n\n2026-01-01 Pump\n    Expenses:Rent  10\n    Expenses:Fuel  5\n    Equity:Opening Balances\n"
    done = _import(client, text)
    assert done.status_code == 200, done.text
    icons = _icons(client)
    assert icons["Fuel"] == "tag" and icons["Rent"] == "tag"


def test_import_unknown_icon_is_refused(client):
    text = (
        "account Expenses:Fuel  ; icon: rocket\n\n2026-01-01 Pump\n    Expenses:Fuel  5\n    Equity:Opening Balances\n"
    )
    done = _import(client, text)
    assert done.status_code == 400
    assert "line 1" in done.text and "'rocket' is not one of finode's category icons" in done.text
    assert "Fuel" not in _icons(client)


def test_import_keeps_an_existing_categorys_icon(client):
    assert client.post("/api/categories/", json={"name": "Fuel", "kind": "spending", "icon": "fuel"}).status_code == 201
    text = "account Expenses:Fuel  ; icon: car\n\n2026-01-01 Pump\n    Expenses:Fuel  5\n    Equity:Opening Balances\n"
    done = _import(client, text)
    assert done.status_code == 200, done.text
    assert _icons(client)["Fuel"] == "fuel"


def test_kind_and_icon_labels_do_not_mix(client):
    text = (
        "account Assets:HDFC  ; kind: Bank Account\n"
        "account Expenses:Fuel  ; icon: fuel\n\n"
        "2026-01-01 Pump\n    Expenses:Fuel  5\n    Assets:HDFC\n"
    )
    done = _import(client, text)
    assert done.status_code == 200, done.text
    assert {a["name"]: a["type"] for a in client.get("/api/accounts/").json() if a["type"]} == {"HDFC": "assets.bank"}
    assert _icons(client)["Fuel"] == "fuel"

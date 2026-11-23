"""The ledger file and the four account types: the export writes each account straight under its root with its kind
as a label (`account Assets:HDFC  ; kind: Bank Account`), the import reads that label or the older path with the type in
the middle (`Assets:Bank Account:HDFC`), and refuses a new account that says neither: finode never picks a type. Older
journals' subcategories are flattened by the rules of services/flatten.py."""

from tests.books import leg


def _import(client, text, **params):
    return client.post("/api/import", files={"file": ("a.ledger", text.encode())}, params=params)


def _kinds(client):
    return {a["name"]: a["type"] for a in client.get("/api/accounts/").json() if a["type"]}


def test_the_export_writes_the_kind_as_a_label(client):
    made = client.post("/api/accounts/", json={"name": "HDFC", "type": "assets.bank", "balance": "100"})
    assert made.status_code == 201
    text = client.get("/api/export", params={"format": "ledger"}).text
    assert "account Assets:HDFC  ; kind: Bank Account" in text
    assert "Bank Account:" not in text, "no type in the middle of a path"
    assert "    Assets:HDFC" in text


def test_an_export_imports_again_for_someone_else(client):
    from tests.data.test_backup import OTHER, as_user
    from tests.conftest import TEST_USER_ID

    hdfc = client.post("/api/accounts/", json={"name": "HDFC", "type": "assets.bank", "balance": "100"}).json()
    amex = client.post("/api/accounts/", json={"name": "Amex", "type": "liabilities.cards"}).json()
    food = client.post("/api/categories/", json={"name": "Food", "kind": "spending"}).json()
    body = {"postings": [leg(food, "debit", "40"), leg(amex, "credit", "40")]}
    assert client.post("/api/transactions/", json=body).status_code == 201
    text = client.get("/api/export", params={"format": "ledger"}).text
    assert hdfc
    try:
        as_user(OTHER)
        done = _import(client, text)
        assert done.status_code == 200, done.text
        assert _kinds(client) == {"HDFC": "assets.bank", "Amex": "liabilities.cards"}
    finally:
        as_user(TEST_USER_ID)


def test_old_paths_still_import(client):
    text = (
        "2026-01-01 Shop\n"
        "    Expenses:Food:Groceries  40\n"
        "    Assets:Bank Account:HDFC\n"
        "2026-01-02 Fuel\n"
        "    Expenses:Car:Fuel  10\n"
        "    Expenses:Car  5\n"
        "    Liabilities:Credit Cards:Amex\n"
    )
    done = _import(client, text)
    assert done.status_code == 200, done.text
    assert _kinds(client) == {"HDFC": "assets.bank", "Amex": "liabilities.cards"}
    names = {c["name"] for c in client.get("/api/categories/").json()}
    assert {"Groceries", "Fuel", "Car"} <= names, "subcategories are categories; Car had a line of its own"
    assert "Food" not in names, "a group with nothing of its own goes"


def test_a_label_gives_a_new_account_its_kind(client):
    text = (
        "account Assets:Paytm  ; kind: Prepaid Wallet\n"
        "account Liabilities:Amex\n"
        "    ; kind: Credit Card\n"
        "\n"
        "2026-01-01 Top up\n"
        "    Assets:Paytm  50\n"
        "    Liabilities:Amex\n"
    )
    done = _import(client, text)
    assert done.status_code == 200, done.text
    assert _kinds(client) == {"Paytm": "assets.wallet", "Amex": "liabilities.cards"}


def test_a_new_untyped_account_refuses_the_import(client):
    text = "2026-01-01 x\n    Assets:HDFC  5\n    Equity:Opening Balances\n"
    refused = _import(client, text)
    assert refused.status_code == 400
    assert (
        "'Assets:HDFC' has no type: add `; kind: Bank Account` (or Cash, Credit Card, Prepaid Wallet) to its "
        "`account` line" in refused.text
    )
    assert _kinds(client) == {}, "nothing was written"


def test_a_kind_that_does_not_fit_the_root_is_refused(client):
    text = "account Assets:Amex  ; kind: Credit Card\n\n2026-01-01 x\n    Assets:Amex  5\n    Equity:Opening Balances\n"
    refused = _import(client, text)
    assert refused.status_code == 400 and "'Assets:Amex' cannot be a Credit Card" in refused.text


def test_a_type_label_is_read_too(client):
    text = "account Assets:Wallet  ; type: Cash\n\n2026-01-01 x\n    Assets:Wallet  5\n    Equity:Opening Balances\n"
    assert _import(client, text).status_code == 200
    assert _kinds(client) == {"Wallet": "assets.cash"}

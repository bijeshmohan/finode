import json

from fastapi.testclient import TestClient


def _quick(client: TestClient, **data):
    return client.post("/accounts/quick", data=data)


def _by_name(client: TestClient, name: str) -> dict:
    return next(a for a in client.get("/api/accounts/").json() if a["name"] == name)


# --- the pickers offer it ---------------------------------------------------


def test_transaction_pickers_offer_a_new_account_entry(client: TestClient, account: dict):
    for url in ("/transactions/new",):
        text = client.get(url).text
        assert '<option value="__new__">+ New account…</option>' in text, url
        assert "data-account-select" in text, url
    assert '<dialog id="quick-account"' in client.get("/transactions/new").text


def test_edit_page_offers_it_too(client: TestClient, account: dict, expense_account: dict):
    tx = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "1.00"},
                {"account": account["aid"], "side": "credit", "amount": "1.00"},
            ]
        },
    ).json()
    assert "__new__" in client.get(f"/transactions/{tx['tid']}/edit").text


def test_other_pages_do_not_offer_it(client: TestClient, account: dict):
    assert "__new__" not in client.get("/transactions").text
    assert "__new__" not in client.get("/accounts/new").text


# --- the sheet --------------------------------------------------------------


def test_sheet_suggests_the_matching_root(client: TestClient, root_accounts: dict[str, str]):
    text = client.get("/accounts/quick", params={"hint": "Expenses"}).text
    assert f'<option value="{root_accounts["Expenses"]}" data-root="Expenses" selected>' in text
    assert "Choose…" not in text

    asset = client.get("/accounts/quick", params={"hint": "Assets"}).text
    assert f'value="{root_accounts["Assets"]}" data-root="Assets" selected' in asset


def test_sheet_without_a_hint_asks_for_a_parent(client: TestClient, root_accounts: dict[str, str]):
    text = client.get("/accounts/quick").text
    assert '<option value="">Choose…</option>' in text
    assert " selected>" not in text
    client.get("/accounts/quick", params={"hint": "nonsense"})


def test_sheet_lists_sub_groups_but_not_the_system_account(
    client: TestClient, root_accounts: dict[str, str]
):
    client.post("/api/accounts/", json={"name": "Food", "parent_id": root_accounts["Expenses"]})
    client.post("/api/accounts/", json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "5.00"})
    text = client.get("/accounts/quick").text
    assert "Food</option>" in text
    assert "Opening Balances" not in text
    assert "data-balance-field hidden" in text
    assert 'name="balance"' in text and "disabled" in text


def test_options_list_reflects_new_accounts(client: TestClient, account: dict):
    text = client.get("/accounts/options").text
    assert '<option value="__new__">+ New account…</option>' in text
    assert f'<option value="{account["aid"]}" data-commodity="INR" >checking</option>' in text


# --- creating ---------------------------------------------------------------


def test_creates_an_expense_account_and_announces_it(
    client: TestClient, root_accounts: dict[str, str]
):
    response = _quick(client, name="  Pharmacy ", parent_id=root_accounts["Expenses"])
    assert response.status_code == 200
    created = _by_name(client, "Pharmacy")
    assert created["parent_id"] == root_accounts["Expenses"]
    assert json.loads(response.headers["HX-Trigger"]) == {
        "account-added": {"aid": created["aid"], "name": "Pharmacy"}
    }
    assert "set-cookie" not in response.headers


def test_records_an_opening_balance_for_assets_and_liabilities(
    client: TestClient, root_accounts: dict[str, str]
):
    _quick(client, name="Wallet", parent_id=root_accounts["Assets"], balance="1,250.50")
    _quick(client, name="Amex", parent_id=root_accounts["Liabilities"], balance="300")
    assert _by_name(client, "Wallet")["balance"] == "1250.50"
    assert _by_name(client, "Amex")["balance"] == "300.00"


def test_ignores_a_balance_for_income_and_expenses(
    client: TestClient, root_accounts: dict[str, str]
):
    for name, root in (("Gym", "Expenses"), ("Bonus", "Income")):
        assert _quick(client, name=name, parent_id=root_accounts[root], balance="99").status_code == 200
        assert _by_name(client, name)["balance"] == "0.00"
    assert client.get("/api/transactions/").json() == []


def test_non_ascii_names_survive_the_header(client: TestClient, root_accounts: dict[str, str]):
    response = _quick(client, name="Café ₹", parent_id=root_accounts["Expenses"])
    assert json.loads(response.headers["HX-Trigger"])["account-added"]["name"] == "Café ₹"


def test_can_create_under_a_sub_group(client: TestClient, root_accounts: dict[str, str]):
    food = client.post("/api/accounts/", json={"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    assert _quick(client, name="Dining", parent_id=food["aid"]).status_code == 200
    assert _by_name(client, "Dining")["parent_id"] == food["aid"]


# --- rejecting --------------------------------------------------------------


def _assert_error(response, message: str):
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#quick-error"
    assert message in response.text
    assert "HX-Trigger" not in response.headers


def test_rejects_a_missing_parent(client: TestClient):
    _assert_error(_quick(client, name="x"), "choose where the account belongs")
    _assert_error(
        _quick(client, name="x", parent_id="00000000-0000-4000-8000-0000000000ff"),
        "choose where the account belongs",
    )


def test_rejects_an_empty_name(client: TestClient, root_accounts: dict[str, str]):
    _assert_error(_quick(client, name="  ", parent_id=root_accounts["Expenses"]), "name must not be empty")


def test_rejects_a_duplicate_sibling_ignoring_case(
    client: TestClient, root_accounts: dict[str, str]
):
    _quick(client, name="Groceries", parent_id=root_accounts["Expenses"])
    _assert_error(
        _quick(client, name="groceries", parent_id=root_accounts["Expenses"]),
        "already has an account named",
    )
    # the same name elsewhere is fine
    assert _quick(client, name="Groceries", parent_id=root_accounts["Income"]).status_code == 200


def test_rejects_a_parent_that_already_has_transactions(
    client: TestClient, account: dict, expense_account: dict
):
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "1.00"},
                {"account": account["aid"], "side": "credit", "amount": "1.00"},
            ]
        },
    )
    _assert_error(_quick(client, name="sub", parent_id=account["aid"]), "has postings")


def test_expense_category_with_transactions_can_gain_a_sub_account(
    client: TestClient, account: dict, expense_account: dict
):
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "1.00"},
                {"account": account["aid"], "side": "credit", "amount": "1.00"},
            ]
        },
    )
    assert _quick(client, name="sub", parent_id=expense_account["aid"]).status_code == 200


def test_rejects_an_invalid_amount(client: TestClient, root_accounts: dict[str, str]):
    _assert_error(
        _quick(client, name="Wallet", parent_id=root_accounts["Assets"], balance="abc"),
        "not a valid amount",
    )
    assert all(a["name"] != "Wallet" for a in client.get("/api/accounts/").json())


def test_error_messages_escape_the_name(client: TestClient, root_accounts: dict[str, str]):
    _quick(client, name="<i>x</i>", parent_id=root_accounts["Expenses"])
    response = _quick(client, name="<I>X</I>", parent_id=root_accounts["Expenses"])
    assert response.status_code == 400
    assert "<I>" not in response.text and "&lt;I&gt;X&lt;/I&gt;" in response.text

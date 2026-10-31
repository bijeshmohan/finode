import json

from fastapi.testclient import TestClient

from .books import leg, post_account


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
                leg(expense_account, "debit", "1.00"),
                leg(account, "credit", "1.00"),
            ]
        },
    ).json()
    assert "__new__" in client.get(f"/transactions/{tx['tid']}/edit").text


def test_other_pages_do_not_offer_it(client: TestClient, account: dict):
    assert "__new__" not in client.get("/transactions").text
    assert "__new__" not in client.get("/accounts/new").text


# --- the sheet --------------------------------------------------------------


def test_sheet_suggests_the_matching_root(client: TestClient, root_accounts: dict[str, str]):
    asset = client.get("/accounts/quick", params={"hint": "Assets"}).text
    assert f'value="{root_accounts["Assets"]}" data-root="Assets" selected' in asset


def test_the_sheet_for_expenses_and_income_makes_a_category(client: TestClient):
    spending = client.get("/accounts/quick", params={"hint": "Expenses"}).text
    assert 'hx-post="/categories/quick"' in spending and 'name="kind" value="spending"' in spending
    earning = client.get("/accounts/quick", params={"hint": "Income"}).text
    assert 'name="kind" value="earning"' in earning


def test_sheet_without_a_hint_asks_for_a_parent(client: TestClient, root_accounts: dict[str, str]):
    text = client.get("/accounts/quick").text
    assert '<option value="">Choose…</option>' in text
    assert " selected>" not in text
    client.get("/accounts/quick", params={"hint": "nonsense"})


def test_sheet_lists_sub_groups_but_not_the_system_account_or_categories(
    client: TestClient, root_accounts: dict[str, str]
):
    post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]})
    post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "5.00"})
    text = client.get("/accounts/quick").text
    assert "bank</option>" in text and "Food</option>" not in text
    assert "Opening Balances" not in text
    assert "data-balance-field hidden" in text
    assert 'name="balance"' in text and "disabled" in text


def test_options_list_reflects_new_accounts_and_categories(client: TestClient, account: dict, expense_account: dict):
    text = client.get("/accounts/options").text
    assert '<option value="__new__">+ New account…</option>' in text
    assert f'<option value="{account["aid"]}" data-budget="1" data-balance="0.00" >checking</option>' in text
    assert f'value="{expense_account["aid"]}"' in text


# --- creating ---------------------------------------------------------------


def _quick_category(client: TestClient, **data):
    return client.post("/categories/quick", data=data)


def test_creates_a_category_and_announces_it(client: TestClient):
    response = _quick_category(client, name="  Pharmacy ", kind="spending")
    assert response.status_code == 200
    created = next(c for c in client.get("/api/categories/").json() if c["name"] == "Pharmacy")
    assert json.loads(response.headers["HX-Trigger"]) == {"account-added": {"aid": created["bcid"], "name": "Pharmacy"}}
    assert "set-cookie" not in response.headers


def test_records_an_opening_balance_for_assets_and_liabilities(client: TestClient, root_accounts: dict[str, str]):
    _quick(client, name="Wallet", parent_id=root_accounts["Assets"], balance="1,250.50")
    _quick(client, name="Amex", parent_id=root_accounts["Liabilities"], balance="300")
    assert _by_name(client, "Wallet")["balance"] == "1250.50"
    assert _by_name(client, "Amex")["balance"] == "300.00"


def test_non_ascii_names_survive_the_header(client: TestClient):
    response = _quick_category(client, name="Café ₹", kind="spending")
    assert json.loads(response.headers["HX-Trigger"])["account-added"]["name"] == "Café ₹"


def test_can_create_a_category_inside_another(client: TestClient):
    group = client.post("/api/categories/", json={"name": "Eating", "kind": "spending"}).json()
    assert _quick_category(client, name="Dining", kind="spending", parent_id=group["bcid"]).status_code == 200
    dining = next(c for c in client.get("/api/categories/").json() if c["name"] == "Dining")
    assert dining["parent_id"] == group["bcid"]


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


def test_expenses_and_income_hold_categories_not_accounts(client: TestClient, root_accounts: dict[str, str]):
    _assert_error(_quick(client, name="x", parent_id=root_accounts["Expenses"]), "hold categories")


def test_rejects_an_empty_name(client: TestClient):
    _assert_error(_quick_category(client, name="  ", kind="spending"), "name must not be empty")


def test_rejects_a_duplicate_sibling_ignoring_case(client: TestClient):
    _quick_category(client, name="Groceries", kind="spending")
    _assert_error(_quick_category(client, name="groceries", kind="spending"), "a category called")
    # the same name in the other kind is fine
    assert _quick_category(client, name="Groceries", kind="earning").status_code == 200


def test_rejects_a_parent_that_already_has_transactions(client: TestClient, account: dict, expense_account: dict):
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "1.00"),
                leg(account, "credit", "1.00"),
            ]
        },
    )
    _assert_error(_quick(client, name="sub", parent_id=account["aid"]), "has postings")


def test_a_category_with_transactions_can_gain_a_subcategory(client: TestClient, account: dict, expense_account: dict):
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "1.00"),
                leg(account, "credit", "1.00"),
            ]
        },
    )
    assert _quick_category(client, name="sub", kind="spending", parent_id=expense_account["aid"]).status_code == 200


def test_rejects_an_invalid_amount(client: TestClient, root_accounts: dict[str, str]):
    _assert_error(
        _quick(client, name="Wallet", parent_id=root_accounts["Assets"], balance="abc"),
        "not a valid amount",
    )
    assert all(a["name"] != "Wallet" for a in client.get("/api/accounts/").json())


def test_error_messages_escape_the_name(client: TestClient):
    _quick_category(client, name="<i>x</i>", kind="spending")
    response = _quick_category(client, name="<I>X</I>", kind="spending")
    assert response.status_code == 400
    assert "<i>" not in response.text.lower() and "&lt;i&gt;x&lt;/i&gt;" in response.text.lower()

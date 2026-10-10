from datetime import date

from fastapi.testclient import TestClient


def _balance(client: TestClient, account: dict) -> str:
    return client.get(f"/api/accounts/{account['aid']}").json()["balance"]




def test_form_only_offers_postable_accounts(
    client: TestClient, root_accounts: dict[str, str], account: dict
):
    parent = client.post(
        "/api/accounts/", json={"name": "food", "parent_id": root_accounts["Expenses"]}
    ).json()
    client.post("/api/accounts/", json={"name": "dining", "parent_id": parent["aid"]})

    text = client.get("/transactions/new").text
    assert f'<option value="{parent["aid"]}"' in text  # expense groups are postable
    asset_group = client.post(
        "/api/accounts/", json={"name": "bank", "parent_id": root_accounts["Assets"]}
    ).json()
    client.post("/api/accounts/", json={"name": "hdfc", "parent_id": asset_group["aid"]})
    text = client.get("/transactions/new").text
    assert f'<option value="{asset_group["aid"]}"' not in text  # asset groups are not
    for aid in root_accounts.values():
        assert f'<option value="{aid}"' not in text  # roots
    assert "Food › dining" in text.replace("food", "Food")






def test_create_simple_transaction(client: TestClient, account: dict, expense_account: dict):
    response = client.post(
        "/transactions",
        data={
            "date": "2026-05-04",
            "amount": "42.50",
            "from_account": account["aid"],
            "to_account": expense_account["aid"],
            "payee": "Market",
            "comment": "weekly",
        },
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/transactions"

    [tx] = client.get("/api/transactions/").json()
    assert tx["date"] == "2026-05-04"
    assert tx["payee"] == "Market"
    sides = {p["account"]: p["side"] for p in tx["postings"]}
    assert sides[expense_account["aid"]] == "debit"
    assert sides[account["aid"]] == "credit"
    assert _balance(client, account) == "-42.50"
    assert _balance(client, expense_account) == "42.50"


def test_create_simple_transaction_defaults_to_today(
    client: TestClient, account: dict, expense_account: dict
):
    client.post(
        "/transactions",
        data={"amount": "1", "from_account": account["aid"], "to_account": expense_account["aid"]},
    )
    [tx] = client.get("/api/transactions/").json()
    assert tx["date"] == date.today().isoformat()
    assert tx["payee"] is None


def test_create_simple_transaction_rejects_same_account(client: TestClient, account: dict):
    response = client.post(
        "/transactions",
        data={"amount": "5", "from_account": account["aid"], "to_account": account["aid"]},
    )
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"
    assert "must differ" in response.text


def test_create_simple_transaction_rejects_bad_amounts(
    client: TestClient, account: dict, expense_account: dict
):
    for amount in ("0", "-3", "abc", "1.234", ""):
        response = client.post(
            "/transactions",
            data={"amount": amount, "from_account": account["aid"], "to_account": expense_account["aid"]},
        )
        assert response.status_code == 400, amount
    assert client.get("/api/transactions/").json() == []


def test_create_simple_transaction_rejects_root_account(
    client: TestClient, root_accounts: dict[str, str], account: dict
):
    response = client.post(
        "/transactions",
        data={"amount": "5", "from_account": account["aid"], "to_account": root_accounts["Expenses"]},
    )
    assert response.status_code == 400
    assert "root account" in response.text


def test_create_split_transaction(
    client: TestClient, account: dict, expense_account: dict, other_account: dict
):
    response = client.post(
        "/transactions/split",
        data={
            "date": "2026-05-04",
            "payee": "Shop",
            "account": [expense_account["aid"], other_account["aid"], account["aid"], ""],
            "side": ["debit", "debit", "credit", "debit"],
            "amount": ["30.00", "20.00", "50.00", ""],
        },
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/transactions"
    [tx] = client.get("/api/transactions/").json()
    assert len(tx["postings"]) == 3
    assert _balance(client, account) == "-50.00"


def test_create_split_transaction_must_balance(
    client: TestClient, account: dict, expense_account: dict
):
    response = client.post(
        "/transactions/split",
        data={
            "account": [expense_account["aid"], account["aid"]],
            "side": ["debit", "credit"],
            "amount": ["30.00", "25.00"],
        },
    )
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"
    assert "must balance" in response.text
    assert client.get("/api/transactions/").json() == []


def test_create_split_transaction_requires_two_postings_and_accounts(
    client: TestClient, account: dict, expense_account: dict
):
    one = client.post(
        "/transactions/split",
        data={"account": [account["aid"]], "side": ["debit"], "amount": ["5.00"]},
    )
    assert one.status_code == 400
    assert "at least two postings" in one.text

    missing_account = client.post(
        "/transactions/split",
        data={
            "account": [account["aid"], ""],
            "side": ["debit", "credit"],
            "amount": ["5.00", "5.00"],
        },
    )
    assert missing_account.status_code == 400
    assert "needs an account" in missing_account.text


def test_edit_page_prefills_existing_postings(
    client: TestClient, account: dict, expense_account: dict
):
    tx = client.post(
        "/api/transactions/",
        json={
            "date": "2026-05-04",
            "payee": "Corner shop",
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "9.99"},
                {"account": account["aid"], "side": "credit", "amount": "9.99"},
            ],
        },
    ).json()

    simple = client.get(f"/transactions/{tx['tid']}/edit")
    assert simple.status_code == 200
    assert 'value="Corner shop"' in simple.text
    assert 'value="2026-05-04"' in simple.text
    assert simple.text.count('value="9.99"') == 3, "the total and one row on each side"
    assert f'hx-post="/transactions/{tx["tid"]}/edit"' in simple.text
    assert f'<option value="{expense_account["aid"]}" data-commodity="INR" selected>' in simple.text
    assert simple.text.count("data-touched") == 2, "existing rows are the user's own, never overwritten by a suggestion"


def test_edit_missing_transaction_is_404(client: TestClient):
    response = client.get("/transactions/00000000-0000-4000-8000-0000000000ff/edit")
    assert response.status_code == 404


def test_update_transaction_from_form(client: TestClient, account: dict, expense_account: dict):
    tx = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "10.00"},
                {"account": account["aid"], "side": "credit", "amount": "10.00"},
            ],
        },
    ).json()

    response = client.post(
        f"/transactions/{tx['tid']}/edit",
        data={
            "date": "2026-06-01",
            "payee": "fixed",
            "account": [expense_account["aid"], account["aid"]],
            "side": ["debit", "credit"],
            "amount": ["12.00", "12.00"],
        },
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/transactions"
    updated = client.get(f"/api/transactions/{tx['tid']}").json()
    assert updated["payee"] == "fixed"
    assert updated["date"] == "2026-06-01"
    assert _balance(client, expense_account) == "12.00"


def test_update_transaction_validation_error(
    client: TestClient, account: dict, expense_account: dict
):
    tx = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "10.00"},
                {"account": account["aid"], "side": "credit", "amount": "10.00"},
            ],
        },
    ).json()
    response = client.post(
        f"/transactions/{tx['tid']}/edit",
        data={
            "date": "2026-06-01",
            "account": [expense_account["aid"], account["aid"]],
            "side": ["debit", "credit"],
            "amount": ["12.00", "11.00"],
        },
    )
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"
    assert _balance(client, expense_account) == "10.00"


def test_update_missing_transaction_is_404(client: TestClient, account: dict, expense_account: dict):
    response = client.post(
        "/transactions/00000000-0000-4000-8000-0000000000ff/edit",
        data={
            "date": "2026-06-01",
            "account": [expense_account["aid"], account["aid"]],
            "side": ["debit", "credit"],
            "amount": ["1.00", "1.00"],
        },
    )
    assert response.status_code == 404


def test_transactions_page_links_to_form(client: TestClient, account: dict, expense_account: dict):
    tx = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "1.00"},
                {"account": account["aid"], "side": "credit", "amount": "1.00"},
            ],
        },
    ).json()
    text = client.get("/transactions").text
    assert 'href="/transactions/new"' in text
    assert f'href="/transactions/{tx["tid"]}/edit"' in text  # the row itself


def test_edit_page_offers_delete(client: TestClient, account: dict, expense_account: dict):
    tx = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "1.00"},
                {"account": account["aid"], "side": "credit", "amount": "1.00"},
            ],
        },
    ).json()
    page = client.get(f"/transactions/{tx['tid']}/edit").text
    assert f'hx-post="/transactions/{tx["tid"]}/delete"' in page
    assert "Delete transaction" in page


def _tx(client: TestClient, debit: dict, credit: dict, amount: str = "10.00") -> dict:
    return client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": debit["aid"], "side": "debit", "amount": amount},
                {"account": credit["aid"], "side": "credit", "amount": amount},
            ],
        },
    ).json()




def test_create_returns_to_the_page_it_came_from(
    client: TestClient, account: dict, expense_account: dict
):
    back = f"/accounts/{account['aid']}"
    response = client.post(
        "/transactions",
        data={"amount": "3", "from_account": account["aid"], "to_account": expense_account["aid"], "back": back},
    )
    assert response.headers["HX-Redirect"] == back


def test_return_path_must_stay_inside_the_app(
    client: TestClient, account: dict, expense_account: dict
):
    for back in ("https://evil.example", "//evil.example/", "/api/accounts/", "/static/x", "/mcp", "/app\\x"):
        response = client.post(
            "/transactions",
            data={"amount": "1", "from_account": account["aid"], "to_account": expense_account["aid"], "back": back},
        )
        assert response.headers["HX-Redirect"] == "/transactions", back


def test_save_and_add_another_reopens_the_form(
    client: TestClient, account: dict, expense_account: dict
):
    simple = client.post(
        "/transactions",
        data={"amount": "1", "from_account": account["aid"], "to_account": expense_account["aid"], "another": "1"},
    )
    assert simple.headers["HX-Redirect"] == "/transactions/new"

    split = client.post(
        "/transactions/split",
        data={
            "account": [expense_account["aid"], account["aid"]],
            "side": ["debit", "credit"],
            "amount": ["2.00", "2.00"],
            "another": "1",
            "back": "/accounts",
        },
    )
    assert split.headers["HX-Redirect"] == "/transactions/new?back=%2Faccounts"


def test_update_simple_transaction(client: TestClient, account: dict, other_account: dict, expense_account: dict):
    tx = _tx(client, expense_account, account)
    response = client.post(
        f"/transactions/{tx['tid']}/edit/simple",
        data={
            "date": "2026-07-01",
            "amount": "15.50",
            "from_account": other_account["aid"],
            "to_account": expense_account["aid"],
            "payee": "moved",
        },
    )
    assert response.status_code == 200
    updated = client.get(f"/api/transactions/{tx['tid']}").json()
    assert updated["payee"] == "moved"
    assert {(p["account"], p["side"], p["amount"]) for p in updated["postings"]} == {
        (expense_account["aid"], "debit", "15.50"),
        (other_account["aid"], "credit", "15.50"),
    }
    assert _balance(client, account) == "0.00"


def test_update_simple_transaction_validates(client: TestClient, account: dict, expense_account: dict):
    tx = _tx(client, expense_account, account)
    response = client.post(
        f"/transactions/{tx['tid']}/edit/simple",
        data={"date": "2026-07-01", "amount": "0", "from_account": account["aid"], "to_account": expense_account["aid"]},
    )
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"


def test_multi_posting_transactions_edit_in_split_mode_only(
    client: TestClient, account: dict, other_account: dict, expense_account: dict
):
    tx = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "30.00"},
                {"account": account["aid"], "side": "credit", "amount": "20.00"},
                {"account": other_account["aid"], "side": "credit", "amount": "10.00"},
            ],
        },
    ).json()
    page = client.get(f"/transactions/{tx['tid']}/edit").text
    assert f'hx-post="/transactions/{tx["tid"]}/edit"' in page
    assert 'class="tabs"' not in page


def test_delete_returns_to_the_page_it_came_from(client: TestClient, account: dict, expense_account: dict):
    tx = _tx(client, expense_account, account)
    back = f"/accounts/{account['aid']}"
    response = client.post(f"/transactions/{tx['tid']}/delete", params={"back": back})
    assert response.headers["HX-Redirect"] == back









def test_new_page_has_a_total_and_a_row_on_each_side(client: TestClient, account: dict, expense_account: dict):
    page = client.get("/transactions/new").text
    assert 'class="tabs' not in page and "Split across" not in page
    assert page.count("data-txn-form") == 1 and 'name="total"' in page and date.today().isoformat() in page
    assert page.index('data-rows="credit"') < page.index('data-rows="debit"')
    credit = page[page.index('data-rows="credit"'):page.index('data-rows="debit"')]
    assert credit.count("class=\"txn-row\"") == 1 and 'name="side" value="credit"' in credit
    assert 'name="side" value="debit"' in page[page.index('data-rows="debit"'):]
    assert 'hx-post="/transactions/split"' in page
    assert "<template" in page and "checking" in page
    assert "data-touched" not in page, "a new form has nothing of the user's yet"


def test_new_form_prefills_from_for_asset_and_to_for_expense(client: TestClient, account: dict, expense_account: dict):
    selected = f'<option value="{account["aid"]}" data-commodity="INR" selected>'
    from_asset = client.get("/transactions/new", params={"account": account["aid"]}).text
    assert from_asset.count(selected) == 1
    assert from_asset.index('data-rows="credit"') < from_asset.index(selected) < from_asset.index('data-rows="debit"')

    to_expense = client.get("/transactions/new", params={"account": expense_account["aid"]}).text
    expected = f'<option value="{expense_account["aid"]}" data-commodity="INR" selected>'
    assert to_expense.index('data-rows="debit"') < to_expense.index(expected)


def test_old_mode_links_still_open_the_form(client: TestClient, account: dict):
    assert client.get("/transactions/new?mode=split").status_code == 200


def test_a_transaction_with_several_rows_shows_them_all(client: TestClient, account: dict, expense_account: dict):
    other = client.post("/api/accounts/", json={"name": "Tips", "parent_id": expense_account["parent_id"]}).json()
    tx = client.post("/api/transactions/", json={"postings": [
        {"account": expense_account["aid"], "side": "debit", "amount": "6"},
        {"account": other["aid"], "side": "debit", "amount": "4"},
        {"account": account["aid"], "side": "credit", "amount": "10"},
    ]}).json()
    page = client.get(f"/transactions/{tx['tid']}/edit").text
    debit = page[page.index('data-rows="debit"'):]
    assert debit.count("data-touched") >= 2 and 'value="10.00"' in page and "Split across" not in page


# ---- the Expense / Income / Transfer buttons ---------------------------------------------------------------------


def _kind(page: str) -> str:
    start = page.index('name="kind" value="') + len('name="kind" value="')
    return page[start:page.index('"', start)]


def _pressed(page: str) -> list[str]:
    return [label for label in ("Expense", "Income", "Transfer", "Other") if f'aria-pressed="true">{label}<' in page]


def test_a_new_entry_starts_as_an_expense_with_four_buttons(client: TestClient, account: dict, expense_account: dict):
    page = client.get("/transactions/new").text
    assert _kind(page) == "expense" and _pressed(page) == ["Expense"]
    for label in ("Expense", "Income", "Transfer", "Other"):
        assert f">{label}</button>" in page
    assert 'data-side-hint' in page


def test_opening_a_form_from_an_account_picks_the_kind(client: TestClient, root_accounts, account: dict, expense_account: dict):
    salary = client.post("/api/accounts/", json={"name": "Salary", "parent_id": root_accounts["Income"]}).json()
    capital = client.post("/api/accounts/", json={"name": "Capital", "parent_id": root_accounts["Equity"]}).json()
    assert _kind(client.get("/transactions/new", params={"account": salary["aid"]}).text) == "income"
    assert _kind(client.get("/transactions/new", params={"account": capital["aid"]}).text) == "other"
    assert _kind(client.get("/transactions/new", params={"account": expense_account["aid"]}).text) == "expense"
    assert _kind(client.get("/transactions/new", params={"account": account["aid"]}).text) == "expense"


def test_editing_shows_what_the_entry_is(client: TestClient, root_accounts, account: dict, other_account: dict, expense_account: dict):
    salary = client.post("/api/accounts/", json={"name": "Salary", "parent_id": root_accounts["Income"]}).json()
    card = client.post("/api/accounts/", json={"name": "Visa", "parent_id": root_accounts["Liabilities"]}).json()
    capital = client.post("/api/accounts/", json={"name": "Capital", "parent_id": root_accounts["Equity"]}).json()

    def entry(debit, credit):
        return client.post("/api/transactions/", json={"postings": [
            {"account": debit["aid"], "side": "debit", "amount": "5"},
            {"account": credit["aid"], "side": "credit", "amount": "5"},
        ]}).json()["tid"]

    expected = {
        entry(expense_account, account): "expense",
        entry(expense_account, card): "expense",
        entry(account, salary): "income",
        entry(card, account): "transfer",
        entry(other_account, account): "transfer",
        entry(account, capital): "other",
        entry(account, expense_account): "other",  # a refund: money back from an expense
    }
    for tid, kind in expected.items():
        assert _kind(client.get(f"/transactions/{tid}/edit").text) == kind, (tid, kind)


def test_a_split_across_expenses_is_still_an_expense(client: TestClient, account: dict, expense_account: dict, root_accounts):
    other = client.post("/api/accounts/", json={"name": "Tips", "parent_id": root_accounts["Expenses"]}).json()
    tid = client.post("/api/transactions/", json={"postings": [
        {"account": expense_account["aid"], "side": "debit", "amount": "6"},
        {"account": other["aid"], "side": "debit", "amount": "4"},
        {"account": account["aid"], "side": "credit", "amount": "10"},
    ]}).json()["tid"]
    assert _kind(client.get(f"/transactions/{tid}/edit").text) == "expense"

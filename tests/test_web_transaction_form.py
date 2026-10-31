from datetime import date

from fastapi.testclient import TestClient

from .books import leg, post_account
from .htmlutil import option_offset, option_selected


def _balance(client: TestClient, account: dict) -> str:
    """An account's balance, or what a category has come to."""
    found = client.get(f"/api/accounts/{account['id']}")
    if found.status_code == 200:
        return found.json()["balance"]
    entries = client.get(f"/api/categories/{account['id']}/register").json()
    return entries[-1]["balance"] if entries else "0.00"


def test_form_only_offers_postable_accounts(client: TestClient, root_accounts: dict[str, str], account: dict):
    parent = post_account(client, {"name": "food", "parent_id": root_accounts["Expenses"]}).json()
    post_account(client, {"name": "dining", "parent_id": parent["id"]})

    text = client.get("/transactions/new").text
    assert f'<option value="{parent["id"]}"' in text  # expense groups are postable
    asset_group = post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"]}).json()
    post_account(client, {"name": "hdfc", "parent_id": asset_group["id"]})
    text = client.get("/transactions/new").text
    assert f'<option value="{asset_group["id"]}"' not in text  # asset groups are not
    for account_id in root_accounts.values():
        assert f'<option value="{account_id}"' not in text  # roots
    assert "Food › dining" in text.replace("food", "Food")


def test_create_simple_transaction(client: TestClient, account: dict, expense_account: dict):
    response = client.post(
        "/transactions/split",
        data={
            "date": "2026-05-04",
            "account": [expense_account["id"], account["id"]],
            "side": ["debit", "credit"],
            "amount": ["42.50", "42.50"],
            "payee": "Market",
            "comment": "weekly",
        },
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/transactions"

    [tx] = client.get("/api/transactions/").json()
    assert tx["date"] == "2026-05-04"
    assert tx["payee"] == "Market"
    sides = {p["category_id"] or p["account_id"]: p["side"] for p in tx["postings"]}
    assert sides[expense_account["id"]] == "debit"
    assert sides[account["id"]] == "credit"
    assert _balance(client, account) == "-42.50"
    assert _balance(client, expense_account) == "42.50"


def test_create_simple_transaction_defaults_to_today(client: TestClient, account: dict, expense_account: dict):
    client.post(
        "/transactions/split",
        data={"account": [expense_account["id"], account["id"]], "side": ["debit", "credit"], "amount": ["1", "1"]},
    )
    [tx] = client.get("/api/transactions/").json()
    assert tx["date"] == date.today().isoformat()
    assert tx["payee"] is None


def test_create_simple_transaction_rejects_bad_amounts(client: TestClient, account: dict, expense_account: dict):
    for amount in ("0", "-3", "abc", "1.234", ""):
        response = client.post(
            "/transactions/split",
            data={
                "account": [expense_account["id"], account["id"]],
                "side": ["debit", "credit"],
                "amount": [amount, amount],
            },
        )
        assert response.status_code == 400, amount
    assert client.get("/api/transactions/").json() == []


def test_create_simple_transaction_rejects_root_account(
    client: TestClient, root_accounts: dict[str, str], account: dict
):
    response = client.post(
        "/transactions/split",
        data={
            "account": [account["id"], root_accounts["Assets"]],
            "side": ["debit", "credit"],
            "amount": ["5", "5"],
        },
    )
    assert response.status_code == 400
    assert "root account" in response.text


def test_create_split_transaction(client: TestClient, account: dict, expense_account: dict, other_account: dict):
    response = client.post(
        "/transactions/split",
        data={
            "date": "2026-05-04",
            "payee": "Shop",
            "account": [expense_account["id"], other_account["id"], account["id"], ""],
            "side": ["debit", "debit", "credit", "debit"],
            "amount": ["30.00", "20.00", "50.00", ""],
        },
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/transactions"
    [tx] = client.get("/api/transactions/").json()
    assert len(tx["postings"]) == 3
    assert _balance(client, account) == "-50.00"


def test_create_split_transaction_must_balance(client: TestClient, account: dict, expense_account: dict):
    response = client.post(
        "/transactions/split",
        data={
            "account": [expense_account["id"], account["id"]],
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
        data={"account": [account["id"]], "side": ["debit"], "amount": ["5.00"]},
    )
    assert one.status_code == 400
    assert "at least two postings" in one.text

    missing_account = client.post(
        "/transactions/split",
        data={
            "account": [account["id"], ""],
            "side": ["debit", "credit"],
            "amount": ["5.00", "5.00"],
        },
    )
    assert missing_account.status_code == 400
    assert "needs an account" in missing_account.text


def test_edit_page_prefills_existing_postings(client: TestClient, account: dict, expense_account: dict):
    tx = client.post(
        "/api/transactions/",
        json={
            "date": "2026-05-04",
            "payee": "Corner shop",
            "postings": [
                leg(expense_account, "debit", "9.99"),
                leg(account, "credit", "9.99"),
            ],
        },
    ).json()

    simple = client.get(f"/transactions/{tx['id']}/edit")
    assert simple.status_code == 200
    assert 'value="Corner shop"' in simple.text
    assert 'value="2026-05-04"' in simple.text
    assert simple.text.count('value="9.99"') == 3, "the total and one row on each side"
    assert f'hx-post="/transactions/{tx["id"]}/edit"' in simple.text
    assert option_selected(simple.text, expense_account["id"])
    assert simple.text.count("data-touched") == 2, "existing rows are the user's own, never overwritten by a suggestion"


def test_edit_missing_transaction_is_404(client: TestClient):
    response = client.get("/transactions/00000000-0000-4000-8000-0000000000ff/edit")
    assert response.status_code == 404


def test_update_transaction_from_form(client: TestClient, account: dict, expense_account: dict):
    tx = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "10.00"),
                leg(account, "credit", "10.00"),
            ],
        },
    ).json()

    response = client.post(
        f"/transactions/{tx['id']}/edit",
        data={
            "date": "2026-06-01",
            "payee": "fixed",
            "account": [expense_account["id"], account["id"]],
            "side": ["debit", "credit"],
            "amount": ["12.00", "12.00"],
        },
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/transactions"
    updated = client.get(f"/api/transactions/{tx['id']}").json()
    assert updated["payee"] == "fixed"
    assert updated["date"] == "2026-06-01"
    assert _balance(client, expense_account) == "12.00"


def test_update_transaction_validation_error(client: TestClient, account: dict, expense_account: dict):
    tx = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "10.00"),
                leg(account, "credit", "10.00"),
            ],
        },
    ).json()
    response = client.post(
        f"/transactions/{tx['id']}/edit",
        data={
            "date": "2026-06-01",
            "account": [expense_account["id"], account["id"]],
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
            "account": [expense_account["id"], account["id"]],
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
                leg(expense_account, "debit", "1.00"),
                leg(account, "credit", "1.00"),
            ],
        },
    ).json()
    text = client.get("/transactions").text
    assert 'href="/transactions/new"' in text
    assert f'href="/transactions/{tx["id"]}/edit"' in text  # the row itself


def test_edit_page_offers_delete(client: TestClient, account: dict, expense_account: dict):
    tx = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "1.00"),
                leg(account, "credit", "1.00"),
            ],
        },
    ).json()
    page = client.get(f"/transactions/{tx['id']}/edit").text
    assert f'hx-post="/transactions/{tx["id"]}/delete"' in page
    assert "Delete transaction" in page


def _tx(client: TestClient, debit: dict, credit: dict, amount: str = "10.00") -> dict:
    return client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(debit, "debit", amount),
                leg(credit, "credit", amount),
            ],
        },
    ).json()


def test_create_returns_to_the_page_it_came_from(client: TestClient, account: dict, expense_account: dict):
    back = f"/accounts/{account['id']}"
    response = client.post(
        "/transactions/split",
        data={
            "account": [expense_account["id"], account["id"]],
            "side": ["debit", "credit"],
            "amount": ["3", "3"],
            "back": back,
        },
    )
    assert response.headers["HX-Redirect"] == back


def test_return_path_must_stay_inside_the_app(client: TestClient, account: dict, expense_account: dict):
    for back in ("https://evil.example", "//evil.example/", "/api/accounts/", "/static/x", "/mcp", "/app\\x"):
        response = client.post(
            "/transactions/split",
            data={
                "account": [expense_account["id"], account["id"]],
                "side": ["debit", "credit"],
                "amount": ["1", "1"],
                "back": back,
            },
        )
        assert response.headers["HX-Redirect"] == "/transactions", back


def test_save_and_add_another_reopens_the_form(client: TestClient, account: dict, expense_account: dict):
    simple = client.post(
        "/transactions/split",
        data={
            "account": [expense_account["id"], account["id"]],
            "side": ["debit", "credit"],
            "amount": ["1", "1"],
            "another": "1",
        },
    )
    assert simple.headers["HX-Redirect"] == "/transactions/new"

    split = client.post(
        "/transactions/split",
        data={
            "account": [expense_account["id"], account["id"]],
            "side": ["debit", "credit"],
            "amount": ["2.00", "2.00"],
            "another": "1",
            "back": "/accounts",
        },
    )
    assert split.headers["HX-Redirect"] == "/transactions/new?back=%2Faccounts"


def test_update_transaction_to_other_accounts(
    client: TestClient, account: dict, other_account: dict, expense_account: dict
):
    tx = _tx(client, expense_account, account)
    response = client.post(
        f"/transactions/{tx['id']}/edit",
        data={
            "date": "2026-07-01",
            "account": [expense_account["id"], other_account["id"]],
            "side": ["debit", "credit"],
            "amount": ["15.50", "15.50"],
            "payee": "moved",
        },
    )
    assert response.status_code == 200
    updated = client.get(f"/api/transactions/{tx['id']}").json()
    assert updated["payee"] == "moved"
    assert {(p["category_id"] or p["account_id"], p["side"], p["amount"]) for p in updated["postings"]} == {
        (expense_account["id"], "debit", "15.50"),
        (other_account["id"], "credit", "15.50"),
    }
    assert _balance(client, account) == "0.00"


def test_multi_posting_transactions_edit_in_split_mode_only(
    client: TestClient, account: dict, other_account: dict, expense_account: dict
):
    tx = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "30.00"),
                leg(account, "credit", "20.00"),
                leg(other_account, "credit", "10.00"),
            ],
        },
    ).json()
    page = client.get(f"/transactions/{tx['id']}/edit").text
    assert f'hx-post="/transactions/{tx["id"]}/edit"' in page
    assert 'class="tabs"' not in page


def test_delete_returns_to_the_page_it_came_from(client: TestClient, account: dict, expense_account: dict):
    tx = _tx(client, expense_account, account)
    back = f"/accounts/{account['id']}"
    response = client.post(f"/transactions/{tx['id']}/delete", params={"back": back})
    assert response.headers["HX-Redirect"] == back


def test_new_page_has_a_total_and_a_row_on_each_side(client: TestClient, account: dict, expense_account: dict):
    page = client.get("/transactions/new").text
    assert 'class="tabs' not in page
    assert page.count("data-txn-form") == 1 and 'name="total"' in page and date.today().isoformat() in page
    assert page.index('data-rows="credit"') < page.index('data-rows="debit"')
    credit = page[page.index('data-rows="credit"') : page.index('data-rows="debit"')]
    assert credit.count('class="txn-row"') == 1 and 'name="side" value="credit"' in credit
    assert 'name="side" value="debit"' in page[page.index('data-rows="debit"') :]
    assert 'hx-post="/transactions/split"' in page
    assert "<template" in page and "checking" in page
    assert "data-touched" not in page, "a new form has nothing of the user's yet"


def test_new_form_prefills_from_for_asset_and_to_for_expense(client: TestClient, account: dict, expense_account: dict):
    from_asset = client.get("/transactions/new", params={"account": account["id"]}).text
    assert option_selected(from_asset, account["id"]) == 1
    where = option_offset(from_asset, account["id"])
    assert from_asset.index('data-rows="credit"') < where < from_asset.index('data-rows="debit"')

    to_expense = client.get("/transactions/new", params={"category": expense_account["id"]}).text
    assert to_expense.index('data-rows="debit"') < option_offset(to_expense, expense_account["id"])


def test_old_mode_links_still_open_the_form(client: TestClient, account: dict):
    assert client.get("/transactions/new?mode=split").status_code == 200


def test_a_transaction_with_several_rows_shows_them_all(
    client: TestClient, root_accounts, account: dict, expense_account: dict
):
    other = post_account(client, {"name": "Tips", "parent_id": root_accounts["Expenses"]}).json()
    tx = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "6"),
                leg(other, "debit", "4"),
                leg(account, "credit", "10"),
            ]
        },
    ).json()
    page = client.get(f"/transactions/{tx['id']}/edit").text
    debit = page[page.index('data-rows="debit"') :]
    assert debit.count("data-touched") >= 2 and 'value="10.00"' in page


# ---- the Expense / Income / Transfer buttons ---------------------------------------------------------------------


def _kind(page: str) -> str:
    start = page.index('name="kind" value="') + len('name="kind" value="')
    return page[start : page.index('"', start)]


def _pressed(page: str) -> list[str]:
    return [label for label in ("Expense", "Income", "Transfer") if f'aria-pressed="true">{label}<' in page]


def test_a_new_entry_starts_as_an_expense_with_three_buttons_in_order(
    client: TestClient, account: dict, expense_account: dict
):
    page = client.get("/transactions/new").text
    assert _kind(page) == "expense" and _pressed(page) == ["Expense"]
    order = [page.index(f">{label}</button>") for label in ("Expense", "Income", "Transfer")]
    assert order == sorted(order), "Expense, Income, Transfer"
    assert ">Other</button>" not in page, "no button for it: selecting nothing offers every account"
    assert "data-side-hint" in page


def test_an_entry_that_fits_no_kind_has_nothing_selected(
    client: TestClient, root_accounts, account: dict, expense_account: dict
):
    capital = post_account(client, {"name": "Capital", "parent_id": root_accounts["Equity"]}).json()
    transaction_id = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(account, "debit", "5"),
                leg(capital, "credit", "5"),
            ]
        },
    ).json()["id"]
    page = client.get(f"/transactions/{transaction_id}/edit").text
    assert _kind(page) == "other" and _pressed(page) == []


def test_opening_a_form_from_an_account_picks_the_kind(
    client: TestClient, root_accounts, account: dict, expense_account: dict
):
    salary = post_account(client, {"name": "Salary", "parent_id": root_accounts["Income"]}).json()
    capital = post_account(client, {"name": "Capital", "parent_id": root_accounts["Equity"]}).json()
    assert _kind(client.get("/transactions/new", params={"category": salary["id"]}).text) == "income"
    assert _kind(client.get("/transactions/new", params={"account": capital["id"]}).text) == "other"
    assert _kind(client.get("/transactions/new", params={"category": expense_account["id"]}).text) == "expense"
    assert _kind(client.get("/transactions/new", params={"account": account["id"]}).text) == "expense"


def test_editing_shows_what_the_entry_is(
    client: TestClient, root_accounts, account: dict, other_account: dict, expense_account: dict
):
    salary = post_account(client, {"name": "Salary", "parent_id": root_accounts["Income"]}).json()
    card = post_account(client, {"name": "Visa", "parent_id": root_accounts["Liabilities"]}).json()
    capital = post_account(client, {"name": "Capital", "parent_id": root_accounts["Equity"]}).json()

    def entry(debit, credit):
        return client.post(
            "/api/transactions/",
            json={
                "postings": [
                    leg(debit, "debit", "5"),
                    leg(credit, "credit", "5"),
                ]
            },
        ).json()["id"]

    expected = {
        entry(expense_account, account): "expense",
        entry(expense_account, card): "expense",
        entry(account, salary): "income",
        entry(card, account): "transfer",
        entry(other_account, account): "transfer",
        entry(account, capital): "other",
        entry(account, expense_account): "other",  # a refund: money back from an expense
    }
    for transaction_id, kind in expected.items():
        assert _kind(client.get(f"/transactions/{transaction_id}/edit").text) == kind, (transaction_id, kind)


def test_a_split_across_expenses_is_still_an_expense(
    client: TestClient, account: dict, expense_account: dict, root_accounts
):
    other = post_account(client, {"name": "Tips", "parent_id": root_accounts["Expenses"]}).json()
    transaction_id = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "6"),
                leg(other, "debit", "4"),
                leg(account, "credit", "10"),
            ]
        },
    ).json()["id"]
    assert _kind(client.get(f"/transactions/{transaction_id}/edit").text) == "expense"

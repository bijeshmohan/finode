"""Several opening balances on one day (a new ledger) fold into one quiet row; one stays as itself."""

from .books import post_account


def test_opening_balances_are_marked_for_the_list_to_fold(client, root_accounts):
    for name, balance in (("Bank", "1000"), ("Wallet", "50"), ("Fund", "700")):
        post_account(client, {"name": name, "parent_id": root_accounts["Assets"], "balance": balance})
    rows = client.get("/api/views/transactions").json()["rows"]
    assert [r["is_opening"] for r in rows] == [True, True, True], "the app folds two or more into one row"
    assert {r["title"] for r in rows} == {"Opening balance"}


def test_an_account_page_still_lists_its_own_opening_balance(client, root_accounts):
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"}).json()
    post_account(client, {"name": "Wallet", "parent_id": root_accounts["Assets"], "balance": "50"})
    entries = client.get(f"/api/views/accounts/{bank['id']}").json()["entries"]
    assert [(r["title"], r["amount"]) for r in entries] == [("Opening balance", "1000.00")]

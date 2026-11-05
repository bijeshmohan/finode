"""Several opening balances on one day (a new ledger) fold into one quiet row; one stays as itself."""

import re

from .books import post_account


def test_two_or_more_opening_balances_fold_into_one_row(client, root_accounts):
    for name, balance in (("Bank", "1000"), ("Wallet", "50"), ("Fund", "700")):
        post_account(client, {"name": name, "parent_id": root_accounts["Assets"], "balance": balance})
    page = client.get("/transactions").text
    assert 'class="tx-fold"' in page and "3 accounts" in page
    fold = page.split('class="tx-fold"', 1)[1].split("</details>", 1)[0]
    assert all(name in fold for name in ("Bank", "Wallet", "Fund")), "they open to the three"
    assert page.count('<li class="tx-fold">') == 1
    assert len(re.findall(r'hx-get="/transactions/[0-9a-f-]{36}/sheet"', page)) == 3, (
        "each is still a row that opens its sheet"
    )


def test_a_single_opening_balance_stays_a_normal_row(client, root_accounts):
    post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"})
    page = client.get("/transactions").text
    assert "tx-fold" not in page.split("<main", 1)[1] and "Opening balance" in page


def test_an_account_page_still_lists_its_own_opening_balance(client, root_accounts):
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"}).json()
    post_account(client, {"name": "Wallet", "parent_id": root_accounts["Assets"], "balance": "50"})
    page = client.get(f"/accounts/{bank['id']}").text
    assert "Opening balance" in page and "tx-fold" not in page.split("<main", 1)[1]

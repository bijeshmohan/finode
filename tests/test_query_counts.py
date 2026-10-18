"""Pages must not ask the database once per account or once per row.

Every query costs a network round trip to the hosted database (about 16 ms), so a page that asks per account took
seconds. These tests count the statements a page runs and check the count does not grow with the size of the books.
"""

from sqlalchemy import event

import pytest

PAGES = ["/transactions/new", "/transactions", "/", "/accounts", "/budget", "/summary", "/categories", "/categories?tab=income"]
# What each page asks today, with one to spare. The session remembers repeated reads (repositories/cache.py), which
# brought these down from 10 to 21 each; a page that climbs back has probably started loading something twice.
CEILING = {
    "/transactions/new": 6, "/transactions": 8, "/": 13, "/accounts": 9, "/budget": 7, "/summary": 8,
    "/categories": 5, "/categories?tab=income": 5,
}


@pytest.fixture
def count_queries(session):
    engine = session.get_bind()
    counter = {"n": 0}

    def bump(*args, **kwargs):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", bump)

    def counted(get):
        counter["n"] = 0
        response = get()
        assert response.status_code == 200
        return counter["n"]

    yield counted
    event.remove(engine, "before_cursor_execute", bump)


def grow(client, root_accounts, accounts: int, transactions: int, start: int = 0):
    made = []
    for i in range(start, start + accounts):
        parent = root_accounts["Assets" if i % 2 else "Expenses"]
        made.append(client.post("/api/accounts/", json={"name": f"Acct{i}", "parent_id": parent}).json())
    assets = [a for a in made if a["parent_id"] == root_accounts["Assets"]]
    expenses = [a for a in made if a["parent_id"] == root_accounts["Expenses"]]
    for i in range(transactions):
        response = client.post("/api/transactions/", json={"postings": [
            {"account": expenses[i % len(expenses)]["aid"], "side": "debit", "amount": "5"},
            {"account": assets[i % len(assets)]["aid"], "side": "credit", "amount": "5"}]})
        assert response.status_code == 201, response.text


def test_the_number_of_queries_does_not_grow_with_the_books(client, root_accounts, count_queries):
    grow(client, root_accounts, accounts=10, transactions=10)
    small = {p: count_queries(lambda p=p: client.get(p)) for p in PAGES}
    grow(client, root_accounts, accounts=40, transactions=40, start=10)
    large = {p: count_queries(lambda p=p: client.get(p)) for p in PAGES}
    for page in PAGES:
        assert large[page] <= small[page] + 2, f"{page} asks the database more often as the books grow: {small[page]} -> {large[page]}"
        assert large[page] <= CEILING[page], f"{page} makes {large[page]} queries"


def test_an_accounts_own_page_and_its_filtered_list_do_not_grow_either(client, root_accounts, count_queries):
    grow(client, root_accounts, accounts=6, transactions=6)
    busiest = client.get("/api/accounts/").json()[0]["aid"]
    first = {
        "page": count_queries(lambda: client.get(f"/accounts/{busiest}")),
        "list": count_queries(lambda: client.get(f"/transactions?account={busiest}")),
    }
    grow(client, root_accounts, accounts=6, transactions=60, start=6)
    second = {
        "page": count_queries(lambda: client.get(f"/accounts/{busiest}")),
        "list": count_queries(lambda: client.get(f"/transactions?account={busiest}")),
    }
    assert second["page"] <= first["page"] + 2 and second["list"] <= first["list"] + 2, (first, second)


def test_saving_a_split_does_not_ask_more_as_it_gets_longer(client, root_accounts, count_queries):
    """Checking each posting's account used to cost two queries per row."""
    grow(client, root_accounts, accounts=14, transactions=0)
    accounts = client.get("/api/accounts/").json()
    leaves = [a for a in accounts if a["parent_id"] in (root_accounts["Assets"], root_accounts["Expenses"])]
    assets = [a["aid"] for a in leaves if a["parent_id"] == root_accounts["Assets"]]
    expenses = [a["aid"] for a in leaves if a["parent_id"] == root_accounts["Expenses"]]

    def save(rows: int):
        data = {"account": [assets[0]] + expenses[:rows], "side": ["credit"] + ["debit"] * rows,
                "amount": [str(rows)] + ["1"] * rows, "payee": "split"}
        return count_queries(lambda: client.post("/transactions/split", data=data))

    short, long = save(2), save(7)
    assert long <= short + 1, (short, long)

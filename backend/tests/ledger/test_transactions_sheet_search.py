"""Searching and filtering the transactions list, the details sheet that opens from a row, and "add again"."""

import pytest

from tests.books import leg, post_account


@pytest.fixture
def books(client, root_accounts):
    def make(name, root, **extra):
        response = post_account(client, {"name": name, "parent_id": root_accounts[root], **extra})
        assert response.status_code == 201, response.text
        return response.json()

    return {
        "hdfc": make("HDFC", "Assets", balance="10000"),
        "cash": make("Cash", "Assets"),
        "card": make("Regalia Gold", "Liabilities"),
        "delivery": make("Delivery", "Expenses"),
        "groceries": make("Groceries", "Expenses"),
        "salary": make("Salary", "Income"),
    }


def post(client, payee, debit, credit, amount="10", **extra):
    response = client.post(
        "/api/transactions/",
        json={
            "payee": payee,
            "postings": [
                leg(debit, "debit", amount),
                leg(credit, "credit", amount),
            ],
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def ledger(client, books):
    return {
        "swiggy": post(client, "Swiggy", books["delivery"], books["card"], "597"),
        "dmart": post(client, "DMart", books["groceries"], books["hdfc"], "1286", comment="weekly shop"),
        "pay": post(client, "Employer", books["hdfc"], books["salary"], "5000"),
        "move": post(client, "Card payment", books["card"], books["hdfc"], "300"),
    }


def titles(found: dict) -> list[str]:
    return [r["title"] for r in found["rows"]]


def page(client, **params) -> dict:
    """The Transactions view of this month (where the ledger's entries are dated)."""
    response = client.get("/api/views/transactions", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ---- search (the views take `q`) -----------------------------------------------------------------------------------


def test_search_finds_a_payee_a_note_or_an_account(client, books, ledger):
    assert titles(page(client, q="swig")) == ["Swiggy"], "part of a name, in any case"
    assert titles(page(client, q="WEEKLY")) == ["DMart"], "the note"
    assert set(titles(page(client, q="groceries"))) == {"DMart"}, "the name of an account used"
    assert set(titles(page(client, q="regalia"))) == {"Swiggy", "Card payment"}
    assert titles(page(client, q="zzz")) == [], "nothing found is an empty list"


def test_search_treats_percent_and_underscore_as_plain_text(client, books, ledger):
    post(client, "100% juice", books["groceries"], books["cash"])
    assert titles(page(client, q="%")) == ["100% juice"]
    assert titles(page(client, q="_")) == []


# ---- the kind ------------------------------------------------------------------------------------------------------


def test_the_kind_filters_by_what_kind_of_entry_it_is(client, books, ledger):
    assert set(titles(page(client, kind="expense"))) == {"Swiggy", "DMart"}
    assert titles(page(client, kind="income")) == ["Employer"]
    assert set(titles(page(client, kind="transfer"))) == {"Card payment", "Opening balance"}
    assert len(titles(page(client))) == 5, "no kind: everything"
    assert len(titles(page(client, kind="nonsense"))) == 5, "an unknown kind is ignored"
    assert (
        titles(page(client, kind="expense", q="swig")) == ["Swiggy"]
        and titles(page(client, kind="income", q="swig")) == []
    )


# ---- the Filter sheet: account, category, merchant ------------------------------------------------------------


def test_the_category_and_the_merchant_narrow_the_list_together_with_the_account(client, books, ledger):
    post(client, "dmart", books["groceries"], books["cash"], "310")  # the same shop, another account and spelling
    assert set(titles(page(client, category=books["groceries"]["id"]))) == {"DMart", "dmart"}
    assert set(titles(page(client, merchant="DMART"))) == {"DMart", "dmart"}, "the payee, capitals aside"
    assert titles(page(client, merchant="DMart", account=books["cash"]["id"])) == ["dmart"], "account and merchant both"
    assert titles(page(client, category=books["delivery"]["id"], merchant="DMart")) == [], "nothing is both"


def test_a_filter_says_how_many_match_and_what_they_come_to(client, books, ledger):
    summary = page(client, category=books["groceries"]["id"])["summary"]
    assert (summary["count"], summary["total"], summary["word"]) == (1, "1286.00", "spent")
    assert page(client)["summary"] is None, "no filter: no summary"
    assert page(client, category=books["salary"]["id"])["summary"]["word"] == "earned"


def test_each_filter_is_listed_with_its_value(client, books, ledger):
    applied = page(client, category=books["groceries"]["id"], merchant="DMart")["applied"]
    assert {(a["key"], a["name"]) for a in applied} == {("category", "Groceries"), ("merchant", "DMart")}


# ---- the details sheet ----------------------------------------------------------------------------------------


def sheet(client, tx) -> dict:
    response = client.get(f"/api/views/transactions/{tx['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_sheet_shows_the_entry_and_labels_its_sides_by_kind(client, books, ledger):
    swiggy = sheet(client, ledger["swiggy"])
    assert (swiggy["row"]["title"], swiggy["row"]["amount"], swiggy["row"]["kind"]) == ("Swiggy", "597.00", "expense")
    assert (swiggy["from_label"], swiggy["to_label"]) == ("Paid from", "Spent on")
    assert [line["name"] for line in swiggy["from_lines"]] == ["Regalia Gold"] and swiggy["comment"] is None
    assert sheet(client, ledger["dmart"])["comment"] == "weekly shop"
    pay = sheet(client, ledger["pay"])
    assert (pay["from_label"], pay["to_label"], pay["row"]["kind"]) == ("Earned from", "Paid into", "income")
    move = sheet(client, ledger["move"])
    assert (move["from_label"], move["to_label"]) == ("From", "To")


def test_a_split_lists_every_account_with_its_amount(client, books):
    tx = client.post(
        "/api/transactions/",
        json={
            "payee": "Big shop",
            "postings": [
                leg(books["groceries"], "debit", "600"),
                leg(books["delivery"], "debit", "300"),
                leg(books["hdfc"], "credit", "900"),
            ],
        },
    ).json()
    seen = sheet(client, tx)
    assert sorted((line["name"], line["amount"]) for line in seen["to_lines"]) == [
        ("Delivery", "300.00"),
        ("Groceries", "600.00"),
    ]
    assert [(line["name"], line["amount"]) for line in seen["from_lines"]] == [("HDFC", "900.00")]


# ---- add again ------------------------------------------------------------------------------------------------


def test_add_again_keeps_every_row_of_a_split(client, books):
    tx = client.post(
        "/api/transactions/",
        json={
            "payee": "Big shop",
            "postings": [
                leg(books["groceries"], "debit", "600"),
                leg(books["delivery"], "debit", "300"),
                leg(books["hdfc"], "credit", "900"),
            ],
        },
    ).json()
    again = client.get("/api/views/entry-form", params={"repeat": tx["id"]}).json()
    assert sorted(r["amount"] for r in again["to_rows"]) == ["300.00", "600.00"]
    assert [r["choice"] for r in again["from_rows"]] == [books["hdfc"]["id"]] and again["total"] == "900.00"


def test_only_an_assistant_or_a_rule_is_named(client, session, books, ledger):
    from uuid import UUID

    from finode.models.transaction import Transaction

    assert sheet(client, ledger["swiggy"])["added_by"] is None, "an entry made through the API says nothing"
    made = session.get(Transaction, UUID(ledger["swiggy"]["id"]))
    made.created_via = "mcp:Claude"
    session.add(made)
    session.commit()
    assert sheet(client, ledger["swiggy"])["added_by"] == "Claude"
    made.created_via = "recurring"
    session.add(made)
    session.commit()
    seen = sheet(client, ledger["swiggy"])
    assert seen["row"]["recurring"] is True and seen["added_by"] is None

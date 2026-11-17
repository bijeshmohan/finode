"""The payee chips on the Add screen: the people you pay most, names only. They never choose an account or a category."""

import pytest

from .books import leg, post_account


@pytest.fixture
def books(client, root_accounts):
    def make(name, root, **extra):
        response = post_account(client, {"name": name, "parent_id": root_accounts[root], **extra})
        assert response.status_code == 201, response.text
        return response.json()

    return {
        "hdfc": make("HDFC", "Assets", balance="10000"),
        "card": make("Regalia Gold", "Liabilities"),
        "delivery": make("Delivery", "Expenses"),
        "groceries": make("Groceries", "Expenses"),
        "salary": make("Salary", "Income"),
    }


def pay(client, payee, source, target, amount="10"):
    response = client.post(
        "/api/transactions/",
        json={
            "payee": payee,
            "postings": [
                leg(target, "debit", amount),
                leg(source, "credit", amount),
            ],
        },
    )
    assert response.status_code == 201, response.text


def chips(client, payee=""):
    """The names the Add screen offers under the payee field for what is typed."""
    found = client.get("/api/transactions/payee-suggestions", params={"payee": payee})
    assert found.status_code == 200, found.text
    return found.json()["names"]


def test_nothing_to_suggest_without_history(client, books):
    assert chips(client, "o") == [], "an account's opening balance is not somebody you paid"


def test_nothing_is_suggested_until_something_is_typed(client, books):
    pay(client, "Swiggy", books["hdfc"], books["delivery"])
    assert chips(client) == [] and chips(client, "   ") == []
    assert chips(client, "sw") == ["Swiggy"]


def test_often_paid_people_come_first_and_typing_narrows(client, books):
    for _ in range(3):
        pay(client, "DMart", books["hdfc"], books["groceries"])
    pay(client, "Swiggy", books["hdfc"], books["delivery"])
    pay(client, "Dunzo", books["hdfc"], books["delivery"])
    assert chips(client, "d") == ["DMart", "Dunzo"]
    assert chips(client, "mart") == ["DMart"], "what is typed may be inside the name"
    assert chips(client, "zzz") == []


def test_a_name_typed_in_full_comes_first_then_those_starting_with_it_then_containing_it(client, books):
    pay(client, "Big Swiggy", books["hdfc"], books["delivery"])
    pay(client, "Swiggy Instamart", books["hdfc"], books["groceries"])
    pay(client, "Swiggy", books["hdfc"], books["delivery"])
    assert chips(client, "swiggy") == ["Swiggy", "Swiggy Instamart", "Big Swiggy"]


def test_income_and_transfers_are_suggested_too(client, books):
    pay(client, "Employer", books["salary"], books["hdfc"], "5000")
    pay(client, "Card payment", books["hdfc"], books["card"], "300")
    assert sorted(chips(client, "employer") + chips(client, "card")) == ["Card payment", "Employer"]


def test_only_six_chips_are_offered(client, books):
    for n in range(8):
        pay(client, f"Shop {n}", books["hdfc"], books["groceries"])
    assert len(chips(client, "shop")) == 6


def test_the_form_starts_with_no_account_chosen_however_often_you_pay_from_one(client, books):
    for _ in range(3):
        pay(client, "A", books["card"], books["delivery"])
    pay(client, "B", books["hdfc"], books["groceries"])
    blank = client.get("/api/views/entry-form").json()
    assert [r["choice"] for r in blank["from_rows"] + blank["to_rows"]] == [None, None], "nothing is pre-filled"


# ---- the same chips through the JSON API (the finode app) ------------------------------------------------------------


def test_api_payee_suggestions_are_names_and_people(client, books):
    for payee in ("Swiggy", "Swiggy", "Swiggy Instamart", "Zepto"):
        pay(client, payee, books["hdfc"], books["delivery"])
    found = client.get("/api/transactions/payee-suggestions", params={"payee": "swi"}).json()
    assert found == {"names": ["Swiggy", "Swiggy Instamart"], "people": []}


def test_api_suggests_people_after_an_at(client, books):
    ada = client.post("/api/contacts/", json={"name": "Ada"}).json()
    found = client.get("/api/transactions/payee-suggestions", params={"payee": "@a"}).json()
    assert found == {"names": [], "people": [{"id": ada["id"], "name": "Ada"}]}


def test_api_only_people(client, books):
    pay(client, "Swiggy", books["hdfc"], books["delivery"])
    found = client.get("/api/transactions/payee-suggestions", params={"payee": "swi", "only": "people"}).json()
    assert found == {"names": [], "people": []}

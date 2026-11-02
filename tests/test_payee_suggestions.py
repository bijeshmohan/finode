"""The payee chips on the Add screen: the people you pay most, names only. They never choose an account or a category."""

import re

import pytest

from .books import leg, post_account
from .htmlutil import option_selected


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
    html = client.get("/transactions/suggest", params={"payee": payee}).text
    return re.findall(r'<button type="button" class="chip" data-suggest data-payee="([^"]*)">', html)


def test_nothing_to_suggest_without_history(client, books):
    assert chips(client, "o") == [], "an account's opening balance is not somebody you paid"


def test_nothing_is_suggested_until_something_is_typed(client, books):
    pay(client, "Swiggy", books["hdfc"], books["delivery"])
    assert chips(client) == [] and chips(client, "   ") == []
    assert chips(client, "sw") == ["Swiggy"]


def test_a_chip_is_a_name_and_nothing_else(client, books):
    pay(client, "Swiggy", books["hdfc"], books["delivery"])
    pay(client, "Swiggy", books["card"], books["delivery"])
    assert chips(client, "s") == ["Swiggy"], "once, even though it was paid twice"
    html = client.get("/transactions/suggest", params={"payee": "s"}).text
    for leftover in ("data-from", "data-to", "data-suggest-kind", "data-exact", "data-amount", "title="):
        assert leftover not in html, leftover


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


def test_the_chips_are_html_escaped(client, books):
    pay(client, '<b>x</b> "q"', books["hdfc"], books["delivery"])
    html = client.get("/transactions/suggest", params={"payee": "x"}).text
    assert "<b>x</b>" not in html and "&lt;b&gt;" in html


def test_the_add_page_asks_for_chips_as_you_type_not_on_load_and_edit_has_none(client, books):
    pay(client, "Swiggy", books["hdfc"], books["delivery"])
    page = client.get("/transactions/new").text
    assert 'id="payee-chips"' in page and 'hx-get="/transactions/suggest"' in page
    assert "load," not in page.split('id="payee-chips"')[1].split(">")[0], (
        "nothing is asked for before the person types"
    )
    transaction_id = client.get("/api/transactions/").json()[0]["id"]
    assert 'id="payee-chips"' not in client.get(f"/transactions/{transaction_id}/edit").text


def test_the_form_starts_with_no_account_chosen_however_often_you_pay_from_one(client, books):
    for _ in range(3):
        pay(client, "A", books["card"], books["delivery"])
    pay(client, "B", books["hdfc"], books["groceries"])
    page = client.get("/transactions/new").text
    assert not option_selected(page, books["card"]["id"])
    assert not option_selected(page, books["hdfc"]["id"])
    assert not option_selected(page, books["delivery"]["id"])


def test_opening_the_form_from_an_account_keeps_that_account(client, books):
    pay(client, "A", books["card"], books["delivery"])
    page = client.get("/transactions/new", params={"account": books["hdfc"]["id"]}).text
    assert option_selected(page, books["hdfc"]["id"])
    assert not option_selected(page, books["card"]["id"])

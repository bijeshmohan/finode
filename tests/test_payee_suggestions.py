"""The payee chips on the Add screen and the quick-add bar: remember who you pay and with what."""

import re

import pytest

from app.routers.web.transactions import split_quick_entry


@pytest.fixture
def books(client, root_accounts):
    def make(name, root, **extra):
        response = client.post("/api/accounts/", json={"name": name, "parent_id": root_accounts[root], **extra})
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
    response = client.post("/api/transactions/", json={"payee": payee, "postings": [
        {"account": target["aid"], "side": "debit", "amount": amount},
        {"account": source["aid"], "side": "credit", "amount": amount}]})
    assert response.status_code == 201, response.text


def chips(client, payee=""):
    html = client.get("/transactions/suggest", params={"payee": payee}).text
    return re.findall(r'<button type="button" class="chip" data-suggest data-payee="([^"]*)" data-suggest-kind="(\w+)" data-from="([0-9a-f-]+)" data-to="([0-9a-f-]+)"( data-exact)?', html)


def test_nothing_to_suggest_without_history(client, books):
    assert chips(client) == [], "an account's opening balance is not somebody you paid"


def test_chips_carry_the_accounts_used_the_last_time(client, books):
    pay(client, "Swiggy", books["hdfc"], books["delivery"])
    pay(client, "Swiggy", books["card"], books["delivery"])  # the newest is the one repeated
    [(payee, kind, from_id, to_id, exact)] = chips(client)  # once, even though it was paid twice
    assert (payee, kind, exact) == ("Swiggy", "expense", "")
    assert (from_id, to_id) == (books["card"]["aid"], books["delivery"]["aid"])


def test_there_is_no_amount_suggestion(client, books):
    pay(client, "Swiggy", books["card"], books["delivery"], "597.50")
    assert "data-amount" not in client.get("/transactions/suggest").text
    form = client.get("/transactions/new").text
    assert "data-amount-quick" not in form and "data-last-amount" not in form and "as last time" not in form


def test_often_paid_people_come_first_and_typing_narrows(client, books):
    for _ in range(3):
        pay(client, "DMart", books["hdfc"], books["groceries"])
    pay(client, "Swiggy", books["hdfc"], books["delivery"])
    pay(client, "Dunzo", books["hdfc"], books["delivery"])
    assert [c[0] for c in chips(client)] == ["DMart", "Dunzo", "Swiggy"]
    assert [c[0] for c in chips(client, "d")] == ["DMart", "Dunzo"]
    assert [c[0] for c in chips(client, "mart")] == ["DMart"], "what is typed may be inside the name"
    assert [c[0] for c in chips(client, "zzz")] == []


def test_a_name_typed_in_full_is_marked_exact(client, books):
    pay(client, "Swiggy", books["hdfc"], books["delivery"])
    pay(client, "Swiggy Instamart", books["hdfc"], books["groceries"])
    found = chips(client, "swiggy")
    assert [(c[0], bool(c[4])) for c in found] == [("Swiggy", True), ("Swiggy Instamart", False)]


def test_income_and_transfers_are_suggested_with_their_kind(client, books):
    pay(client, "Employer", books["salary"], books["hdfc"], "5000")
    pay(client, "Card payment", books["hdfc"], books["card"], "300")
    kinds = {c[0]: c[1] for c in chips(client)}
    assert kinds == {"Employer": "income", "Card payment": "transfer"}


def test_splits_entries_without_a_payee_and_closed_accounts_are_left_out(client, books):
    client.post("/api/transactions/", json={"payee": "Big shop", "postings": [
        {"account": books["groceries"]["aid"], "side": "debit", "amount": "6"},
        {"account": books["delivery"]["aid"], "side": "debit", "amount": "4"},
        {"account": books["hdfc"]["aid"], "side": "credit", "amount": "10"}]})
    pay(client, "", books["hdfc"], books["groceries"])
    extra = client.post("/api/accounts/", json={"name": "Gone", "parent_id": books["delivery"]["parent_id"]}).json()
    pay(client, "Old place", books["hdfc"], extra)
    pay(client, "Refund", extra, books["hdfc"])  # back to zero, so it can be closed
    assert {c[0] for c in chips(client)} == {"Old place", "Refund"}
    assert client.post(f"/api/accounts/{extra['aid']}/close").status_code == 200
    assert chips(client) == [], "a closed account is never suggested, and splits and entries without a payee are not either"


def test_the_chips_are_html_escaped(client, books):
    pay(client, '<b>x</b> "q"', books["hdfc"], books["delivery"])
    html = client.get("/transactions/suggest").text
    assert "<b>x</b>" not in html and "&lt;b&gt;" in html


def test_the_add_page_loads_the_chips_and_keeps_edit_free_of_them(client, books):
    pay(client, "Swiggy", books["hdfc"], books["delivery"])
    page = client.get("/transactions/new").text
    assert 'id="payee-chips"' in page and 'hx-get="/transactions/suggest"' in page
    tid = client.get("/api/transactions/").json()[0]["tid"]
    assert 'id="payee-chips"' not in client.get(f"/transactions/{tid}/edit").text


# ---- the quick-add bar -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("typed, expected", [
    ("250 swiggy", ("250", "swiggy")),
    ("swiggy 250", ("250", "swiggy")),
    ("1,250.50 dmart groceries", ("1250.50", "dmart groceries")),
    ("450", ("450", "")),
    ("swiggy", ("", "swiggy")),
    ("  ", ("", "")),
    ("", ("", "")),
    ("2 for 1 pizza", ("2", "for 1 pizza")),
])
def test_what_is_typed_in_the_bar(typed, expected):
    assert split_quick_entry(typed) == expected


def field(html, name):
    return re.search(rf'name="{name}"[^>]*value="([^"]*)"', html).group(1)


def test_the_quick_bar_opens_the_form_filled_in(client, books):
    pay(client, "Swiggy", books["card"], books["delivery"])
    page = client.get("/transactions/new", params={"q": "250 swiggy"}).text
    assert field(page, "total") == "250" and field(page, "payee") == "Swiggy"  # spelled as before
    assert f'<option value="{books["card"]["aid"]}" selected' in page, "paid from the same card"
    assert f'<option value="{books["delivery"]["aid"]}" selected' in page
    assert 'name="kind" value="expense"' in page


def test_an_unknown_payee_still_fills_the_amount_and_name(client, books):
    page = client.get("/transactions/new", params={"q": "180 chai point"}).text
    assert 'value="180"' in page and 'value="chai point"' in page


def test_the_form_starts_with_no_account_chosen_however_often_you_pay_from_one(client, books):
    for _ in range(3):
        pay(client, "A", books["card"], books["delivery"])
    pay(client, "B", books["hdfc"], books["groceries"])
    page = client.get("/transactions/new").text
    assert f'<option value="{books["card"]["aid"]}" selected' not in page
    assert f'<option value="{books["hdfc"]["aid"]}" selected' not in page
    assert f'<option value="{books["delivery"]["aid"]}" selected' not in page


def test_opening_the_form_from_an_account_keeps_that_account(client, books):
    pay(client, "A", books["card"], books["delivery"])
    page = client.get("/transactions/new", params={"account": books["hdfc"]["aid"]}).text
    assert f'<option value="{books["hdfc"]["aid"]}" selected' in page
    assert f'<option value="{books["card"]["aid"]}" selected' not in page

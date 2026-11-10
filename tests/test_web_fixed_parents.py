"""The built-in groups on the web: Accounts page headings with a round +, the form starting as the group says, no menu."""

import re

import pytest

from app.services import account as account_service

from .test_fixed_parents import group, make


@pytest.fixture(autouse=True)
def new_person(monkeypatch):
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)


def test_with_no_accounts_every_built_in_shelf_shows_with_its_own_add_card(client):
    text = client.get("/accounts").text
    shown = text[text.index("data-accounts") :]
    for name in ("Bank Accounts", "Cash", "Investments", "Credit Cards", "Loans"):
        assert f">{name}</a></h2>" in shown, name
    assert shown.count("acc-card-add") == 5 and "0.00 · 0 accounts" in shown
    assert 'href="/accounts/new"' not in shown and "Built in" not in text and "lock" not in shown.lower()


def test_a_shelf_with_accounts_shows_them_beside_the_add_card(client):
    make(client, "HDFC", "Bank Accounts", balance="500")
    text = client.get("/accounts").text
    shown = text[text.index("data-accounts") :]
    assert "HDFC" in shown and "500.00 · 1 account<" in shown
    assert "Nothing here yet" not in text


def test_the_form_offers_the_five_kinds_in_the_pages_order_and_starts_on_none(client):
    page = client.get("/accounts/new").text
    chips = re.findall(r'data-kind-chip="[^"]+" aria-pressed="(\w+)">([^<]+)<', page)
    assert [name for _state, name in chips] == ["Bank Accounts", "Cash", "Credit Cards", "Investments", "Loans"]
    assert {state for state, _name in chips} == {"false"}, "nothing is chosen for the person"
    assert ">Under<" not in page and ">Kind<" in page
    loans = group(client, "Loans")["id"]
    chosen = client.get(f"/accounts/new?parent={loans}").text
    assert re.search(rf'data-kind-chip="{loans}" aria-pressed="true"', chosen)


def test_the_form_starts_as_the_group_says(client):
    investments = group(client, "Investments")["id"]
    page = client.get(f"/accounts/new?parent={investments}").text
    assert 'name="on_budget" value="1" checked' not in page
    bank = client.get(f"/accounts/new?parent={group(client, 'Bank Accounts')['id']}").text
    assert 'name="on_budget" value="1" checked' in bank
    assert 'data-start="outside"' in page and 'data-start="budget"' in page, "the choice can follow the group chosen"
    assert 'data-start="outside"' in client.get(f"/accounts/new?parent={group(client, 'Loans')['id']}").text


def test_creating_a_loan_from_the_form_leaves_it_outside_the_budget(client):
    loans = group(client, "Loans")["id"]
    done = client.post(
        "/accounts", data={"name": "Home Loan", "parent_id": loans, "balance": "1000000", "budget_choice": "1"}
    )
    assert done.status_code == 200, done.text
    made = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Home Loan")
    assert made["on_budget"] is False


def test_a_groups_page_has_no_edit_or_menu_but_can_add_an_account(client):
    page = client.get(f"/accounts/{group(client, 'Cash')['id']}").text
    assert "/edit" not in page
    assert "Close account" not in page and "Delete" not in page
    assert "More actions" not in page and f"/accounts/new?parent={group(client, 'Cash')['id']}" in page
    assert client.get(f"/accounts/{group(client, 'Cash')['id']}/edit").status_code == 404


def test_the_empty_groups_are_not_offered_to_post_to(client):
    make(client, "HDFC", "Bank Accounts")
    form = client.get("/transactions/new").text
    assert "HDFC" in form
    assert ">Investments<" not in form and ">Loans<" not in form


def test_an_empty_groups_page_has_the_add_card_and_no_transactions_yet(client):
    page = client.get(f"/accounts/{group(client, 'Investments')['id']}").text
    assert "<h2>Accounts</h2>" in page and "No transactions yet" in page
    assert "Built in · money I own" in page and "More actions" not in page, "built in: nothing to change"
    assert f"/accounts/new?parent={group(client, 'Investments')['id']}" in page

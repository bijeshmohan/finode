"""The built-in groups on the web: Accounts page headings with a round +, the form starting as the group says, no menu."""

import re

import pytest

from app.repositories import profile
from app.services import account as account_service

from .test_fixed_parents import group, make


@pytest.fixture(autouse=True)
def new_person(monkeypatch):
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)
    monkeypatch.setattr(profile, "NEW_PROFILE_PLAN_BUILD", False)
    monkeypatch.setattr(profile, "NEW_PROFILE_ADVANCED", False)


def test_the_accounts_page_lists_every_group_even_when_empty_without_a_plus_on_each(client):
    text = client.get("/accounts").text
    for name in ("Bank Accounts", "Cash", "Investments"):
        assert name in text and f'href="/accounts/{group(client, name)["aid"]}"' in text, name
        assert f"Add to {name}" not in text and f'/accounts/new?parent={group(client, name)["aid"]}' not in text
    assert text.count("circ-button") == 1, "only the round + at the top of the page"
    assert text.count("Nothing here yet.") == 3
    liabilities = client.get("/accounts?tab=liabilities").text
    assert "Credit Cards" in liabilities and "Loans" in liabilities and liabilities.count("Nothing here yet.") == 2
    assert "Built in" in text


def test_an_account_appears_under_its_group_and_the_empty_note_goes(client):
    make(client, "HDFC", "Bank Accounts", balance="500")
    text = client.get("/accounts").text
    assert "HDFC" in text and text.count("Nothing here yet.") == 2


def test_the_plus_on_a_type_starts_on_its_first_group(client):
    page = client.get("/accounts/new?root=assets").text
    bank = group(client, "Bank Accounts")["aid"]
    assert re.search(rf'<option value="{bank}"[^>]*selected', page)
    liabilities = client.get("/accounts/new?root=liabilities").text
    assert re.search(rf'<option value="{group(client, "Credit Cards")["aid"]}"[^>]*selected', liabilities)


def test_the_form_starts_as_the_group_says(client):
    investments = group(client, "Investments")["aid"]
    page = client.get(f"/accounts/new?parent={investments}").text
    assert 'name="saving" value="1" checked' in page and 'name="on_budget" value="1" checked' not in page
    assert "Planned under Build" in page, "the folded summary says it"
    bank = client.get(f"/accounts/new?parent={group(client, 'Bank Accounts')['aid']}").text
    assert 'name="on_budget" value="1" checked' in bank and 'name="saving" value="1" checked' not in bank
    assert f'data-start="build"' in page and 'data-start="budget"' in page, "the choice can follow the group chosen"
    assert 'data-start="build"' in client.get(f"/accounts/new?parent={group(client, 'Loans')['aid']}").text


def test_creating_a_loan_from_the_form_goes_under_build(client):
    loans = group(client, "Loans")["aid"]
    done = client.post("/accounts", data={
        "name": "Home Loan", "parent_id": loans, "balance": "1000000", "budget_choice": "1", "saving": "1"})
    assert done.status_code == 200, done.text
    made = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Home Loan")
    assert made["saving"] is True and made["on_budget"] is False
    assert ">Build<" in client.get("/plan").text


def test_a_groups_page_has_no_edit_or_menu_but_can_add_an_account(client):
    page = client.get(f"/accounts/{group(client, 'Cash')['aid']}").text
    assert "Built in" in page and "/edit" not in page
    assert "Close account" not in page and "Delete" not in page
    assert "Add sub-account" in page
    assert client.get(f"/accounts/{group(client, 'Cash')['aid']}/edit").status_code == 404


def test_the_empty_groups_are_not_offered_to_post_to(client):
    make(client, "HDFC", "Bank Accounts")
    form = client.get("/transactions/new").text
    assert "HDFC" in form
    assert ">Investments<" not in form and ">Loans<" not in form


def test_an_empty_groups_page_is_about_adding_accounts_not_transactions(client):
    page = client.get(f"/accounts/{group(client, 'Investments')['aid']}").text
    assert "Sub-accounts" in page and "Nothing here yet" in page
    assert "<h2>Transactions</h2>" not in page and "No transactions yet" not in page
    assert f'/accounts/new?parent={group(client, "Investments")["aid"]}' in page

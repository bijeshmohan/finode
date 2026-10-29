"""Books accounts: the Income and Expenses accounts behind the categories, and the extra ones a person can add."""

from uuid import UUID

import pytest
from sqlmodel import select

from app.models.account import Account
from app.models.category import BudgetCategory

from .conftest import TEST_USER_ID
from .test_budget import account, budget, line
from .test_budget_categories import paid


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="100000")
    loan = account(client, root_accounts, "Home Loan", "Liabilities", on_budget=False)
    emi = account(client, root_accounts, "EMI", "Expenses")
    food = account(client, root_accounts, "Food", "Expenses")
    salary = account(client, root_accounts, "Salary", "Income")
    return {"bank": bank, "loan": loan, "emi": emi, "food": food, "salary": salary, "roots": root_accounts}


def extra(client, books, name="Interest", category="emi", root="Expenses"):
    made = client.post(
        "/api/accounts/", json={"name": name, "parent_id": books["roots"][root], "category_id": books[category]["aid"]}
    )
    assert made.status_code == 201, made.text
    return made.json()


def test_an_extra_account_feeds_a_category_without_making_one(client, session, books):
    interest = extra(client, books)
    assert interest["category_id"] == books["emi"]["aid"]
    names = {c.name for c in session.exec(select(BudgetCategory).where(BudgetCategory.user == TEST_USER_ID)).all()}
    assert "Interest" not in names, "an extra books account is not a category"
    assert {c["path"] for c in client.get("/api/categories/").json()} == {"EMI", "Food", "Salary"}


def test_an_entry_on_the_extra_account_counts_for_its_category_and_is_a_real_expense(client, books):
    interest = extra(client, books)
    paid(client, books["bank"], books["loan"], "14120", books["emi"])
    paid(client, books["bank"], interest, "5157")
    assert line(budget(client), "EMI")["activity"] == "19277.00"
    by_account = client.get("/api/reports/breakdown", params={"by": "account"}).json()
    assert [(l["account"], l["amount"]) for l in by_account["lines"]] == [("Interest", "5157.00")]
    by_category = client.get("/api/reports/breakdown").json()
    assert [(l["account"], l["amount"]) for l in by_category["lines"]] == [("EMI", "19277.00")]


def test_it_is_not_offered_as_a_category(client, books):
    extra(client, books)
    form = client.get("/transactions/new").text
    assert ">Interest<" not in form and ">EMI<" in form
    assert "Interest" not in client.get("/categories").text


def test_the_rules_for_extra_accounts(client, books):
    wrong_kind = client.post(
        "/api/accounts/", json={"name": "X", "parent_id": books["roots"]["Income"], "category_id": books["emi"]["aid"]}
    )
    assert wrong_kind.status_code == 400 and "spending category" in wrong_kind.text
    on_asset = client.post(
        "/api/accounts/", json={"name": "X", "parent_id": books["roots"]["Assets"], "category_id": books["emi"]["aid"]}
    )
    assert on_asset.status_code == 400 and "Income or Expenses" in on_asset.text
    own = client.patch(f"/api/accounts/{books['emi']['aid']}", json={"category_id": books["food"]["aid"]})
    assert own.status_code == 400 and "stands for its own category" in own.text
    interest = extra(client, books)
    nothing = client.patch(f"/api/accounts/{interest['aid']}", json={"category_id": None})
    assert nothing.status_code == 400


def test_moving_an_extra_account_to_another_category_moves_its_lines(client, session, books):
    interest = extra(client, books)
    paid(client, books["bank"], interest, "100")
    moved = client.patch(f"/api/accounts/{interest['aid']}", json={"category_id": books["food"]["aid"]})
    assert moved.status_code == 200 and moved.json()["category_id"] == books["food"]["aid"]
    data = budget(client)
    assert line(data, "Food")["activity"] == "100.00" and line(data, "EMI")["activity"] == "0.00"


def test_the_books_page_lists_the_accounts_and_what_the_extra_ones_feed(client, books):
    extra(client, books)
    page = client.get("/books").text
    assert "Books accounts" in page and "Spending" in page and "Earning" in page
    assert "feeds EMI" in page and "Expenses:Interest" in page and "Income:Salary" in page
    assert 'href="/books"' in client.get("/settings").text


def test_the_sheet_of_an_own_account_explains_and_an_extra_one_can_be_changed(client, session, books):
    interest = extra(client, books)
    own = client.get(f"/books/{books['emi']['aid']}/sheet").text
    assert "stands for the category" in own and "Open the category" in own and 'name="name"' not in own
    sheet = client.get(f"/books/{interest['aid']}/sheet").text
    assert 'name="name"' in sheet and "Close" in sheet and "Delete account" in sheet
    assert client.get(f"/books/{MISSING}/sheet").status_code == 404


MISSING = "00000000-0000-4000-8000-0000000000aa"


def test_making_renaming_closing_and_deleting_an_extra_account_from_the_page(client, session, books):
    made = client.post("/books", data={"name": "Fees", "category": books["emi"]["aid"]})
    assert made.status_code == 200 and made.headers["HX-Redirect"] == "/books"
    fees = session.exec(select(Account).where(Account.user == TEST_USER_ID, Account.name == "Fees")).one()
    assert fees.category_id == UUID(books["emi"]["aid"])
    assert (
        client.post(f"/books/{fees.aid}", data={"name": "Charges", "category": books["food"]["aid"]}).status_code == 200
    )
    session.expire_all()
    fees = session.get(Account, fees.aid)
    assert (fees.name, fees.category_id) == ("Charges", UUID(books["food"]["aid"]))
    assert client.post(f"/books/{fees.aid}/close").status_code == 200
    session.expire_all()
    assert session.get(Account, fees.aid).closed_on is not None
    assert client.post(f"/books/{fees.aid}/reopen").status_code == 200
    assert client.post(f"/books/{fees.aid}/delete").status_code == 200
    session.expire_all()
    assert session.get(Account, fees.aid) is None


def test_an_own_account_cannot_be_changed_from_here_and_an_account_with_entries_is_not_deleted(client, books):
    refused = client.post(f"/books/{books['emi']['aid']}", data={"name": "Nope"})
    assert refused.status_code == 400 and "stands for its category" in refused.text
    interest = extra(client, books)
    paid(client, books["bank"], interest, "10")
    kept = client.post(f"/books/{interest['aid']}/delete")
    assert kept.status_code == 400 and "postings" in kept.text
    bad = client.post("/books", data={"name": "X", "category": ""})
    assert bad.status_code == 400

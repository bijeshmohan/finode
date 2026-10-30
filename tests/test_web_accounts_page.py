"""The accounts page: every group open under its heading, unused accounts tucked away."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from app.models.account import Account


@pytest.fixture
def tree(client, root_accounts, session):
    def make(name, parent, **extra):
        return client.post("/api/accounts/", json={"name": name, "parent_id": parent, **extra}).json()["aid"]

    banks = make("Banks", root_accounts["Assets"])
    ids = {
        "banks": banks,
        "hdfc": make("HDFC", banks, balance="5000"),
        "old": make("Old Savings", banks),
    }
    cards = make("Credit Cards", root_accounts["Liabilities"])
    ids["amex"] = make("Amex", cards, balance="300")
    food = make(
        "Food", root_accounts["Assets"]
    )  # a second group, so the tests need no Expenses account (those are Categories)
    ids["food"] = food
    ids["groceries"] = make("Groceries", food)
    ids["snacks"] = make("Snacks", food)
    ids["rent"] = make("Rent", root_accounts["Assets"])
    return ids


def age(session, *names, days=30):
    old = datetime.now(UTC) - timedelta(days=days)
    table = Account.__table__
    session.exec(table.update().where(table.c.name.in_(names)).values(created=old))
    session.commit()


def item(page: str, aid: str) -> str:
    """The <li> of one account."""
    start = page.index('<li data-path="', page.index(f'/accounts/{aid}"') - 400)
    return page[start : page.index("</li>", page.index(f'/accounts/{aid}"'))]


def test_a_group_is_a_heading_with_its_accounts_under_it_and_nothing_folds(client, tree):
    page = client.get("/accounts").text
    assert f'href="/accounts/{tree["food"]}" title="Open Food"' in page, "the heading opens the group's own page"
    assert f'href="/accounts/{tree["hdfc"]}"' in page
    assert "<details" not in page
    assert page.count('<a class="acc-gh"') == 2, "Banks and Food"
    assert 'class="mono"' not in page, "plain rows, like Budgets and Categories"


def test_plain_accounts_under_a_type_share_one_block_under_others(client, tree):
    page = client.get("/accounts").text
    assert page.count('<div class="acc-block') == 3, "Banks, Food and the plain ones"
    assert page.count('<a class="acc-gh"') == 2, "the two groups open pages"
    assert page.count("data-others") == 1 and ">Others</span>" in page, (
        "the plain ones sit under Others, a label and not a link"
    )


def test_the_second_row_of_chips_lists_expense_equity_and_income_and_tapping_the_chosen_one_goes_back(client, tree):
    chip = r'<a class="chip" href="/accounts\?tab=(\w+)" aria-pressed="(\w+)">(\w+)</a>'
    # Neither Asset nor Liability: Expense, Equity (chosen) and Income; the chosen chip leads back to Assets.
    equity = client.get("/accounts?tab=equity").text
    assert re.findall(chip, equity) == [
        ("expense", "false", "Expense"),
        ("assets", "true", "Equity"),
        ("income", "false", "Income"),
    ]
    for tab, name, lead in (("expense", "Expense", "Total spent"), ("income", "Income", "Total earned")):
        page = client.get(f"/accounts?tab={tab}").text
        found = re.findall(chip, page)
        assert [n for _, _, n in found] == ["Expense", "Equity", "Income"], tab
        assert (("assets", "true", name) in found) and lead in page, tab
        assert f'href="/categories/new?root={tab}"' in page, "adding makes a category, with its books account"
    assert re.findall(chip, client.get("/accounts?tab=expense").text)[1] == ("equity", "false", "Equity")


def test_the_chips_pick_a_type_in_the_order_assets_liabilities_and_equity_has_none(client, tree):
    page = client.get("/accounts").text
    chips = re.findall(r'<a class="chip" href="/accounts\?tab=(\w+)" aria-pressed="(\w+)">(\w+)</a>', page)
    # The chosen chip links to Equity (tapping it again leaves neither chosen); the other one links to itself.
    assert chips == [("equity", "true", "Asset"), ("liabilities", "false", "Liability")]
    assert client.get("/accounts?tab=nonsense").text.count('aria-pressed="true"') == 1 and client.get(
        "/accounts?tab=nonsense"
    ).text.split('aria-pressed="true">')[1].startswith("Asset<")
    assert "Amex" not in page and "Opening Balances" not in page, "only the chosen type is listed"
    liabilities = client.get("/accounts?tab=liabilities").text
    assert "Amex" in liabilities and "HDFC" not in liabilities and 'aria-pressed="true">Liability<' in liabilities
    assert "Opening Balances" in client.get("/accounts?tab=equity").text
    assert "data-account-search" not in page and "Recently used" not in page and "Search accounts" not in page
    assert "Net worth" not in page and 'class="add-row" href="/accounts/new?root=assets"' in page, (
        "an Add account row ends the page"
    )
    assert "circ-button" not in page and "head-icons" not in page, "no round + or bin beside the switcher"
    assert page.index('class="add-row"') > page.index('class="tile list"'), "after the accounts"


def test_the_figure_is_the_chosen_types_total(client, tree):
    page = client.get("/accounts").text
    assert (
        '<span class="muted">What you own</span>' in page
        and "5,000.00" in page.split('cat-hero"', 1)[1].split("</span>\n</div>", 1)[0]
    )
    owed = client.get("/accounts?tab=liabilities").text
    assert "What you owe" in owed and "300.00" in owed.split('cat-hero"', 1)[1].split("</span>\n</div>", 1)[0]


def test_the_quiet_line_counts_the_open_accounts_of_the_type(client, tree):
    page = client.get("/accounts").text
    line = page.split('hero-note"><span>', 1)[1].split("</span>", 1)[0]
    assert line.endswith((" accounts", " account")), line


def test_every_open_account_shows_even_with_no_entries_and_no_balance(client, tree, session):
    age(session, "Old Savings", "Snacks", "Rent", "Food", "Groceries", "HDFC", "Amex")
    page = client.get("/accounts").text
    assert "unused" not in page and "Load more" not in page, "nothing is tucked away for being quiet"
    assert "closed-hidden" not in page
    for name in ("old", "snacks", "rent", "food", "groceries", "hdfc"):
        assert f'href="/accounts/{tree[name]}"' in page, name
    assert f'href="/accounts/{tree["amex"]}"' in client.get("/accounts?tab=liabilities").text


def test_closed_accounts_wait_behind_load_more(client, tree, session):
    assert client.post(f"/api/accounts/{tree['old']}/close").status_code == 200
    page = client.get("/accounts").text
    assert "closed-hidden" in item(page, tree["old"]) and "closed-hidden" not in item(page, tree["hdfc"])
    assert ">Load more</button>" in page


def test_the_page_has_no_note_under_its_list(client, root_accounts):
    page = client.get("/accounts").text
    assert "What it was spent on" not in page and 'class="muted budget-fine' not in page


def test_categories_end_with_an_add_row_and_an_empty_page_keeps_its_button(client, root_accounts):
    empty = client.get("/categories").text
    assert "Add a category" in empty and 'class="add-row"' not in empty
    client.post("/api/accounts/", json={"name": "Dining", "parent_id": root_accounts["Expenses"]})
    page = client.get("/categories?tab=expense").text
    assert 'class="add-row" href="/categories/new?root=expense"' in page and "circ-button" not in page
    assert client.get("/categories?tab=income").text.count('class="add-row"') == 0, (
        "nothing in Income yet: its own button"
    )


def test_the_expense_chip_shows_what_each_category_took_even_when_the_money_went_into_a_loan(
    client, tree, root_accounts
):
    emi = client.post("/api/accounts/", json={"name": "EMI", "parent_id": root_accounts["Expenses"]}).json()["aid"]
    loan = client.post("/api/accounts/", json={"name": "Home loan", "parent_id": root_accounts["Liabilities"]}).json()[
        "aid"
    ]
    made = client.post(
        "/api/transactions/",
        json={
            "date": "2026-01-05",
            "postings": [
                {"account": tree["hdfc"], "side": "credit", "amount": "700"},
                {"account": loan, "side": "debit", "amount": "700", "category": emi},
            ],
        },
    )
    assert made.status_code == 201, made.text
    page = client.get("/accounts?tab=expense").text
    assert "700.00" in page

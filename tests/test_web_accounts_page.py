"""The accounts page: every group open under its heading, unused accounts tucked away."""

from datetime import datetime, timedelta, timezone

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
    food = make("Food", root_accounts["Assets"])  # a second group, so the tests need no Expenses account (those are Categories)
    ids["food"] = food
    ids["groceries"] = make("Groceries", food)
    ids["snacks"] = make("Snacks", food)
    ids["rent"] = make("Rent", root_accounts["Assets"])
    return ids


def age(session, *names, days=30):
    old = datetime.now(timezone.utc) - timedelta(days=days)
    table = Account.__table__
    session.exec(table.update().where(table.c.name.in_(names)).values(created=old))
    session.commit()


def item(page: str, aid: str) -> str:
    """The <li> of one account."""
    start = page.index(f'<li data-path="', page.index(f'/accounts/{aid}"') - 400)
    return page[start:page.index("</li>", page.index(f'/accounts/{aid}"'))]


def test_a_group_is_a_heading_with_its_accounts_under_it_and_nothing_folds(client, tree):
    page = client.get("/accounts").text
    assert f'href="/accounts/{tree["food"]}" title="Open Food"' in page, "the heading opens the group's own page"
    assert f'href="/accounts/{tree["hdfc"]}"' in page and "data-account-search" in page
    assert "<details" not in page.split('<section class="acc-section"', 1)[1].split('<details class="acc-section equity"')[0], "Assets and Liabilities never fold"
    assert page.count('class="acc-gh"') == 3, "Banks, Food and Credit Cards"
    assert 'class="mono" aria-hidden="true">H<' in page, "each account has its initial"


def test_plain_accounts_under_a_type_share_one_block_without_a_heading(client, tree):
    page = client.get("/accounts").text
    assert page.count('<div class="acc-block') == 5, "Banks, Food, Rent (no heading), Credit Cards, and Equity's Opening Balances"
    assert page.count('class="acc-gh"') == 3, "Rent has no heading of its own"


def test_assets_and_liabilities_are_open_equity_folds_and_there_is_no_net_worth_card(client, tree):
    page = client.get("/accounts").text
    assert page.count("data-section") == 3, "Assets, Liabilities and Equity: the Expenses and Income accounts are on the Categories page"
    assert '<details class="acc-section equity"' in page and "<details class=\"acc-section\"" not in page
    assert "Net worth" not in page and "net-worth" not in page
    assert 'class="circ-button" href="/accounts/new"' in page, "the round + adds an account"


def test_every_open_account_shows_even_with_no_entries_and_no_balance(client, tree, session):
    age(session, "Old Savings", "Snacks", "Rent", "Food", "Groceries", "HDFC", "Amex")
    page = client.get("/accounts").text
    assert "unused" not in page and "Load more" not in page, "nothing is tucked away for being quiet"
    assert "closed-hidden" not in page
    for name in ("old", "snacks", "rent", "food", "groceries", "hdfc", "amex"):
        assert f'href="/accounts/{tree[name]}"' in page, name


def test_closed_accounts_wait_behind_load_more(client, tree, session):
    assert client.post(f"/api/accounts/{tree['old']}/close").status_code == 200
    page = client.get("/accounts").text
    assert "closed-hidden" in item(page, tree["old"]) and "closed-hidden" not in item(page, tree["hdfc"])
    assert ">Load more</button>" in page


def test_the_page_has_no_note_under_its_list(client, root_accounts):
    page = client.get("/accounts").text
    assert "What it was spent on" not in page and 'class="muted budget-fine' not in page

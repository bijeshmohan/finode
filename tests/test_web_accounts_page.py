"""The accounts page: every group open under its heading, unused accounts tucked away."""

import re
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
    assert f'href="/accounts/{tree["hdfc"]}"' in page
    assert "<details" not in page
    assert page.count('class="acc-gh"') == 2, "Banks and Food"
    assert 'class="mono" aria-hidden="true">H<' in page, "each account has its initial"


def test_plain_accounts_under_a_type_share_one_block_without_a_heading(client, tree):
    page = client.get("/accounts").text
    assert page.count('<div class="acc-block') == 3, "Banks, Food and Rent (no heading)"
    assert page.count('class="acc-gh"') == 2, "Rent has no heading of its own"


def test_the_chips_pick_a_type_in_the_order_assets_liabilities_equity(client, tree):
    page = client.get("/accounts").text
    chips = re.findall(r'<a class="chip" href="/accounts\?tab=(\w+)" aria-pressed="(\w+)">(\w+)</a>', page)
    assert chips == [("assets", "true", "Assets"), ("liabilities", "false", "Liabilities"), ("equity", "false", "Equity")]
    assert client.get("/accounts?tab=nonsense").text.count('aria-pressed="true"') == 1 and 'tab=assets" aria-pressed="true"' in client.get("/accounts?tab=nonsense").text
    assert "Amex" not in page and "Opening Balances" not in page, "only the chosen type is listed"
    liabilities = client.get("/accounts?tab=liabilities").text
    assert "Amex" in liabilities and "HDFC" not in liabilities and 'tab=liabilities" aria-pressed="true"' in liabilities
    assert "Opening Balances" in client.get("/accounts?tab=equity").text
    assert "data-account-search" not in page and "Recently used" not in page and "Search accounts" not in page
    assert "Net worth" not in page and 'class="circ-button" href="/accounts/new"' in page, "the round + adds an account"


def test_the_figure_is_the_chosen_types_total(client, tree):
    page = client.get("/accounts").text
    assert '<span class="sr-only">What you own</span>' in page and "5,000.00" in page.split('class="ready zero cat-hero"', 1)[1].split("</div>", 1)[0]
    owed = client.get("/accounts?tab=liabilities").text
    assert "What you owe" in owed and "300.00" in owed.split('class="ready zero cat-hero"', 1)[1].split("</div>", 1)[0]


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

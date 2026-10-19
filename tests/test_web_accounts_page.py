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


def test_unused_accounts_are_tucked_away_but_new_ones_are_not(client, tree, session):
    page = client.get("/accounts").text
    assert "unused-hidden" not in page and "Load more" not in page, "everything is new"
    age(session, "Old Savings", "Snacks", "Rent")
    page = client.get("/accounts").text
    assert page.count("unused-hidden") == 4, "three accounts, and Rent's block, which has nothing else in it"
    assert ">Load more</button>" in page and "unused accounts hidden" not in page
    assert "unused-hidden" in item(page, tree["old"]) and "unused-hidden" not in item(page, tree["hdfc"])
    assert "unused-hidden" not in item(page, tree["groceries"]), "a new account stays"


def test_an_account_with_entries_or_a_balance_is_never_unused(client, tree, session):
    age(session, "HDFC", "Amex", "Old Savings")
    client.post("/api/transactions/", json={"postings": [
        {"account": tree["groceries"], "side": "debit", "amount": "5"},
        {"account": tree["hdfc"], "side": "credit", "amount": "5"},
    ]})
    age(session, "Groceries")
    page = client.get("/accounts").text
    assert "unused-hidden" not in item(page, tree["hdfc"]) and "unused-hidden" not in item(page, tree["amex"])
    assert "unused-hidden" not in item(page, tree["groceries"])
    assert "unused-hidden" in item(page, tree["old"])


def test_a_group_is_unused_only_when_everything_in_it_is(client, tree, session):
    age(session, "Food", "Groceries", "Snacks")
    page = client.get("/accounts").text
    assert page.count("unused-hidden") == 3, "the group's heading block and its two accounts"
    client.post("/api/transactions/", json={"postings": [
        {"account": tree["groceries"], "side": "debit", "amount": "5"},
        {"account": tree["hdfc"], "side": "credit", "amount": "5"},
    ]})
    age(session, "Food", "Groceries", "Snacks")
    page = client.get("/accounts").text
    assert 'class="acc-block "' in page and page.count("unused-hidden") == 1, "only Snacks: the group holds an account that was used"


def test_an_account_a_recurring_rule_uses_is_not_hidden(client, tree, session):
    client.post("/api/recurring/", json={
        "from_account": tree["hdfc"], "to_account": tree["rent"], "amount": "10", "start_date": "2999-01-01",
    })
    age(session, "Rent")
    assert "unused-hidden" not in item(client.get("/accounts").text, tree["rent"])


def test_a_group_emptied_by_a_move_leaves_no_empty_tile(client, tree, session):
    """Vehicles holds only Car; Car moves to Valuables. Vehicles is then an unused plain account, and the block it
    shares with other unused plain accounts must hide with it instead of showing an empty line."""
    assets = client.get(f"/api/accounts/{tree['banks']}").json()["parent_id"]
    vehicles = client.post("/api/accounts/", json={"name": "Vehicles", "parent_id": assets}).json()["aid"]
    valuables = client.post("/api/accounts/", json={"name": "Valuables", "parent_id": assets}).json()["aid"]
    car = client.post("/api/accounts/", json={"name": "Car", "parent_id": vehicles, "balance": "900"}).json()["aid"]
    assert client.patch(f"/api/accounts/{car}", json={"parent_id": valuables}).status_code == 200
    age(session, "Vehicles", "Rent", "Valuables", "Car")
    page = client.get("/accounts").text
    assert "unused-hidden" in item(page, vehicles)
    opening = page[:page.index(f'href="/accounts/{vehicles}"')].rsplit('<div class="acc-block', 1)[1].split(">", 1)[0]
    assert "unused-hidden" in opening, "its block is hidden too"
    assert ">Load more</button>" in page


def test_the_page_has_no_note_under_its_list(client, root_accounts):
    page = client.get("/accounts").text
    assert "What it was spent on" not in page and 'class="muted budget-fine' not in page

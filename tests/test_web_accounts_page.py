"""The accounts page: groups that open, what starts open, unused accounts tucked away, net worth."""

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
    food = make("Food", root_accounts["Expenses"])
    ids["food"] = food
    ids["groceries"] = make("Groceries", food)
    ids["snacks"] = make("Snacks", food)
    ids["rent"] = make("Rent", root_accounts["Expenses"])
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


def test_groups_are_rows_that_open_with_their_own_link(client, tree):
    page = client.get("/accounts").text
    assert f'data-key="{tree["banks"]}" open' not in page, "a group starts closed, under every type"
    assert f'data-key="{tree["food"]}" open' not in page, "under Expenses only the top level shows"
    assert f'href="/accounts/{tree["food"]}" title="Open Food"' in page
    assert f'href="/accounts/{tree["hdfc"]}"' in page and "data-account-search" in page and "data-toggle-all" in page


def test_every_type_starts_open_and_there_is_no_net_worth_card(client, tree):
    page = client.get("/accounts").text
    heads = page.split('<details class="account-group"')[1:]
    assert len(heads) == 5 and all(" open>" in h.split(">", 1)[0] + ">" for h in heads), "all five types open"
    assert "Net worth" not in page and "net-worth" not in page


def test_unused_accounts_are_tucked_away_but_new_ones_are_not(client, tree, session):
    page = client.get("/accounts").text
    assert "unused-hidden" not in page and "hidden · Show" not in page, "everything is new"
    age(session, "Old Savings", "Snacks", "Rent")
    page = client.get("/accounts").text
    assert page.count("unused-hidden") == 3
    assert "3 unused accounts hidden · Show" in page
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
    assert "unused-hidden" in item(page, tree["food"])
    client.post("/api/transactions/", json={"postings": [
        {"account": tree["groceries"], "side": "debit", "amount": "5"},
        {"account": tree["hdfc"], "side": "credit", "amount": "5"},
    ]})
    age(session, "Food", "Groceries", "Snacks")
    page = client.get("/accounts").text
    assert "unused-hidden" not in item(page, tree["food"]), "it holds an account that was used"


def test_an_account_a_recurring_rule_uses_is_not_hidden(client, tree, session):
    client.post("/api/recurring/", json={
        "from_account": tree["hdfc"], "to_account": tree["rent"], "amount": "10", "start_date": "2999-01-01",
    })
    age(session, "Rent")
    assert "unused-hidden" not in item(client.get("/accounts").text, tree["rent"])


def test_each_group_shows_how_many_accounts_it_holds(client, tree):
    page = client.get("/accounts").text
    assert '>Food <small class="muted">2</small>' in page and '>Banks <small class="muted">2</small>' in page

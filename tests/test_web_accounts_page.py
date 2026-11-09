"""The accounts page: a row of cards under each kind, closed accounts tucked away."""

import re
from datetime import UTC, date, datetime, timedelta

import pytest

from app.clock import local_today
from app.models.account import Account
from app.templating import short_date

from .books import post_account


@pytest.fixture
def tree(client, root_accounts, session):
    def make(name, parent, **extra):
        return post_account(client, {"name": name, "parent_id": parent, **extra}).json()["id"]

    banks = make("Banks", root_accounts["Assets"])
    ids = {
        "banks": banks,
        "hdfc": make("HDFC", banks, balance="5000"),
        "old": make("Old Savings", banks),
    }
    cards = make("Credit Cards", root_accounts["Liabilities"])
    ids["cards"] = cards
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


def card(page: str, account_id: str) -> str:
    """The card of one account."""
    start = page.rindex("<a ", 0, page.index(f'/accounts/{account_id}"'))
    return page[start : page.index("</a>", start)]


def test_each_kind_is_a_heading_over_a_row_of_cards(client, tree):
    page = client.get("/accounts").text
    heads = re.findall(r'<div class="acc-gh">\s*<span>([^<]+)<', page)
    assert heads == ["Banks", "Credit Cards", "Food", "Other"], heads
    assert f'href="/accounts/{tree["hdfc"]}"' in page and "<details" not in page
    assert page.count("data-rail") == len(heads), "one row of cards per kind"
    assert 'class="mono"' not in page and "account-row" not in page, "cards, not rows"


def test_the_plain_accounts_share_one_other_row_at_the_end(client, tree):
    page = client.get("/accounts").text
    assert re.findall(r'<div class="acc-gh">\s*<span>([^<]+)<', page)[-1] == "Other"
    assert f'href="/accounts/{tree["rent"]}"' in page.split(">Other<", 1)[1]


def test_a_row_ends_with_a_card_that_adds_an_account_of_that_kind(client, tree):
    page = client.get("/accounts").text
    assert f'class="acc-card acc-card-add" href="/accounts/new?parent={tree["banks"]}"' in page
    assert 'class="add-row" href="/accounts/new"' in page, "the page ends with one for a kind that has no row yet"


def test_the_figure_is_the_net_worth_and_credit_cards_read_owed(client, tree):
    page = client.get("/accounts").text
    hero = page.split('cat-hero"', 1)[1].split("</span>\n</div>", 1)[0]
    assert "Net worth" in hero and "4,700.00" in hero, "5,000 owned less 300 owed"
    assert "300.00 owed" in page and "−" not in hero


def test_the_quiet_line_counts_the_open_accounts(client, tree):
    page = client.get("/accounts").text
    line = page.split('hero-note"><span>', 1)[1].split("</span>", 1)[0]
    assert line.endswith((" accounts", " account")), line


def test_every_open_account_shows_even_with_no_entries_and_no_balance(client, tree, session):
    age(session, "Old Savings", "Snacks", "Rent", "Food", "Groceries", "HDFC", "Amex")
    page = client.get("/accounts").text
    assert "unused" not in page and "Load more" not in page, "nothing is tucked away for being quiet"
    assert "closed-hidden" not in page
    for name in ("old", "snacks", "rent", "groceries", "hdfc", "amex"):
        assert f'href="/accounts/{tree[name]}"' in page, name


def test_closed_accounts_wait_behind_load_more(client, tree, session):
    assert client.post(f"/api/accounts/{tree['old']}/close").status_code == 200
    page = client.get("/accounts").text
    assert "closed-hidden" in card(page, tree["old"]) and "closed-hidden" not in card(page, tree["hdfc"])
    assert ">Load more</button>" in page


def test_a_kind_with_only_closed_accounts_hides_whole(client, tree):
    for name in ("groceries", "snacks"):
        assert client.post(f"/api/accounts/{tree[name]}/close").status_code == 200
    page = client.get("/accounts").text
    assert re.search(r'<section class="acc-kind closed-hidden">\s*<div class="acc-gh">\s*<span>Food<', page)
    assert re.search(r'<section class="acc-kind">\s*<div class="acc-gh">\s*<span>Banks<', page)


def test_the_page_has_no_note_under_its_list(client, root_accounts):
    page = client.get("/accounts").text
    assert "What it was spent on" not in page and 'class="muted budget-fine' not in page


def test_categories_end_with_an_add_row_and_an_empty_page_keeps_its_button(client, root_accounts):
    empty = client.get("/categories").text
    assert "Add a category" in empty and 'class="add-row"' not in empty
    post_account(client, {"name": "Dining", "parent_id": root_accounts["Expenses"]})
    page = client.get("/categories?tab=expense").text
    assert 'class="add-row" href="/categories/new?root=expense"' in page and "circ-button" not in page
    assert client.get("/categories?tab=income").text.count('class="add-row"') == 0, (
        "nothing in Income yet: its own button"
    )


def test_accounts_in_the_budget_carry_a_dot_and_the_line_explains_it(client, tree):
    assert "budget-dot" in card(client.get("/accounts").text, tree["hdfc"])
    client.patch(f"/api/accounts/{tree['hdfc']}", json={"on_budget": False})
    html = client.get("/accounts").text
    assert "budget-dot" not in card(html, tree["hdfc"])
    assert "budget-dot" in card(html, tree["rent"])


def test_the_key_shows_only_when_an_account_feeds_the_budget(client, tree, root_accounts):
    assert "budget-key" in client.get("/accounts").text
    for account in client.get("/api/accounts/").json():
        if account["on_budget"]:
            client.patch(f"/api/accounts/{account['id']}", json={"on_budget": False})
    assert "budget-key" not in client.get("/accounts").text


# ---- the quiet line on a card -----------------------------------------------------------------------------------


def transfer(client, source, target, amount, day):
    return client.post(
        "/api/transactions/",
        json={
            "date": day.isoformat(),
            "payee": "move",
            "postings": [
                {"account_id": target, "side": "debit", "amount": amount},
                {"account_id": source, "side": "credit", "amount": amount},
            ],
        },
    )


def test_a_card_says_when_its_last_entry_was_or_that_it_has_none(client, tree):
    day = local_today() - timedelta(days=3)
    assert transfer(client, tree["hdfc"], tree["old"], "10", day).status_code == 201
    page = client.get("/accounts").text
    assert f"Last entry {short_date(day)}" in card(page, tree["old"])
    assert "No entries yet" in card(page, tree["rent"])


def test_an_entry_dated_ahead_is_not_the_last_entry(client, tree):
    ahead = local_today() + timedelta(days=9)
    assert transfer(client, tree["hdfc"], tree["old"], "10", ahead).status_code == 201
    assert "No entries yet" in card(client.get("/accounts").text, tree["old"])


def test_a_credit_card_with_a_bill_says_when_it_is_due(client, tree, root_accounts):
    made = post_account(
        client,
        {"name": "Visa", "parent_id": tree["cards"], "statement_day": 1, "due_day": 20},
    ).json()
    assert transfer(client, made["id"], tree["hdfc"], "700", local_today() - timedelta(days=60)).status_code == 201
    line = card(client.get("/accounts").text, made["id"])
    bill = client.get(f"/api/accounts/{made['id']}/bill").json()
    due = date.fromisoformat(bill["due_date"])
    assert bill["bill"] != "0.00" and (f"Bill due {short_date(due)}" in line or "Bill overdue" in line), line
    assert "Last entry" not in line


def test_a_card_with_nothing_to_pay_says_its_last_entry_instead(client, tree):
    made = post_account(client, {"name": "Visa", "parent_id": tree["cards"], "statement_day": 1, "due_day": 20}).json()
    assert transfer(client, made["id"], tree["hdfc"], "10", local_today()).status_code == 201
    assert "Bill due" not in card(client.get("/accounts").text, made["id"])


def test_the_kinds_come_in_the_pages_order_with_owed_ones_marked(client, monkeypatch):
    from app.services import account as account_service

    from .test_fixed_parents import make

    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)
    make(client, "Home loan", "Loans", balance="900")
    make(client, "Fund", "Investments", balance="400")
    make(client, "Visa", "Credit Cards", balance="50")
    make(client, "Wallet", "Cash", balance="30")
    make(client, "HDFC", "Bank Accounts", balance="10")
    page = client.get("/accounts").text
    heads = re.findall(r'<div class="acc-gh">\s*<span>([^<]+)<', page)
    assert heads == ["Bank Accounts", "Cash", "Credit Cards", "Investments", "Loans"]
    assert "50.00 owed" in page and "900.00 owed" in page and "400.00 owed" not in page

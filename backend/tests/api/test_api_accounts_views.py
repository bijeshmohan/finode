"""/api/views/accounts and /api/views/accounts/{account_id}: what the finode app's Accounts page and an account's page
show, worked out by services/accounts_view.py."""

import itertools
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from finode.clock import local_today
from finode.models.account import Account
from finode.services.accounts_view import STALE_DAYS
from tests.books import leg, post_account
from tests.guards.test_isolation import B_USER, signed_in_as


@pytest.fixture
def tree(client, root_accounts, session):
    """Accounts of every type: two Bank Accounts, a Credit Card, two Prepaid Wallets and a Cash account."""
    roots = {a["name"]: a["id"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None}

    def make(name, kind, **extra):
        made = client.post("/api/accounts/", json={"name": name, "type": kind, **extra})
        assert made.status_code == 201, made.text
        return made.json()["id"]

    ids = {"banks": roots["Assets"], "cards": roots["Liabilities"], "food": roots["Assets"]}
    ids |= {"hdfc": make("HDFC", "assets.bank", balance="5000"), "old": make("Old Savings", "assets.bank")}
    ids["amex"] = make("Amex", "liabilities.cards", balance="300")
    ids["groceries"] = make("Groceries", "assets.wallet")
    ids["snacks"] = make("Snacks", "assets.wallet")
    ids["rent"] = make("Rent", "assets.cash")
    return ids


def age(session, *names, days=30):
    """Make these accounts look made `days` ago."""
    old = datetime.now(UTC) - timedelta(days=days)
    table = Account.__table__
    session.exec(table.update().where(table.c.name.in_(names)).values(created=old))
    session.commit()


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


def view(client, path="/api/views/accounts", **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def cards_of(seen):
    return {c["name"]: c for k in seen["kinds"] for c in k["cards"]}


def running(rows):
    """Each row's running balance is the next (older) one's plus what the row changed."""
    for newer, older in itertools.pairwise(rows):
        change = Decimal(newer["amount"]) * (1 if newer["inflow"] else -1)
        assert Decimal(newer["balance"]) == Decimal(older["balance"]) + change, (newer, older)


def test_the_accounts_page_view(client, session, tree):
    transfer(client, tree["hdfc"], tree["rent"], "100", local_today())
    transfer(client, tree["hdfc"], tree["groceries"], "10", local_today() - timedelta(days=45))
    age(session, "Old Savings", "Snacks", days=40)
    seen = view(client)
    assert [(k["name"], k["type"]) for k in seen["kinds"]] == [
        ("Bank Account", "assets.bank"),
        ("Cash", "assets.cash"),
        ("Credit Card", "liabilities.cards"),
        ("Prepaid Wallet", "assets.wallet"),
    ], "the four types in their starting order"
    banks = seen["kinds"][0]
    assert (banks["total"], banks["owed"], banks["open_count"], banks["add_url"]) == (
        "4890.00",
        False,
        2,
        "/accounts/new?type=assets.bank",
    )
    assert seen["kinds"][2]["owed"] is True
    assert "net_worth" not in seen and "has_budget_accounts" not in seen
    cards = cards_of(seen)
    assert cards["Old Savings"]["note"] == {"kind": "empty", "on": None, "soon": False}
    assert cards["Groceries"]["note"]["kind"] == "stale"
    assert cards["HDFC"]["note"] is None and cards["Rent"]["note"] is None
    assert "on_budget" not in cards["HDFC"], "every account is in the budget: no dot to draw"
    assert seen["account_count"] == 6 and seen["has_closed"] is False


def test_a_cards_bill_is_its_note(client, tree):
    visa = post_account(client, {"name": "Visa", "parent_id": tree["cards"], "statement_day": 1, "due_day": 20}).json()
    transfer(client, visa["id"], tree["hdfc"], "700", local_today() - timedelta(days=60))
    note = cards_of(view(client))["Visa"]["note"]
    assert note["kind"] in ("due", "overdue") and note["soon"] in (True, False)


def test_pinned_never_holds_a_closed_account(client, tree):
    for name in ("hdfc", "old"):
        client.patch(f"/api/accounts/{tree[name]}", json={"pinned": True})
    assert client.post(f"/api/accounts/{tree['old']}/close").status_code == 200
    seen = view(client)
    assert [c["name"] for c in seen["pinned"]] == ["HDFC"]
    assert seen["has_closed"] is True and cards_of(seen)["Old Savings"]["closed"] is True


def test_a_kind_whose_accounts_are_all_closed_says_so(client, tree):
    for name in ("groceries", "snacks"):
        assert client.post(f"/api/accounts/{tree[name]}/close").status_code == 200
    wallets = next(k for k in view(client)["kinds"] if k["name"] == "Prepaid Wallet")
    assert wallets["all_closed"] is True and wallets["open_count"] == 0


def test_an_accounts_page_view(client, tree):
    transfer(client, tree["hdfc"], tree["rent"], "100", local_today())
    transfer(client, tree["rent"], tree["hdfc"], "30", local_today())
    transfer(client, tree["hdfc"], tree["rent"], "5", local_today() + timedelta(days=3))
    seen = view(client, f"/api/views/accounts/{tree['hdfc']}")
    assert (seen["name"], seen["sub"], seen["balance"]) == ("HDFC", "Bank Account", "4930.00")
    assert seen["can_pin"] is True and seen["can_edit"] is True and seen["is_group"] is False
    assert seen["balance_after"] == "4925.00" and [u["amount"] for u in seen["upcoming"]] == ["5.00"]
    rows = seen["entries"]
    assert sorted((r["title"], r["amount"], r["inflow"]) for r in rows) == [
        ("Opening balance", "5000.00", True),
        ("move", "100.00", False),
        ("move", "30.00", True),
    ]
    assert rows[0]["balance"] == "4930.00"
    running(rows)
    assert seen["new_transaction_url"] == f"/transactions/new?account={tree['hdfc']}&back=/accounts/{tree['hdfc']}"


def test_load_more_never_repeats_or_drops_an_entry(client, tree):
    for day in range(70):
        transfer(client, tree["hdfc"], tree["rent"], "1", local_today() - timedelta(days=day // 3))
    seen, ids, offset = [], set(), 0
    while True:
        page = view(client, f"/api/views/accounts/{tree['hdfc']}", offset=offset)
        seen += page["entries"]
        ids |= {r["id"] for r in page["entries"]}
        if not page["has_more"]:
            break
        offset = page["next_offset"]
    assert len(seen) == 71 and len(ids) == 71, "every entry once (the opening balance too)"
    assert seen[0]["balance"] == "4930.00"
    running(seen)


def test_an_accounts_page_says_its_type(client, tree):
    """There are no type pages: an account's own page names its type under its name, and holds no accounts."""
    seen = view(client, f"/api/views/accounts/{tree['hdfc']}")
    assert seen["sub"] == "Bank Account" and seen["is_group"] is False and "add_url" not in seen
    assert view(client, f"/api/views/accounts/{tree['amex']}")["sub"] == "Credit Card"


def test_a_cards_bill_and_the_days_to_set(client, tree):
    plain = post_account(client, {"name": "Card", "parent_id": tree["cards"]}).json()
    assert view(client, f"/api/views/accounts/{plain['id']}")["can_set_days"] is True
    visa = post_account(client, {"name": "Visa", "parent_id": tree["cards"], "statement_day": 1, "due_day": 20}).json()
    transfer(client, visa["id"], tree["hdfc"], "700", local_today() - timedelta(days=60))
    seen = view(client, f"/api/views/accounts/{visa['id']}")
    assert seen["bill"] is not None and seen["bill"]["statement_day"] == 1 and seen["can_set_days"] is False
    assert seen["bill_soon"] is (0 <= seen["bill"]["days_to_due"] <= 5)


def test_another_persons_account_is_not_found(client, tree):
    with signed_in_as(B_USER):
        assert client.get(f"/api/views/accounts/{tree['hdfc']}").status_code == 404
        assert "HDFC" not in client.get("/api/views/accounts").text
    assert client.get("/api/views/accounts/not-a-uuid").status_code == 422


# ---- the account form ---------------------------------------------------------------------------------------------


def form(client, **params):
    return view(client, "/api/views/account-form", **params)


def test_a_new_account_form_by_type(client, tree):
    blank = form(client)
    assert blank["editing"] is False and blank["type"] is None
    assert [(t["key"], t["name"]) for t in blank["types"]] == [
        ("assets.bank", "Bank Account"),
        ("assets.cash", "Cash"),
        ("liabilities.cards", "Credit Card"),
        ("assets.wallet", "Prepaid Wallet"),
    ]
    assert form(client, type="liabilities.cards")["type"] == "liabilities.cards"
    assert form(client, type="liabilities.loans")["type"] is None, "only the four"


def test_an_edit_form(client, tree):
    hdfc = form(client, account_id=tree["hdfc"])
    assert (hdfc["editing"], hdfc["name"], hdfc["balance"], hdfc["type"]) == (True, "HDFC", "5000.00", "assets.bank")
    assert hdfc["types"] == [], "an account keeps its type"
    assert client.get("/api/views/account-form", params={"account_id": tree["banks"]}).status_code == 404


def test_a_strangers_account_form_is_not_found(client, root_accounts, tree):
    with signed_in_as(B_USER):
        assert client.get("/api/views/account-form", params={"account_id": tree["hdfc"]}).status_code == 404
    assert client.get("/api/views/account-form", params={"account_id": root_accounts["Assets"]}).status_code == 404


# Ported from test_web_accounts.py (the old pages), step 10: what reads as money in on an account's page.


def test_a_payment_into_a_card_and_money_into_a_bank_read_as_money_in(client, root_accounts):
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"}).json()
    card = post_account(client, {"name": "Visa", "parent_id": root_accounts["Liabilities"]}).json()
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    for payee, debit, credit, amount in (("Dinner", food, card, "300"), ("Pay the card", card, bank, "100")):
        made = client.post(
            "/api/transactions/",
            json={"payee": payee, "postings": [leg(debit, "debit", amount), leg(credit, "credit", amount)]},
        )
        assert made.status_code == 201, made.text
    on_card = {
        (r["title"], r["amount"]): r["inflow"] for r in view(client, f"/api/views/accounts/{card['id']}")["entries"]
    }
    assert on_card == {("Pay the card", "100.00"): True, ("Dinner", "300.00"): False}, "a payment in, a charge not"
    on_bank = {
        (r["title"], r["amount"]): r["inflow"] for r in view(client, f"/api/views/accounts/{bank['id']}")["entries"]
    }
    assert on_bank == {("Opening balance", "1000.00"): True, ("Pay the card", "100.00"): False}


def test_upcoming_on_a_card_follows_the_same_rule(client, root_accounts):
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"}).json()
    card = post_account(client, {"name": "Visa", "parent_id": root_accounts["Liabilities"], "balance": "500"}).json()
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    later = str(local_today() + timedelta(days=9))
    for payee, debit, credit, amount in (("Later", food, card, "70"), ("Pay later", card, bank, "200")):
        made = client.post(
            "/api/transactions/",
            json={
                "date": later,
                "payee": payee,
                "postings": [leg(debit, "debit", amount), leg(credit, "credit", amount)],
            },
        )
        assert made.status_code == 201, made.text
    upcoming = {u["title"]: u["income"] for u in view(client, f"/api/views/accounts/{card['id']}")["upcoming"]}
    assert upcoming == {"Later": False, "Pay later": True}, "an upcoming charge is plain, a payment in is money in"


# Ported from test_web_accounts_page.py (the old Accounts page), step 10.


def test_a_cards_quiet_line_follows_its_newest_entry_and_ignores_one_dated_ahead(client, tree):
    assert transfer(client, tree["hdfc"], tree["old"], "10", local_today() + timedelta(days=9)).status_code == 201
    assert cards_of(view(client))["Old Savings"]["note"]["kind"] == "empty", "an entry dated ahead is not the last"
    stale = local_today() - timedelta(days=STALE_DAYS + 1)
    assert transfer(client, tree["hdfc"], tree["old"], "10", stale).status_code == 201
    assert cards_of(view(client))["Old Savings"]["note"] == {"kind": "stale", "on": stale.isoformat(), "soon": False}
    recent = local_today() - timedelta(days=STALE_DAYS - 1)
    assert transfer(client, tree["hdfc"], tree["old"], "10", recent).status_code == 201
    assert cards_of(view(client))["Old Savings"]["note"] is None, "the newest entry counts"


def test_a_card_with_nothing_to_pay_says_no_bill(client, tree):
    made = post_account(client, {"name": "Visa", "parent_id": tree["cards"], "statement_day": 1, "due_day": 20}).json()
    assert transfer(client, made["id"], tree["hdfc"], "10", local_today()).status_code == 201
    note = cards_of(view(client))["Visa"]["note"]
    assert note is None or note["kind"] not in ("due", "overdue")

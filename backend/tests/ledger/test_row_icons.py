"""Which icon a row leads with (services/row_icon.py), and every view row that shows an entry or a category carrying it."""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest

from finode.clock import local_today
from finode.services.row_icon import row_icon
from tests.books import leg


@dataclass
class Line:
    account_id: UUID
    category_id: UUID | None = None


EXPENSES, INCOME, BANK, CARD, ASHA, OPENING = (uuid4() for _ in range(6))
FOOD, FEES = uuid4(), uuid4()
ROOTS = {
    EXPENSES: "Expenses",
    INCOME: "Income",
    BANK: "Assets",
    CARD: "Liabilities",
    ASHA: "Assets",
    OPENING: "Equity",
}
ICONS = {FOOD: "utensils", FEES: "receipt"}


def icon(*lines: Line) -> str:
    return row_icon(lines, ROOTS, ICONS, {ASHA}, OPENING)


def test_opening_is_flag():
    assert icon(Line(BANK), Line(OPENING)) == "flag"


def test_one_category_is_its_icon():
    assert icon(Line(EXPENSES, FOOD), Line(BANK)) == "utensils"
    assert icon(Line(EXPENSES, FOOD), Line(EXPENSES, FOOD), Line(CARD)) == "utensils"


def test_two_categories_is_layers():
    assert icon(Line(EXPENSES, FOOD), Line(EXPENSES, FEES), Line(BANK)) == "layers"


def test_category_plus_uncategorised_is_layers():
    assert icon(Line(EXPENSES, FOOD), Line(EXPENSES, None), Line(BANK)) == "layers"


def test_uncategorised_is_circle_dashed():
    assert icon(Line(EXPENSES, None), Line(BANK)) == "circle-dashed"
    assert icon(Line(BANK), Line(INCOME, None)) == "circle-dashed"


def test_shared_bill_shows_the_category():
    assert icon(Line(EXPENSES, FOOD), Line(ASHA), Line(BANK)) == "utensils"


def test_loan_is_user():
    assert icon(Line(ASHA), Line(BANK)) == "user"


def test_transfer_is_arrows():
    assert icon(Line(CARD), Line(BANK)) == "arrow-left-right"


def test_unknown_category_id_is_tag():
    assert icon(Line(EXPENSES, uuid4()), Line(BANK)) == "tag"


# Through the views: each list's rows carry the icon the rule picks.

AHEAD = date(2999, 11, 2)


@pytest.fixture
def books(client, root_accounts):
    """HDFC with an opening balance, Food (utensils), Asha (a contact) lent 300, a card paid from HDFC, a meal."""
    hdfc = client.post("/api/accounts/", json={"name": "HDFC", "type": "assets.bank", "balance": "5000"}).json()
    amex = client.post("/api/accounts/", json={"name": "Amex", "type": "liabilities.cards"}).json()
    food = client.post("/api/categories/", json={"name": "Food", "kind": "spending", "icon": "utensils"}).json()
    asha = client.post("/api/contacts/", json={"name": "Asha"}).json()
    lent = client.post(
        f"/api/contacts/{asha['id']}/transfers",
        json={"direction": "sent", "purpose": "loan", "amount": "300", "account_id": hdfc["id"]},
    )
    assert lent.status_code == 201, lent.text
    for postings, payee in (
        ([leg(amex, "debit", "100"), leg(hdfc, "credit", "100")], "Card bill"),
        (
            [leg({"id": root_accounts["Expenses"]}, "debit", "40", category_id=food["id"]), leg(hdfc, "credit", "40")],
            "Swiggy",
        ),
    ):
        made = client.post("/api/transactions/", json={"payee": payee, "postings": postings})
        assert made.status_code == 201, made.text
    return {"hdfc": hdfc, "food": food, "expenses": root_accounts["Expenses"]}


def _by_title(rows):
    return {r["title"]: r["icon"] for r in rows}


def test_transactions_view_rows_carry_icons(client, books):
    rows = client.get("/api/views/transactions").json()["rows"]
    icons = _by_title(rows)
    assert icons["Swiggy"] == "utensils"
    assert icons["Card bill"] == "arrow-left-right"
    assert "user" in icons.values(), icons
    assert "flag" in icons.values(), icons


def test_upcoming_rows_carry_icons(client, books):
    ahead = local_today() + timedelta(days=3)
    if ahead.month != local_today().month:
        pytest.skip("the upcoming card lists only this month's first page")
    body = {
        "date": str(ahead),
        "payee": "Dinner",
        "postings": [
            leg({"id": books["expenses"]}, "debit", "20", category_id=books["food"]["id"]),
            leg(books["hdfc"], "credit", "20"),
        ],
    }
    assert client.post("/api/transactions/", json=body).status_code == 201
    upcoming = client.get("/api/views/transactions").json()["upcoming"]
    assert _by_title(upcoming)["Dinner"] == "utensils"


def test_closed_category_keeps_its_icon_on_rows(client, books):
    closed = client.post(f"/api/categories/{books['food']['id']}/close")
    assert closed.status_code == 200, closed.text
    assert _by_title(client.get("/api/views/transactions").json()["rows"])["Swiggy"] == "utensils"


def test_account_register_rows_carry_icons(client, books):
    rows = client.get(f"/api/views/accounts/{books['hdfc']['id']}").json()["entries"]
    icons = _by_title(rows)
    assert icons["Swiggy"] == "utensils" and icons["Card bill"] == "arrow-left-right"


def test_coming_up_rows_carry_icons(client, books, monkeypatch):
    monkeypatch.setattr("finode.services.coming_up.local_today", lambda: AHEAD)
    monkeypatch.setattr("finode.services.budget.local_today", lambda: AHEAD)
    body = {
        "date": "2999-11-04",
        "payee": "Feast",
        "postings": [
            leg({"id": books["expenses"]}, "debit", "20", category_id=books["food"]["id"]),
            leg(books["hdfc"], "credit", "20"),
        ],
    }
    assert client.post("/api/transactions/", json=body).status_code == 201
    days = client.get("/api/views/coming-up").json()["days"]
    assert [r["icon"] for d in days for r in d["rows"] if r["title"] == "Feast"] == ["utensils"]


def test_budget_and_categories_rows_carry_icons(client, books):
    lines = client.get("/api/views/budget").json()["rows"]
    assert {r["name"]: r["icon"] for r in lines}["Food"] == "utensils"
    rows = client.get("/api/views/categories").json()["rows"]
    assert {r["name"]: r["icon"] for r in rows}["Food"] == "utensils"
    page = client.get(f"/api/views/categories/{books['food']['id']}").json()
    assert page["icon"] == "utensils"
    assert page["entries"] and all(r["icon"] is None for r in page["entries"])


def test_picker_options_carry_icons(client, books):
    groups = client.get("/api/views/entry-form").json()["groups"]
    options = {o["label"]: o["icon"] for g in groups for o in g["options"]}
    assert options["Food"] == "utensils"
    assert options["HDFC"] is None

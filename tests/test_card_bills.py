"""A card's bill: the calendar arithmetic, the figures worked out from the postings, the two days on the account (create,
change, history, backup, restore), the API route, the assistants' tool and the card's page."""

from datetime import date

import pytest

from app.services import cards

from .books import post_account
from .conftest import TEST_USER_ID
from .mcputil import make_token, mcp_client, payload, running_app
from .svc import services
from .test_transaction_references import body


def test_the_last_statement_is_on_or_before_today():
    assert cards.last_statement(22, date(2026, 11, 1)) == date(2026, 10, 22)
    assert cards.last_statement(22, date(2026, 10, 22)) == date(2026, 10, 22)
    assert cards.last_statement(22, date(2026, 10, 21)) == date(2026, 9, 22)
    assert cards.last_statement(5, date(2026, 1, 3)) == date(2025, 12, 5), "across a year"


def test_day_31_is_the_last_day_of_a_shorter_month():
    assert cards.last_statement(31, date(2026, 3, 15)) == date(2026, 2, 28)
    assert cards.last_statement(31, date(2028, 3, 15)) == date(2028, 2, 29), "leap year"
    assert cards.next_statement(31, date(2026, 1, 31)) == date(2026, 2, 28)
    assert cards.next_statement(30, date(2026, 2, 28)) == date(2026, 3, 30)


def test_the_next_statement_is_after_today():
    assert cards.next_statement(22, date(2026, 11, 1)) == date(2026, 11, 22)
    assert cards.next_statement(22, date(2026, 11, 22)) == date(2026, 12, 22)
    assert cards.next_statement(22, date(2026, 12, 25)) == date(2027, 1, 22)


def test_the_due_day_follows_the_statement():
    assert cards.due_date(date(2026, 10, 22), 22, 15) == date(2026, 11, 15), "earlier in the month: next month"
    assert cards.due_date(date(2026, 10, 5), 5, 25) == date(2026, 10, 25), "later in the month: same month"
    assert cards.due_date(date(2026, 12, 22), 22, 15) == date(2027, 1, 15), "across a year"
    assert cards.due_date(date(2026, 10, 10), 10, 10) == date(2026, 11, 10), "the same day: next month"
    assert cards.due_date(date(2026, 1, 10), 10, 31) == date(2026, 1, 31)
    assert cards.due_date(date(2026, 1, 31), 31, 31) == date(2026, 2, 28), "a short month's last day"


@pytest.fixture
def card(client, root_accounts):
    return post_account(
        client, {"name": "Visa", "parent_id": root_accounts["Liabilities"], "statement_day": 22, "due_day": 15}
    ).json()


def spend(client, expense_account, card, amount, on):
    made = client.post("/api/transactions/", json=body(expense_account, card, amount, on=on))
    assert made.status_code == 201, made.text


def pay(client, card, bank, amount, on):
    made = client.post("/api/transactions/", json=body(card, bank, amount, on=on))
    assert made.status_code == 201, made.text


def test_the_bill_is_the_statement_less_what_was_paid_since(client, session, card, account, expense_account):
    spend(client, expense_account, card, "10000", "2026-10-05")
    spend(client, expense_account, card, "11740", "2026-10-22")  # the statement day itself is on the statement
    spend(client, expense_account, card, "8180", "2026-10-28")  # after it: the next bill
    pay(client, card, account, "3500", "2026-10-30")
    bill = services(session).accounts.bill(card["id"] and __import__("uuid").UUID(card["id"]), date(2026, 11, 1))
    assert (bill.statement_date, bill.due_date, bill.next_statement_date) == (
        date(2026, 10, 22),
        date(2026, 11, 15),
        date(2026, 11, 22),
    )
    assert bill.days_to_due == 14
    assert str(bill.statement_balance) == "21740.00"
    assert str(bill.paid_since) == "3500.00" and str(bill.spent_since) == "8180.00"
    assert str(bill.bill) == "18240.00" and str(bill.owed_total) == "26420.00"


def test_a_paid_statement_is_a_zero_bill_and_never_negative(client, session, card, account, expense_account):
    import uuid

    spend(client, expense_account, card, "500", "2026-10-05")
    pay(client, card, account, "800", "2026-10-25")  # more than the statement
    bill = services(session).accounts.bill(uuid.UUID(card["id"]), date(2026, 11, 1))
    assert str(bill.bill) == "0.00" and str(bill.statement_balance) == "500.00"
    assert str(bill.owed_total) == "0.00", "a card in credit owes nothing"


def test_dated_ahead_is_not_counted_yet(client, session, card, expense_account):
    import uuid

    spend(client, expense_account, card, "500", "2026-10-05")
    spend(client, expense_account, card, "900", "2026-11-20")
    bill = services(session).accounts.bill(uuid.UUID(card["id"]), date(2026, 11, 1))
    assert str(bill.bill) == "500.00" and str(bill.spent_since) == "0.00"


def test_the_api_route(client, card, expense_account):
    spend(client, expense_account, card, "700", "2026-01-05")
    got = client.get(f"/api/accounts/{card['id']}/bill")
    assert got.status_code == 200, got.text
    assert {"bill", "due_date", "statement_balance", "days_to_due"} <= set(got.json())


def test_the_route_says_when_the_days_are_missing_or_the_account_is_not_there(client, root_accounts, account):
    plain = post_account(client, {"name": "Loan", "parent_id": root_accounts["Liabilities"]}).json()
    assert client.get(f"/api/accounts/{plain['id']}/bill").status_code == 400
    assert client.get("/api/accounts/00000000-0000-4000-8000-0000000000aa/bill").status_code == 404


def test_days_come_as_a_pair_inside_one_to_thirty_one(client, root_accounts):
    parent = root_accounts["Liabilities"]
    for extra in (
        {"statement_day": 22},
        {"due_day": 15},
        {"statement_day": 0, "due_day": 15},
        {"statement_day": 22, "due_day": 32},
    ):
        assert client.post("/api/accounts/", json={"name": "X", "parent_id": parent, **extra}).status_code == 422, extra


def test_only_a_liability_without_sub_accounts_takes_days(client, root_accounts):
    response = client.post(
        "/api/accounts/",
        json={"name": "Bank", "parent_id": root_accounts["Assets"], "statement_day": 1, "due_day": 5},
    )
    assert response.status_code == 400 and "card or loan" in response.text
    group = post_account(client, {"name": "Cards", "parent_id": root_accounts["Liabilities"]}).json()
    post_account(client, {"name": "Amex", "parent_id": group["id"]})
    changed = client.patch(f"/api/accounts/{group['id']}", json={"statement_day": 1, "due_day": 5})
    assert changed.status_code == 400


def test_days_are_changed_and_cleared_and_the_history_says_so(client, card):
    changed = client.patch(f"/api/accounts/{card['id']}", json={"statement_day": 25, "due_day": 18})
    assert changed.status_code == 200 and (changed.json()["statement_day"], changed.json()["due_day"]) == (25, 18)
    one = client.patch(f"/api/accounts/{card['id']}", json={"statement_day": 3})
    assert one.status_code == 200 and (one.json()["statement_day"], one.json()["due_day"]) == (3, 18), "the other stays"
    assert client.patch(f"/api/accounts/{card['id']}", json={"due_day": None}).status_code == 400, (
        "not just one cleared"
    )
    client.patch(f"/api/accounts/{card['id']}", json={"statement_day": 25})
    steps = client.get(f"/api/accounts/{card['id']}/changes").json()
    assert steps[-1]["changes"]["statement_day"] == {"from": 3, "to": 25}
    cleared = client.patch(f"/api/accounts/{card['id']}", json={"statement_day": None, "due_day": None})
    assert cleared.status_code == 200 and cleared.json()["statement_day"] is None


@pytest.mark.anyio
async def test_assistants_read_a_bill_and_set_the_days(session, client, root_accounts, expense_account):
    visa = post_account(client, {"name": "Visa", "parent_id": root_accounts["Liabilities"]}).json()
    spend(client, expense_account, visa, "400", "2026-01-05")
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="manage")) as c:
        updated = payload(await c.call_tool("update_account", {"account": "Visa", "statement_day": 22, "due_day": 15}))
        assert updated["updated"]["statement_day"] == 22 and updated["updated"]["due_day"] == 15
        bill = payload(await c.call_tool("get_card_bill", {"account": "Visa"}))
        assert bill["bill"] == "400.00" and bill["account"] == "Liabilities:Visa"
    assert visa["id"]


def test_the_cards_page_shows_the_bill_and_a_pay_button(client, card, account, expense_account):
    spend(client, expense_account, card, "700", "2026-01-05")
    page = client.get(f"/accounts/{card['id']}").text
    assert 'aria-label="Bill"' in page and "700.00" in page
    assert f"/transactions/new?pay={card['id']}&amp;amount=700.00" in page or f"?pay={card['id']}&amount=700.00" in page


def test_a_card_without_days_offers_to_add_them(client, root_accounts):
    plain = post_account(client, {"name": "Axis", "parent_id": root_accounts["Liabilities"]}).json()
    page = client.get(f"/accounts/{plain['id']}").text
    assert "Add the days" in page and f"/accounts/{plain['id']}/edit" in page
    assert (
        "Add the days"
        not in client.get(
            f"/accounts/{post_account(client, {'name': 'Cash2', 'parent_id': root_accounts['Assets']}).json()['id']}"
        ).text
    )


def test_pay_bill_opens_the_form_with_the_card_and_the_amount_and_no_account_to_pay_from(client, card):
    page = client.get("/transactions/new", params={"pay": card["id"], "amount": "18240.00"}).text
    assert 'value="18240.00"' in page
    assert (
        f'<option value="{card["id"]}"' in page
        and f'value="{card["id"]}" data-budget="0" data-balance="0.00" selected' in page
    )


def test_the_account_form_takes_the_days_for_a_liability(client, root_accounts):
    made = client.post(
        "/accounts",
        data={
            "name": "Rupay",
            "parent_id": root_accounts["Liabilities"],
            "bill_choice": "1",
            "statement_day": "10",
            "due_day": "28",
        },
    )
    assert made.status_code == 200, made.text
    card = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Rupay")
    assert (card["statement_day"], card["due_day"]) == (10, 28)
    bad = client.post(
        "/accounts",
        data={"name": "Rupay2", "parent_id": root_accounts["Liabilities"], "bill_choice": "1", "statement_day": "10"},
    )
    assert "both the statement day and the due day" in bad.text
    again = client.post(
        f"/accounts/{card['id']}/edit",
        data={"name": "Rupay", "bill_choice": "1", "statement_day": "", "due_day": ""},
    )
    assert again.status_code == 200
    assert next(a for a in client.get("/api/accounts/").json() if a["name"] == "Rupay")["statement_day"] is None

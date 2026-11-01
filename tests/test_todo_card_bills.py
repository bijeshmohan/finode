"""A card bill that is due soon or overdue is a to-do (the bell) until it is paid; nothing is stored."""

from datetime import timedelta

import pytest

from app.clock import local_today

from .books import post_account
from .test_transaction_references import body


def card_with_bill(client, root_accounts, expense_account, due_in, amount="1250"):
    """A card whose statement closed 10 days ago on `amount` and which is due `due_in` days from today."""
    today = local_today()
    statement = today - timedelta(days=10)
    made = post_account(
        client,
        {
            "name": "Visa",
            "parent_id": root_accounts["Liabilities"],
            "statement_day": statement.day,
            "due_day": (today + timedelta(days=due_in)).day,
        },
    ).json()
    on = (statement - timedelta(days=5)).isoformat()
    assert client.post("/api/transactions/", json=body(expense_account, made, amount, on=on)).status_code == 201
    return made


def bills(client):
    return client.get("/api/todo/").json()


def test_a_bill_due_in_a_few_days_is_a_to_do(client, root_accounts, expense_account):
    card = card_with_bill(client, root_accounts, expense_account, due_in=2)
    todo = bills(client)
    assert todo["count"] == 1 and len(todo["card_bills"]) == 1
    item = todo["card_bills"][0]
    assert (item["account_id"], item["bill"], item["days_to_due"]) == (card["id"], "1250.00", 2)
    sheet = client.get("/todo/sheet").text
    assert "Visa bill is due in 2 days" in sheet and "Pay bill" in sheet
    assert (
        f"/transactions/new?pay={card['id']}&amp;amount=1250.00" in sheet
        or f"?pay={card['id']}&amount=1250.00" in sheet
    )


def test_a_bill_due_later_is_not_yet(client, root_accounts, expense_account):
    card_with_bill(client, root_accounts, expense_account, due_in=12)
    assert bills(client)["card_bills"] == []
    assert bills(client)["count"] == 0


def test_an_overdue_bill_says_how_late(client, root_accounts, expense_account):
    card_with_bill(client, root_accounts, expense_account, due_in=-2)
    item = bills(client)["card_bills"][0]
    assert item["days_to_due"] == -2
    assert "Visa bill is overdue by 2 days" in client.get("/todo/sheet").text


def test_a_paid_bill_goes_from_the_list(client, root_accounts, expense_account, account):
    card = card_with_bill(client, root_accounts, expense_account, due_in=1)
    assert bills(client)["count"] == 1
    paid = client.post("/api/transactions/", json=body(card, account, "1250", on=local_today().isoformat()))
    assert paid.status_code == 201
    assert bills(client)["card_bills"] == []
    assert "bill is" not in client.get("/todo/sheet").text


def test_a_closed_card_and_a_card_without_days_are_never_reminded(client, root_accounts, expense_account):
    card = card_with_bill(client, root_accounts, expense_account, due_in=1)
    client.patch(f"/api/accounts/{card['id']}", json={"statement_day": None, "due_day": None})
    assert bills(client)["card_bills"] == []


@pytest.mark.parametrize("due_in", [5, 6])
def test_the_reminder_starts_five_days_before(client, root_accounts, expense_account, due_in):
    card_with_bill(client, root_accounts, expense_account, due_in=due_in)
    assert len(bills(client)["card_bills"]) == (1 if due_in == 5 else 0)

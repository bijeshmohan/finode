"""A line's posting date (when a card posts it, if not on the entry's own day) and a card's bill rounding."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.services import cards

from .books import post_account
from .conftest import TEST_USER_ID
from .mcputil import make_token, mcp_client, payload, running_app
from .svc import services
from .test_transaction_references import body


@pytest.fixture
def card(client, root_accounts):
    return post_account(
        client, {"name": "Regalia", "parent_id": root_accounts["Liabilities"], "statement_day": 16, "due_day": 5}
    ).json()


def buy(client, expense_account, card, amount, on, posted_on=None):
    data = body(expense_account, card, amount, on=on)
    if posted_on:
        data["postings"][1]["posted_on"] = posted_on
    made = client.post("/api/transactions/", json=data)
    assert made.status_code == 201, made.text
    return made.json()


def bill(session, card, today):
    return services(session).accounts.bill(uuid.UUID(card["id"]), today)


def test_a_posting_date_is_stored_and_read_back(client, card, expense_account):
    made = buy(client, expense_account, card, "180", "2026-10-16", posted_on="2026-10-18")
    lines = {p["account_id"]: p for p in made["postings"]}
    assert lines[card["id"]]["posted_on"] == "2026-10-18"
    assert client.get(f"/api/transactions/{made['id']}").json()["postings"]
    other = next(p for p in made["postings"] if p["account_id"] != card["id"])
    assert other["posted_on"] is None


def test_a_line_cannot_post_before_the_entry(client, card, expense_account):
    data = body(expense_account, card, "180", on="2026-10-16")
    data["postings"][1]["posted_on"] = "2026-10-15"
    refused = client.post("/api/transactions/", json=data)
    assert refused.status_code == 400 and "before the entry's own date" in refused.text


def test_moving_the_date_past_a_posting_date_is_refused(client, card, expense_account):
    made = buy(client, expense_account, card, "180", "2026-10-16", posted_on="2026-10-18")
    refused = client.patch(f"/api/transactions/{made['id']}", json={"date": "2026-10-20"})
    assert refused.status_code == 400
    assert client.patch(f"/api/transactions/{made['id']}", json={"date": "2026-10-17"}).status_code == 200


def test_the_bill_counts_a_line_by_the_day_the_card_posts_it(client, session, card, expense_account):
    buy(client, expense_account, card, "1000", "2026-10-10")
    igst = buy(client, expense_account, card, "180", "2026-10-16")
    today = date(2026, 10, 25)
    assert str(bill(session, card, today).statement_balance) == "1180.00", "on the statement day: in this bill"
    client.patch(
        f"/api/transactions/{igst['id']}",
        json={
            "postings": [
                {
                    "account_id": p["account_id"],
                    "side": p["side"],
                    "amount": p["amount"],
                    **({"posted_on": "2026-10-17"} if p["account_id"] == card["id"] else {}),
                }
                for p in igst["postings"]
            ]
        },
    )
    after = bill(session, card, today)
    assert str(after.statement_balance) == "1000.00" and str(after.spent_since) == "180.00"
    assert str(after.owed_total) == "1180.00", "what is owed today does not change"
    next_month = bill(session, card, date(2026, 11, 17))
    assert str(next_month.statement_balance) == "1180.00", "it lands in the next bill"


def test_editing_keeps_the_posting_date_and_history_says_when_it_changes(client, card, expense_account):
    made = buy(client, expense_account, card, "180", "2026-10-16", posted_on="2026-10-18")
    lines = [
        {"account_id": p["account_id"], "side": p["side"], "amount": p["amount"], "posted_on": p["posted_on"]}
        for p in made["postings"]
    ]
    same = client.patch(f"/api/transactions/{made['id']}", json={"payee": "IGST", "postings": lines})
    assert same.status_code == 200
    assert {p["posted_on"] for p in same.json()["postings"]} == {None, "2026-10-18"}
    for line in lines:
        if line["account_id"] == card["id"]:
            line["posted_on"] = "2026-10-20"
    assert client.patch(f"/api/transactions/{made['id']}", json={"postings": lines}).status_code == 200
    steps = client.get(f"/api/transactions/{made['id']}/changes").json()
    assert steps[-1]["changes"]["posting_dates"]["to"][0]["posted_on"] == "2026-10-20"


def test_a_restored_entry_keeps_its_posting_date(client, card, expense_account):
    made = buy(client, expense_account, card, "180", "2026-10-16", posted_on="2026-10-18")
    assert client.delete(f"/api/transactions/{made['id']}").status_code in (200, 204)
    deleted = client.get("/api/transactions/deleted").json()[0]
    restored = client.post(f"/api/transactions/deleted/{deleted['id']}/restore")
    assert restored.status_code == 200, restored.text
    assert "2026-10-18" in {p["posted_on"] for p in restored.json()["postings"]}


@pytest.mark.parametrize(
    ("rule", "owed", "due"),
    [
        ("none", "18240.37", "18240.37"),
        ("nearest", "18240.37", "18240.00"),
        ("nearest", "18240.50", "18241.00"),
        ("up", "18240.01", "18241.00"),
        ("up", "18240.00", "18240.00"),
    ],
)
def test_the_rounding_rule(rule, owed, due):
    assert cards.round_bill(Decimal(owed), rule) == Decimal(due)


def test_a_rounded_bill_is_paid_by_paying_it(client, session, card, account, expense_account):
    client.patch(f"/api/accounts/{card['id']}", json={"bill_rounding": "nearest"})
    buy(client, expense_account, card, "18240.37", "2026-10-10")
    first = bill(session, card, date(2026, 10, 25))
    assert (str(first.statement_balance), str(first.statement_due), str(first.rounded_by)) == (
        "18240.37",
        "18240.00",
        "-0.37",
    )
    assert str(first.bill) == "18240.00"
    paid = client.post("/api/transactions/", json=body(card, account, "18240", on="2026-10-26"))
    assert paid.status_code == 201
    assert str(bill(session, card, date(2026, 10, 27)).bill) == "0.00"


def test_the_rule_is_checked_and_shows_in_the_history(client, card):
    assert client.patch(f"/api/accounts/{card['id']}", json={"bill_rounding": "sometimes"}).status_code == 422
    assert client.patch(f"/api/accounts/{card['id']}", json={"bill_rounding": "up"}).json()["bill_rounding"] == "up"
    steps = client.get(f"/api/accounts/{card['id']}/changes").json()
    assert steps[-1]["changes"]["bill_rounding"] == {"from": "none", "to": "up"}


def test_the_card_page_shows_when_a_line_posts_and_the_rounding(client, card, expense_account):
    client.patch(f"/api/accounts/{card['id']}", json={"bill_rounding": "nearest"})
    buy(client, expense_account, card, "100.40", "2026-01-10")
    buy(client, expense_account, card, "180", "2026-10-16", posted_on="2026-10-18")
    page = client.get(f"/accounts/{card['id']}").text
    assert "Posts 18 Oct" in page
    assert ">Rounded<" in page and "−0.40" in page


def test_a_backup_carries_posting_dates_and_the_rule(client, card, expense_account):
    client.patch(f"/api/accounts/{card['id']}", json={"bill_rounding": "up"})
    buy(client, expense_account, card, "180", "2026-10-16", posted_on="2026-10-18")
    file = client.get("/api/backup").json()
    assert next(a for a in file["accounts"] if a["name"] == "Regalia")["bill_rounding"] == "up"
    assert any(p["posted_on"] == "2026-10-18" for t in file["transactions"] for p in t["postings"])


@pytest.mark.anyio
async def test_assistants_set_a_posting_date_and_read_the_rounding(session, client, root_accounts, expense_account):
    post_account(
        client,
        {
            "name": "Visa",
            "parent_id": root_accounts["Liabilities"],
            "statement_day": 16,
            "due_day": 5,
            "bill_rounding": "nearest",
        },
    )
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="write")) as c:
        made = payload(
            await c.call_tool(
                "record_split",
                {
                    "date": "2026-10-16",
                    "postings": [
                        {"category": expense_account["name"], "side": "debit", "amount": "180.60"},
                        {"account": "Visa", "side": "credit", "amount": "180.60", "posted_on": "2026-10-18"},
                    ],
                },
            )
        )
        lines = made["recorded"]["postings"]
        assert any(line.get("posted_on") == "2026-10-18" for line in lines)
        bill = payload(await c.call_tool("get_card_bill", {"account": "Visa"}))
    assert "statement_due" in bill and "rounded_by" in bill


def test_a_journal_carries_posting_dates_out_and_back(client, session, card, expense_account):
    buy(client, expense_account, card, "180", "2026-10-16", posted_on="2026-10-18")
    text = client.get("/api/export").text
    assert "posted: 2026-10-18" in text
    from app.ledger.parse import parse

    posted = [p.posted for t in parse(text).transactions for p in t.postings if p.posted]
    assert posted == [date(2026, 10, 18)]

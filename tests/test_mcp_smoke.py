"""Every read-only assistant tool, called against a ledger that uses every feature (cards in the budget, loans outside it,
people, shared bills, split entries, tags, a recurring rule, a plan for last month and this one).

A tool's answer is built from many branches that only run when the books have the matching thing (a card, a loan, a
contact). A rename that misses one of them fails there, so this test runs them all and fails for a read tool it has no
call for: a new one has to be added here."""

from datetime import date, timedelta

import pytest

from .books import category, leg, post_account
from .conftest import TEST_USER_ID
from .mcputil import make_token, mcp_client, payload, running_app

pytestmark = pytest.mark.anyio

TODAY = date.today()
THIS_MONTH = TODAY.replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


def made(client, name, parent, **extra):
    response = post_account(client, {"name": name, "parent_id": parent, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def entry(client, *lines, **extra):
    response = client.post("/api/transactions/", json={"postings": list(lines), **extra})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def ledger(client, root_accounts):
    bank = made(client, "HDFC", root_accounts["Assets"], balance="90000")
    fund = made(client, "Fund", root_accounts["Assets"], balance="20000", on_budget=False)
    card = made(client, "Visa", root_accounts["Liabilities"], on_budget=True, statement_day=5, due_day=25)
    loan = made(
        client, "Car loan", root_accounts["Liabilities"], balance="40000", on_budget=False, statement_day=1, due_day=10
    )
    food = category(client, "Food")
    groceries = category(client, "Groceries", parent=food)
    dining = category(client, "Dining")
    salary = category(client, "Salary", kind="earning")
    rent = category(client, "Rent", kind="earning")
    alice = client.post("/api/contacts/", json={"name": "Alice"}).json()
    earlier = (TODAY - timedelta(days=3)).isoformat()
    entry(client, leg(bank, "debit", "50000"), leg(salary, "credit", "50000"), date=earlier, payee="Acme", tags=["pay"])
    entry(client, leg(groceries, "debit", "1200"), leg(card, "credit", "1200"), date=earlier, payee="BigBasket")
    entry(
        client,
        leg(groceries, "debit", "300"),
        leg(dining, "debit", "200"),
        leg(bank, "credit", "500"),
        date=earlier,
        payee="Market",
    )
    entry(client, leg(card, "debit", "700"), leg(bank, "credit", "700"), date=earlier, payee="Visa payment")
    entry(client, leg(loan, "debit", "2000"), leg(bank, "credit", "2000"), date=earlier, payee="EMI")
    for month in (LAST_MONTH, THIS_MONTH):
        for item, amount in ((groceries, "3000"), (dining, "1500")):
            assert (
                client.put(
                    f"/api/budget/categories/{item['id']}", json={"month": month.isoformat(), "amount": amount}
                ).status_code
                == 200
            )
    loaned = client.post(
        f"/api/contacts/{alice['id']}/transfers",
        json={"direction": "sent", "purpose": "loan", "amount": "5000", "account_id": bank["id"]},
    )
    assert loaned.status_code == 201, loaned.text
    shared = client.post(
        "/api/shared-expenses/",
        params={"confirm": True},
        json={
            "description": "Dinner",
            "total_amount": "900",
            "category_id": dining["id"],
            "participants": [{"is_self": True}, {"contact_id": alice["id"]}],
            "payments": [{"account_id": bank["id"], "amount": "900"}],
        },
    )
    assert shared.status_code == 201, shared.text
    rented = client.post(
        "/api/shared-incomes/",
        json={
            "description": "Rent, Flat 4B",
            "total_amount": "1000",
            "category_id": rent["id"],
            "theirs": [{"contact_id": alice["id"], "amount": "400"}],
            "deposits": [{"account_id": bank["id"], "amount": "1000"}],
        },
    )
    assert rented.status_code == 201, rented.text
    rule = client.post(
        "/api/recurring/",
        json={
            "postings": [leg(groceries, "debit", "60"), leg(dining, "debit", "40"), leg(bank, "credit", "100")],
            "frequency": "weekly",
            "start_date": (TODAY + timedelta(days=30)).isoformat(),
            "payee": "Split rule",
        },
    )
    assert rule.status_code == 201, rule.text
    return {"bank": bank, "fund": fund, "card": card, "loan": loan, "alice": alice, "entry": rented.json()}


async def test_every_read_only_tool_answers_on_a_ledger_that_uses_every_feature(session, ledger):
    bank, card, loan = ledger["bank"], ledger["card"], ledger["loan"]
    calls: dict[str, list[dict]] = {
        "get_status": [{}],
        "get_overview": [{}],
        "list_accounts": [{}, {"include_closed": True}, {"type": "Liabilities"}],
        "get_account": [{"account": a["id"], "recent": 5} for a in (bank, ledger["fund"], card, loan)],
        "search_transactions": [{}, {"tag": "pay"}, {"text_contains": "Dinner"}, {"account": card["id"]}],
        "get_transaction": [{"transaction_id": ledger["entry"]["transaction_id"]}],
        "list_tags": [{}],
        "list_categories": [{}, {"kind": "earning"}],
        "payee_defaults": [{"payee": "BigBasket"}],
        "check_balance": [
            {"account": bank["id"], "statement_balance": "1"},
            {"account": card["id"], "statement_balance": "1"},
        ],
        "get_card_bill": [{"account": card["id"]}, {"account": loan["id"]}],
        "spending_breakdown": [{}, {"kind": "income"}],
        "list_recurring": [{}],
        "check_books": [{}],
        "get_budget": [{}, {"month": THIS_MONTH.strftime("%Y-%m")}, {"month": LAST_MONTH.strftime("%Y-%m")}],
    }
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="read")) as c:
        read_only = {t.name for t in (await c.list_tools()).tools if t.annotations and t.annotations.read_only_hint}
        assert read_only == set(calls), "a read-only tool without a call here (or a call for a tool that is gone)"
        for name, argument_sets in calls.items():
            for arguments in argument_sets:
                try:
                    answer = payload(await c.call_tool(name, arguments))
                except Exception as e:  # report which tool and arguments, whatever went wrong
                    raise AssertionError(f"{name} {arguments}: {e}") from e
                assert answer is not None, name
        budget = payload(await c.call_tool("get_budget", {}))
        assert budget["credit_cards"] and budget["categories"], "the budget used the card and the categories"

"""Setting a statement's balance against the books: the difference and the entries that could explain it."""

from datetime import date, timedelta

import pytest

from .conftest import TEST_USER_ID
from .mcputil import make_token, mcp_client, payload, running_app
from .test_transaction_references import body

TODAY = date.today()


def day(back):
    return (TODAY - timedelta(days=back)).isoformat()


@pytest.fixture
def books(client, root_accounts, expense_account, income_account):
    bank = client.post("/api/accounts/", json={"name": "HDFC", "parent_id": root_accounts["Assets"]}).json()
    client.post("/api/transactions/", json=body(bank, income_account, "1000", on=day(40), payee="Pay"))
    for back, amount in ((30, "5"), (6, "40"), (2, "75")):
        client.post("/api/transactions/", json=body(expense_account, bank, amount, on=day(back), payee=f"p{amount}"))
    return bank


def test_matching_statement(client, books):
    check = client.get(f"/api/accounts/{books['aid']}/check-balance", params={"statement_balance": "880"}).json()
    assert check["matches"] is True and check["difference"] == "0.00" and check["book_balance"] == "880.00"
    assert check["path"] == "Assets:HDFC"
    assert [e["change"] for e in check["recent"]] == ["-40.00", "-75.00"], "only the last 14 days"


def test_a_difference_points_at_the_entry_of_that_size(client, books):
    check = client.get(f"/api/accounts/{books['aid']}/check-balance", params={"statement_balance": "920"}).json()
    assert check["matches"] is False and check["difference"] == "40.00"
    assert [e["payee"] for e in check["same_size_as_difference"]] == ["p40"]


def test_as_of_and_days(client, books):
    params = {"statement_balance": "955", "as_of": day(3), "days": 30}
    check = client.get(f"/api/accounts/{books['aid']}/check-balance", params=params).json()
    assert check["matches"] is True and check["book_balance"] == "955.00"
    assert [e["change"] for e in check["recent"]] == ["-5.00", "-40.00"]
    assert client.get(f"/api/accounts/{books['aid']}/check-balance").status_code == 422


def test_unknown_account(client):
    missing = "00000000-0000-4000-8000-000000000000"
    assert client.get(f"/api/accounts/{missing}/check-balance", params={"statement_balance": "1"}).status_code == 404


@pytest.mark.anyio
async def test_assistants_can_check_a_statement(session, books):
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="read")) as c:
        ok = payload(await c.call_tool("check_balance", {"account": "HDFC", "statement_balance": "880"}))
        assert ok["matches"] is True and ok["account"] == "Assets:HDFC"
        off = payload(await c.call_tool("check_balance", {"account": books["aid"], "statement_balance": "805"}))
        assert off["difference"] == "-75.00" and off["same_size_as_difference"][0]["change"] == "-75.00"
        assert off["matches"] is False

"""The MCP tools, called over HTTP through /mcp like a real assistant would."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app


pytestmark = pytest.mark.anyio

TODAY = date.today()


def make(client, name, parent, commodity=None, **extra):
    body = {"name": name, "parent_id": parent, **extra}
    if commodity:
        body["commodity"] = commodity
    response = client.post("/accounts/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def books(client, root_accounts):
    """A small set of books: a bank with money, a card, food under two parents, salary."""
    bank_group = make(client, "Bank", root_accounts["Assets"])
    hdfc = make(client, "HDFC", bank_group["aid"], balance="10000")
    card = make(client, "Card", root_accounts["Liabilities"])
    food = make(client, "Food", root_accounts["Expenses"])
    groceries = make(client, "Groceries", food["aid"])
    travel = make(client, "Travel", root_accounts["Expenses"])
    travel_food = make(client, "Food", travel["aid"])
    salary = make(client, "Salary", root_accounts["Income"])
    wise = make(client, "Wise", root_accounts["Assets"], "USD")
    return {
        "hdfc": hdfc, "card": card, "food": food, "groceries": groceries, "travel_food": travel_food,
        "salary": salary, "wise": wise, "bank": bank_group,
    }


async def call(client, tool, /, **arguments):
    return payload(await client.call_tool(tool, arguments))


@pytest.fixture
def secret(session):
    return make_token(session, TEST_USER_ID, name="Claude")


# ---- reading ---------------------------------------------------------------------------------------


async def test_overview_and_accounts(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        overview = await call(c, "get_overview")
        assert overview["currency"] == "INR" and overview["net_worth"] == "10000.00"
        accounts = await call(c, "list_accounts")
        paths = {a["path"]: a for a in accounts["accounts"]}
        assert paths["Assets:Bank:HDFC"]["balance"] == "10000.00"
        assert paths["Assets:Bank"]["can_post"] is False, "an asset group takes no postings"
        assert paths["Expenses:Food"]["can_post"] is True, "an expense group does"
        assert paths["Assets:Wise"]["holds"] == "USD"
        only = await call(c, "list_accounts", type="Income")
        assert [a["path"] for a in only["accounts"]] == ["Income", "Income:Salary"]


async def test_record_by_short_names_and_read_it_back(session, client, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        recorded = (await call(c, "record_transaction", amount="450", from_account="HDFC", to_account="Groceries", payee="DMart"))["recorded"]
        assert recorded["total"] == "450.00" and recorded["payee"] == "DMart"
        assert {(p["account"], p["side"]) for p in recorded["postings"]} == {
            ("Expenses:Food:Groceries", "debit"),
            ("Assets:Bank:HDFC", "credit"),
        }
        assert recorded["created_via"] == "assistant (Claude)"
        account = await call(c, "get_account", account="Assets:Bank:HDFC")
        assert account["balance"] == "9550.00" and account["recent"][0]["payee"] == "DMart"

    stored = client.get(f"/transactions/{recorded['id']}").json()
    assert stored["created_via"] == "mcp:Claude" and stored["updated_via"] == "mcp:Claude"


async def test_ambiguous_and_unknown_accounts_are_explained(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        with pytest.raises(ToolFailed, match="matches 2 accounts: Expenses:Food, Expenses:Travel:Food"):
            await call(c, "record_transaction", amount="10", from_account="HDFC", to_account="Food")
        with pytest.raises(ToolFailed, match="Did you mean .*Groceries"):
            await call(c, "record_transaction", amount="10", from_account="HDFC", to_account="Grocries")
        # the full path, the end of one and other separators all work
        for name in ("Expenses:Travel:Food", "Travel:Food", "expenses › travel › food", "Expense:Food"):
            await call(c, "record_transaction", amount="1", from_account="HDFC", to_account=name)


async def test_ledger_rules_still_apply(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        with pytest.raises(ToolFailed, match="sub-accounts"):
            await call(c, "record_transaction", amount="10", from_account="Assets:Bank", to_account="Groceries")
        with pytest.raises(ToolFailed, match="top-level"):
            await call(c, "record_transaction", amount="10", from_account="HDFC", to_account="Expenses")
        with pytest.raises(ToolFailed, match="say how much USD arrives"):
            await call(c, "record_transaction", amount="8350", from_account="HDFC", to_account="Wise")
        with pytest.raises(ToolFailed, match="balance"):
            await call(
                c,
                "record_split",
                postings=[
                    {"account": "Groceries", "side": "debit", "amount": "100"},
                    {"account": "HDFC", "side": "credit", "amount": "90"},
                ],
            )
        with pytest.raises(ToolFailed):
            await call(c, "record_transaction", amount="-5", from_account="HDFC", to_account="Groceries")


async def test_conversion_and_holding_value(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        recorded = (
            await call(c, "record_transaction", amount="8350", from_account="HDFC", to_account="Wise", received_amount="100")
        )["recorded"]
        assert recorded["currency"] == "INR"
        wise = next(p for p in recorded["postings"] if p["account"] == "Assets:Wise")
        assert (wise["amount"], wise["commodity"], wise["value"]) == ("100.00", "USD", "8350.00")
        holding = (await call(c, "get_account", account="Wise"))["holding"]
        assert holding["invested"] == "8350.00" and holding["rate"] == "83.50"
        prices = await call(c, "get_prices")
        assert prices["rates_today"] == [{"commodity": "USD", "rate": "83.50", "as_of": TODAY.isoformat()}]


async def test_split_update_and_delete(session, client, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        split = (
            await call(
                c,
                "record_split",
                payee="Supermarket",
                date=(TODAY - timedelta(days=1)).isoformat(),
                postings=[
                    {"account": "Groceries", "side": "debit", "amount": "300"},
                    {"account": "Expenses:Travel:Food", "side": "debit", "amount": "200"},
                    {"account": "Card", "side": "credit", "amount": "500"},
                ],
            )
        )["recorded"]
        assert split["total"] == "500.00" and len(split["postings"]) == 3

        updated = (await call(c, "update_transaction", transaction_id=split["id"], payee="BigBasket", note=""))["updated"]
        assert updated["payee"] == "BigBasket" and len(updated["postings"]) == 3, "postings are kept"
        updated = (
            await call(
                c,
                "update_transaction",
                transaction_id=split["id"],
                postings=[
                    {"account": "Groceries", "side": "debit", "amount": "550"},
                    {"account": "Card", "side": "credit", "amount": "550"},
                ],
            )
        )["updated"]
        assert updated["total"] == "550.00" and len(updated["postings"]) == 2
        with pytest.raises(ToolFailed, match="nothing to change"):
            await call(c, "update_transaction", transaction_id=split["id"])
        with pytest.raises(ToolFailed, match="not a transaction id"):
            await call(c, "update_transaction", transaction_id="abc", payee="x")

        deleted = (await call(c, "delete_transaction", transaction_id=split["id"]))["deleted"]
        assert deleted["payee"] == "BigBasket"
        with pytest.raises(ToolFailed, match="not found"):
            await call(c, "delete_transaction", transaction_id=split["id"])
    assert client.get(f"/transactions/{split['id']}").status_code == 404


async def test_editing_a_web_entry_marks_who_changed_it(session, client, books, secret):
    created = client.post(
        "/app/transactions",
        data={"amount": "120", "from_account": books["hdfc"]["aid"], "to_account": books["groceries"]["aid"], "payee": "Shop"},
    )
    assert created.status_code == 200
    tid = client.get("/transactions/").json()[0]["tid"]
    async with running_app(session), mcp_client(secret) as c:
        updated = (await call(c, "update_transaction", transaction_id=tid, note="eggs"))["updated"]
    assert updated["created_via"] == "web" and updated["updated_via"] == "assistant (Claude)"
    page = client.get(f"/app/transactions/{tid}/edit").text
    assert "Added by the app" in page and "last changed by Claude (AI assistant)" in page
    listing = client.get("/app/transactions").text
    assert "Changed by Claude" in listing


async def test_search_filters(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        for amount, payee, to in (("100", "DMart", "Groceries"), ("2500", "Airline", "Travel:Food"), ("40", "Tea stall", "Groceries")):
            await call(c, "record_transaction", amount=amount, from_account="HDFC", to_account=to, payee=payee)
        found = await call(c, "search_transactions", text_contains="dmart")
        assert [t["payee"] for t in found["transactions"]] == ["DMart"]
        found = await call(c, "search_transactions", min_amount="50", max_amount="1000", account="Expenses")
        assert [t["payee"] for t in found["transactions"]] == ["DMart"]
        found = await call(c, "search_transactions", account="Groceries")
        assert {t["payee"] for t in found["transactions"]} == {"DMart", "Tea stall"}
        limited = await call(c, "search_transactions", limit=2)
        assert len(limited["transactions"]) == 2 and limited["truncated"] is True
        one = await call(c, "get_transaction", transaction_id=limited["transactions"][0]["id"])
        assert one["id"] == limited["transactions"][0]["id"]


async def test_spending_breakdown(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        await call(c, "record_transaction", amount="100", from_account="HDFC", to_account="Groceries")
        await call(c, "record_transaction", amount="30", from_account="HDFC", to_account="Expenses:Food")
        await call(c, "record_transaction", amount="500", from_account="HDFC", to_account="Travel:Food")
        await call(c, "record_transaction", amount="5000", from_account="Salary", to_account="HDFC")
        top = await call(c, "spending_breakdown")
        assert top["total"] == "630.00"
        assert top["by_account"] == [{"account": "Travel", "amount": "500.00"}, {"account": "Food", "amount": "130.00"}]
        deep = await call(c, "spending_breakdown", depth=2)
        assert {line["account"]: line["amount"] for line in deep["by_account"]} == {
            "Travel:Food": "500.00",
            "Food:Groceries": "100.00",
            "Food": "30.00",
        }
        income = await call(c, "spending_breakdown", kind="income")
        assert income["by_account"] == [{"account": "Salary", "amount": "5000.00"}]
        last_year = await call(c, "spending_breakdown", date_from="2020-01-01", date_to="2020-12-31")
        assert last_year["total"] == "0.00" and last_year["by_account"] == []


async def test_create_account_and_set_price(session, client, books, secret):
    client.post("/commodities/", json={"code": "INFY", "name": "Infosys", "kind": "stock", "decimals": 0})
    async with running_app(session), mcp_client(secret) as c:
        created = (await call(c, "create_account", name="Infosys", parent="Assets", holds="INFY", opening_balance="10", opening_value="15000"))["created"]
        assert created == {"path": "Assets:Infosys", "holds": "INFY", "balance": "10.00"}
        with pytest.raises(ToolFailed, match="already has an account named 'Infosys'"):
            await call(c, "create_account", name="infosys", parent="Assets")
        with pytest.raises(ToolFailed, match="only asset and liability"):
            await call(c, "create_account", name="Snacks", parent="Expenses", opening_balance="5")
        saved = (await call(c, "set_price", commodity="INFY", price="1600"))["saved"]
        assert saved == {"commodity": "INFY", "quote": "INR", "date": TODAY.isoformat(), "price": "1600.00"}
        holding = (await call(c, "get_account", account="Infosys"))["holding"]
        assert holding["value"] == "16000.00" and holding["gain"] == "1000.00"
        with pytest.raises(ToolFailed, match="unknown commodity"):
            await call(c, "set_price", commodity="NOPE", price="1")


async def test_accounts_cannot_be_deleted_and_prompts_exist(session, secret):
    async with running_app(session), mcp_client(secret) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert "delete_transaction" in names
        assert not any("account" in n and n.startswith(("delete", "remove", "update")) for n in names)
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert tools["delete_transaction"].annotations.destructive_hint is True
        assert tools["get_overview"].annotations.read_only_hint is True
        assert tools["record_transaction"].annotations.read_only_hint is False
        prompts = {p.name for p in (await c.list_prompts()).prompts}
        assert "monthly_review" in prompts


# ---- recurring transactions -------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_assistants_can_list_create_and_stop_recurring_transactions(session, root_accounts, client):
    client.post("/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "5000"})
    client.post("/accounts/", json={"name": "Rent", "parent_id": root_accounts["Expenses"]})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        assert payload(await c.call_tool("list_recurring", {}))["recurring"] == []
        made = payload(await c.call_tool("create_recurring", {
            "amount": "1500", "from_account": "Bank", "to_account": "Rent", "payee": "Landlord",
            "start_date": "2999-01-01",
        }))["created"]
        assert made["from"] == "Assets:Bank" and made["to"] == "Expenses:Rent" and made["next_due"] == "2999-01-01"
        listed = payload(await c.call_tool("list_recurring", {}))["recurring"]
        assert listed[0]["id"] == made["id"] and listed[0]["every"] == "monthly" and listed[0]["status"] == "active"
        with pytest.raises(ToolFailed, match="differ"):
            payload(await c.call_tool("create_recurring", {"amount": "1", "from_account": "Bank", "to_account": "Bank"}))
        assert payload(await c.call_tool("stop_recurring", {"recurring_id": made["id"]}))["paused"] == made["id"]
        assert payload(await c.call_tool("list_recurring", {}))["recurring"][0]["status"] == "paused or ended"
        with pytest.raises(ToolFailed, match="not a recurring transaction id"):
            payload(await c.call_tool("stop_recurring", {"recurring_id": "nope"}))
        with pytest.raises(ToolFailed, match="no recurring transaction"):
            payload(await c.call_tool("stop_recurring", {"recurring_id": "00000000-0000-4000-8000-0000000000aa"}))


@pytest.mark.anyio
async def test_read_only_assistants_can_list_but_not_create_recurring(session, root_accounts):
    secret = make_token(session, TEST_USER_ID, scope="read")
    async with running_app(session), mcp_client(secret) as c:
        assert payload(await c.call_tool("list_recurring", {}))["recurring"] == []
        with pytest.raises(ToolFailed, match="read-only"):
            payload(await c.call_tool("create_recurring", {"amount": "1", "from_account": "a", "to_account": "b"}))
        with pytest.raises(ToolFailed, match="read-only"):
            payload(await c.call_tool("stop_recurring", {"recurring_id": "x"}))

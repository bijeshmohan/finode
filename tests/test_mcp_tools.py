"""The MCP tools, called over HTTP through /mcp like a real assistant would."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app


pytestmark = pytest.mark.anyio

TODAY = date.today()


def make(client, name, parent, **extra):
    body = {"name": name, "parent_id": parent, **extra}
    response = client.post("/api/accounts/", json=body)
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
    return {
        "hdfc": hdfc, "card": card, "food": food, "groceries": groceries, "travel_food": travel_food,
        "salary": salary, "bank": bank_group,
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
        assert "holds" not in paths["Assets:Bank:HDFC"] and accounts["currency"] == "INR"
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

    stored = client.get(f"/api/transactions/{recorded['id']}").json()
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


async def test_weekly_and_yearly_targets(session, books, client, secret):
    async with running_app(session), mcp_client(secret) as c:
        weekly = payload(await c.call_tool("set_budget_target", {"category": "Groceries", "kind": "weekly", "amount": "200", "weekday": "friday"}))
        line = next(l for l in weekly["categories"] if l["category"].endswith("Groceries"))
        assert line["target"]["kind"] == "weekly" and line["target"]["weekday"] == "Friday" and line["underfunded"] != "0.00"
        yearly = payload(await c.call_tool("set_budget_target", {"category": "Groceries", "kind": "yearly", "amount": "1200", "by": "2030-03"}))
        line = next(l for l in yearly["categories"] if l["category"].endswith("Groceries"))
        assert line["target"]["kind"] == "yearly" and line["target"]["by"] == "2030-03-01" and "weekday" not in line["target"]
        with pytest.raises(ToolFailed, match="the weekday must be one of"):
            payload(await c.call_tool("set_budget_target", {"category": "Groceries", "kind": "weekly", "amount": "5", "weekday": "someday"}))
        with pytest.raises(ToolFailed, match="day of the week"):
            payload(await c.call_tool("set_budget_target", {"category": "Groceries", "kind": "weekly", "amount": "5"}))


async def test_ledger_rules_still_apply(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        with pytest.raises(ToolFailed, match="sub-accounts"):
            await call(c, "record_transaction", amount="10", from_account="Assets:Bank", to_account="Groceries")
        with pytest.raises(ToolFailed, match="top-level"):
            await call(c, "record_transaction", amount="10", from_account="HDFC", to_account="Expenses")
        with pytest.raises(ToolFailed, match="must differ"):
            await call(c, "record_transaction", amount="10", from_account="HDFC", to_account="HDFC")
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


async def test_amounts_respect_the_currencys_decimals(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        with pytest.raises(ToolFailed, match="at most 2 decimal places"):
            await call(c, "record_transaction", amount="10.005", from_account="HDFC", to_account="Groceries")


async def test_the_removed_tools_and_arguments_are_gone(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert "get_prices" not in names and "set_price" not in names
        recorded = (await call(c, "record_transaction", amount="10", from_account="HDFC", to_account="Groceries"))["recorded"]
        assert "currency" not in recorded and all(set(p) == {"account", "side", "amount"} for p in recorded["postings"])


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
    assert client.get(f"/api/transactions/{split['id']}").status_code == 404


async def test_editing_a_web_entry_marks_who_changed_it(session, client, books, secret):
    created = client.post(
        "/transactions/split",
        data={
            "account": [books["groceries"]["aid"], books["hdfc"]["aid"]],
            "side": ["debit", "credit"],
            "amount": ["120", "120"],
            "payee": "Shop",
        },
    )
    assert created.status_code == 200
    tid = client.get("/api/transactions/").json()[0]["tid"]
    async with running_app(session), mcp_client(secret) as c:
        updated = (await call(c, "update_transaction", transaction_id=tid, note="eggs"))["updated"]
    assert updated["created_via"] == "web" and updated["updated_via"] == "assistant (Claude)"
    page = client.get(f"/transactions/{tid}/edit").text
    assert "Added by the app" in page and "last changed by Claude (AI assistant)" in page
    listing = client.get("/transactions").text
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


async def test_create_account(session, client, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        created = (await call(c, "create_account", name="Savings", parent="Assets", opening_balance="10"))["created"]
        assert created == {"path": "Assets:Savings", "balance": "10.00"}
        with pytest.raises(ToolFailed, match="already has an account named 'Savings'"):
            await call(c, "create_account", name="savings", parent="Assets")
        with pytest.raises(ToolFailed, match="only asset and liability"):
            await call(c, "create_account", name="Snacks", parent="Expenses", opening_balance="5")


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
    client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "5000"})
    client.post("/api/accounts/", json={"name": "Rent", "parent_id": root_accounts["Expenses"]})
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


@pytest.mark.anyio
async def test_assistants_can_check_the_books(session, root_accounts, client):
    client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "250"})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="read")) as c:
        result = payload(await c.call_tool("check_books", {}))
        assert result["balanced"] and result["problems"] == []
        assert (result["currency"], result["total_debit"], result["total_credit"]) == ("INR", "250.00", "250.00")
        assert {a["account"] for a in result["accounts"]} == {"Assets:Bank", "Equity:Opening Balances"}
        with pytest.raises(ToolFailed, match="YYYY-MM-DD"):
            payload(await c.call_tool("check_books", {"as_of": "yesterday"}))


@pytest.mark.anyio
async def test_assistants_can_read_and_plan_the_budget(session, root_accounts, client):
    client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"})
    client.post("/api/accounts/", json={"name": "Food", "parent_id": root_accounts["Expenses"]})
    client.post("/api/accounts/", json={"name": "Rent", "parent_id": root_accounts["Expenses"]})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        start = payload(await c.call_tool("get_budget", {}))
        assert start["ready_to_assign"] == "1000.00" and start["budget_accounts"] == ["Assets:Bank"]
        assert [x["category"] for x in start["categories"]] == ["Food", "Rent"]

        after = payload(await c.call_tool("assign_to_category", {"category": "Food", "amount": "300"}))
        assert after["ready_to_assign"] == "700.00"
        assert after["categories"][0]["assigned"] == "300.00" and after["categories"][0]["available"] == "300.00"

        moved = payload(await c.call_tool(
            "move_budget_money", {"from_category": "Food", "to_category": "Rent", "amount": "120"}
        ))
        assert [x["available"] for x in moved["categories"]] == ["180.00", "120.00"]
        assert moved["ready_to_assign"] == "700.00"

        with pytest.raises(ToolFailed, match="only 180.00 is available"):
            payload(await c.call_tool("move_budget_money", {"from_category": "Food", "to_category": "Rent", "amount": "500"}))
        with pytest.raises(ToolFailed, match="not an expense account"):
            payload(await c.call_tool("assign_to_category", {"category": "Bank", "amount": "5"}))
        with pytest.raises(ToolFailed, match="YYYY-MM"):
            payload(await c.call_tool("get_budget", {"month": "last"}))
        assert payload(await c.call_tool("get_budget", {"month": "2020-01"}))["month"] == "2020-01"


@pytest.mark.anyio
async def test_the_budget_tool_reports_last_months_overspending(session, root_accounts, client):
    from datetime import date, timedelta

    this = date.today().replace(day=1)
    last = (this - timedelta(days=1)).replace(day=1)
    bank = client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"]}).json()
    salary = client.post("/api/accounts/", json={"name": "Salary", "parent_id": root_accounts["Income"]}).json()
    food = client.post("/api/accounts/", json={"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    for debit, credit, amount, on in ((bank, salary, "1000", 2), (food, bank, "30", 5)):
        client.post("/api/transactions/", json={"date": last.replace(day=on).isoformat(), "postings": [
            {"account": debit["aid"], "side": "debit", "amount": amount},
            {"account": credit["aid"], "side": "credit", "amount": amount}]})
    client.put(f"/api/budget/categories/{food['aid']}", json={"month": last.isoformat(), "amount": "10"})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        data = payload(await c.call_tool("get_budget", {}))
        assert data["overspent_last_month"] == "20.00" and data["ready_to_assign"] == "970.00"
        assert data["categories"][0]["overspent_last_month"] == "20.00" and data["categories"][0]["available"] == "0.00"


@pytest.mark.anyio
async def test_assistants_can_set_targets_and_fund_them(session, root_accounts, client):
    client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"})
    client.post("/api/accounts/", json={"name": "Rent", "parent_id": root_accounts["Expenses"]})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        data = payload(await c.call_tool("set_budget_target", {"category": "Rent", "kind": "monthly", "amount": "600"}))
        rent = data["categories"][0]
        assert rent["target"] == {"kind": "monthly", "amount": "600.00"} and rent["underfunded"] == "600.00"
        assert data["underfunded"] == "600.00"
        funded = payload(await c.call_tool("fund_budget_targets", {}))
        assert funded["categories"][0]["assigned"] == "600.00" and funded["underfunded"] == "0.00"
        assert "underfunded" not in funded["categories"][0]
        gone = payload(await c.call_tool("set_budget_target", {"category": "Rent", "kind": "none"}))
        assert "target" not in gone["categories"][0]
        with pytest.raises(ToolFailed, match="amount is required"):
            payload(await c.call_tool("set_budget_target", {"category": "Rent", "kind": "monthly"}))
        with pytest.raises(ToolFailed, match="not an expense account"):
            payload(await c.call_tool("set_budget_target", {"category": "Bank", "kind": "monthly", "amount": "5"}))


@pytest.mark.anyio
async def test_assistants_can_copy_last_months_budget(session, root_accounts, client):
    from datetime import date, timedelta

    this = date.today().replace(day=1)
    last = (this - timedelta(days=1)).replace(day=1)
    client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"})
    food = client.post("/api/accounts/", json={"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    client.put(f"/api/budget/categories/{food['aid']}", json={"month": last.isoformat(), "amount": "200"})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        data = payload(await c.call_tool("copy_budget_from_previous_month", {}))
        assert data["categories"][0]["assigned"] == "200.00" and data["ready_to_assign"] == "600.00"
        with pytest.raises(ToolFailed, match="already assigned"):
            payload(await c.call_tool("copy_budget_from_previous_month", {}))


@pytest.mark.anyio
async def test_assistants_can_create_split_recurring_transactions_and_skip_one(session, root_accounts, client):
    client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "5000"})
    client.post("/api/accounts/", json={"name": "Rent", "parent_id": root_accounts["Expenses"]})
    client.post("/api/accounts/", json={"name": "Water", "parent_id": root_accounts["Expenses"]})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        made = payload(await c.call_tool("create_recurring", {
            "postings": [
                {"account": "Rent", "side": "debit", "amount": "1400"},
                {"account": "Water", "side": "debit", "amount": "100"},
                {"account": "Bank", "side": "credit", "amount": "1500"},
            ],
            "payee": "Landlord", "start_date": "2999-01-01",
        }))["created"]
        assert made["next_due"] == "2999-01-01" and len(made["postings"]) == 3
        listed = payload(await c.call_tool("list_recurring", {}))["recurring"][0]
        assert {p["account"] for p in listed["postings"]} == {"Expenses:Rent", "Expenses:Water", "Assets:Bank"}
        with pytest.raises(ToolFailed, match="not both"):
            payload(await c.call_tool("create_recurring", {"amount": "1", "from_account": "Bank", "to_account": "Rent",
                "postings": [{"account": "Rent", "side": "debit", "amount": "1"}, {"account": "Bank", "side": "credit", "amount": "1"}]}))
        with pytest.raises(ToolFailed, match="or postings"):
            payload(await c.call_tool("create_recurring", {"amount": "1"}))
        with pytest.raises(ToolFailed, match="balance"):
            payload(await c.call_tool("create_recurring", {"postings": [
                {"account": "Rent", "side": "debit", "amount": "10"}, {"account": "Bank", "side": "credit", "amount": "9"}]}))

        skipped = payload(await c.call_tool("skip_recurring_occurrence", {"recurring_id": made["id"]}))
        assert skipped["skipped"] == "2999-01-01" and skipped["next_due"] == "2999-02-01"
        assert payload(await c.call_tool("list_recurring", {}))["recurring"][0]["next_due"] == "2999-02-01"
        with pytest.raises(ToolFailed, match="no recurring transaction"):
            payload(await c.call_tool("skip_recurring_occurrence", {"recurring_id": "00000000-0000-4000-8000-0000000000aa"}))
        await c.call_tool("stop_recurring", {"recurring_id": made["id"]})
        with pytest.raises(ToolFailed, match="resume it first"):
            payload(await c.call_tool("skip_recurring_occurrence", {"recurring_id": made["id"]}))


@pytest.mark.anyio
async def test_get_budget_shows_category_notes(session, books, client, secret):
    rent = client.post("/api/accounts/", json={"name": "Rent", "parent_id": books["food"]["parent_id"]}).json()
    client.post("/plan/note", data={"category": rent["aid"], "note": "Due on the 5th"})
    async with running_app(session), mcp_client(secret) as c:
        data = payload(await c.call_tool("get_budget", {}))
        mine = next(l for l in data["categories"] if l["category"].endswith("Rent"))
        assert mine["note"] == "Due on the 5th"
        assert all("note" not in l for l in data["categories"] if not l["category"].endswith("Rent"))


@pytest.mark.anyio
async def test_get_budget_lists_the_weeks_of_a_weekly_target(session, books, client, secret):
    rent = client.post("/api/accounts/", json={"name": "Pocket money", "parent_id": books["food"]["parent_id"]}).json()
    client.put(f"/api/budget/categories/{rent['aid']}/target", json={"kind": "weekly", "amount": "100", "weekday": 0})
    async with running_app(session), mcp_client(secret) as c:
        data = payload(await c.call_tool("get_budget", {}))
        mine = next(l for l in data["categories"] if l["category"].endswith("Pocket money"))
        assert mine["weeks"] and all({"from", "to", "spent"} <= set(w) for w in mine["weeks"])
        assert all(w["allowance"] == "100.00" for w in mine["weeks"] if "allowance" in w)
        assert all("weeks" not in l for l in data["categories"] if not l["category"].endswith("Pocket money"))


@pytest.mark.anyio
async def test_only_expense_categories_can_be_planned(session, root_accounts, client):
    client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"})
    client.post("/api/accounts/", json={"name": "Fund", "parent_id": root_accounts["Assets"], "on_budget": False})
    client.post("/api/accounts/", json={"name": "Salary", "parent_id": root_accounts["Income"]})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        for name in ("Bank", "Fund", "Salary"):
            with pytest.raises(ToolFailed, match="not an expense account"):
                payload(await c.call_tool("assign_to_category", {"category": name, "amount": "5"}))

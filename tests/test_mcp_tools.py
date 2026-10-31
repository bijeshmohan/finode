"""The MCP tools, called over HTTP through /mcp like a real assistant would."""

from datetime import date, timedelta

import pytest

from .books import leg, post_account
from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app

pytestmark = pytest.mark.anyio

TODAY = date.today()


def make(client, name, parent, **extra):
    body = {"name": name, "parent_id": parent, **extra}
    response = post_account(client, body)
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
        "hdfc": hdfc,
        "card": card,
        "food": food,
        "groceries": groceries,
        "travel_food": travel_food,
        "salary": salary,
        "bank": bank_group,
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
        assert "Expenses:Food" not in paths, "categories are listed by list_categories, not here"
        assert "holds" not in paths["Assets:Bank:HDFC"] and accounts["currency"] == "INR"
        only = await call(c, "list_accounts", type="Income")
        assert [a["path"] for a in only["accounts"]] == ["Income"]


async def test_record_by_short_names_and_read_it_back(session, client, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        recorded = (
            await call(
                c, "record_transaction", amount="450", from_account="HDFC", to_account="Groceries", payee="DMart"
            )
        )["recorded"]
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
        recorded = (await call(c, "record_transaction", amount="10", from_account="HDFC", to_account="Groceries"))[
            "recorded"
        ]
        assert "currency" not in recorded and all(
            {"account", "account_id", "side", "amount"}
            <= set(p)
            <= {"account", "account_id", "side", "amount", "category", "category_id"}
            for p in recorded["postings"]
        )


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

        updated = (await call(c, "update_transaction", transaction_id=split["id"], payee="BigBasket", note=""))[
            "updated"
        ]
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
    assert "Added by" not in page and "last changed by" not in page  # not on the edit page: it is in the details sheet
    sheet = client.get(f"/transactions/{tid}/sheet").text
    assert "Added by the app · last changed by Claude</span>" in " ".join(sheet.split())
    listing = client.get("/transactions").text
    assert "Changed by Claude" in listing


async def test_search_filters(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        for amount, payee, to in (
            ("100", "DMart", "Groceries"),
            ("2500", "Airline", "Travel:Food"),
            ("40", "Tea stall", "Groceries"),
        ):
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
        assert top["by_category"] == [
            {"category": "Travel", "amount": "500.00"},
            {"category": "Food", "amount": "130.00"},
        ]
        deep = await call(c, "spending_breakdown", depth=2)
        assert {line["category"]: line["amount"] for line in deep["by_category"]} == {
            "Travel:Food": "500.00",
            "Food:Groceries": "100.00",
            "Food": "30.00",
        }
        income = await call(c, "spending_breakdown", kind="income")
        assert income["by_category"] == [{"category": "Salary", "amount": "5000.00"}]
        last_year = await call(c, "spending_breakdown", date_from="2020-01-01", date_to="2020-12-31")
        assert last_year["total"] == "0.00" and last_year["by_category"] == []


async def test_create_account(session, client, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        created = (await call(c, "create_account", name="Savings", parent="Assets", opening_balance="10"))["created"]
        assert {k: v for k, v in created.items() if k != "id"} == {"path": "Assets:Savings", "balance": "10.00"}
        with pytest.raises(ToolFailed, match="already has an account named 'Savings'"):
            await call(c, "create_account", name="savings", parent="Assets")
        with pytest.raises(ToolFailed, match="only asset and liability"):
            await call(c, "create_account", name="Snacks", parent="Expenses", opening_balance="5")


async def test_accounts_cannot_be_deleted_and_prompts_exist(session, secret):
    async with running_app(session), mcp_client(secret) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert "delete_transaction" in names
        assert not any("account" in n and n.startswith(("delete", "remove")) for n in names), (
            "accounts are never deleted"
        )
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert tools["delete_transaction"].annotations.destructive_hint is True
        assert tools["get_overview"].annotations.read_only_hint is True
        assert tools["record_transaction"].annotations.read_only_hint is False
        prompts = {p.name for p in (await c.list_prompts()).prompts}
        assert "monthly_review" in prompts


# ---- recurring transactions -------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_assistants_can_list_create_and_stop_recurring_transactions(session, root_accounts, client):
    post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "5000"})
    post_account(client, {"name": "Rent", "parent_id": root_accounts["Expenses"]})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        assert payload(await c.call_tool("list_recurring", {}))["recurring"] == []
        made = payload(
            await c.call_tool(
                "create_recurring",
                {
                    "amount": "1500",
                    "from_account": "Bank",
                    "to_account": "Rent",
                    "payee": "Landlord",
                    "start_date": "2999-01-01",
                    "tags": ["#Rent", "home"],
                },
            )
        )["created"]
        assert made["from"] == "Assets:Bank" and made["to"] == "Expenses:Rent" and made["next_due"] == "2999-01-01"
        assert made["tags"] == ["rent", "home"]
        listed = payload(await c.call_tool("list_recurring", {}))["recurring"]
        assert listed[0]["id"] == made["id"] and listed[0]["every"] == "monthly" and listed[0]["status"] == "active"
        assert listed[0]["tags"] == ["rent", "home"]
        with pytest.raises(ToolFailed, match="differ"):
            payload(
                await c.call_tool("create_recurring", {"amount": "1", "from_account": "Bank", "to_account": "Bank"})
            )
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
    post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "250"})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="read")) as c:
        result = payload(await c.call_tool("check_books", {}))
        assert result["balanced"] and result["problems"] == []
        assert (result["currency"], result["total_debit"], result["total_credit"]) == ("INR", "250.00", "250.00")
        assert {a["account"] for a in result["accounts"]} == {"Assets:Bank", "Equity:Opening Balances"}
        with pytest.raises(ToolFailed, match="YYYY-MM-DD"):
            payload(await c.call_tool("check_books", {"as_of": "yesterday"}))


@pytest.mark.anyio
async def test_assistants_can_read_and_plan_the_budget(session, root_accounts, client):
    post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"})
    post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]})
    post_account(client, {"name": "Rent", "parent_id": root_accounts["Expenses"]})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        start = payload(await c.call_tool("get_budget", {}))
        assert start["ready_to_assign"] == "1000.00" and start["budget_accounts"] == ["Assets:Bank"]
        assert [x["category"] for x in start["categories"]] == ["Food", "Rent"]

        after = payload(await c.call_tool("assign_to_category", {"category": "Food", "amount": "300"}))
        assert after["ready_to_assign"] == "700.00"
        assert after["categories"][0]["assigned"] == "300.00" and after["categories"][0]["available"] == "300.00"

        moved = payload(
            await c.call_tool("move_budget_money", {"from_category": "Food", "to_category": "Rent", "amount": "120"})
        )
        assert [x["available"] for x in moved["categories"]] == ["180.00", "120.00"]
        assert moved["ready_to_assign"] == "700.00"

        with pytest.raises(ToolFailed, match="only 180.00 is available"):
            payload(
                await c.call_tool(
                    "move_budget_money", {"from_category": "Food", "to_category": "Rent", "amount": "500"}
                )
            )
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
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"]}).json()
    salary = post_account(client, {"name": "Salary", "parent_id": root_accounts["Income"]}).json()
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    for debit, credit, amount, on in ((bank, salary, "1000", 2), (food, bank, "30", 5)):
        client.post(
            "/api/transactions/",
            json={
                "date": last.replace(day=on).isoformat(),
                "postings": [
                    leg(debit, "debit", amount),
                    leg(credit, "credit", amount),
                ],
            },
        )
    client.put(f"/api/budget/categories/{food['aid']}", json={"month": last.isoformat(), "amount": "10"})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        data = payload(await c.call_tool("get_budget", {}))
        assert data["overspent_last_month"] == "20.00" and data["ready_to_assign"] == "970.00"
        assert data["categories"][0]["overspent_last_month"] == "20.00" and data["categories"][0]["available"] == "0.00"


@pytest.mark.anyio
async def test_assistants_can_set_money_aside_for_a_goal_and_hand_it_to_a_category(session, root_accounts, client):
    post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"})
    post_account(client, {"name": "Hospital", "parent_id": root_accounts["Expenses"]})
    client.post("/budget/goal", data={"name": "Emergency fund", "amount": "600", "by": "2999-12"})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        data = payload(await c.call_tool("assign_to_goal", {"goal": "emergency FUND", "amount": "300"}))
        assert (
            data["saved_for_goals"] == "300.00"
            and data["goals"][0]["goal"] == "Emergency fund"
            and data["ready_to_assign"] == "700.00"
        )
        used = payload(
            await c.call_tool("use_goal", {"goal": "Emergency fund", "category": "Hospital", "amount": "120"})
        )
        assert used["goals"][0]["saved"] == "180.00" and used["ready_to_assign"] == "700.00"
        assert used["categories"][0]["category"] == "Hospital" and used["categories"][0]["available"] == "120.00"
        with pytest.raises(ToolFailed, match="no goal is called 'Bike'.*Emergency fund"):
            payload(await c.call_tool("assign_to_goal", {"goal": "Bike", "amount": "5"}))
        with pytest.raises(ToolFailed, match="only 180"):
            payload(await c.call_tool("use_goal", {"goal": "Emergency fund", "category": "Hospital", "amount": "500"}))


@pytest.mark.anyio
async def test_assistants_can_copy_last_months_budget(session, root_accounts, client):
    from datetime import date, timedelta

    this = date.today().replace(day=1)
    last = (this - timedelta(days=1)).replace(day=1)
    post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"})
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    client.put(f"/api/budget/categories/{food['aid']}", json={"month": last.isoformat(), "amount": "200"})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        data = payload(await c.call_tool("copy_budget_from_previous_month", {}))
        assert data["categories"][0]["assigned"] == "200.00" and data["ready_to_assign"] == "600.00"
        with pytest.raises(ToolFailed, match="already assigned"):
            payload(await c.call_tool("copy_budget_from_previous_month", {}))


@pytest.mark.anyio
async def test_assistants_can_create_split_recurring_transactions_and_skip_one(session, root_accounts, client):
    post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "5000"})
    post_account(client, {"name": "Rent", "parent_id": root_accounts["Expenses"]})
    post_account(client, {"name": "Water", "parent_id": root_accounts["Expenses"]})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        made = payload(
            await c.call_tool(
                "create_recurring",
                {
                    "postings": [
                        {"account": "Rent", "side": "debit", "amount": "1400"},
                        {"account": "Water", "side": "debit", "amount": "100"},
                        {"account": "Bank", "side": "credit", "amount": "1500"},
                    ],
                    "payee": "Landlord",
                    "start_date": "2999-01-01",
                },
            )
        )["created"]
        assert made["next_due"] == "2999-01-01" and len(made["postings"]) == 3
        listed = payload(await c.call_tool("list_recurring", {}))["recurring"][0]
        assert {p["account"] for p in listed["postings"]} == {"Expenses:Rent", "Expenses:Water", "Assets:Bank"}
        with pytest.raises(ToolFailed, match="not both"):
            payload(
                await c.call_tool(
                    "create_recurring",
                    {
                        "amount": "1",
                        "from_account": "Bank",
                        "to_account": "Rent",
                        "postings": [
                            {"account": "Rent", "side": "debit", "amount": "1"},
                            {"account": "Bank", "side": "credit", "amount": "1"},
                        ],
                    },
                )
            )
        with pytest.raises(ToolFailed, match="or postings"):
            payload(await c.call_tool("create_recurring", {"amount": "1"}))
        with pytest.raises(ToolFailed, match="balance"):
            payload(
                await c.call_tool(
                    "create_recurring",
                    {
                        "postings": [
                            {"account": "Rent", "side": "debit", "amount": "10"},
                            {"account": "Bank", "side": "credit", "amount": "9"},
                        ]
                    },
                )
            )

        skipped = payload(await c.call_tool("skip_recurring_occurrence", {"recurring_id": made["id"]}))
        assert skipped["skipped"] == "2999-01-01" and skipped["next_due"] == "2999-02-01"
        assert payload(await c.call_tool("list_recurring", {}))["recurring"][0]["next_due"] == "2999-02-01"
        with pytest.raises(ToolFailed, match="no recurring transaction"):
            payload(
                await c.call_tool("skip_recurring_occurrence", {"recurring_id": "00000000-0000-4000-8000-0000000000aa"})
            )
        await c.call_tool("stop_recurring", {"recurring_id": made["id"]})
        with pytest.raises(ToolFailed, match="resume it first"):
            payload(await c.call_tool("skip_recurring_occurrence", {"recurring_id": made["id"]}))


@pytest.mark.anyio
async def test_only_expense_categories_can_be_planned(session, root_accounts, client):
    post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"})
    post_account(client, {"name": "Fund", "parent_id": root_accounts["Assets"], "on_budget": False})
    post_account(client, {"name": "Salary", "parent_id": root_accounts["Income"]})
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        for name in ("Bank", "Fund", "Salary"):
            with pytest.raises(ToolFailed, match="not an expense account"):
                payload(await c.call_tool("assign_to_category", {"category": name, "amount": "5"}))


# ---- related entries, deleted entries, resuming, goals -------------------------------------------------------------


async def test_assistants_can_link_a_refund_to_the_purchase(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        bought = (
            await call(
                c, "record_transaction", amount="1200", from_account="HDFC", to_account="Groceries", payee="DMart"
            )
        )["recorded"]
        assert bought["related_to"] is None
        refund = (
            await call(
                c,
                "record_transaction",
                amount="400",
                from_account="Groceries",
                to_account="HDFC",
                payee="DMart",
                related_to=bought["id"],
            )
        )["recorded"]
        assert refund["related_to"] == bought["id"]
        original = await call(c, "get_transaction", transaction_id=bought["id"])
        assert [r["id"] for r in original["related"]] == [refund["id"]]
        # a split can be linked too, and the link can be changed and removed
        split = (
            await call(
                c,
                "record_split",
                postings=[
                    {"account": "Groceries", "side": "credit", "amount": "50"},
                    {"account": "HDFC", "side": "debit", "amount": "50"},
                ],
                related_to=bought["id"],
            )
        )["recorded"]
        assert split["related_to"] == bought["id"]
        moved = (await call(c, "update_transaction", transaction_id=split["id"], related_to=refund["id"]))["updated"]
        assert moved["related_to"] == refund["id"]
        cleared = (await call(c, "update_transaction", transaction_id=split["id"], related_to=""))["updated"]
        assert cleared["related_to"] is None
        with pytest.raises(ToolFailed, match="related transaction was not found"):
            await call(
                c, "update_transaction", transaction_id=split["id"], related_to="00000000-0000-4000-8000-0000000000aa"
            )
        with pytest.raises(ToolFailed, match="relate"):
            await call(c, "update_transaction", transaction_id=bought["id"], related_to=bought["id"])
        with pytest.raises(ToolFailed, match="not a transaction id"):
            await call(
                c, "record_transaction", amount="1", from_account="HDFC", to_account="Groceries", related_to="abc"
            )


async def test_assistants_can_list_and_restore_deleted_transactions(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        assert (await call(c, "list_deleted_transactions"))["deleted"] == []
        made = (
            await call(c, "record_transaction", amount="75", from_account="HDFC", to_account="Groceries", payee="Milk")
        )["recorded"]
        await call(c, "delete_transaction", transaction_id=made["id"])
        gone = (await call(c, "list_deleted_transactions"))["deleted"]
        assert (
            len(gone) == 1
            and gone[0]["payee"] == "Milk"
            and gone[0]["total"] == "75.00"
            and gone[0]["transaction_id"] == made["id"]
        )
        back = (await call(c, "restore_transaction", deleted_id=gone[0]["deleted_id"]))["restored"]
        assert back["id"] == made["id"] and back["total"] == "75.00"
        assert (await call(c, "list_deleted_transactions"))["deleted"] == []
        with pytest.raises(ToolFailed, match="already back"):
            await call(c, "restore_transaction", deleted_id=gone[0]["deleted_id"])
        with pytest.raises(ToolFailed, match="no deleted transaction"):
            await call(c, "restore_transaction", deleted_id="00000000-0000-4000-8000-0000000000aa")
        with pytest.raises(ToolFailed, match="not a deleted-transaction id"):
            await call(c, "restore_transaction", deleted_id="abc")


async def test_assistants_can_resume_a_paused_recurring_transaction(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        made = (
            await call(
                c,
                "create_recurring",
                from_account="HDFC",
                to_account="Groceries",
                amount="10",
                frequency="monthly",
                start_date="2999-01-01",
            )
        )["created"]
        await call(c, "stop_recurring", recurring_id=made["id"])
        assert (await call(c, "list_recurring"))["recurring"][0]["next_due"] is None
        resumed = await call(c, "resume_recurring", recurring_id=made["id"])
        assert resumed["resumed"] == made["id"] and resumed["next_due"] == "2999-01-01"
        with pytest.raises(ToolFailed, match="no recurring transaction"):
            await call(c, "resume_recurring", recurring_id="00000000-0000-4000-8000-0000000000aa")


async def test_assistants_can_create_change_and_delete_a_goal(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        made = await call(c, "create_goal", name="Laptop", amount="60000", by="2999-12")
        goal = next(g for g in made["goals"] if g["goal"] == "Laptop")
        assert goal["target"] == "60000.00" and goal["by"] == "2999-12-01"
        changed = await call(c, "update_goal", goal="laptop", name="New laptop", amount="70000")
        goal = next(g for g in changed["goals"] if g["goal"] == "New laptop")
        assert goal["target"] == "70000.00" and goal["by"] == "2999-12-01"
        with pytest.raises(ToolFailed, match="nothing to change"):
            await call(c, "update_goal", goal="New laptop")
        with pytest.raises(ToolFailed, match="already have a goal"):
            await call(c, "create_goal", name="new LAPTOP", amount="1", by="2999-12")
        with pytest.raises(ToolFailed, match="YYYY-MM"):
            await call(c, "create_goal", name="Trip", amount="1", by="soon")
        gone = await call(c, "delete_goal", goal="New laptop")
        assert gone["deleted"] == "New laptop"
        assert "goals" not in await call(c, "get_budget")
        with pytest.raises(ToolFailed, match="no goal is called"):
            await call(c, "delete_goal", goal="New laptop")


async def test_a_read_only_connection_refuses_the_new_tools(session, books):
    read_only = make_token(session, TEST_USER_ID, scope="read")
    async with running_app(session), mcp_client(read_only) as c:
        assert "list_deleted_transactions" in {t.name for t in (await c.list_tools()).tools}
        assert (await call(c, "list_deleted_transactions"))["deleted"] == []
        for tool, args in (
            ("restore_transaction", {"deleted_id": "x"}),
            ("resume_recurring", {"recurring_id": "x"}),
            ("create_goal", {"name": "a", "amount": "1", "by": "2999-12"}),
            ("update_goal", {"goal": "a", "name": "b"}),
            ("delete_goal", {"goal": "a"}),
        ):
            with pytest.raises(ToolFailed, match="read-only"):
                await call(c, tool, **args)


# ---- ids, status and search totals (agent-friendly, phase 1) ---------------------------------------------------


async def test_ids_and_account_facts_are_listed(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        accounts = {a["path"]: a for a in (await call(c, "list_accounts"))["accounts"]}
        hdfc = accounts["Assets:Bank:HDFC"]
        assert hdfc["id"] == books["hdfc"]["aid"] and hdfc["type"] == "Assets" and hdfc["on_budget"] is True
        assert "details" in hdfc and "Expenses:Food" not in accounts
        by_id = await call(c, "get_account", account=hdfc["id"])
        assert by_id["id"] == hdfc["id"] and by_id["path"] == "Assets:Bank:HDFC"
        made = await call(c, "record_transaction", amount="10", from_account=hdfc["id"], to_account="Groceries")
        assert made["recorded"]["postings"][0]["account_id"] in {hdfc["id"], books["groceries"]["aid"]}
        created = await call(c, "create_account", name="Loan X", parent="Liabilities", on_budget=False)
        assert created["created"]["id"]


async def test_status_says_what_the_connection_may_do(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        empty = await call(c, "get_status")
        assert empty["connection"] == {
            "name": "Claude",
            "access": "read & write",
            "can_change_things": True,
            "can_change_accounts": False,
        }
        before = empty["books"]["transactions"]  # the bank's opening balance is an entry too
        await call(c, "record_transaction", amount="10", from_account="HDFC", to_account="Groceries")
        status = await call(c, "get_status")
        assert status["currency"] == "INR" and status["books"]["transactions"] == before + 1
        assert status["books"]["last_change"] and status["limits"]["new_transactions_left_today"] == 999 - before
    read_only = make_token(session, TEST_USER_ID, name="Looker", scope="read")
    async with running_app(session), mcp_client(read_only) as c:
        got = await call(c, "get_status")
        assert got["connection"]["access"] == "read only" and got["connection"]["can_change_things"] is False


async def test_search_counts_totals_and_pages(session, books, secret):
    async with running_app(session), mcp_client(secret) as c:
        for amount, payee in (("100", "DMart"), ("40", "Tea stall"), ("7", "DMart")):
            await call(c, "record_transaction", amount=amount, from_account="HDFC", to_account="Groceries", payee=payee)
        await call(c, "record_transaction", amount="900", from_account="Salary", to_account="HDFC", payee="Acme")
        everything = await call(c, "search_transactions", limit=2)
        assert everything["count"] == 5 and everything["truncated"] is True
        assert everything["spent"] == "147.00" and everything["earned"] == "900.00"
        second = await call(c, "search_transactions", limit=2, offset=2)
        last = await call(c, "search_transactions", limit=2, offset=4)
        assert second["truncated"] is True and last["truncated"] is False and len(last["transactions"]) == 1
        seen = {t["id"] for page in (everything, second, last) for t in page["transactions"]}
        assert len(seen) == 5 and everything["transferred"] == "10000.00"
        dmart = await call(c, "search_transactions", payee="dmart")
        assert dmart["count"] == 2 and dmart["spent"] == "107.00"
        assert (await call(c, "search_transactions", kind="income"))["count"] == 1
        bank = await call(c, "search_transactions", account="HDFC")
        assert bank["account_net_change"] == "10753.00"  # with the opening balance

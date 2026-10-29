"""The categories in the JSON API and in the assistants' tools."""

import pytest

from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app
from .test_budget import account, budget, line

MISSING = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="100000")
    loan = account(client, root_accounts, "Home Loan", "Liabilities", on_budget=False)
    food = account(client, root_accounts, "Food", "Expenses")
    groceries = client.post("/api/accounts/", json={"name": "Groceries", "parent_id": food["aid"]}).json()
    emi = account(client, root_accounts, "EMI", "Expenses")
    salary = account(client, root_accounts, "Salary", "Income")
    return {"bank": bank, "loan": loan, "food": food, "groceries": groceries, "emi": emi, "salary": salary}


# ---- the JSON API ------------------------------------------------------------------------------


def test_the_list_has_every_category_with_its_path_and_kind(client, books):
    got = {c["path"]: c for c in client.get("/api/categories/").json()}
    assert set(got) == {"Food", "Food:Groceries", "EMI", "Salary"}
    assert got["Food:Groceries"]["parent_id"] == got["Food"]["bcid"] == books["food"]["aid"]
    assert (got["Food"]["kind"], got["Salary"]["kind"]) == ("spending", "earning")
    assert [c["path"] for c in client.get("/api/categories/", params={"kind": "earning"}).json()] == ["Salary"]


def test_a_category_is_made_changed_closed_and_removed(client, books):
    made = client.post(
        "/api/categories/", json={"name": "Dining", "kind": "spending", "parent_id": books["food"]["aid"]}
    )
    assert made.status_code == 201 and made.json()["path"] == "Food:Dining"
    bcid = made.json()["bcid"]
    assert client.get(f"/api/categories/{bcid}").json()["name"] == "Dining"
    assert client.patch(f"/api/categories/{bcid}", json={"name": "Eating out"}).json()["path"] == "Food:Eating out"
    assert client.patch(f"/api/categories/{bcid}", json={"parent_id": None}).json()["path"] == "Eating out"
    assert client.post(f"/api/categories/{bcid}/close").json()["closed_on"]
    assert bcid not in [c["bcid"] for c in client.get("/api/categories/").json()]
    assert client.post(f"/api/categories/{bcid}/reopen").json()["closed_on"] is None
    gone = client.post(f"/api/categories/{bcid}/delete").json()
    assert gone["outcome"] == "deleted" and client.get(f"/api/categories/{bcid}").status_code == 404


def test_a_category_with_history_is_closed_not_deleted(client, books):
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"category": books["emi"]["aid"], "side": "debit", "amount": "10"},
                {"account": books["bank"]["aid"], "side": "credit", "amount": "10"},
            ]
        },
    )
    answer = client.post(f"/api/categories/{books['emi']['aid']}/delete").json()
    assert answer["outcome"] == "closed" and answer["category"]["closed_on"]


def test_the_rules_of_names_and_levels_apply(client, books):
    taken = client.post("/api/categories/", json={"name": "food", "kind": "spending"})
    assert taken.status_code == 400
    deep = client.post(
        "/api/categories/", json={"name": "Pizza", "kind": "spending", "parent_id": books["groceries"]["aid"]}
    )
    assert deep.status_code == 400
    wrong_kind = client.post(
        "/api/categories/", json={"name": "Tips", "kind": "earning", "parent_id": books["food"]["aid"]}
    )
    assert wrong_kind.status_code == 400 and "cannot hold" in wrong_kind.text
    assert client.get(f"/api/categories/{MISSING}").status_code == 404
    assert client.post(f"/api/categories/{MISSING}/close").status_code == 404
    assert client.post(f"/api/categories/{MISSING}/delete").status_code == 404


def test_categories_merge_with_a_dry_run(client, books):
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": books["groceries"]["aid"], "side": "debit", "amount": "10"},
                {"account": books["bank"]["aid"], "side": "credit", "amount": "10"},
            ]
        },
    )
    preview = client.post(
        f"/api/categories/{books['groceries']['aid']}/merge",
        params={"dry_run": True},
        json={"into": books["emi"]["aid"]},
    )
    assert preview.status_code == 200 and preview.json()["entries_moved"] == 1 and not preview.json()["merged"]
    assert client.get(f"/api/categories/{books['groceries']['aid']}").status_code == 200
    done = client.post(f"/api/categories/{books['groceries']['aid']}/merge", json={"into": books["emi"]["aid"]})
    assert done.status_code == 200 and done.json()["merged"]
    assert client.get(f"/api/categories/{books['groceries']['aid']}").status_code == 404


def test_a_line_may_name_only_its_category(client, books):
    made = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"category": books["groceries"]["aid"], "side": "debit", "amount": "12"},
                {"account": books["bank"]["aid"], "side": "credit", "amount": "12"},
            ]
        },
    )
    assert made.status_code == 201, made.text
    first = made.json()["postings"][0]
    assert first["account"] == books["groceries"]["aid"] and first["category"] == books["groceries"]["aid"]
    neither = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"side": "debit", "amount": "1"},
                {"account": books["bank"]["aid"], "side": "credit", "amount": "1"},
            ]
        },
    )
    assert neither.status_code == 422


def test_the_account_says_which_category_it_stands_for(client, books):
    got = client.get(f"/api/accounts/{books['emi']['aid']}").json()
    assert got["category_id"] == books["emi"]["aid"]
    assert client.get(f"/api/accounts/{books['bank']['aid']}").json()["category_id"] is None


# ---- the assistants' tools -------------------------------------------------------------------------


async def call(c, tool, **args):
    return payload(await c.call_tool(tool, args))


@pytest.mark.anyio
async def test_an_assistant_lists_categories_and_labels_a_payment_into_a_loan(session, client, books):
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="write")) as c:
        listed = await call(c, "list_categories")
        assert {x["path"] for x in listed["categories"]} == {"Food", "Food:Groceries", "EMI", "Salary"}
        saved = (
            await call(
                c,
                "record_transaction",
                amount="15000",
                from_account="Bank",
                to_account="Home Loan",
                category="EMI",
            )
        )["recorded"]
        row = next(p for p in saved["postings"] if p["account"].endswith("Home Loan"))
        assert row["category"] == "EMI" and row["category_id"] == books["emi"]["aid"]
        assert line(budget(client), "EMI")["activity"] == "15000.00"
        with pytest.raises(ToolFailed, match="no category matches"):
            await call(
                c, "record_transaction", amount="1", from_account="Bank", to_account="Home Loan", category="Nowhere"
            )
        with pytest.raises(ToolFailed, match="earning category"):
            await call(
                c, "record_transaction", amount="1", from_account="Bank", to_account="Home Loan", category="Salary"
            )


@pytest.mark.anyio
async def test_a_split_row_may_name_only_a_category_and_a_rule_may_carry_one(session, client, books):
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="write")) as c:
        saved = (
            await call(
                c,
                "record_split",
                postings=[
                    {"category": "Food:Groceries", "side": "debit", "amount": "30"},
                    {"account": "Home Loan", "category": "EMI", "side": "debit", "amount": "70"},
                    {"account": "Bank", "side": "credit", "amount": "100"},
                ],
            )
        )["recorded"]
        assert {p.get("category") for p in saved["postings"]} == {"Food:Groceries", "EMI", None}
        rule = (
            await call(c, "create_recurring", amount="500", from_account="Bank", to_account="Home Loan", category="EMI")
        )["created"]
        assert rule["id"]
        assert client.get("/api/recurring/").json()[0]["category"] == books["emi"]["aid"]


@pytest.mark.anyio
async def test_making_a_category_needs_write_and_changing_one_needs_manage(session, client, books):
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="write")) as c:
        made = (await call(c, "create_category", name="Dining", kind="spending", group="Food"))["created"]
        assert made["path"] == "Food:Dining" and made["kind"] == "spending"
        with pytest.raises(ToolFailed, match="not manage accounts, categories or tags"):
            await call(c, "update_category", category="Food:Dining", name="Eating out")
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, name="Manager", scope="manage")) as c:
        assert (await call(c, "update_category", category="Food:Dining", name="Eating out"))["updated"][
            "path"
        ] == "Food:Eating out"
        closed = await call(c, "close_category", category="Food:Eating out")
        assert closed["closed"]["closed"]
        assert "closed" not in (await call(c, "reopen_category", category="Food:Eating out"))["reopened"]
        preview = await call(c, "merge_categories", category="Food:Eating out", into="Food:Groceries", dry_run=True)
        assert preview["dry_run"] is True and preview["into"] == "Food:Groceries"
        done = await call(c, "merge_categories", category="Food:Eating out", into="Food:Groceries")
        assert done["merged"] is True
        assert "Food:Eating out" not in {x["path"] for x in (await call(c, "list_categories"))["categories"]}

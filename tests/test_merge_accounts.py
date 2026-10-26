"""Merging one account into another: everything moves, all or nothing, with history, and the rules that keep it safe."""

import pytest

from app.services.account import AccountService

from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app
from .test_transaction_references import body


def account(client, name, parent, **extra):
    made = client.post("/api/accounts/", json={"name": name, "parent_id": parent, **extra})
    assert made.status_code == 201, made.text
    return made.json()


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, "Bank", root_accounts["Assets"], balance="1000")
    loan = account(client, "Loan", root_accounts["Liabilities"], on_budget=False)
    swiggy = account(client, "Swiggy", root_accounts["Expenses"])
    zomato = account(client, "Zomato", root_accounts["Expenses"])
    salary = account(client, "Salary", root_accounts["Income"])
    return {"bank": bank, "loan": loan, "swiggy": swiggy, "zomato": zomato, "salary": salary, "roots": root_accounts}


def spend(client, books, to, amount, on="2026-10-10"):
    made = client.post("/api/transactions/", json=body(to, books["bank"], amount, on=on, payee="x"))
    assert made.status_code == 201, made.text
    return made.json()


def merge(client, source, target, **params):
    return client.post(f"/api/accounts/{source['aid']}/merge", json={"into": target["aid"]}, params=params)


def balance(client, a):
    return client.get(f"/api/accounts/{a['aid']}").json()["balance"]


def test_everything_moves_and_the_account_goes(client, books):
    one = spend(client, books, books["swiggy"], "30")
    spend(client, books, books["zomato"], "20", on="2026-10-11")
    rule = client.post(
        "/api/recurring/",
        json={
            "from_account": books["bank"]["aid"],
            "to_account": books["swiggy"]["aid"],
            "amount": "5",
            "frequency": "monthly",
            "start_date": "2999-01-01",
            "payee": "Sub",
        },
    ).json()
    for category, amount in ((books["swiggy"], "100"), (books["zomato"], "50")):
        client.put(f"/api/budget/categories/{category['aid']}", json={"month": "2026-10-01", "amount": amount})
    client.patch(f"/api/accounts/{books['loan']['aid']}", json={"payment_category_id": books["swiggy"]["aid"]})
    ready_before = client.get("/api/budget/", params={"month": "2026-10-01"}).json()["ready_to_assign"]

    done = merge(client, books["swiggy"], books["zomato"])
    assert done.status_code == 200, done.text
    result = done.json()
    assert (result["source"], result["into"]) == ("Expenses:Swiggy", "Expenses:Zomato")
    assert (result["entries_moved"], result["plan_months_moved"], result["recurring_rules_moved"]) == (1, 1, 1)
    assert result["payment_links_moved"] == 1 and result["balance_moved"] == "30.00" and result["merged"] is True

    assert client.get(f"/api/accounts/{books['swiggy']['aid']}").status_code == 404
    assert balance(client, books["zomato"]) == "50.00"
    moved = client.get(f"/api/transactions/{one['tid']}").json()
    assert books["zomato"]["aid"] in {p["account"] for p in moved["postings"]}
    assert client.get(f"/api/recurring/{rule['rid']}").json()["to_account"] == books["zomato"]["aid"]
    assert client.get(f"/api/accounts/{books['loan']['aid']}").json()["payment_category_id"] == books["zomato"]["aid"]
    assert client.get("/api/budget/", params={"month": "2026-10-01"}).json()["ready_to_assign"] == ready_before
    assert client.get("/api/reports/trial-balance").json()["balanced"] is True


def test_the_plan_of_both_is_added(client, books):
    for category, amount in ((books["swiggy"], "100"), (books["zomato"], "50")):
        client.put(f"/api/budget/categories/{category['aid']}", json={"month": "2026-10-01", "amount": amount})
    merge(client, books["swiggy"], books["zomato"])
    lines = client.get("/api/budget/", params={"month": "2026-10-01"}).json()["lines"]
    zomato = next(line for line in lines if line["name"] == "Zomato")
    assert zomato["assigned"] == "150.00"


def test_history_remembers_the_merge(client, books):
    one = spend(client, books, books["swiggy"], "30")
    merge(client, books["swiggy"], books["zomato"])
    gone = client.get(f"/api/accounts/{books['swiggy']['aid']}/changes").json()
    assert [s["action"] for s in gone] == ["created", "deleted"] and gone[-1]["entry"][
        "merged_into"
    ] == "Expenses:Zomato"
    kept = client.get(f"/api/accounts/{books['zomato']['aid']}/changes").json()
    assert kept[-1]["action"] == "updated" and kept[-1]["changes"]["merged_in"] == "Expenses:Swiggy"
    entry = client.get(f"/api/transactions/{one['tid']}/changes").json()
    assert [s["action"] for s in entry] == ["created", "updated"] and entry[-1]["via"] == "api"
    assert {p["account"] for p in entry[-1]["entry"]["postings"]} == {"Assets:Bank", "Expenses:Zomato"}
    client.patch(f"/api/accounts/{books['zomato']['aid']}", json={"name": "Zomato"})
    assert len(client.get(f"/api/accounts/{books['zomato']['aid']}/changes").json()) == len(kept), (
        "a no-op save adds no step"
    )


def test_a_dry_run_changes_nothing(client, books):
    spend(client, books, books["swiggy"], "30")
    seen = merge(client, books["swiggy"], books["zomato"], dry_run="true").json()
    assert seen["dry_run"] is True and seen["merged"] is False and seen["entries_moved"] == 1
    assert client.get(f"/api/accounts/{books['swiggy']['aid']}").status_code == 200
    assert balance(client, books["swiggy"]) == "30.00" and balance(client, books["zomato"]) == "0.00"


def test_unsafe_merges_are_refused(client, books):
    roots = books["roots"]
    refused = {
        "itself": merge(client, books["swiggy"], books["swiggy"]),
        "other kind": merge(client, books["swiggy"], books["bank"]),
        "a root": merge(client, {"aid": roots["Expenses"]}, books["zomato"]),
        "into a root": merge(client, books["swiggy"], {"aid": roots["Expenses"]}),
    }
    kid = account(client, "Kid", books["zomato"]["aid"])
    refused["source with sub-accounts"] = merge(client, books["zomato"], books["swiggy"])
    assert all(r.status_code == 400 for r in refused.values()), {k: r.text for k, r in refused.items()}
    assert merge(client, books["swiggy"], kid).status_code == 200, "a group's sub-account can take it"


def test_money_between_the_two_blocks_the_merge(client, books, root_accounts):
    other = account(client, "Other", root_accounts["Assets"])
    client.post("/api/transactions/", json=body(other, books["bank"], "5", payee="move"))
    refused = merge(client, books["bank"], other)
    assert refused.status_code == 400 and "move money between" in refused.json()["detail"]


def test_budget_flag_must_match_and_closed_targets_are_refused(client, books, root_accounts):
    off = account(client, "Off", root_accounts["Assets"], on_budget=False)
    assert "budget" in merge(client, off, books["bank"]).json()["detail"]
    spare = account(client, "Spare", root_accounts["Expenses"])
    client.post(f"/api/accounts/{spare['aid']}/close")
    assert "closed" in merge(client, books["swiggy"], spare).json()["detail"]


def test_a_rule_using_both_blocks_the_merge(client, books):
    client.post(
        "/api/recurring/",
        json={
            "from_account": books["swiggy"]["aid"],
            "to_account": books["zomato"]["aid"],
            "amount": "5",
            "frequency": "monthly",
            "start_date": "2999-01-01",
            "payee": "Odd",
        },
    )
    refused = merge(client, books["swiggy"], books["zomato"])
    assert refused.status_code == 400 and "Odd" in refused.json()["detail"]


def test_the_built_in_groups_and_unknown_accounts(client, books, root_accounts):
    missing = {"aid": "00000000-0000-4000-8000-000000000000"}
    assert merge(client, missing, books["zomato"]).status_code == 404
    assert merge(client, books["swiggy"], missing).status_code == 404


def test_a_failure_part_way_leaves_everything_as_it_was(client, books, monkeypatch):
    spend(client, books, books["swiggy"], "30")

    def broken(self, *args, **kwargs):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(AccountService, "delete", broken)
    with pytest.raises(RuntimeError):
        merge(client, books["swiggy"], books["zomato"])
    monkeypatch.undo()
    assert balance(client, books["swiggy"]) == "30.00" and balance(client, books["zomato"]) == "0.00"
    assert client.get("/api/reports/trial-balance").json()["balanced"] is True


@pytest.mark.anyio
async def test_assistants_merge_only_when_allowed(session, client, books):
    spend(client, books, books["swiggy"], "30")
    args = {"from_account": "Swiggy", "into_account": "Zomato"}
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, name="Claude", scope="write")) as c:
        seen = payload(await c.call_tool("merge_accounts", args | {"dry_run": True}))
        assert seen["dry_run"] is True and seen["entries_moved"] == 1 and seen["balance_moved"] == "30.00"
        with pytest.raises(ToolFailed, match="not manage accounts or tags"):
            payload(await c.call_tool("merge_accounts", args))
    assert client.get(f"/api/accounts/{books['swiggy']['aid']}").status_code == 200
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, name="Boss", scope="manage")) as c:
        done = payload(await c.call_tool("merge_accounts", args))
        assert (
            done["merged"] is True and done["into"] == "Expenses:Zomato" and done["into_id"] == books["zomato"]["aid"]
        )
        history = payload(await c.call_tool("get_account_history", {"account": books["swiggy"]["aid"]}))
        assert history["exists"] is False and history["history"][-1]["by"] == "assistant (Boss)"

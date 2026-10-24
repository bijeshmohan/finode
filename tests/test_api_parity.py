"""The JSON API does what the web app does (the pieces added so the API is complete)."""

from datetime import date, timedelta

import pytest

TODAY = date.today()
THIS_MONTH = TODAY.replace(day=1).isoformat()
MISSING = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def books(client, root_accounts):
    def make(name, root, **extra):
        response = client.post("/api/accounts/", json={"name": name, "parent_id": root_accounts[root], **extra})
        assert response.status_code == 201, response.text
        return response.json()

    return {
        "bank": make("Bank", "Assets", balance="5000"),
        "food": make("Food", "Expenses"),
        "rent": make("Rent", "Expenses"),
        "salary": make("Salary", "Income"),
        "spare": make("Spare", "Assets"),
    }


def entry(client, books, amount="10", to="food", **extra):
    response = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": books[to]["aid"], "side": "debit", "amount": amount},
                {"account": books["bank"]["aid"], "side": "credit", "amount": amount},
            ],
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---- accounts -------------------------------------------------------------------------------------------------------


def test_close_reopen_and_the_closed_list(client, books):
    spare = books["spare"]["aid"]
    assert client.get("/api/accounts/closed").json() == []
    assert client.post(f"/api/accounts/{spare}/close").status_code == 200
    closed = client.get("/api/accounts/closed").json()
    assert (
        [c["aid"] for c in closed] == [spare] and closed[0]["root"] == "Assets" and closed[0]["path"].endswith("Spare")
    )
    reopened = client.post(f"/api/accounts/{spare}/reopen")
    assert reopened.status_code == 200 and reopened.json()["closed_on"] is None
    assert client.get("/api/accounts/closed").json() == []
    assert client.post(f"/api/accounts/{MISSING}/reopen").status_code == 404


def test_deleted_accounts_are_listed_and_restored(client, books):
    spare = books["spare"]["aid"]
    assert client.delete(f"/api/accounts/{spare}").status_code == 204
    gone = client.get("/api/accounts/deleted").json()
    assert len(gone) == 1 and gone[0]["account_id"] == spare and gone[0]["name"] == "Spare"
    restored = client.post(f"/api/accounts/deleted/{gone[0]['did']}/restore")
    assert restored.status_code == 200 and restored.json()["aid"] == spare, "back with its old id"
    assert client.get("/api/accounts/deleted").json() == []
    assert client.post(f"/api/accounts/deleted/{gone[0]['did']}/restore").status_code == 400, "already back"
    assert client.post(f"/api/accounts/deleted/{MISSING}/restore").status_code == 404


def test_the_register_has_the_running_balance(client, books):
    entry(client, books, "10")
    entry(client, books, "25")
    rows = client.get(f"/api/accounts/{books['bank']['aid']}/register").json()
    assert [float(r["change"]) for r in rows] == [5000, -10, -25], "the opening balance, then the two entries"
    assert [float(r["balance"]) for r in rows] == [5000, 4990, 4965]
    assert len(client.get(f"/api/accounts/{books['bank']['aid']}/register", params={"limit": 1}).json()) == 1
    assert len(client.get(f"/api/accounts/{books['bank']['aid']}/register", params={"offset": 1}).json()) == 2
    assert client.get(f"/api/accounts/{MISSING}/register").status_code == 404


# ---- transactions ---------------------------------------------------------------------------------------------------


def test_the_list_filters_like_the_web_page(client, books):
    entry(client, books, "10", payee="Swiggy", comment="lunch")
    entry(client, books, "20", to="rent", payee="Landlord")
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": books["bank"]["aid"], "side": "debit", "amount": "99"},
                {"account": books["salary"]["aid"], "side": "credit", "amount": "99"},
            ],
            "payee": "Employer",
        },
    )

    def payees(**params):
        return sorted(t["payee"] for t in client.get("/api/transactions/", params=params).json())

    assert payees(text="lunch") == ["Swiggy"]
    assert payees(kind="income") == ["Employer"]
    assert payees(kind="expense") == ["Landlord", "Swiggy"]
    assert payees(category=books["rent"]["aid"]) == ["Landlord"]
    assert payees(payee="swiggy") == ["Swiggy"]
    assert client.get("/api/transactions/", params={"kind": "bogus"}).status_code == 422


def test_payees_most_used_first(client, books):
    for payee in ("A", "B", "B"):
        entry(client, books, payee=payee)
    assert client.get("/api/transactions/payees").json() == [{"payee": "B", "count": 2}, {"payee": "A", "count": 1}]


def test_deleted_transactions_are_listed_and_restored(client, books):
    made = entry(client, books, "42", payee="Milk")
    assert client.get("/api/transactions/deleted").json() == []
    assert client.delete(f"/api/transactions/{made['tid']}").status_code == 204
    gone = client.get("/api/transactions/deleted").json()
    assert len(gone) == 1 and gone[0]["transaction"] == made["tid"] and gone[0]["action"] == "deleted"
    back = client.post(f"/api/transactions/deleted/{gone[0]['hid']}/restore")
    assert back.status_code == 200 and back.json()["tid"] == made["tid"] and back.json()["payee"] == "Milk"
    assert client.get("/api/transactions/deleted").json() == []
    assert client.post(f"/api/transactions/deleted/{gone[0]['hid']}/restore").status_code == 400
    assert client.post(f"/api/transactions/deleted/{MISSING}/restore").status_code == 404


def test_history_and_related(client, books):
    made = entry(client, books, "10", payee="Shop")
    client.patch(f"/api/transactions/{made['tid']}", json={"payee": "Shop 2"})
    history = client.get(f"/api/transactions/{made['tid']}/history").json()
    assert [h["action"] for h in history] == ["created", "updated"]
    refund = entry(client, books, "4", payee="Shop refund", related_id=made["tid"])
    assert [r["tid"] for r in client.get(f"/api/transactions/{made['tid']}/related").json()] == [refund["tid"]]
    assert client.get(f"/api/transactions/{refund['tid']}/related").json() == []
    assert client.get(f"/api/transactions/{MISSING}/history").status_code == 404
    assert client.get(f"/api/transactions/{MISSING}/related").status_code == 404


# ---- recurring ------------------------------------------------------------------------------------------------------


def test_pause_and_resume_a_recurring_rule(client, books):
    rule = client.post(
        "/api/recurring/",
        json={
            "from_account": books["bank"]["aid"],
            "to_account": books["food"]["aid"],
            "amount": "5",
            "frequency": "monthly",
            "start_date": (TODAY + timedelta(days=40)).isoformat(),
        },
    ).json()
    paused = client.post(f"/api/recurring/{rule['rid']}/pause")
    assert paused.status_code == 200 and paused.json()["active"] is False
    resumed = client.post(f"/api/recurring/{rule['rid']}/resume")
    assert resumed.status_code == 200 and resumed.json()["active"] is True
    assert client.post(f"/api/recurring/{MISSING}/pause").status_code == 404
    assert client.post(f"/api/recurring/{MISSING}/resume").status_code == 404


# ---- budget ---------------------------------------------------------------------------------------------------------


def budget(client):
    return client.get("/api/budget/").json()


def line(data, name):
    return next(l for l in data["lines"] if l["name"] == name)


def test_move_and_copy_budget_money(client, books):
    client.put(f"/api/budget/categories/{books['food']['aid']}", json={"amount": "100"})
    moved = client.post(
        "/api/budget/move",
        json={"from_category": books["food"]["aid"], "to_category": books["rent"]["aid"], "amount": "30"},
    )
    assert moved.status_code == 200, moved.text
    assert float(line(moved.json(), "Food")["available"]) == 70 and float(line(moved.json(), "Rent")["available"]) == 30
    too_much = client.post(
        "/api/budget/move",
        json={"from_category": books["food"]["aid"], "to_category": books["rent"]["aid"], "amount": "500"},
    )
    assert too_much.status_code == 400
    next_month = (date.fromisoformat(THIS_MONTH) + timedelta(days=32)).replace(day=1).isoformat()
    copied = client.post("/api/budget/copy", json={"month": next_month})
    assert copied.status_code == 200
    assert float(line(client.get("/api/budget/", params={"month": next_month}).json(), "Food")["assigned"]) == 70


def test_include_an_account_in_the_budget(client, books):
    out = client.post(
        "/api/accounts/", json={"name": "Outside", "parent_id": books["bank"]["parent_id"], "on_budget": False}
    ).json()
    done = client.post(f"/api/budget/accounts/{out['aid']}/include")
    assert done.status_code == 200 and client.get(f"/api/accounts/{out['aid']}").json()["on_budget"] is True
    assert client.post(f"/api/budget/accounts/{MISSING}/include").status_code == 404


def test_a_group_budget(client, books, root_accounts):
    dining = client.post("/api/accounts/", json={"name": "Dining", "parent_id": root_accounts["Expenses"]}).json()
    cafe = client.post("/api/accounts/", json={"name": "Cafe", "parent_id": dining["aid"]}).json()
    client.put(f"/api/budget/categories/{cafe['aid']}", json={"amount": "40"})
    assert client.put(f"/api/budget/groups/{dining['aid']}", json={"total": "10"}).status_code == 400, (
        "below its categories"
    )
    ok = client.put(f"/api/budget/groups/{dining['aid']}", json={"total": "60"})
    assert ok.status_code == 200, ok.text
    assert float(line(ok.json(), "Dining")["assigned"]) == 60


def test_goals_from_start_to_finish(client, books):
    made = client.post("/api/budget/goals", json={"name": "Laptop", "amount": "6000", "by": "2999-12-01"})
    assert made.status_code == 201, made.text
    goal = made.json()["goals"][0]
    gid = goal["gid"]
    assert goal["name"] == "Laptop" and float(goal["amount"]) == 6000
    assert (
        client.post("/api/budget/goals", json={"name": "laptop", "amount": "1", "by": "2999-12-01"}).status_code == 400
    )
    changed = client.put(f"/api/budget/goals/{gid}", json={"name": "New laptop", "amount": "7000", "by": "2999-12-01"})
    assert changed.json()["goals"][0]["name"] == "New laptop" and float(changed.json()["goals"][0]["amount"]) == 7000
    saved = client.put(f"/api/budget/goals/{gid}/month", json={"amount": "500"})
    assert saved.status_code == 200 and float(saved.json()["goals"][0]["available"]) == 500
    used = client.post(f"/api/budget/goals/{gid}/use", json={"category": books["rent"]["aid"], "amount": "200"})
    assert used.status_code == 200 and float(line(used.json(), "Rent")["available"]) == 200
    assert (
        client.post(
            f"/api/budget/goals/{gid}/use", json={"category": books["rent"]["aid"], "amount": "9999"}
        ).status_code
        == 400
    )
    assert client.delete(f"/api/budget/goals/{gid}").status_code == 204
    assert budget(client)["goals"] == []
    assert client.delete(f"/api/budget/goals/{gid}").status_code == 404
    assert client.put(f"/api/budget/goals/{gid}/month", json={"amount": "1"}).status_code == 404


# ---- reports and profile --------------------------------------------------------------------------------------------


def test_summary_and_breakdown(client, books):
    entry(client, books, "30")
    entry(client, books, "70", to="rent")
    summary = client.get("/api/reports/summary").json()
    assert float(summary["expenses"]) == 100 and float(summary["net_worth"]) == 4900
    breakdown = client.get("/api/reports/breakdown").json()
    assert breakdown["root"] == "Expenses" and float(breakdown["total"]) == 100
    assert float(breakdown["lines"][0]["amount"]) == 70, "largest first"
    assert client.get("/api/reports/breakdown", params={"kind": "income"}).json()["root"] == "Income"
    assert (
        client.get("/api/reports/summary", params={"date_from": "2026-02-01", "date_to": "2026-01-01"}).status_code
        == 400
    )


def test_the_currency_list(client):
    listed = client.get("/api/profile/currencies").json()
    inr = next(c for c in listed if c["code"] == "INR")
    assert inr["decimals"] == 2 and len(listed) > 100

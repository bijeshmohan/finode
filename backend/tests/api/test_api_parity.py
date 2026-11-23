"""The JSON API does everything the app does (the pieces added so the API is complete)."""

from datetime import date, timedelta

import pytest

from tests.books import into, leg, post_account

TODAY = date.today()
THIS_MONTH = TODAY.replace(day=1).isoformat()
MISSING = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def books(client, root_accounts):
    def make(name, root, **extra):
        response = post_account(client, {"name": name, "parent_id": root_accounts[root], **extra})
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
                leg(books[to], "debit", amount),
                leg(books["bank"], "credit", amount),
            ],
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---- accounts -------------------------------------------------------------------------------------------------------


def test_close_reopen_and_the_closed_list(client, books):
    spare = books["spare"]["id"]
    assert client.get("/api/accounts/closed").json() == []
    assert client.post(f"/api/accounts/{spare}/close").status_code == 200
    closed = client.get("/api/accounts/closed").json()
    assert (
        [c["id"] for c in closed] == [spare] and closed[0]["root"] == "Assets" and closed[0]["path"].endswith("Spare")
    )
    reopened = client.post(f"/api/accounts/{spare}/reopen")
    assert reopened.status_code == 200 and reopened.json()["closed_on"] is None
    assert client.get("/api/accounts/closed").json() == []
    assert client.post(f"/api/accounts/{MISSING}/reopen").status_code == 404


def test_the_register_has_the_running_balance(client, books):
    entry(client, books, "10")
    entry(client, books, "25")
    rows = client.get(f"/api/accounts/{books['bank']['id']}/register").json()
    assert [float(r["change"]) for r in rows] == [5000, -10, -25], "the opening balance, then the two entries"
    assert [float(r["balance"]) for r in rows] == [5000, 4990, 4965]
    assert len(client.get(f"/api/accounts/{books['bank']['id']}/register", params={"limit": 1}).json()) == 1
    assert len(client.get(f"/api/accounts/{books['bank']['id']}/register", params={"offset": 1}).json()) == 2
    assert client.get(f"/api/accounts/{MISSING}/register").status_code == 404


# ---- transactions ---------------------------------------------------------------------------------------------------


def test_the_list_filters_like_the_web_page(client, books):
    entry(client, books, "10", payee="Swiggy", comment="lunch")
    entry(client, books, "20", to="rent", payee="Landlord")
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(books["bank"], "debit", "99"),
                leg(books["salary"], "credit", "99"),
            ],
            "payee": "Employer",
        },
    )

    def payees(**params):
        return sorted(t["payee"] for t in client.get("/api/transactions/", params=params).json())

    assert payees(text="lunch") == ["Swiggy"]
    assert payees(kind="income") == ["Employer"]
    assert payees(kind="expense") == ["Landlord", "Swiggy"]
    assert payees(category_id=books["rent"]["id"]) == ["Landlord"]
    assert payees(payee="swiggy") == ["Swiggy"]
    assert client.get("/api/transactions/", params={"kind": "bogus"}).status_code == 422


def test_payees_most_used_first(client, books):
    for payee in ("A", "B", "B"):
        entry(client, books, payee=payee)
    assert client.get("/api/transactions/payees").json() == [{"payee": "B", "count": 2}, {"payee": "A", "count": 1}]


def test_related(client, books):
    made = entry(client, books, "10", payee="Shop")
    refund = entry(client, books, "4", payee="Shop refund", related_id=made["id"])
    assert [r["id"] for r in client.get(f"/api/transactions/{made['id']}/related").json()] == [refund["id"]]
    assert client.get(f"/api/transactions/{refund['id']}/related").json() == []
    assert client.get(f"/api/transactions/{MISSING}/related").status_code == 404


# ---- recurring ------------------------------------------------------------------------------------------------------


def test_pause_and_resume_a_recurring_rule(client, books):
    rule = client.post(
        "/api/recurring/",
        json={
            "from_account_id": books["bank"]["id"],
            **into(client, books["food"]),
            "amount": "5",
            "frequency": "monthly",
            "start_date": (TODAY + timedelta(days=40)).isoformat(),
        },
    ).json()
    paused = client.post(f"/api/recurring/{rule['id']}/pause")
    assert paused.status_code == 200 and paused.json()["active"] is False
    resumed = client.post(f"/api/recurring/{rule['id']}/resume")
    assert resumed.status_code == 200 and resumed.json()["active"] is True
    assert client.post(f"/api/recurring/{MISSING}/pause").status_code == 404
    assert client.post(f"/api/recurring/{MISSING}/resume").status_code == 404


# ---- budget ---------------------------------------------------------------------------------------------------------


def budget(client):
    return client.get("/api/budget/").json()


def line(data, name):
    return next(l for l in data["lines"] if l["name"] == name)


def test_a_rule_from_the_recurring_forms_rows(client, books):
    body = {
        "payee": "Landlord",
        "rows": [
            {"choice": books["bank"]["id"], "side": "credit", "amount": "900"},
            {"choice": books["rent"]["id"], "side": "debit", "amount": "900"},
        ],
        "start_date": "2999-01-01",
    }
    made = client.post("/api/recurring/form", json=body)
    assert made.status_code == 201, made.text
    rule = made.json()
    assert rule["category_id"] == books["rent"]["id"] and rule["amount"] == "900.00"
    body["every"] = 2
    changed = client.put(f"/api/recurring/{rule['id']}/form", json=body)
    assert changed.status_code == 200 and changed.json()["every"] == 2
    assert client.put(f"/api/recurring/{MISSING}/form", json=body).status_code == 404


def test_a_person_with_an_opening_balance_and_reversing_an_entry_of_theirs(client, books):
    made = client.post("/api/contacts/", json={"name": "Asha", "opening": {"direction": "payable", "amount": "40"}})
    assert made.status_code == 201 and made.json()["payable"] == "40.00"
    who = made.json()["id"]
    opening = client.get(f"/api/contacts/{who}/activity").json()["items"][0]
    done = client.post(f"/api/contacts/{who}/entries/{opening['transaction_id']}/reverse")
    assert done.status_code == 204 and client.get(f"/api/contacts/{who}").json()["payable"] == "0.00"
    assert client.post(f"/api/contacts/{who}/entries/{MISSING}/reverse").status_code == 404
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_move_and_copy_budget_money(client, books):
    client.put(f"/api/budget/categories/{books['food']['id']}", json={"amount": "100"})
    moved = client.post(
        "/api/budget/move",
        json={"from_category": books["food"]["id"], "to_category": books["rent"]["id"], "amount": "30"},
    )
    assert moved.status_code == 200, moved.text
    assert float(line(moved.json(), "Food")["available"]) == 70 and float(line(moved.json(), "Rent")["available"]) == 30
    too_much = client.post(
        "/api/budget/move",
        json={"from_category": books["food"]["id"], "to_category": books["rent"]["id"], "amount": "500"},
    )
    assert too_much.status_code == 400
    next_month = (date.fromisoformat(THIS_MONTH) + timedelta(days=32)).replace(day=1).isoformat()
    copied = client.post("/api/budget/copy", json={"month": next_month})
    assert copied.status_code == 200
    assert float(line(client.get("/api/budget/", params={"month": next_month}).json(), "Food")["assigned"]) == 70


def test_summary_and_breakdown(client, books):
    entry(client, books, "30")
    entry(client, books, "70", to="rent")
    summary = client.get("/api/reports/summary").json()
    assert float(summary["expenses"]) == 100 and float(summary["cash_on_hand"]) == 4900
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


# ---- your data ------------------------------------------------------------------------------------------------------


def test_data_options(client):
    options = client.get("/api/data-options").json()
    assert options == {
        "can_import": True,
        "can_restore": True,
        "confirm_word": "test@example.com",
        "can_delete_login": False,
    }


def test_erase_needs_the_confirm_word(client, books):
    entry(client, books)
    assert client.post("/api/erase", json={"confirm": "nope"}).json()["detail"] == "Type test@example.com to confirm."
    assert client.get("/api/transactions/").json() != []
    assert client.post("/api/erase", json={"confirm": " TEST@example.com "}).status_code == 204
    assert client.get("/api/transactions/").json() == []


def test_delete_account_when_logins_cannot_be_deleted(client, books):
    entry(client, books)
    refused = client.post("/api/delete-account", json={"confirm": "test@example.com"})
    assert refused.status_code == 503
    assert refused.json()["detail"] == "Deleting your login is not set up here: ask the person who runs finode."
    assert client.get("/api/transactions/").json() != []


def test_delete_account(client, books, monkeypatch):
    from finode.config import settings
    from finode.routers import data as data_router

    monkeypatch.setattr(settings, "supabase_service_role_key", "sb_secret_test_key")
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    deleted = []
    monkeypatch.setattr(data_router, "delete_user", deleted.append)
    entry(client, books)
    response = client.post("/api/delete-account", json={"confirm": "test@example.com"})
    assert response.status_code == 204 and len(deleted) == 1
    assert any(c.startswith("finode_access=") and "Max-Age=0" in c for c in response.headers.get_list("set-cookie"))
    assert client.get("/api/transactions/").json() == []

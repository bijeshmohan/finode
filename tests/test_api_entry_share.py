"""The finode app's Split and quick-add through the API: a bill or an income shared with people saved with
/api/entries, the form's view of it (and of several lines), the share preview, and where a new account or category can
go."""

from .books import category, post_account
from .svc import services
from .test_api_entries import entry, made
from .test_isolation import B_USER, signed_in_as


def form_view(client, **params):
    response = client.get("/api/views/entry-form", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def shared_bill(bank, food, ada, total="900", **share):
    return {
        "kind": "expense",
        "payee": "Dinner",
        "total": total,
        "share": {
            "kind": "expense",
            "category_id": food["id"],
            "account_id": bank["id"],
            "people": [{"contact_id": ada["id"]}],
            **share,
        },
    }


def owed(client, person):
    got = client.get(f"/api/contacts/{person['id']}").json()
    return got["receivable"], got["payable"]


def test_a_bill_shared_through_the_api(client, session, root_accounts):
    bank, food, ada = made(client, root_accounts)
    saved = client.post("/api/entries", json=shared_bill(bank, food, ada))
    assert saved.status_code == 201, saved.text
    assert saved.json()["recorded"] == "expense-shared"
    assert owed(client, ada) == ("450.00", "0.00")
    assert services(session).reports.trial_balance().balanced


def test_an_income_shared_through_the_api(client, session, root_accounts):
    bank, _, ada = made(client, root_accounts)
    rent = category(client, "Rent", "earning")
    saved = client.post(
        "/api/entries",
        json={
            "kind": "income",
            "payee": "Rent, Flat 4B",
            "total": "10000",
            "share": {
                "kind": "income",
                "category_id": rent["id"],
                "account_id": bank["id"],
                "people": [{"contact_id": ada["id"], "theirs": "4000"}],
            },
        },
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["recorded"] == "income-shared"
    assert owed(client, ada) == ("0.00", "4000.00")
    assert services(session).reports.trial_balance().balanced


def test_a_shared_bill_edited_through_the_api(client, session, root_accounts):
    bank, food, ada = made(client, root_accounts)
    saved = client.post("/api/entries", json=entry(bank, food, "600")).json()
    changed = client.put(f"/api/entries/{saved['transaction_id']}", json=shared_bill(bank, food, ada, "600"))
    assert changed.status_code == 200, changed.text
    assert owed(client, ada) == ("300.00", "0.00")
    back = client.put(f"/api/entries/{saved['transaction_id']}", json=entry(bank, food, "600"))
    assert back.status_code == 200, back.text
    assert owed(client, ada) == ("0.00", "0.00")
    assert services(session).reports.trial_balance().balanced


def test_a_conflict_is_409_and_a_stranger_is_404(client, root_accounts):
    bank, food, ada = made(client, root_accounts)
    saved = client.post("/api/entries", json=shared_bill(bank, food, ada)).json()
    paid = client.post(
        f"/api/contacts/{ada['id']}/settlements",
        json={"direction": "received", "amount": "450", "account_id": bank["id"]},
    )
    assert paid.status_code == 201, paid.text
    refused = client.put(f"/api/entries/{saved['transaction_id']}", json=entry(bank, food, "900"))
    assert refused.status_code == 409, refused.text
    with signed_in_as(B_USER):
        stranger = client.post("/api/entries", json=shared_bill(bank, food, ada))
    assert stranger.status_code == 404, stranger.text


def test_the_form_view_of_a_shared_bill(client, root_accounts):
    bank, food, ada = made(client, root_accounts)
    body = shared_bill(bank, food, ada, "1000", method="percentage", self_value="60")
    body["share"]["people"] = [{"contact_id": ada["id"], "value": "40"}]
    saved = client.post("/api/entries", json=body).json()
    seen = form_view(client, transaction_id=saved["transaction_id"])
    assert (seen["mode"], seen["kind"], seen["total"]) == ("split", "expense", "1000.00")
    share = seen["expense_share"]
    assert share["method"] == "percentage" and share["category_id"] == food["id"] and share["account_id"] == bank["id"]
    assert [p["contact_id"] for p in share["people"]] == [ada["id"]]
    assert seen["people"] == [{"id": ada["id"], "name": "Ada"}]
    assert "simple" not in seen


def test_the_form_view_of_several_lines(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    rent = category(client, "Rent")
    saved = client.post(
        "/api/entries",
        json={
            "kind": "expense",
            "date": "2026-11-01",
            "rows": [
                {"choice": bank["id"], "side": "credit", "amount": "100", "posted_on": "2026-11-03"},
                {"choice": food["id"], "side": "debit", "amount": "60"},
                {"choice": rent["id"], "side": "debit", "amount": "40"},
            ],
        },
    ).json()
    seen = form_view(client, transaction_id=saved["transaction_id"])
    assert seen["mode"] == "simple"
    assert sorted((r["choice"], r["amount"]) for r in seen["to_rows"]) == sorted(
        [(food["id"], "60.00"), (rent["id"], "40.00")]
    )
    assert seen["from_rows"][0]["posted_on"] == "2026-11-03"


def test_split_with_a_person_starts_ticked(client, root_accounts):
    _, _, ada = made(client, root_accounts)
    seen = form_view(client, mode="split", **{"with": ada["id"]})
    assert (seen["mode"], seen["kind"]) == ("split", "expense")
    assert [p["contact_id"] for p in seen["expense_share"]["people"]] == [ada["id"]]
    assert form_view(client)["mode"] == "simple"


def test_the_parents_a_new_account_can_go_under(client, root_accounts):
    post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"]})
    seen = form_view(client)
    parents = {p["name"]: p for p in seen["account_parents"]}
    assert "Expenses" not in parents and "Income" not in parents and "Opening Balances" not in parents
    assert parents["Assets"]["opening_balance"] is True and parents["Assets"]["depth"] == 0
    assert parents["Bank"]["depth"] == 1 and parents["Bank"]["root"] == "Assets"
    assert parents["Equity"]["opening_balance"] is False
    food = category(client, "Food")
    assert {"id": food["id"], "name": "Food", "kind": "spending"} in form_view(client)["category_parents"]


def test_the_share_preview(client, root_accounts):
    bank, food, ada = made(client, root_accounts)
    seen = client.post("/api/views/entry-share-preview", json=shared_bill(bank, food, ada))
    assert seen.status_code == 200, seen.text
    got = seen.json()
    assert got["kind"] == "expense" and got["income"] is None
    assert [(o["name"], o["direction"], o["amount"]) for o in got["expense"]["owed"]] == [
        ("Ada", "receivable", "450.00")
    ]


def test_the_share_preview_says_what_is_wrong(client, root_accounts):
    bank, food, ada = made(client, root_accounts)
    body = shared_bill(bank, food, ada)
    body["share"]["account_id"] = None
    refused = client.post("/api/views/entry-share-preview", json=body)
    assert (refused.status_code, refused.json()["detail"]) == (400, "choose the account you paid from!")
    with signed_in_as(B_USER):
        stranger = client.post("/api/views/entry-share-preview", json=shared_bill(bank, food, ada))
    assert (stranger.status_code, stranger.json()["detail"]) == (404, "contact not found!")


def test_a_split_records_what_the_web_form_records(client, root_accounts):
    bank, food, ada = made(client, root_accounts)
    client.post("/api/entries", json=shared_bill(bank, food, ada))
    web = client.post(
        "/transactions/split",
        data={
            "mode": "split",
            "kind": "expense",
            "total": "900",
            "payee": "Dinner",
            "category_id": food["id"],
            "account_id": bank["id"],
            "split_method": "equal",
            f"with_{ada['id']}": "1",
        },
    )
    assert web.status_code == 200 and "HX-Redirect" in web.headers, web.text
    assert owed(client, ada) == ("900.00", "0.00"), "450 from each"
    bills = client.get("/api/shared-expenses/").json()
    assert sorted((b["description"], b["total_amount"], b["split_method"]) for b in bills) == [
        ("Dinner", "900.00", "equal"),
        ("Dinner", "900.00", "equal"),
    ]

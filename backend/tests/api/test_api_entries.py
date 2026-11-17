"""/api/entries: what the finode app's Add screen saves."""

from decimal import Decimal

from tests.books import category, post_account
from tests.guards.test_isolation import B_USER, signed_in_as
from tests.svc import services


def made(client, root_accounts):
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"}).json()
    food = category(client, "Food")
    ada = client.post("/api/contacts/", json={"name": "Ada"}).json()
    return bank, food, ada


def entry(bank, to, amount="30", **extra):
    return {
        "kind": "expense",
        "rows": [
            {"choice": bank["id"], "side": "credit", "amount": amount},
            {"choice": to["id"], "side": "debit", "amount": amount},
        ],
        **extra,
    }


def lines(client, transaction_id):
    found = client.get(f"/api/transactions/{transaction_id}").json()
    return sorted((p["account_id"], p["side"], Decimal(p["amount"]), p["category_id"]) for p in found["postings"])


def test_an_entry_on_a_category_posts_on_expenses_with_the_category(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    saved = client.post("/api/entries", json=entry(bank, food, payee="Swiggy"))
    assert saved.status_code == 201, saved.text
    assert saved.json()["recorded"] == "transaction"
    assert lines(client, saved.json()["transaction_id"]) == sorted(
        [
            (bank["id"], "credit", Decimal("30"), None),
            (root_accounts["Expenses"], "debit", Decimal("30"), food["id"]),
        ]
    )


def test_a_transfer_to_a_person_is_a_loan(client, root_accounts):
    bank, _, ada = made(client, root_accounts)
    saved = client.post("/api/entries", json={**entry(bank, ada, "200"), "kind": "transfer"})
    assert saved.status_code == 201 and saved.json()["recorded"] == "transfer"
    assert client.get(f"/api/contacts/{ada['id']}").json()["receivable"] == "200.00"


def test_editing_an_entry(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    saved = client.post("/api/entries", json=entry(bank, food)).json()
    changed = client.put(f"/api/entries/{saved['transaction_id']}", json=entry(bank, food, "45", payee="Cafe"))
    assert changed.status_code == 200, changed.text
    found = client.get(f"/api/transactions/{saved['transaction_id']}").json()
    assert found["payee"] == "Cafe" and {p["amount"] for p in found["postings"]} == {"45.00"}


def test_refusals_say_why(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    body = entry(bank, food)
    body["rows"][1]["amount"] = "20"
    refused = client.post("/api/entries", json=body)
    assert refused.status_code == 400 and refused.json()["detail"]


def test_another_persons_entry_is_not_found(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    saved = client.post("/api/entries", json=entry(bank, food)).json()
    with signed_in_as(B_USER):
        assert client.put(f"/api/entries/{saved['transaction_id']}", json=entry(bank, food)).status_code == 404


def test_the_books_stay_balanced(client, session, root_accounts):
    bank, food, ada = made(client, root_accounts)
    client.post("/api/entries", json=entry(bank, food))
    client.post("/api/entries", json={**entry(bank, ada, "50"), "kind": "transfer"})
    assert services(session).reports.trial_balance().balanced


# Ported from test_web_transaction_form.py (the old Add screen), step 10: what /api/entries refuses and records.


def rows(*lines):
    return [{"choice": c, "side": s, "amount": a, **({"posted_on": p} if p else {})} for c, s, a, p in lines]


def test_an_entry_with_no_date_is_today_and_has_no_payee(client, root_accounts):
    from finode.clock import local_today

    bank, food, _ = made(client, root_accounts)
    saved = client.post("/api/entries", json=entry(bank, food))
    assert saved.status_code == 201, saved.text
    [tx] = client.get("/api/transactions/").json()[:1]
    assert tx["date"] == local_today().isoformat() and tx["payee"] is None


def test_an_amount_must_be_a_positive_number_with_the_currencys_places(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    before = len(client.get("/api/transactions/").json())
    for amount in ("0", "-3", "abc", "1.234", ""):
        refused = client.post("/api/entries", json=entry(bank, food, amount=amount))
        assert refused.status_code in (400, 422), amount
    assert len(client.get("/api/transactions/").json()) == before, "nothing is saved"


def test_a_root_account_a_single_line_and_a_line_with_no_account_are_refused(client, root_accounts):
    bank, _food, _ = made(client, root_accounts)
    root = client.post(
        "/api/entries",
        json={
            "kind": "transfer",
            "rows": rows((bank["id"], "debit", "5", None), (root_accounts["Assets"], "credit", "5", None)),
        },
    )
    assert root.status_code == 400 and "root account" in root.json()["detail"]
    one = client.post("/api/entries", json={"kind": "expense", "rows": rows((bank["id"], "credit", "5", None))})
    assert one.status_code in (400, 422)
    nobody = client.post(
        "/api/entries",
        json={
            "kind": "expense",
            "rows": [{"choice": None, "side": "debit", "amount": "5"}, *rows((bank["id"], "credit", "5", None))],
        },
    )
    assert nobody.status_code in (400, 422)


def test_an_unbalanced_entry_says_it_must_balance(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    body = entry(bank, food)
    body["rows"][1]["amount"] = "25"
    refused = client.post("/api/entries", json=body)
    assert refused.status_code == 400 and "must balance" in refused.json()["detail"]


def test_an_edit_moves_the_entry_and_a_refused_edit_changes_nothing(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    other = post_account(client, {"name": "Cash", "parent_id": root_accounts["Assets"], "balance": "100"}).json()
    first = client.post("/api/entries", json=entry(bank, food, amount="10")).json()
    moved = client.put(
        f"/api/entries/{first['transaction_id']}",
        json={**entry(other, food, amount="15.50"), "date": "2026-07-01", "payee": "moved"},
    )
    assert moved.status_code == 200, moved.text
    again = client.get(f"/api/transactions/{first['transaction_id']}").json()
    assert (again["payee"], again["date"]) == ("moved", "2026-07-01")
    assert {(p["account_id"], p["amount"]) for p in again["postings"] if p["side"] == "credit"} == {
        (other["id"], "15.50")
    }
    body = entry(other, food, amount="12")
    body["rows"][1]["amount"] = "11"
    assert client.put(f"/api/entries/{first['transaction_id']}", json=body).status_code == 400
    assert client.get(f"/api/transactions/{first['transaction_id']}").json() == again, "a refused edit changes nothing"
    missing = "00000000-0000-4000-8000-0000000000ff"
    assert client.put(f"/api/entries/{missing}", json=entry(bank, food)).status_code == 404


def test_a_line_keeps_its_posting_day_and_one_before_the_entry_is_refused(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    body = {
        "kind": "expense",
        "date": "2026-05-04",
        "rows": rows((food["id"], "debit", "42.50", None), (bank["id"], "credit", "42.50", "2026-05-06")),
    }
    saved = client.post("/api/entries", json=body)
    assert saved.status_code == 201, saved.text
    lines_ = client.get(f"/api/transactions/{saved.json()['transaction_id']}").json()["postings"]
    assert {p["side"]: p["posted_on"] for p in lines_} == {"debit": None, "credit": "2026-05-06"}
    form = client.get("/api/views/entry-form", params={"transaction_id": saved.json()["transaction_id"]}).json()
    assert [r["posted_on"] for r in form["from_rows"]] == ["2026-05-06"], "the edit form shows it"
    early = {**body, "rows": rows((food["id"], "debit", "10", None), (bank["id"], "credit", "10", "2026-05-01"))}
    refused = client.post("/api/entries", json=early)
    assert refused.status_code == 400 and "before the entry" in refused.json()["detail"]
    repeat = client.get("/api/views/entry-form", params={"repeat": saved.json()["transaction_id"]}).json()
    assert all(r["posted_on"] is None for r in repeat["from_rows"] + repeat["to_rows"]), (
        "a repeat starts on its own day"
    )


# Ported from test_related_transactions.py (the old Add screen), step 10: an entry's link to an earlier one.


def test_an_entry_keeps_its_link_an_edit_can_remove_it_and_a_missing_one_is_refused(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    first = client.post("/api/entries", json=entry(bank, food, amount="1000", payee="Swiggy")).json()
    refund = {
        "kind": "other",
        "payee": "Swiggy refund",
        "rows": rows((bank["id"], "debit", "300", None), (food["id"], "credit", "300", None)),
    }
    saved = client.post("/api/entries", json={**refund, "related_id": first["transaction_id"]})
    assert saved.status_code == 201, saved.text
    second = saved.json()["transaction_id"]
    assert client.get(f"/api/transactions/{second}").json()["related_id"] == first["transaction_id"]
    form = client.get("/api/views/entry-form", params={"transaction_id": second}).json()
    assert form["related"]["id"] == first["transaction_id"], "the edit form shows the link"
    cleared = client.put(f"/api/entries/{second}", json={**refund, "related_id": None})
    assert cleared.status_code == 200 and client.get(f"/api/transactions/{second}").json()["related_id"] is None
    missing = client.post("/api/entries", json={**refund, "related_id": "00000000-0000-4000-8000-0000000000aa"})
    assert missing.status_code == 400 and "related" in missing.json()["detail"]

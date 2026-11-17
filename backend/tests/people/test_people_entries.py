"""People through the app (ported from the old pages' tests, step 10): the list and a person's page (/api/views/people),
lending, borrowing and paying back on the Add screen, bills and income shared with people, and turning an entry into
any of these and back, all saved through /api/entries and the people routes the app uses."""

import pytest

from tests.books import category

OK = (200, 201)


@pytest.fixture
def bank(client, root_accounts):
    return client.post(
        "/api/accounts/", json={"name": "HDFC", "parent_id": root_accounts["Assets"], "balance": "10000"}
    ).json()


def person(client, name="Alice", **extra):
    return client.post("/api/contacts/", json={"name": name, **extra}).json()


def view(client, path, status=200, **params):
    answer = client.get(f"/api/views/{path}", params=params)
    assert answer.status_code == status, (path, answer.status_code, answer.text[:200])
    return answer.json()


def contact(client, who) -> dict:
    return client.get(f"/api/contacts/{who['id']}").json()


def balance(client, name="HDFC") -> float:
    return float(next(a for a in client.get("/api/accounts/").json() if a["name"] == name)["balance"])


def lend(client, who, bank, amount="500", **extra):
    made = client.post(
        f"/api/contacts/{who['id']}/transfers",
        json={"direction": "sent", "purpose": "loan", "amount": amount, "account_id": bank["id"], **extra},
    )
    assert made.status_code == 201, made.text
    return made.json()


def reverse(client, who, transaction_id):
    return client.post(f"/api/contacts/{who['id']}/entries/{transaction_id}/reverse")


def entry_body(form: dict) -> dict:
    """The Add screen's body for what the old form posted: rows (account, side, amount), or with mode=split the Split's
    total and how it is shared (with_<id>, value_<id>, paid_<id>; for income theirs_<id>, got_<id>)."""
    body: dict = {k: form[k] for k in ("date", "payee", "comment", "payee_contact") if k in form}
    body["kind"] = form.get("kind", "other")
    body["tags"] = form.get("tags", [])
    if form.get("mode") == "split" and form.get("kind") != "transfer":
        body["total"] = form["total"]
        ids = {k.split("_", 1)[1] for k in form if k.startswith(("with_", "value_", "paid_", "theirs_", "got_"))}
        ids -= {"self"}
        if form.get("kind") == "income":
            body["share"] = {
                "kind": "income",
                "category_id": form.get("income_category_id"),
                "account_id": form.get("income_account_id"),
                "people": [
                    {"contact_id": i, "theirs": form.get(f"theirs_{i}"), "received": form.get(f"got_{i}")}
                    for i in sorted(ids)
                ],
            }
        else:
            body["kind"] = "expense"
            body["share"] = {
                "kind": "expense",
                "category_id": form.get("category_id"),
                "account_id": form.get("account_id"),
                "method": form.get("split_method", "equal"),
                "self_value": form.get("value_self"),
                "self_paid": form.get("paid_self"),
                "people": [
                    {"contact_id": i, "value": form.get(f"value_{i}"), "paid": form.get(f"paid_{i}")}
                    for i in sorted(ids)
                    if f"with_{i}" in form
                ],
            }
        return body
    body["rows"] = [
        {"choice": c, "side": s, "amount": a}
        for c, s, a in zip(form["account"], form["side"], form["amount"], strict=True)
        if c
    ]
    return body


def save(client, form: dict, transaction_id: str | None = None):
    body = entry_body(form)
    if transaction_id:
        return client.put(f"/api/entries/{transaction_id}", json=body)
    return client.post("/api/entries", json=body)


def ordinary_expense(client, bank, name="Cab", amount="300", **extra):
    misc = category(client, name + " spend")
    made = client.post(
        "/api/transactions/",
        json={
            "payee": name,
            "postings": [
                {"category_id": misc["id"], "side": "debit", "amount": amount},
                {"account_id": bank["id"], "side": "credit", "amount": amount},
            ],
            **extra,
        },
    )
    assert made.status_code == 201, made.text
    return made.json(), misc


def rows(bank, who, sent=True, amount="300"):
    return {
        "account": [bank["id"], who["id"]] if sent else [who["id"], bank["id"]],
        "side": ["credit", "debit"],
        "amount": [amount, amount],
        "date": "2026-11-01",
        "comment": "Cab money",
    }


def people_form(bank, dining, who, method="equal", total="1500", **extra):
    """The Split of a bill: the total, who it is for, how it is split and who paid."""
    data = {
        "mode": "split",
        "total": total,
        "payee": "Dinner",
        "date": "2026-11-08",
        "category_id": dining["id"],
        "account_id": bank["id"],
        "split_method": method,
    }
    data.update({f"with_{p['id']}": "1" for p in who})
    data.update(extra)
    return data


def income_form(bank, rent, who, **extra):
    """The Split of an income: the total, which part is theirs, and where it landed."""
    data = {
        "mode": "split",
        "kind": "income",
        "total": "10000",
        "payee": "Rent, Flat 4B",
        "date": "2026-11-08",
        "income_category_id": rent["id"],
        "income_account_id": bank["id"],
    }
    data.update({f"theirs_{p['id']}": "4000" for p in who})
    data.update(extra)
    return data


def spent(client, name="Dining"):
    lines = client.get("/api/reports/breakdown").json()["lines"]
    return next((float(x["amount"]) for x in lines if x["account"] == name), 0.0)


def earned(client, name="Rent"):
    lines = client.get("/api/reports/breakdown", params={"kind": "income"}).json()["lines"]
    return next((float(x["amount"]) for x in lines if x["account"] == name), 0.0)


# ---- the list and a person ------------------------------------------------------------------------------------------


def test_adding_a_person_needs_a_name_of_their_own(client):
    assert client.post("/api/contacts/", json={"name": "Alice", "phone": "99"}).status_code == 201
    assert client.post("/api/contacts/", json={"name": "  "}).status_code in (400, 422)
    again = client.post("/api/contacts/", json={"name": "alice"})
    assert again.status_code == 400 and "already" in again.json()["detail"]
    assert [r["name"] for r in view(client, "people")["rows"]] == ["Alice"]


def test_the_list_shows_who_owes_what(client, bank):
    alice, bob = person(client), person(client, "Bob")
    lend(client, alice, bank)
    client.post(
        f"/api/contacts/{bob['id']}/transfers",
        json={"direction": "received", "purpose": "borrowing", "amount": "200", "account_id": bank["id"]},
    )
    everyone = {r["name"]: r["net"] for r in view(client, "people")["rows"]}
    assert everyone == {"Alice": "500.00", "Bob": "-200.00"}
    assert [r["name"] for r in view(client, "people", show="owed")["rows"]] == ["Alice"]
    assert [r["name"] for r in view(client, "people", show="owe")["rows"]] == ["Bob"]
    assert view(client, "people", show="nonsense")["show"] == "all"


def test_a_persons_page(client, bank):
    alice = person(client, phone="99", email="a@example.com")
    seen = view(client, f"people/{alice['id']}")
    assert (seen["phone"], seen["email"], seen["net"], seen["open"]) == ("99", "a@example.com", "0.00", [])
    lend(client, alice, bank, description="Rent help")
    seen = view(client, f"people/{alice['id']}")
    assert seen["receivable"] == "500.00" and [o["name"] for o in seen["open"]] == ["Rent help"]
    view(client, "people/00000000-0000-4000-8000-0000000000aa", status=404)


def test_editing_removing_and_archiving_a_person(client, bank):
    alice = person(client)
    assert (
        client.patch(f"/api/contacts/{alice['id']}", json={"name": "Alicia", "notes": "x"}).json()["name"] == "Alicia"
    )
    lend(client, alice, bank, "5")
    blocked = client.post(f"/api/contacts/{alice['id']}/archive")
    assert blocked.status_code in (400, 409) and "owes you" in blocked.json()["detail"]
    bob = person(client, "Bob")
    assert client.delete(f"/api/contacts/{bob['id']}").status_code == 200
    assert client.get(f"/api/contacts/{bob['id']}").status_code == 404
    carol = person(client, "Carol")
    assert client.post(f"/api/contacts/{carol['id']}/archive").status_code == 200
    assert [r["name"] for r in view(client, "people", show="archived")["rows"]] == ["Carol"]
    assert view(client, f"people/{carol['id']}")["archived"] is True
    assert client.post(f"/api/contacts/{carol['id']}/restore").status_code == 200
    assert "Carol" in [r["name"] for r in view(client, "people")["rows"]]


def test_the_activity_and_undoing_an_entry(client, bank):
    alice = person(client)
    loan = lend(client, alice, bank)
    sheet = view(client, f"people/{alice['id']}/entries/{loan['id']}")
    assert sheet["amount"] == "500.00" and sheet["can_reverse"] is True
    assert reverse(client, alice, loan["id"]).status_code == 204
    assert float(contact(client, alice)["net"]) == 0
    view(client, f"people/{alice['id']}/entries/{loan['id']}", status=404)
    expense = client.post(
        "/api/shared-expenses/",
        params={"confirm": True},
        json={
            "description": "Dinner",
            "total_amount": "100",
            "participants": [{"is_self": True}, {"contact_id": alice["id"]}],
            "payments": [{"account_id": bank["id"], "amount": "100"}],
        },
    ).json()
    assert reverse(client, alice, expense["transaction_id"]).status_code == 204
    assert client.get(f"/api/shared-expenses/{expense['id']}").status_code == 404
    lent = lend(client, alice, bank, "50")
    paid = client.post(
        f"/api/contacts/{alice['id']}/settlements",
        json={"direction": "received", "amount": "20", "account_id": bank["id"]},
    ).json()
    blocked = reverse(client, alice, lent["id"])
    assert blocked.status_code == 409 and "settle" in blocked.json()["detail"]
    assert reverse(client, alice, paid["id"]).status_code == 204


def test_a_persons_accounts_stay_off_the_accounts_page_and_the_pickers(client, bank):
    alice = person(client)
    names = {c["name"] for k in view(client, "accounts")["kinds"] for c in k["cards"]}
    assert not [n for n in names if n.startswith("Due")]
    options = {o["id"] for g in view(client, "entry-form")["groups"] for o in g["options"]}
    assert alice["receivable_account_id"] not in options and alice["payable_account_id"] not in options
    assert client.get(f"/api/accounts/{alice['receivable_account_id']}").json()["contact_account"] is True
    refused = client.post("/api/accounts/", json={"name": "Sub", "parent_id": alice["receivable_account_id"]})
    assert refused.status_code == 400 and "belongs to a contact" in refused.json()["detail"]


def test_an_entry_made_through_a_person_is_looked_after_on_their_page(client, bank):
    alice = person(client)
    loan = lend(client, alice, bank)
    sheet = view(client, f"transactions/{loan['id']}")
    assert sheet["person"]["id"] == alice["id"] and sheet["loan_like"] is True, "a loan is edited from here too"
    gift = client.post(
        f"/api/contacts/{alice['id']}/transfers",
        json={"direction": "sent", "purpose": "gift", "amount": "5", "account_id": bank["id"]},
    ).json()
    assert view(client, f"transactions/{gift['id']}")["loan_like"] is False, "a gift is an ordinary entry"


# ---- money to or from a person on the Add screen -------------------------------------------------------------------


def test_a_transfer_to_or_from_a_person_on_the_add_screen(client, bank):
    alice = person(client)
    assert [o["id"] for g in view(client, "entry-form")["groups"] if g["title"] == "People" for o in g["options"]] == [
        alice["id"]
    ]
    lent = save(client, {**rows(bank, alice), "kind": "transfer"})
    assert lent.status_code in OK and lent.json()["recorded"] == "transfer", lent.text
    assert float(contact(client, alice)["receivable"]) == 300
    assert client.get(f"/api/contacts/{alice['id']}/obligations").json()[0]["source_type"] == "loan"
    back = save(client, {**rows(bank, alice, sent=False, amount="50"), "kind": "transfer"})
    assert back.status_code in OK
    now = contact(client, alice)
    assert (float(now["receivable"]), float(now["payable"])) == (250, 0), "money from someone who owes you pays back"
    assert client.get(f"/api/contacts/{alice['id']}/activity", params={"purpose": "settlement"}).json()["total"] == 1
    assert balance(client) == 9750


def test_the_rules_of_a_transfer_with_a_person(client, bank):
    alice = person(client)
    cash = client.post("/api/accounts/", json={"name": "Cash", "parent_id": bank["parent_id"]}).json()

    def attempt(**data):
        return save(client, {**rows(bank, alice), "kind": "transfer", **data})

    assert "same on both sides" in attempt(amount=["10", "20"]).text
    assert "one side" in attempt(side=["debit", "debit"]).text
    assert "tags" in attempt(tags=["trip"]).text
    three = save(
        client,
        {
            "kind": "transfer",
            "account": [bank["id"], alice["id"], cash["id"]],
            "side": ["credit", "debit", "debit"],
            "amount": ["10", "5", "5"],
        },
    )
    assert three.status_code == 400 and "one side" in three.text
    assert float(contact(client, alice)["net"]) == 0, "nothing was recorded"
    client.post(f"/api/contacts/{alice['id']}/archive")
    assert attempt().status_code == 400, "an archived person is not lent to"


def test_people_are_offered_only_once_there_are_some(client, bank):
    assert "People" not in [g["title"] for g in view(client, "entry-form")["groups"]]
    person(client)
    assert "People" in [g["title"] for g in view(client, "entry-form")["groups"]]


def test_adding_a_person_who_already_owes_you_or_is_owed(client):
    made = client.post(
        "/api/contacts/",
        json={"name": "Alice", "opening": {"direction": "receivable", "amount": "4000", "date": "2026-01-01"}},
    )
    assert made.status_code == 201, made.text
    assert float(made.json()["receivable"]) == 4000
    assert view(client, f"people/{made.json()['id']}")["open"][0]["outstanding"] == "4000.00"
    bob = client.post("/api/contacts/", json={"name": "Bob", "opening": {"direction": "payable", "amount": "75"}})
    assert float(bob.json()["payable"]) == 75


def test_a_bad_opening_balance_leaves_nobody_half_made(client):
    for amount in ("x", "0"):
        bad = client.post(
            "/api/contacts/", json={"name": "Dave", "opening": {"direction": "receivable", "amount": amount}}
        )
        assert bad.status_code in (400, 422), amount
    assert client.get("/api/contacts/", params={"include_archived": True}).json() == []


def test_adding_an_opening_balance_later_and_undoing_it(client):
    alice = person(client)
    done = client.post(
        f"/api/contacts/{alice['id']}/opening-balance",
        json={"direction": "payable", "amount": "90", "date": "2026-02-01", "description": "Rent"},
    )
    assert done.status_code == 201 and float(contact(client, alice)["payable"]) == 90
    blank = client.post(f"/api/contacts/{alice['id']}/opening-balance", json={"direction": "payable"})
    assert blank.status_code in (400, 422)
    entry = done.json()["id"]
    assert view(client, f"people/{alice['id']}/entries/{entry}")["can_edit"] is True
    assert reverse(client, alice, entry).status_code == 204


def test_editing_an_opening_balance(client, bank):
    alice = person(client)
    made = client.post(
        f"/api/contacts/{alice['id']}/opening-balance",
        json={"direction": "receivable", "amount": "4000", "date": "2026-01-01", "description": "Old loan"},
    ).json()
    form = view(client, "opening-form", contact_id=alice["id"], transaction_id=made["id"])
    assert (form["editing"], form["amount"], form["description"], form["paid"]) == (True, "4000.00", "Old loan", None)
    changed = client.patch(
        f"/api/transfers/{made['id']}",
        json={"direction": "payable", "amount": "900", "date": "2026-02-01", "description": "Changed"},
    )
    assert changed.status_code == 200, changed.text
    now = contact(client, alice)
    assert float(now["payable"]) == 900 and float(now["receivable"]) == 0
    client.post(
        f"/api/contacts/{alice['id']}/settlements",
        json={"direction": "sent", "amount": "300", "account_id": bank["id"]},
    )
    assert view(client, "opening-form", contact_id=alice["id"], transaction_id=made["id"])["paid"] == "300.00"
    low = client.patch(f"/api/transfers/{made['id']}", json={"amount": "100"})
    assert low.status_code == 400 and "go below that" in low.json()["detail"]
    loan = lend(client, alice, bank, "5")
    assert client.patch(f"/api/transfers/{loan['id']}", json={"amount": "6"}).status_code in (400, 404)
    assert view(client, f"people/{alice['id']}/entries/{loan['id']}")["can_edit"] is False


# ---- an entry turned into a loan, a shared bill or shared income, and back ------------------------------------------


def test_an_existing_entry_becomes_a_loan_in_place(client, bank):
    alice = person(client)
    entry, _ = ordinary_expense(client, bank, tags=["trip"])
    done = save(client, {**rows(bank, alice), "kind": "transfer", "tags": ["trip"], "payee": "Cab"}, entry["id"])
    assert done.status_code in OK, done.text
    same = client.get(f"/api/transactions/{entry['id']}").json()
    assert (same["id"], same["payee"], same["tags"], same["date"]) == (entry["id"], "Alice", ["trip"], "2026-11-01")
    assert {p["account_id"] for p in same["postings"]} == {bank["id"], alice["receivable_account_id"]}
    owed = client.get(f"/api/contacts/{alice['id']}/obligations").json()
    assert [(o["source_type"], float(o["outstanding_amount"])) for o in owed] == [("loan", 300.0)]
    assert balance(client) == 9700 and client.get("/api/reports/trial-balance").json()["balanced"]
    form = view(client, "entry-form", transaction_id=entry["id"])
    assert alice["id"] in [r["choice"] for r in form["from_rows"] + form["to_rows"]], "the edit form shows the person"


def test_a_loan_can_move_to_another_person_or_the_other_way_round(client, bank):
    alice, bob = person(client), person(client, "Bob")
    entry, _ = ordinary_expense(client, bank)
    assert save(client, {**rows(bank, alice), "kind": "transfer"}, entry["id"]).status_code in OK
    moved = save(client, {**rows(bank, bob, sent=False, amount="450"), "kind": "transfer"}, entry["id"])
    assert moved.status_code in OK, moved.text
    assert float(contact(client, alice)["net"]) == 0
    now = contact(client, bob)
    assert float(now["payable"]) == 450 and float(now["receivable"]) == 0
    assert [o["source_type"] for o in client.get(f"/api/contacts/{bob['id']}/obligations").json()] == ["borrowing"]
    assert balance(client) == 10450


def plain(bank, misc, amount="300", **extra):
    return {
        "kind": "expense",
        "account": [bank["id"], misc["id"]],
        "side": ["credit", "debit"],
        "amount": [amount, amount],
        "date": "2026-11-01",
        **extra,
    }


def test_a_loan_can_be_edited_back_into_an_ordinary_entry(client, bank):
    alice = person(client)
    entry, misc = ordinary_expense(client, bank)
    save(client, {**rows(bank, alice), "kind": "transfer"}, entry["id"])
    back = save(client, plain(bank, misc, payee="Cab"), entry["id"])
    assert back.status_code in OK, back.text
    assert client.get(f"/api/contacts/{alice['id']}/obligations").json() == []
    assert (
        float(contact(client, alice)["net"]) == 0 and client.get(f"/api/contacts/{alice['id']}/transfers").json() == []
    )
    again = client.get(f"/api/transactions/{entry['id']}").json()
    assert again["payee"] == "Cab" and any(p["category_id"] == misc["id"] for p in again["postings"])
    assert client.delete(f"/api/transactions/{entry['id']}").status_code == 204, "an ordinary entry again"


def test_nothing_changes_once_something_was_paid_back_or_if_the_edit_fails(client, bank):
    alice = person(client)
    entry, misc = ordinary_expense(client, bank)
    save(client, {**rows(bank, alice), "kind": "transfer"}, entry["id"])
    broken = save(client, plain(bank, misc, amount="300") | {"amount": ["300", "200"]}, entry["id"])
    assert broken.status_code == 400
    assert float(contact(client, alice)["receivable"]) == 300, "a failed edit leaves the loan as it was"
    assert len(client.get(f"/api/contacts/{alice['id']}/obligations").json()) == 1
    client.post(
        f"/api/contacts/{alice['id']}/settlements",
        json={"direction": "received", "amount": "50", "account_id": bank["id"]},
    )
    ordinary = save(client, plain(bank, misc), entry["id"])
    assert ordinary.status_code in (400, 409) and "paid back" in ordinary.text
    bigger = save(client, {**rows(bank, alice, amount="400"), "kind": "transfer"}, entry["id"])
    assert bigger.status_code in (400, 409) and "paid back" in bigger.text
    assert float(contact(client, alice)["receivable"]) == 250


def test_only_a_loan_or_a_borrowing_is_edited_this_way(client, bank):
    alice = person(client)
    opening = client.post(
        f"/api/contacts/{alice['id']}/opening-balance", json={"direction": "receivable", "amount": "5"}
    ).json()
    refused = save(client, {**rows(bank, alice), "kind": "transfer"}, opening["id"])
    assert refused.status_code == 400 and "only a loan, a borrowing, or a bill or income" in refused.text
    entry, _ = ordinary_expense(client, bank)
    uneven = save(client, {**rows(bank, alice), "kind": "transfer", "amount": ["300", "200"]}, entry["id"])
    assert uneven.status_code == 400 and "same on both sides" in uneven.text
    assert all(
        p["account_id"] != alice["receivable_account_id"]
        for p in client.get(f"/api/transactions/{entry['id']}").json()["postings"]
    )


def test_a_bill_shared_equally(client, bank):
    alice, bob = person(client), person(client, "Bob")
    dining = category(client, "Dining")
    done = save(client, people_form(bank, dining, [alice, bob], comment="Friday", tags=["trip"]))
    assert done.status_code in OK and done.json()["recorded"] == "expense-shared", done.text
    assert float(contact(client, alice)["receivable"]) == 500 and float(contact(client, bob)["receivable"]) == 500
    assert balance(client) == 8500 and spent(client) == 500, "only your share is spending"
    made = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Dinner")
    assert made["comment"] == "Friday" and made["tags"] == ["trip"]
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_the_other_ways_to_split(client, bank):
    alice = person(client)
    dining = category(client, "Dining")
    pct = people_form(
        bank, dining, [alice], method="percentage", total="100", value_self="75", **{f"value_{alice['id']}": "25"}
    )
    assert save(client, pct).status_code in OK
    assert float(contact(client, alice)["receivable"]) == 25
    bad = save(client, {**pct, f"value_{alice['id']}": "20"})
    assert bad.status_code == 400 and "not 100" in bad.text
    shares = people_form(
        bank, dining, [alice], method="shares", total="90", value_self="2", **{f"value_{alice['id']}": "1"}
    )
    assert save(client, shares).status_code in OK
    assert float(contact(client, alice)["receivable"]) == 55
    exact = people_form(
        bank, dining, [alice], method="exact", total="100", value_self="60", **{f"value_{alice['id']}": "40"}
    )
    assert save(client, exact).status_code in OK
    assert float(contact(client, alice)["receivable"]) == 95


def test_a_friend_paid_part_or_all_of_it(client, bank):
    alice, bob = person(client), person(client, "Bob")
    dining = category(client, "Dining")
    assert (
        save(
            client, people_form(bank, dining, [alice, bob], **{f"paid_{alice['id']}": "1500", "paid_self": "0"})
        ).status_code
        in OK
    )
    assert (float(contact(client, alice)["payable"]), float(contact(client, bob)["receivable"])) == (1000, 500)
    assert balance(client) == 10000


def test_the_rules_of_a_bill_with_people(client, bank):
    alice = person(client)
    dining = category(client, "Dining")
    nobody = save(client, people_form(bank, dining, []))
    assert nobody.status_code == 400 and "at least 2" in nobody.text
    no_account = save(client, {k: v for k, v in people_form(bank, dining, [alice]).items() if k != "account_id"})
    assert no_account.status_code == 400 and "account" in no_account.text
    short = save(client, people_form(bank, dining, [alice], paid_self="400"))
    assert short.status_code == 400 and "not the total" in short.text
    assert client.get("/api/shared-expenses/").json() == []
    assert save(client, people_form(bank, dining, [alice])).status_code in OK


def converted(client, bank, who, total="3000"):
    entry, misc = ordinary_expense(client, bank, amount=total, tags=["trip"])
    done = save(
        client,
        people_form(bank, misc, who, total=total, payee="Restaurant", date="2026-10-09", tags=["trip"]),
        entry["id"],
    )
    assert done.status_code in OK, done.text
    return entry, misc


def test_an_existing_entry_becomes_a_shared_bill_in_place(client, bank):
    alice, bob = person(client), person(client, "Bob")
    entry, _ = converted(client, bank, [alice, bob])
    same = client.get(f"/api/transactions/{entry['id']}").json()
    assert (same["id"], same["date"], same["tags"], same["payee"]) == (
        entry["id"],
        "2026-10-09",
        ["trip"],
        "Restaurant",
    )
    assert float(contact(client, alice)["receivable"]) == 1000 and float(contact(client, bob)["receivable"]) == 1000
    bills = client.get("/api/shared-expenses/").json()
    assert len(bills) == 1 and bills[0]["transaction_id"] == entry["id"] and float(bills[0]["user_share"]) == 1000
    lines = client.get("/api/reports/breakdown", params={"date_from": "2026-10-01", "date_to": "2026-10-31"}).json()[
        "lines"
    ]
    assert float(lines[0]["amount"]) == 1000, "only your share is spending now"
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_the_edit_screen_of_a_shared_bill_opens_on_its_split_as_entered(client, bank):
    alice, bob = person(client), person(client, "Bob")
    entry, misc = converted(client, bank, [alice, bob])
    form = view(client, "entry-form", transaction_id=entry["id"])
    share = form["expense_share"]
    assert form["mode"] == "split" and share["method"] == "equal"
    assert (share["category_id"], share["account_id"]) == (misc["id"], bank["id"])
    assert {p["contact_id"] for p in share["people"]} == {alice["id"], bob["id"]}
    assert sorted(view(client, f"transactions/{entry['id']}")["with_names"]) == ["Alice", "Bob"]


def test_an_unevenly_shared_bill_edits_with_its_values(client, bank):
    alice = person(client)
    dining = category(client, "Dining")
    save(
        client,
        people_form(
            bank, dining, [alice], method="percentage", total="200", value_self="75", **{f"value_{alice['id']}": "25"}
        ),
    )
    entry = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Dinner")
    share = view(client, "entry-form", transaction_id=entry["id"])["expense_share"]
    assert share["method"] == "percentage" and float(share["self_value"]) == 75
    assert [float(p["value"]) for p in share["people"]] == [25]


def test_a_shared_bill_can_be_reshared_and_made_ordinary_again(client, bank):
    alice, bob = person(client), person(client, "Bob")
    entry, misc = converted(client, bank, [alice, bob])
    reshared = save(
        client, people_form(bank, misc, [alice], total="3000", payee="Restaurant", date="2026-10-09"), entry["id"]
    )
    assert reshared.status_code in OK
    assert float(contact(client, bob)["net"]) == 0 and float(contact(client, alice)["receivable"]) == 1500
    assert len(client.get("/api/shared-expenses/").json()) == 1, "re-recorded, not duplicated"
    ordinary = save(client, plain(bank, misc, amount="3000", payee="Restaurant") | {"date": "2026-10-09"}, entry["id"])
    assert ordinary.status_code in OK, ordinary.text
    assert client.get("/api/shared-expenses/").json() == [] and float(contact(client, alice)["net"]) == 0
    assert client.get(f"/api/contacts/{alice['id']}/obligations").json() == []
    assert client.delete(f"/api/transactions/{entry['id']}").status_code == 204, "an ordinary entry again"


def test_a_loan_and_a_shared_bill_can_turn_into_each_other(client, bank):
    alice, bob = person(client), person(client, "Bob")
    entry, misc = ordinary_expense(client, bank, amount="300")
    save(client, {**rows(bank, alice), "kind": "transfer"}, entry["id"])
    assert [t["purpose"] for t in client.get(f"/api/contacts/{alice['id']}/transfers").json()] == ["loan"]
    assert save(client, people_form(bank, misc, [alice], total="300", payee="Cab"), entry["id"]).status_code in OK
    assert client.get(f"/api/contacts/{alice['id']}/transfers").json() == [], "no longer a loan"
    assert float(contact(client, alice)["receivable"]) == 150
    assert save(client, {**rows(bank, bob), "kind": "transfer"}, entry["id"]).status_code in OK
    assert client.get("/api/shared-expenses/").json() == []
    assert float(contact(client, alice)["net"]) == 0 and float(contact(client, bob)["receivable"]) == 300
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_nothing_changes_once_a_share_was_paid_back_or_when_the_edit_fails(client, bank):
    alice, bob = person(client), person(client, "Bob")
    entry, misc = converted(client, bank, [alice, bob])
    broken = save(
        client, people_form(bank, misc, [alice, bob], total="3000", paid_self="100", date="2026-10-09"), entry["id"]
    )
    assert broken.status_code == 400
    assert float(contact(client, bob)["receivable"]) == 1000, "a failed edit leaves the bill as it was"
    assert len(client.get("/api/shared-expenses/").json()) == 1
    client.post(
        f"/api/contacts/{alice['id']}/settlements",
        json={"direction": "received", "amount": "200", "account_id": bank["id"]},
    )
    again = save(
        client,
        people_form(
            bank,
            misc,
            [alice, bob],
            method="percentage",
            total="3000",
            value_self="50",
            **{f"value_{alice['id']}": "25", f"value_{bob['id']}": "25"},
        ),
        entry["id"],
    )
    assert again.status_code in (400, 409) and "paid back" in again.text
    ordinary = save(client, plain(bank, misc, amount="3000") | {"date": "2026-10-09"}, entry["id"])
    assert ordinary.status_code in (400, 409) and "paid back" in ordinary.text
    assert float(contact(client, alice)["receivable"]) == 800 and float(contact(client, bob)["receivable"]) == 1000


def test_income_with_part_of_it_theirs(client, bank):
    alice = person(client)
    rent = category(client, "Rent", kind="earning")
    done = save(client, income_form(bank, rent, [alice], comment="Q4", tags=["rent"]))
    assert done.status_code in OK and done.json()["recorded"] == "income-shared", done.text
    assert float(contact(client, alice)["payable"]) == 4000 and earned(client) == 6000, "only your part is income"
    assert balance(client) == 20000
    made = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Rent, Flat 4B")
    assert made["comment"] == "Q4" and made["tags"] == ["rent"]
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_someone_received_it_for_you(client, bank):
    alice = person(client)
    rent = category(client, "Rent", kind="earning")
    assert save(client, income_form(bank, rent, [], **{f"got_{alice['id']}": "3000"})).status_code in OK
    assert float(contact(client, alice)["receivable"]) == 3000 and earned(client) == 10000 and balance(client) == 17000


def test_the_rules_of_income_with_people(client, bank):
    alice = person(client)
    rent = category(client, "Rent", kind="earning")
    nobody = save(client, income_form(bank, rent, []))
    assert nobody.status_code == 400 and "name a person" in nobody.text
    no_account = save(client, {k: v for k, v in income_form(bank, rent, [alice]).items() if k != "income_account_id"})
    assert no_account.status_code == 400 and "account" in no_account.text
    both = save(client, income_form(bank, rent, [alice], **{f"got_{alice['id']}": "1000"}))
    assert both.status_code == 400 and "both" in both.text
    assert all(t["payee"] != "Rent, Flat 4B" for t in client.get("/api/transactions/").json())


def test_shared_income_is_edited_in_place_and_back_into_an_ordinary_one(client, bank):
    alice, bob = person(client), person(client, "Bob")
    rent = category(client, "Rent", kind="earning")
    assert save(client, income_form(bank, rent, [alice])).status_code in OK
    made = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Rent, Flat 4B")
    form = view(client, "entry-form", transaction_id=made["id"])
    assert form["mode"] == "split" and form["kind"] == "income"
    assert [(p["contact_id"], float(p["theirs"])) for p in form["income_share"]["people"]] == [(alice["id"], 4000)]
    changed = save(client, income_form(bank, rent, [bob], **{"theirs_" + bob["id"]: "1000"}), made["id"])
    assert changed.status_code in OK, changed.text
    assert float(contact(client, alice)["payable"]) == 0 and float(contact(client, bob)["payable"]) == 1000
    assert earned(client) == 9000
    assert [t["id"] for t in client.get("/api/transactions/").json() if t["payee"] == "Rent, Flat 4B"] == [made["id"]]
    back = save(
        client,
        {
            "kind": "income",
            "date": "2026-11-08",
            "payee": "Rent, Flat 4B",
            "account": [rent["id"], bank["id"]],
            "side": ["credit", "debit"],
            "amount": ["10000", "10000"],
        },
        made["id"],
    )
    assert back.status_code in OK, back.text
    assert (
        float(contact(client, bob)["payable"]) == 0
        and client.get(f"/api/contacts/{bob['id']}/obligations").json() == []
    )
    assert earned(client) == 10000


def test_an_ordinary_income_becomes_shared_in_place(client, bank):
    alice = person(client)
    rent = category(client, "Rent", kind="earning")
    made = client.post(
        "/api/transactions/",
        json={
            "payee": "Rent, Flat 4B",
            "postings": [
                {"category_id": rent["id"], "side": "credit", "amount": "10000"},
                {"account_id": bank["id"], "side": "debit", "amount": "10000"},
            ],
        },
    ).json()
    done = save(client, income_form(bank, rent, [alice]), made["id"])
    assert done.status_code in OK, done.text
    assert earned(client) == 6000 and float(contact(client, alice)["payable"]) == 4000
    assert [t["id"] for t in client.get("/api/transactions/").json() if t["payee"] == "Rent, Flat 4B"] == [made["id"]]


def test_shared_income_shows_on_the_persons_page_and_can_be_reversed_there(client, bank):
    alice = person(client)
    rent = category(client, "Rent", kind="earning")
    assert save(client, income_form(bank, rent, [alice])).status_code in OK
    made = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Rent, Flat 4B")
    seen = view(client, f"people/{alice['id']}")
    assert [(o["name"], o["outstanding"]) for o in seen["open"]] == [("Rent, Flat 4B", "4000.00")]
    sheet = view(client, f"people/{alice['id']}/entries/{made['id']}")
    assert any("hold it for them" in n for n in sheet["notes"])
    assert reverse(client, alice, made["id"]).status_code == 204
    assert client.get(f"/api/shared-incomes/{made['id']}").status_code == 404 and earned(client) == 0


def test_a_transfer_with_a_person_is_a_loan_whatever_the_split_says(client, bank):
    alice = person(client)
    lent = save(client, {"mode": "split", "kind": "transfer", "date": "2026-11-01", **rows(bank, alice)})
    assert lent.status_code in OK, lent.text
    assert float(contact(client, alice)["receivable"]) == 300


def test_an_old_entry_still_opens_and_can_be_undone_after_a_long_history(client, bank):
    """The sheet used to look for the entry among the newest 200 only: an older amount still owed would not open."""
    alice = person(client)
    first = lend(client, alice, bank, "1", date="2020-01-01", description="The first one")
    for _ in range(200):
        lend(client, alice, bank, "1")
    assert first["id"] in [o["transaction_id"] for o in view(client, f"people/{alice['id']}")["open"]]
    sheet = view(client, f"people/{alice['id']}/entries/{first['id']}")
    assert sheet["title"] == "Loan" and "The first one" in str(sheet), "it opens, with its description"
    bob = person(client, "Bob")
    view(client, f"people/{bob['id']}/entries/{first['id']}", status=404)
    assert reverse(client, bob, first["id"]).status_code == 404
    assert reverse(client, alice, first["id"]).status_code == 204
    assert float(contact(client, alice)["net"]) == 200

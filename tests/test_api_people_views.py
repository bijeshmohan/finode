"""/api/views/people, /api/views/people/{contact_id}, its entries and /api/views/opening-form: what the finode app's
People pages show, worked out as the web pages work it out (services/people_view.py); a person added with an opening
balance all or nothing, and an entry reversed the way its kind is reversed."""

from .books import category
from .test_isolation import B_USER, signed_in_as
from .test_web_people import bank, income_form, person  # noqa: F401  # bank is a fixture

LOAN = {"direction": "sent", "purpose": "loan", "account_id": None}


def view(client, path, status=200, **params):
    response = client.get(path, params=params)
    assert response.status_code == status, response.text
    return response.json()


def lend(client, who, bank, amount="500", **extra):
    response = client.post(
        f"/api/contacts/{who['id']}/transfers",
        json={"direction": "sent", "purpose": "loan", "amount": amount, "account_id": bank["id"], **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def borrow(client, who, bank, amount="200"):
    response = client.post(
        f"/api/contacts/{who['id']}/transfers",
        json={"direction": "received", "purpose": "borrowing", "amount": amount, "account_id": bank["id"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def settle(client, who, bank, direction="received", amount="20"):
    response = client.post(
        f"/api/contacts/{who['id']}/settlements",
        json={"direction": direction, "amount": amount, "account_id": bank["id"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def balanced(client) -> bool:
    return client.get("/api/reports/trial-balance").json()["balanced"]


def test_the_list_and_its_switcher(client, bank):
    seen = view(client, "/api/views/people")
    assert (seen["everyone"], seen["rows"], seen["has_archived"]) == (False, [], False)
    alice, bob, cara = person(client), person(client, "Bob"), person(client, "Cara")
    lend(client, alice, bank)
    borrow(client, bob, bank)
    seen = view(client, "/api/views/people")
    assert [s["key"] for s in seen["shows"]] == ["all", "owed", "owe"] and seen["show"] == "all"
    rows = {r["name"]: r for r in seen["rows"]}
    assert (rows["Alice"]["net"], rows["Bob"]["net"], rows["Cara"]["net"]) == ("500.00", "-200.00", "0.00")
    assert rows["Cara"]["sub"] == "Nothing yet" and rows["Alice"]["sub"].startswith("Last ")
    assert (seen["owed_total"], seen["owe_total"]) == ("500.00", "200.00")
    assert [r["name"] for r in view(client, "/api/views/people", show="owed")["rows"]] == ["Alice"]
    assert [r["name"] for r in view(client, "/api/views/people", show="owe")["rows"]] == ["Bob"]
    assert view(client, "/api/views/people", show="nonsense")["show"] == "all"
    assert client.post(f"/api/contacts/{cara['id']}/archive").status_code == 200
    seen = view(client, "/api/views/people")
    assert seen["has_archived"] is True and "Cara" not in [r["name"] for r in seen["rows"]]
    archived = view(client, "/api/views/people", show="archived")
    assert [(r["name"], r["sub"]) for r in archived["rows"]] == [("Cara", "Archived")]


def test_settled_and_even_read_as_the_page(client, bank):
    alice = person(client)
    lend(client, alice, bank, amount="50")
    settle(client, alice, bank, amount="50")
    assert view(client, "/api/views/people")["rows"][0]["sub"] == "Settled up"


def test_a_persons_page_owed_both_ways(client, bank, session):
    from app.services.people_view import person_page  # noqa: F401  # the service the view reads

    alice = person(client)
    loan = lend(client, alice, bank, amount="500")
    settle(client, alice, bank, amount="100")
    seen = view(client, f"/api/views/people/{alice['id']}")
    assert (seen["name"], seen["net"], seen["receivable"], seen["payable"]) == ("Alice", "400.00", "400.00", "0.00")
    [row] = seen["open"]
    assert row["transaction_id"] == loan["id"] and row["name"] == "Loan" and row["who"] is None
    assert (row["settled"], row["original"], row["outstanding"], row["receivable"]) == (
        "100.00",
        "500.00",
        "400.00",
        True,
    )


def test_open_rows_say_which_way_only_when_owed_both_ways(client, bank, monkeypatch):
    """Owed both ways happens only until it evens out; the page then says which way each open amount is."""
    from app.services import people_view

    alice = person(client)
    lend(client, alice, bank, amount="500")
    page = people_view.PersonPage
    monkeypatch.setattr(page, "both_ways", property(lambda self: True))
    [row] = view(client, f"/api/views/people/{alice['id']}")["open"]
    assert row["who"] == "they owe you"


def test_the_activity_reads_as_the_page(client, bank):
    alice = person(client)
    lend(client, alice, bank, amount="500", description="Rent help")
    settle(client, alice, bank, amount="100")
    rent = category(client, "Rent", kind="earning")
    assert client.post("/transactions/split", data=income_form(bank, rent, [alice])).status_code == 200
    client.post(
        "/api/shared-expenses/",
        params={"confirm": True},
        json={
            "description": "Dinner",
            "total_amount": "100",
            "participants": [{"is_self": True}, {"contact_id": alice["id"]}],
            "payments": [{"account_id": bank["id"], "amount": "100"}],
        },
    )
    seen = view(client, f"/api/views/people/{alice['id']}")
    rows = {r["title"]: r for r in seen["activity"]}
    assert rows["Loan"]["sub"] == "Rent help" and rows["Loan"]["income"] is False
    assert rows["Paid back"]["income"] is True and rows["Paid back"]["amount"] == "100.00"
    assert rows["Dinner"]["sub"] == "their share"
    assert rows["Rent, Flat 4B"]["sub"] == "their part"
    assert seen["more_activity"] == 0


def test_an_entrys_sheet(client, bank):
    alice = person(client)
    loan = lend(client, alice, bank, amount="500", description="Rent help")
    sheet = view(client, f"/api/views/people/{alice['id']}/entries/{loan['id']}")
    assert (sheet["title"], sheet["amount"], sheet["notes"], sheet["can_edit"], sheet["can_reverse"]) == (
        "Loan",
        "500.00",
        ["Rent help"],
        False,
        True,
    )
    opening = client.post(
        f"/api/contacts/{alice['id']}/opening-balance", json={"direction": "receivable", "amount": "70"}
    ).json()
    assert view(client, f"/api/views/people/{alice['id']}/entries/{opening['id']}")["can_edit"] is True
    bob = person(client, "Bob")
    view(client, f"/api/views/people/{bob['id']}/entries/{loan['id']}", status=404)


def test_an_evened_out_entry_cannot_be_reversed_by_itself(client, bank):
    alice = person(client)
    lend(client, alice, bank, amount="500")
    borrow(client, alice, bank, amount="200")
    netoff = next(
        a for a in client.get(f"/api/contacts/{alice['id']}/activity").json()["items"] if a["purpose"] == "netoff"
    )
    sheet = view(client, f"/api/views/people/{alice['id']}/entries/{netoff['transaction_id']}")
    assert sheet["title"] == "Evened out" and sheet["can_reverse"] is False
    assert any("cleared against each other" in note for note in sheet["notes"])
    refused = client.post(f"/api/contacts/{alice['id']}/entries/{netoff['transaction_id']}/reverse")
    assert refused.status_code == 400


def test_reversing_each_kind(client, bank):
    alice = person(client)
    loan = lend(client, alice, bank, amount="500")
    done = client.post(f"/api/contacts/{alice['id']}/entries/{loan['id']}/reverse")
    assert done.status_code == 204, done.text
    assert client.get(f"/api/contacts/{alice['id']}").json()["net"] == "0.00" and balanced(client)
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
    assert client.post(f"/api/contacts/{alice['id']}/entries/{expense['transaction_id']}/reverse").status_code == 204
    assert client.get(f"/api/shared-expenses/{expense['id']}").status_code == 404
    rent = category(client, "Rent", kind="earning")
    assert client.post("/transactions/split", data=income_form(bank, rent, [alice])).status_code == 200
    income = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Rent, Flat 4B")
    assert client.post(f"/api/contacts/{alice['id']}/entries/{income['id']}/reverse").status_code == 204
    lent = lend(client, alice, bank, amount="50")
    paid = settle(client, alice, bank, amount="20")
    blocked = client.post(f"/api/contacts/{alice['id']}/entries/{lent['id']}/reverse")
    assert blocked.status_code in (400, 409) and "settle" in blocked.json()["detail"]
    assert client.post(f"/api/contacts/{alice['id']}/entries/{paid['id']}/reverse").status_code == 204
    assert balanced(client)
    missing = "00000000-0000-4000-8000-0000000000aa"
    assert client.post(f"/api/contacts/{alice['id']}/entries/{missing}/reverse").status_code == 404


def test_adding_a_person_with_an_opening_balance_is_all_or_nothing(client):
    made = client.post(
        "/api/contacts/", json={"name": "Alice", "opening": {"direction": "receivable", "amount": "250"}}
    )
    assert made.status_code == 201, made.text
    assert made.json()["receivable"] == "250.00"
    for amount in ("0", "1.234", "lots"):
        refused = client.post(
            "/api/contacts/", json={"name": "Bob", "opening": {"direction": "payable", "amount": amount}}
        )
        assert refused.status_code in (400, 422), refused.text
    with_places = client.post(
        "/api/contacts/", json={"name": "Cara", "opening": {"direction": "payable", "amount": "1.234"}}
    )
    assert with_places.status_code == 400 and "decimal" in with_places.json()["detail"]
    assert [c["name"] for c in client.get("/api/contacts/").json()] == ["Alice"], "nobody half made"
    alone = client.post("/api/contacts/", json={"name": "Dev"})
    assert alone.status_code == 201 and alone.json()["receivable"] == "0.00"
    assert balanced(client)


def test_the_opening_form_view(client, bank):
    alice = person(client)
    new = view(client, "/api/views/opening-form", contact_id=alice["id"])
    assert (new["person_name"], new["editing"], new["direction"], new["amount"], new["paid"]) == (
        "Alice",
        False,
        "receivable",
        None,
        None,
    )
    assert new["date"]
    opening = client.post(
        f"/api/contacts/{alice['id']}/opening-balance",
        json={"direction": "receivable", "amount": "300", "date": "2026-01-05", "description": "From before"},
    ).json()
    settle(client, alice, bank, amount="100")
    seen = view(client, "/api/views/opening-form", contact_id=alice["id"], transaction_id=opening["id"])
    assert (seen["editing"], seen["direction"], seen["amount"], seen["date"], seen["description"], seen["paid"]) == (
        True,
        "receivable",
        "300.00",
        "2026-01-05",
        "From before",
        "100.00",
    )
    loan = lend(client, alice, bank)
    view(client, "/api/views/opening-form", status=404, contact_id=alice["id"], transaction_id=loan["id"])
    bob = person(client, "Bob")
    view(client, "/api/views/opening-form", status=404, contact_id=bob["id"], transaction_id=opening["id"])


def test_strangers(client, bank):
    alice = person(client)
    loan = lend(client, alice, bank)
    with signed_in_as(B_USER):
        assert view(client, "/api/views/people")["rows"] == []
        view(client, f"/api/views/people/{alice['id']}", status=404)
        view(client, f"/api/views/people/{alice['id']}/entries/{loan['id']}", status=404)
        view(client, "/api/views/opening-form", status=404, contact_id=alice["id"])
        assert client.post(f"/api/contacts/{alice['id']}/entries/{loan['id']}/reverse").status_code == 404
    assert client.get(f"/api/contacts/{alice['id']}").json()["net"] == "500.00"

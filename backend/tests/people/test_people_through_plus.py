"""People through "+": the pills on a person's page only open the new-transaction screen with the person filled in; money
to or from a person pays back what is owed first; nobody is ever owed both ways; a gift is an ordinary entry that names
the person as its payee."""

import pytest

from tests.books import category
from tests.people.test_people_entries import save

MISSING = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def bank(client, root_accounts):
    return client.post(
        "/api/accounts/", json={"name": "HDFC", "parent_id": root_accounts["Assets"], "balance": "10000"}
    ).json()


def person(client, name="Alice"):
    return client.post("/api/contacts/", json={"name": name}).json()


def lend(client, who, bank, amount="3000", direction="sent", purpose="loan", day="2026-10-01"):
    made = client.post(
        f"/api/contacts/{who['id']}/transfers",
        json={"direction": direction, "purpose": purpose, "amount": amount, "account_id": bank["id"], "date": day},
    )
    assert made.status_code == 201, made.text
    return made.json()


def move(client, who, bank, to_them, amount, **extra):
    """What the Add screen saves for a transfer with a person on one side (/api/entries)."""
    accounts = [bank["id"], who["id"]] if to_them else [who["id"], bank["id"]]
    form = {"account": accounts, "side": ["credit", "debit"], "amount": [amount, amount], "kind": "transfer", **extra}
    return save(client, form)


def owed(client, who):
    now = client.get(f"/api/contacts/{who['id']}").json()
    return float(now["receivable"]), float(now["payable"])


def activity(client, who, purpose):
    return client.get(f"/api/contacts/{who['id']}/activity", params={"purpose": purpose}).json()["total"]


# ---- the pills -------------------------------------------------------------------------------------------------


def form(client, **params) -> dict:
    answer = client.get("/api/views/entry-form", params=params)
    assert answer.status_code == 200, answer.text
    return answer.json()


def side_of(seen, who):
    """The side of the form (`credit` or `debit`) the person is picked on."""
    if who["id"] in [r["choice"] for r in seen["from_rows"]]:
        return "credit"
    return "debit" if who["id"] in [r["choice"] for r in seen["to_rows"]] else None


def test_lend_and_borrow_open_a_transfer_with_the_person_on_one_side(client, bank):
    alice = person(client)
    lent = form(client, move="lend", **{"with": alice["id"]})
    assert lent["kind"] == "transfer" and side_of(lent, alice) == "debit", "the money goes to them"
    assert side_of(form(client, move="borrow", **{"with": alice["id"]}), alice) == "credit", "it comes from them"
    assert client.get("/api/views/entry-form", params={"move": "lend", "with": MISSING}).status_code == 404


def test_settle_fills_in_what_is_owed_on_the_side_that_clears_it(client, bank):
    alice = person(client)
    lend(client, alice, bank, "3000")
    owed_to_you = form(client, move="settle", **{"with": alice["id"]})
    assert side_of(owed_to_you, alice) == "credit" and owed_to_you["total"].startswith("3000"), "they pay you back"
    lend(client, alice, bank, "5000", direction="received", purpose="borrowing", day="2026-10-02")
    # Alice now owes you nothing and you owe Alice 2,000: the 5,000 you borrowed first paid back her 3,000.
    assert owed(client, alice) == (0, 2000)
    you_owe = form(client, move="settle", **{"with": alice["id"]})
    assert side_of(you_owe, alice) == "debit" and you_owe["total"].startswith("2000"), "you pay them back"


def test_the_people_in_the_pickers_carry_what_they_owe_for_the_note_under_the_form(client, bank):
    alice, bob = person(client), person(client, "Bob")
    lend(client, alice, bank, "3000")
    lend(client, bob, bank, "700", direction="received", purpose="borrowing")
    people = {o["id"]: o["balance"] for g in form(client)["groups"] if g["title"] == "People" for o in g["options"]}
    assert (people[alice["id"]], people[bob["id"]]) == ("3000.00", "-700.00")


# ---- money to or from a person ----------------------------------------------------------------------------------


def test_money_from_someone_who_owes_you_pays_that_back_first(client, bank):
    alice = person(client)
    lend(client, alice, bank, "3000")
    part = move(client, alice, bank, to_them=False, amount="1000")
    assert part.status_code == 201, part.text
    assert owed(client, alice) == (2000, 0) and activity(client, alice, "settlement") == 1
    assert activity(client, alice, "borrowing") == 0
    more = move(client, alice, bank, to_them=False, amount="2500")
    assert more.status_code == 201
    assert owed(client, alice) == (0, 500), "the extra 500 is borrowed: you owe Alice"
    assert client.get("/api/reports/trial-balance").json()["balanced"]
    assert (
        float(next(a for a in client.get("/api/accounts/").json() if a["name"] == "HDFC")["balance"])
        == 10000 - 3000 + 3500
    )


def test_money_to_someone_you_owe_pays_that_back_first(client, bank):
    alice = person(client)
    lend(client, alice, bank, "1000", direction="received", purpose="borrowing")
    assert move(client, alice, bank, to_them=True, amount="1500").status_code == 201
    assert owed(client, alice) == (500, 0), "1,000 paid back and 500 lent"
    assert activity(client, alice, "settlement") == 1
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_with_nothing_owed_money_to_or_from_a_person_is_a_loan_or_a_borrowing(client, bank):
    alice = person(client)
    assert move(client, alice, bank, to_them=True, amount="300").status_code == 201
    assert activity(client, alice, "loan") == 1 and owed(client, alice) == (300, 0)
    bob = person(client, "Bob")
    assert move(client, bob, bank, to_them=False, amount="80").status_code == 201
    assert activity(client, bob, "borrowing") == 1 and owed(client, bob) == (0, 80)


# ---- nobody is owed both ways ------------------------------------------------------------------------------------


def shared_dinner(client, bank, alice, total="900", paid_by_alice="900"):
    """A bill Alice paid: you owe Alice your share."""
    dining = next((c for c in client.get("/api/categories/").json() if c["name"] == "Dining"), None) or category(
        client, "Dining"
    )
    return client.post(
        "/api/shared-expenses/",
        params={"confirm": True},
        json={
            "description": "Dinner",
            "total_amount": total,
            "date": "2026-10-05",
            "category_id": dining["id"],
            "participants": [{"is_self": True}, {"contact_id": alice["id"]}],
            "contributions": [{"contact_id": alice["id"], "amount": paid_by_alice}],
        },
    )


def test_a_bill_a_friend_paid_is_evened_out_against_what_they_owe_you(client, bank):
    alice = person(client)
    lend(client, alice, bank, "1000")
    made = shared_dinner(client, bank, alice)
    assert made.status_code == 201, made.text
    assert owed(client, alice) == (550, 0), "you owed Alice 450 for the dinner: it came off the 1,000"
    assert activity(client, alice, "netoff") == 1
    assert client.get("/api/reports/trial-balance").json()["balanced"]
    seen = client.get(f"/api/views/people/{alice['id']}").json()
    assert seen["net"] == "550.00" and "Evened out" in [r["title"] for r in seen["activity"]]
    assert "each way" not in client.get("/api/views/people").json()["label"]


def test_undoing_one_side_takes_the_evening_out_with_it(client, bank):
    alice = person(client)
    loan = lend(client, alice, bank, "1000")
    bill = shared_dinner(client, bank, alice).json()
    assert owed(client, alice) == (550, 0)
    cancelled = client.post(f"/api/shared-expenses/{bill['id']}/cancel")
    assert cancelled.status_code == 204, cancelled.text
    assert owed(client, alice) == (1000, 0) and activity(client, alice, "netoff") == 0
    shared_dinner(client, bank, alice)
    assert client.delete(f"/api/transfers/{loan['id']}").status_code == 204, "the loan was evened out: still undone"
    assert owed(client, alice) == (0, 450) and activity(client, alice, "netoff") == 0
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_the_evening_out_has_no_reverse_of_its_own(client, bank):
    alice = person(client)
    lend(client, alice, bank, "1000")
    shared_dinner(client, bank, alice)
    entry = client.get(f"/api/contacts/{alice['id']}/activity", params={"purpose": "netoff"}).json()["items"][0]
    sheet = client.get(f"/api/views/people/{alice['id']}/entries/{entry['transaction_id']}").json()
    assert sheet["title"] == "Evened out" and sheet["can_reverse"] is False


def test_it_is_dated_the_day_of_the_later_entry(client, bank):
    alice = person(client)
    lend(client, alice, bank, "1000", day="2026-10-01")
    shared_dinner(client, bank, alice)
    entry = client.get(f"/api/contacts/{alice['id']}/activity", params={"purpose": "netoff"}).json()["items"][0]
    assert entry["date"] == "2026-10-05"


# ---- a gift names the person as its payee -------------------------------------------------------------------------


def expense_form(bank, treats, **extra):
    return {
        "kind": "expense",
        "account": [bank["id"], treats["id"]],
        "side": ["credit", "debit"],
        "amount": ["500", "500"],
        "payee": "Alice",
        **extra,
    }


def test_choosing_a_person_as_the_payee_makes_an_ordinary_gift_in_their_activity(client, bank):
    alice = person(client)
    treats = category(client, "Treats")
    saved = save(client, expense_form(bank, treats, payee_contact=alice["id"]))
    assert saved.status_code == 201, saved.text
    assert activity(client, alice, "gift") == 1 and owed(client, alice) == (0, 0)
    entry = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Alice")
    assert client.get("/api/reports/breakdown").json()["lines"][0]["account"] == "Treats", "it is spending"
    # edited as any entry; taking the person off leaves an ordinary expense
    free = save(client, expense_form(bank, treats, payee="Alice", date="2026-11-11"), entry["id"])
    assert free.status_code == 200, free.text
    assert activity(client, alice, "gift") == 0
    save(client, expense_form(bank, treats, payee_contact=alice["id"], date="2026-11-11"), entry["id"])
    assert activity(client, alice, "gift") == 1
    assert client.delete(f"/api/transactions/{entry['id']}").status_code == 204, "an ordinary entry: it can go"
    assert activity(client, alice, "gift") == 0


def test_an_income_from_a_person_is_a_gift_received(client, bank):
    alice = person(client)
    presents = category(client, "Presents", kind="earning")
    data = {
        "kind": "income",
        "account": [presents["id"], bank["id"]],
        "side": ["credit", "debit"],
        "amount": ["200", "200"],
        "payee": "Alice",
        "payee_contact": alice["id"],
    }
    assert save(client, data).status_code == 201
    item = client.get(f"/api/contacts/{alice['id']}/activity", params={"purpose": "gift"}).json()["items"][0]
    assert item["direction"] == "received" and owed(client, alice) == (0, 0)


def test_a_person_can_be_named_on_an_expense_or_income_only(client, bank):
    alice = person(client)
    treats = category(client, "Treats")
    bad = save(client, expense_form(bank, treats, kind="transfer", payee_contact=alice["id"]))
    assert bad.status_code == 400 and "expense or an income only" in bad.text
    assert save(client, expense_form(bank, treats, payee_contact=MISSING)).status_code in (400, 404)
    assert save(client, expense_form(bank, treats, payee_contact="not-an-id")).status_code == 422
    assert all(t["payee"] != "Alice" for t in client.get("/api/transactions/").json()), "nothing was saved"


def test_an_at_sign_in_the_payee_lists_your_people(client, bank):
    person(client, "Anjali"), person(client, "Anand"), person(client, "Ravi")
    gone = person(client, "Anil")
    client.post(f"/api/contacts/{gone['id']}/archive")

    def people(typed):
        found = client.get("/api/transactions/payee-suggestions", params={"payee": typed}).json()
        return [p["name"] for p in found["people"]]

    assert people("@An") == ["Anand", "Anjali"], "A to Z, the archived one left out, Ravi does not match"
    assert people("@") == ["Anand", "Anjali", "Ravi"]
    assert people("An") == [] and people("@zz") == []

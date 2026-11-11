"""People through "+": the pills on a person's page only open the new-transaction screen with the person filled in; money
to or from a person pays back what is owed first; nobody is ever owed both ways; a gift is an ordinary entry that names
the person as its payee."""

import re

import pytest

from .books import category

MISSING = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def bank(client, root_accounts):
    return client.post(
        "/api/accounts/", json={"name": "HDFC", "parent_id": root_accounts["Assets"], "balance": "10000"}
    ).json()


def person(client, name="Alice"):
    return client.post("/api/contacts/", json={"name": name}).json()


def page(client, path, status=200, **params):
    response = client.get(path, params=params)
    assert response.status_code == status, (path, response.status_code, response.text[:200])
    return response.text


def flat(html):
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def lend(client, who, bank, amount="3000", direction="sent", purpose="loan", day="2026-10-01"):
    made = client.post(
        f"/api/contacts/{who['id']}/transfers",
        json={"direction": direction, "purpose": purpose, "amount": amount, "account_id": bank["id"], "date": day},
    )
    assert made.status_code == 201, made.text
    return made.json()


def move(client, who, bank, to_them, amount, **extra):
    """What the "+" screen posts for a transfer with a person on one side."""
    accounts = [bank["id"], who["id"]] if to_them else [who["id"], bank["id"]]
    return client.post(
        "/transactions/split",
        data={
            "account": accounts,
            "side": ["credit", "debit"],
            "amount": [amount, amount],
            "kind": "transfer",
            **extra,
        },
    )


def owed(client, who):
    now = client.get(f"/api/contacts/{who['id']}").json()
    return float(now["receivable"]), float(now["payable"])


def activity(client, who, purpose):
    return client.get(f"/api/contacts/{who['id']}/activity", params={"purpose": purpose}).json()["total"]


# ---- the pills -------------------------------------------------------------------------------------------------


def test_the_pills_only_open_the_new_screen_and_settle_shows_while_something_is_owed(client, bank):
    alice = person(client)
    html = page(client, f"/people/{alice['id']}").replace("&amp;", "&")
    head = html.split("Activity")[0]
    for label in ("Expense", "Lend", "Borrow"):
        assert re.search(rf">\s*{label}\s*<", head), label
    assert not re.search(r">\s*Settle\s*<", head), "nothing is owed, nothing to settle"
    back = f"back=/people/{alice['id']}"
    assert f"/transactions/new?mode=split&with={alice['id']}&{back}" in html
    assert f"/transactions/new?move=lend&with={alice['id']}&{back}" in html
    assert f"/transactions/new?move=borrow&with={alice['id']}&{back}" in html
    lend(client, alice, bank)
    html = page(client, f"/people/{alice['id']}").replace("&amp;", "&")
    assert f"/transactions/new?move=settle&with={alice['id']}&{back}" in html
    for gone in ("transfer", "settle", "netoff"):
        assert client.get(f"/people/{alice['id']}/{gone}").status_code in (404, 405), gone


def selected(html, who):
    """The side of the form (`credit` or `debit`) the person is picked on."""
    for side in ("credit", "debit"):
        section = html.split(f'data-rows="{side}"')[1].split("</section>")[0]
        if re.search(rf'<option value="{who["id"]}"[^>]*selected', section):
            return side
    return None


def test_lend_and_borrow_open_a_transfer_with_the_person_on_one_side(client, bank):
    alice = person(client)
    lent = page(client, "/transactions/new", move="lend", **{"with": alice["id"]})
    assert 'data-txn-kind="transfer"' in lent or 'name="kind" value="transfer"' in lent
    assert selected(lent, alice) == "debit", "the money goes to them"
    borrowed = page(client, "/transactions/new", move="borrow", **{"with": alice["id"]})
    assert selected(borrowed, alice) == "credit", "the money comes from them"
    assert page(client, "/transactions/new", move="lend", **{"with": MISSING}, status=404)


def test_settle_fills_in_what_is_owed_on_the_side_that_clears_it(client, bank):
    alice = person(client)
    lend(client, alice, bank, "3000")
    html = page(client, "/transactions/new", move="settle", **{"with": alice["id"]})
    assert selected(html, alice) == "credit", "they pay you back"
    assert 'value="3000' in html.split('name="total"')[1].split(">")[0]
    lend(client, alice, bank, "5000", direction="received", purpose="borrowing", day="2026-10-02")
    # Alice now owes you nothing and you owe Alice 2,000: the 5,000 you borrowed first paid back her 3,000.
    assert owed(client, alice) == (0, 2000)
    html = page(client, "/transactions/new", move="settle", **{"with": alice["id"]})
    assert selected(html, alice) == "debit", "you pay them back"
    assert 'value="2000' in html.split('name="total"')[1].split(">")[0]


def test_the_people_in_the_pickers_carry_what_they_owe_for_the_note_under_the_form(client, bank):
    alice, bob = person(client), person(client, "Bob")
    lend(client, alice, bank, "3000")
    lend(client, bob, bank, "700", direction="received", purpose="borrowing")
    html = page(client, "/transactions/new")
    assert re.search(rf'<option value="{alice["id"]}"[^>]*data-owes="3000', html)
    assert re.search(rf'<option value="{bob["id"]}"[^>]*data-owes="-700', html)


# ---- money to or from a person ----------------------------------------------------------------------------------


def test_money_from_someone_who_owes_you_pays_that_back_first(client, bank):
    alice = person(client)
    lend(client, alice, bank, "3000")
    part = move(client, alice, bank, to_them=False, amount="1000")
    assert part.status_code == 200, part.text
    assert owed(client, alice) == (2000, 0) and activity(client, alice, "settlement") == 1
    assert activity(client, alice, "borrowing") == 0
    more = move(client, alice, bank, to_them=False, amount="2500")
    assert more.status_code == 200
    assert owed(client, alice) == (0, 500), "the extra 500 is borrowed: you owe Alice"
    assert client.get("/api/reports/trial-balance").json()["balanced"]
    assert (
        float(next(a for a in client.get("/api/accounts/").json() if a["name"] == "HDFC")["balance"])
        == 10000 - 3000 + 3500
    )


def test_money_to_someone_you_owe_pays_that_back_first(client, bank):
    alice = person(client)
    lend(client, alice, bank, "1000", direction="received", purpose="borrowing")
    assert move(client, alice, bank, to_them=True, amount="1500").status_code == 200
    assert owed(client, alice) == (500, 0), "1,000 paid back and 500 lent"
    assert activity(client, alice, "settlement") == 1
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_with_nothing_owed_money_to_or_from_a_person_is_a_loan_or_a_borrowing(client, bank):
    alice = person(client)
    assert move(client, alice, bank, to_them=True, amount="300").status_code == 200
    assert activity(client, alice, "loan") == 1 and owed(client, alice) == (300, 0)
    bob = person(client, "Bob")
    assert move(client, bob, bank, to_them=False, amount="80").status_code == 200
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
    html = page(client, f"/people/{alice['id']}")
    assert "Alice owes you" in flat(html) and "550.00" in flat(html) and "Evened out" in flat(html)
    assert "each way" not in flat(page(client, "/people"))


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
    sheet = page(client, f"/people/{alice['id']}/entry/{entry['transaction_id']}/sheet")
    assert "Evened out" in sheet and "Reverse" not in sheet


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
    saved = client.post("/transactions/split", data=expense_form(bank, treats, payee_contact=alice["id"]))
    assert saved.status_code == 200, saved.text
    assert activity(client, alice, "gift") == 1 and owed(client, alice) == (0, 0)
    entry = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Alice")
    assert client.get("/api/reports/breakdown").json()["lines"][0]["account"] == "Treats", "it is spending"
    html = page(client, f"/transactions/{entry['id']}/edit")
    assert "data-payee-contact" in html and f'value="{alice["id"]}"' in html and "Saved in" in html
    # edited as any entry; taking the person off leaves an ordinary expense
    free = client.post(
        f"/transactions/{entry['id']}/edit", data=expense_form(bank, treats, payee="Alice", date="2026-11-11")
    )
    assert free.status_code == 200, free.text
    assert activity(client, alice, "gift") == 0
    client.post(
        f"/transactions/{entry['id']}/edit",
        data=expense_form(bank, treats, payee_contact=alice["id"], date="2026-11-11"),
    )
    assert activity(client, alice, "gift") == 1
    assert client.delete(f"/api/transactions/{entry['id']}").status_code == 204, "an ordinary entry: it can go"
    assert activity(client, alice, "gift") == 0


def test_an_income_from_a_person_is_a_gift_received(client, bank):
    alice = person(client)
    salary = category(client, "Presents", kind="earning")
    data = {
        "kind": "income",
        "account": [salary["id"], bank["id"]],
        "side": ["credit", "debit"],
        "amount": ["200", "200"],
        "payee": "Alice",
        "payee_contact": alice["id"],
    }
    assert client.post("/transactions/split", data=data).status_code == 200
    item = client.get(f"/api/contacts/{alice['id']}/activity", params={"purpose": "gift"}).json()["items"][0]
    assert item["direction"] == "received" and owed(client, alice) == (0, 0)


def test_a_person_can_be_named_on_an_expense_or_income_only(client, bank):
    alice = person(client)
    treats = category(client, "Treats")
    bad = client.post(
        "/transactions/split", data=expense_form(bank, treats, kind="transfer", payee_contact=alice["id"])
    )
    assert bad.status_code == 400 and "expense or an income only" in bad.text
    nobody = client.post("/transactions/split", data=expense_form(bank, treats, payee_contact=MISSING))
    assert nobody.status_code == 400
    assert all(t["payee"] != "Alice" for t in client.get("/api/transactions/").json()), "nothing was saved"
    junk = client.post("/transactions/split", data=expense_form(bank, treats, payee_contact="not-an-id"))
    assert junk.status_code == 400 and "choose the person" in junk.text


def test_an_at_sign_in_the_payee_lists_your_people(client, bank):
    person(client, "Anjali"), person(client, "Anand"), person(client, "Ravi")
    gone = person(client, "Anil")
    client.post(f"/api/contacts/{gone['id']}/archive")
    chips = client.get("/transactions/suggest", params={"payee": "@An"}).text
    names = re.findall(r'data-payee="([^"]+)" data-contact', chips)
    assert names == ["Anand", "Anjali"], "A to Z, the archived one left out, Ravi does not match"
    assert re.findall(
        r'data-payee="([^"]+)" data-contact', client.get("/transactions/suggest", params={"payee": "@"}).text
    ) == [
        "Anand",
        "Anjali",
        "Ravi",
    ]
    assert "data-contact" not in client.get("/transactions/suggest", params={"payee": "An"}).text
    assert client.get("/transactions/suggest", params={"payee": "@zz"}).text.strip() == ""

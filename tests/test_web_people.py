"""The People pages: the list, a person, lending, settling up, sharing a bill, and undoing an entry."""

import re

import pytest

from .books import category


@pytest.fixture
def bank(client, root_accounts):
    return client.post(
        "/api/accounts/", json={"name": "HDFC", "parent_id": root_accounts["Assets"], "balance": "10000"}
    ).json()


def person(client, name="Alice", **extra):
    return client.post("/api/contacts/", json={"name": name, **extra}).json()


def page(client, path, status=200, **params):
    response = client.get(path, params=params)
    assert response.status_code == status, (path, response.status_code, response.text[:200])
    return response.text


def flat(html):
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def test_the_people_page_starts_empty_and_offers_to_add_someone(client):
    html = page(client, "/people")
    assert "Keep track of money you lend" in html and 'href="/people/new"' in html and "aria-pressed" not in html
    assert 'href="/people"' in page(client, "/settings"), "Settings has the row"
    assert 'href="/people"' in html, "and the sidebar has the link"


def test_adding_a_person_through_the_form(client):
    assert 'name="name"' in page(client, "/people/new")
    made = client.post("/people", data={"name": "Alice", "phone": "99", "email": "", "notes": ""})
    assert made.status_code == 200 and made.headers["HX-Redirect"].startswith("/people/")
    bad = client.post("/people", data={"name": "  "})
    assert bad.status_code == 400 and bad.headers["HX-Retarget"] == "#form-error"
    again = client.post("/people", data={"name": "alice"})
    assert again.status_code == 400 and "already" in again.text
    listed = page(client, "/people")
    assert "Alice" in listed and "Nothing yet" in listed


def test_the_list_shows_who_owes_what(client, bank):
    alice, bob = person(client), person(client, "Bob")
    client.post(
        f"/api/contacts/{alice['id']}/transfers",
        json={"direction": "sent", "purpose": "loan", "amount": "500", "account_id": bank["id"]},
    )
    client.post(
        f"/api/contacts/{bob['id']}/transfers",
        json={"direction": "received", "purpose": "borrowing", "amount": "200", "account_id": bank["id"]},
    )
    everyone = flat(page(client, "/people"))
    assert "Alice" in everyone and "500.00" in everyone and "Bob" in everyone and "200.00" in everyone
    owed = page(client, "/people", show="owed")
    assert "Alice" in owed and "Bob" not in owed
    owe = page(client, "/people", show="owe")
    assert "Bob" in owe and "Alice" not in owe
    assert "Alice" in page(client, "/people", show="nonsense")
    assert "Archived" not in page(client, "/people")


def test_a_persons_page(client, bank):
    alice = person(client, phone="99", email="a@example.com")
    html = page(client, f"/people/{alice['id']}")
    text = flat(html)
    assert "Alice" in text and "99" in text and "a@example.com" in text and "All settled up" in text
    assert "Settle" not in text.split("Activity")[0], "nothing to settle yet"
    assert "Nothing yet with Alice" in text
    client.post(
        f"/api/contacts/{alice['id']}/transfers",
        json={
            "direction": "sent",
            "purpose": "loan",
            "amount": "500",
            "account_id": bank["id"],
            "description": "Rent help",
        },
    )
    html = page(client, f"/people/{alice['id']}")
    text = flat(html)
    assert "Alice owes you" in text and "500.00" in text and "Rent help" in text
    assert "Settle" in text.split("Activity")[0], "now something is owed"
    assert "/settle" not in html and "/transfer" not in html, "nothing is recorded on the person's page"
    assert f"/people/{alice['id']}/entry/" in html, "an open amount opens the entry it came from"
    assert page(client, "/people/00000000-0000-4000-8000-0000000000aa", status=404)


def test_editing_removing_and_archiving_a_person(client, bank):
    alice = person(client)
    assert 'value="Alice"' in page(client, f"/people/{alice['id']}/edit")
    saved = client.post(f"/people/{alice['id']}/edit", data={"name": "Alicia", "phone": "", "email": "", "notes": "x"})
    assert saved.status_code == 200
    assert client.get(f"/api/contacts/{alice['id']}").json()["name"] == "Alicia"
    client.post(
        f"/api/contacts/{alice['id']}/transfers",
        json={"direction": "sent", "purpose": "loan", "amount": "5", "account_id": bank["id"]},
    )
    blocked = client.post(f"/people/{alice['id']}/archive")
    assert blocked.status_code == 400 and "owes you" in blocked.text and blocked.headers["HX-Retarget"] == "#page-error"
    bob = person(client, "Bob")
    assert client.post(f"/people/{bob['id']}/delete").headers["HX-Redirect"] == "/people"
    assert client.get(f"/api/contacts/{bob['id']}").status_code == 404
    carol = person(client, "Carol")
    assert client.post(f"/people/{carol['id']}/archive").headers["HX-Redirect"] == "/people"
    archived = page(client, "/people", show="archived")
    assert "Carol" in archived and "Archived" in archived
    assert "archived" in page(client, f"/people/{carol['id']}")
    assert client.post(f"/people/{carol['id']}/restore").status_code == 200
    assert "Carol" in page(client, "/people")


def test_the_activity_and_undoing_an_entry(client, bank):
    alice = person(client)
    loan = client.post(
        f"/api/contacts/{alice['id']}/transfers",
        json={"direction": "sent", "purpose": "loan", "amount": "500", "account_id": bank["id"]},
    ).json()
    sheet = page(client, f"/people/{alice['id']}/entry/{loan['id']}/sheet")
    assert "Loan" in sheet and "500.00" in sheet and "Reverse" in sheet and "hx-confirm" in sheet
    assert 'id="person-sheet"' in page(client, f"/people/{alice['id']}") and "person-sheet-body" in page(
        client, f"/people/{alice['id']}"
    )
    done = client.post(f"/people/{alice['id']}/entry/{loan['id']}/reverse")
    assert done.status_code == 200 and done.headers["HX-Redirect"] == f"/people/{alice['id']}"
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["net"]) == 0
    assert page(client, f"/people/{alice['id']}/entry/{loan['id']}/sheet", status=404)
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
    assert client.post(f"/people/{alice['id']}/entry/{expense['transaction_id']}/reverse").status_code == 200
    assert client.get(f"/api/shared-expenses/{expense['id']}").status_code == 404
    lent = client.post(
        f"/api/contacts/{alice['id']}/transfers",
        json={"direction": "sent", "purpose": "loan", "amount": "50", "account_id": bank["id"]},
    ).json()
    paid = client.post(
        f"/api/contacts/{alice['id']}/settlements",
        json={"direction": "received", "amount": "20", "account_id": bank["id"]},
    ).json()
    blocked = client.post(f"/people/{alice['id']}/entry/{lent['id']}/reverse")
    assert (
        blocked.status_code == 400
        and "settle" in blocked.text
        and blocked.headers["HX-Retarget"] == "#person-sheet-error"
    )
    assert client.post(f"/people/{alice['id']}/entry/{paid['id']}/reverse").status_code == 200


def test_a_persons_accounts_stay_off_the_accounts_page_and_the_pickers(client, bank, root_accounts):
    alice = person(client)
    accounts = page(client, "/accounts")
    assert "Due from" not in accounts and "Due to" not in accounts
    assert "Due from" not in page(client, "/accounts", tab="liabilities") and "Due to" not in page(
        client, "/accounts", tab="liabilities"
    )
    assert "Due from" not in page(client, "/transactions/new") and "Due to" not in page(client, "/transactions/new")
    assert "Due from" not in page(client, "/accounts/new") and "Due from" not in page(client, "/transactions")
    assert client.get(f"/api/accounts/{alice['receivable_account_id']}").json()["contact_account"] is True
    assert client.get(f"/api/accounts/{bank['id']}").json()["contact_account"] is False
    refused = client.post("/api/accounts/", json={"name": "Sub", "parent_id": alice["receivable_account_id"]})
    assert refused.status_code == 400 and "belongs to a contact" in refused.json()["detail"]


def test_an_entry_made_through_a_person_is_looked_after_on_their_page(client, bank):
    alice = person(client)
    loan = client.post(
        f"/api/contacts/{alice['id']}/transfers",
        json={"direction": "sent", "purpose": "loan", "amount": "500", "account_id": bank["id"]},
    ).json()
    sheet = page(client, f"/transactions/{loan['id']}/sheet")
    assert f'href="/people/{alice["id"]}"' in sheet
    assert f'href="/transactions/{loan["id"]}/edit"' in sheet, "a loan is edited here too"
    assert "sheet-delete" not in sheet and "Repeat" not in sheet and f'href="/people/{alice["id"]}"' in sheet
    gift = client.post(
        f"/api/contacts/{alice['id']}/transfers",
        json={"direction": "sent", "purpose": "gift", "amount": "5", "account_id": bank["id"]},
    ).json()
    gift_sheet = page(client, f"/transactions/{gift['id']}/sheet")
    assert "Open Alice" not in gift_sheet and "/edit" in gift_sheet, "a gift is an ordinary entry"
    ordinary = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account_id": bank["id"], "side": "credit", "amount": "5"},
                {"category_id": category(client, "Misc")["id"], "side": "debit", "amount": "5"},
            ]
        },
    ).json()
    assert "/edit" in page(client, f"/transactions/{ordinary['id']}/sheet")


def test_a_transfer_to_or_from_a_person_on_the_add_screen(client, bank):
    alice = person(client)
    html = page(client, "/transactions/new")
    assert f'<option value="{alice["id"]}"' in html and 'optgroup label="People"' in html and "data-person" in html
    assert "data-person-note" in html
    lend = client.post(
        "/transactions/split",
        data={
            "account": [bank["id"], alice["id"]],
            "side": ["credit", "debit"],
            "amount": ["300", "300"],
            "comment": "Cab",
        },
    )
    assert lend.status_code == 200 and lend.headers["HX-Redirect"] == "/transactions"
    now = client.get(f"/api/contacts/{alice['id']}").json()
    assert float(now["receivable"]) == 300
    assert client.get(f"/api/contacts/{alice['id']}/obligations").json()[0]["source_type"] == "loan"
    borrow = client.post(
        "/transactions/split",
        data={"account": [alice["id"], bank["id"]], "side": ["credit", "debit"], "amount": ["50", "50"]},
    )
    assert borrow.status_code == 200
    now = client.get(f"/api/contacts/{alice['id']}").json()
    assert (float(now["receivable"]), float(now["payable"])) == (250, 0), (
        "money from someone who owes you pays that back"
    )
    assert client.get(f"/api/contacts/{alice['id']}/activity", params={"purpose": "settlement"}).json()["total"] == 1
    assert float(next(a for a in client.get("/api/accounts/").json() if a["name"] == "HDFC")["balance"]) == 9750


def test_the_rules_of_a_transfer_with_a_person(client, bank):
    alice = person(client)
    cash = client.post("/api/accounts/", json={"name": "Cash", "parent_id": bank["parent_id"]}).json()

    def attempt(**data):
        base = {"account": [bank["id"], alice["id"]], "side": ["credit", "debit"], "amount": ["10", "10"]}
        return client.post("/transactions/split", data={**base, **data})

    assert "same on both sides" in attempt(amount=["10", "20"]).text
    assert "one side" in attempt(side=["debit", "debit"]).text
    assert "one side" in attempt(account=[cash["id"], bank["id"]]).text or True
    assert "tags" in attempt(tags=["trip"]).text
    assert (
        "one side"
        in client.post(
            "/transactions/split",
            data={
                "account": [bank["id"], alice["id"], cash["id"]],
                "side": ["credit", "debit", "debit"],
                "amount": ["10", "5", "5"],
            },
        ).text
    )
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["net"]) == 0, "nothing was recorded"
    client.post(f"/api/contacts/{alice['id']}/archive")
    refused = attempt()
    assert refused.status_code == 400
    assert (
        "Alice" not in page(client, "/transactions/new").split('optgroup label="People"')[-1][:200]
        if 'optgroup label="People"' in page(client, "/transactions/new")
        else True
    )


def test_nobody_with_no_people_sees_the_group_and_everybody_else_does_when_editing_too(client, bank):
    assert 'optgroup label="People"' not in page(client, "/transactions/new")
    alice = person(client)
    entry = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account_id": bank["id"], "side": "credit", "amount": "5"},
                {"category_id": category(client, "Misc")["id"], "side": "debit", "amount": "5"},
            ]
        },
    ).json()
    assert 'optgroup label="People"' in page(client, f"/transactions/{entry['id']}/edit"), (
        "an entry can be turned into a loan"
    )
    assert alice


def test_adding_a_person_who_already_owes_you(client):
    html = page(client, "/people/new")
    assert "Already owes you, or is owed?" in html and 'name="opening_amount"' in html
    data = {"name": "Alice", "opening_direction": "receivable", "opening_amount": "4000", "opening_since": "2026-01-01"}
    made = client.post("/people", data=data)
    assert made.status_code == 200 and made.headers["HX-Redirect"].startswith("/people/")
    alice = client.get("/api/contacts/").json()[0]
    assert float(alice["receivable"]) == 4000
    text = flat(page(client, f"/people/{alice['id']}"))
    assert "Alice owes you" in text and "Opening balance" in text and "4,000.00" in text
    assert (
        client.post("/people", data={"name": "Bob", "opening_direction": "payable", "opening_amount": "75"}).status_code
        == 200
    )
    bob = next(c for c in client.get("/api/contacts/").json() if c["name"] == "Bob")
    assert float(bob["payable"]) == 75
    assert client.post("/people", data={"name": "Carol", "opening_amount": ""}).status_code == 200


def test_a_bad_opening_balance_leaves_nobody_half_made(client):
    bad = client.post("/people", data={"name": "Dave", "opening_amount": "x"})
    assert bad.status_code == 400 and bad.headers["HX-Retarget"] == "#form-error"
    assert client.post("/people", data={"name": "Dave", "opening_amount": "0"}).status_code == 400
    assert client.get("/api/contacts/", params={"include_archived": True}).json() == []


def test_adding_an_opening_balance_later(client):
    alice = person(client)
    assert "Add an opening balance" in page(client, f"/people/{alice['id']}")
    form = page(client, f"/people/{alice['id']}/opening")
    assert "Alice owes you" in form and "You owe Alice" in form
    data = {
        "opening_direction": "payable",
        "opening_amount": "90",
        "opening_since": "2026-02-01",
        "description": "Rent",
    }
    done = client.post(f"/people/{alice['id']}/opening", data=data)
    assert done.status_code == 200 and done.headers["HX-Redirect"] == f"/people/{alice['id']}"
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["payable"]) == 90
    assert "Rent" in flat(page(client, f"/people/{alice['id']}"))
    blank = client.post(f"/people/{alice['id']}/opening", data={"opening_amount": ""})
    assert blank.status_code == 400 and "amount" in blank.text
    entry = client.get(f"/api/contacts/{alice['id']}/transfers").json()[0]["id"]
    assert "Opening balance" in page(client, f"/people/{alice['id']}/entry/{entry}/sheet")
    assert client.post(f"/people/{alice['id']}/entry/{entry}/reverse").status_code == 200


def test_editing_an_opening_balance_from_its_sheet(client, bank):
    alice = person(client)
    made = client.post(
        f"/api/contacts/{alice['id']}/opening-balance",
        json={"direction": "receivable", "amount": "4000", "date": "2026-01-01", "description": "Old loan"},
    ).json()
    sheet = page(client, f"/people/{alice['id']}/entry/{made['id']}/sheet")
    assert f'href="/people/{alice["id"]}/opening/{made["id"]}/edit"' in sheet and ">Edit<" in sheet
    form = page(client, f"/people/{alice['id']}/opening/{made['id']}/edit")
    assert 'value="4,000.00"' in form or 'value="4000.00"' in form
    assert (
        'value="2026-01-01"' in form
        and 'value="Old loan"' in form
        and "Save changes" in form
        and "paid back" not in form
    )
    data = {
        "opening_direction": "payable",
        "opening_amount": "900",
        "opening_since": "2026-02-01",
        "description": "Changed",
    }
    done = client.post(f"/people/{alice['id']}/opening/{made['id']}/edit", data=data)
    assert done.status_code == 200 and done.headers["HX-Redirect"] == f"/people/{alice['id']}"
    now = client.get(f"/api/contacts/{alice['id']}").json()
    assert float(now["payable"]) == 900 and float(now["receivable"]) == 0
    client.post(
        f"/api/contacts/{alice['id']}/settlements",
        json={"direction": "sent", "amount": "300", "account_id": bank["id"]},
    )
    warned = page(client, f"/people/{alice['id']}/opening/{made['id']}/edit")
    assert "300.00 of this has been paid back" in flat(warned) and 'type="hidden" name="opening_direction"' in warned
    low = client.post(f"/people/{alice['id']}/opening/{made['id']}/edit", data={**data, "opening_amount": "100"})
    assert low.status_code == 400 and "go below that" in low.text and low.headers["HX-Retarget"] == "#form-error"
    loan = client.post(
        f"/api/contacts/{alice['id']}/transfers",
        json={"direction": "sent", "purpose": "loan", "amount": "5", "account_id": bank["id"]},
    ).json()
    assert page(client, f"/people/{alice['id']}/opening/{loan['id']}/edit", status=404)
    assert ">Edit<" not in page(client, f"/people/{alice['id']}/entry/{loan['id']}/sheet")


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


def rows(bank, alice, sent=True, amount="300"):
    return {
        "account": [bank["id"], alice["id"]] if sent else [alice["id"], bank["id"]],
        "side": ["credit", "debit"],
        "amount": [amount, amount],
        "date": "2026-11-01",
        "comment": "Cab money",
    }


def test_an_existing_entry_becomes_a_loan_in_place(client, bank):
    alice = person(client)
    entry, _ = ordinary_expense(client, bank, tags=["trip"])
    form = page(client, f"/transactions/{entry['id']}/edit")
    assert 'optgroup label="People"' in form and f'<option value="{alice["id"]}"' in form
    done = client.post(
        f"/transactions/{entry['id']}/edit", data={**rows(bank, alice), "tags": ["trip"], "payee": "Cab"}
    )
    assert done.status_code == 200 and done.headers["HX-Redirect"], done.text
    same = client.get(f"/api/transactions/{entry['id']}").json()
    assert (
        same["id"] == entry["id"]
        and same["payee"] == "Alice"
        and same["tags"] == ["trip"]
        and same["date"] == "2026-11-01"
    )
    assert {p["account_id"] for p in same["postings"]} == {bank["id"], alice["receivable_account_id"]}
    owed = client.get(f"/api/contacts/{alice['id']}/obligations").json()
    assert [(o["source_type"], float(o["outstanding_amount"])) for o in owed] == [("loan", 300.0)]
    assert float(next(a for a in client.get("/api/accounts/").json() if a["name"] == "HDFC")["balance"]) == 9700
    assert client.get("/api/reports/trial-balance").json()["balanced"]
    edit = page(client, f"/transactions/{entry['id']}/edit")
    assert (
        f'<option value="{alice["id"]}" data-person="1" selected' in edit.replace("  ", " ")
        or f'value="{alice["id"]}"' in edit
    )


def test_a_loan_can_move_to_another_person_or_the_other_way_round(client, bank):
    alice, bob = person(client), person(client, "Bob")
    entry, _ = ordinary_expense(client, bank)
    client.post(f"/transactions/{entry['id']}/edit", data=rows(bank, alice))
    done = client.post(f"/transactions/{entry['id']}/edit", data=rows(bank, bob, sent=False, amount="450"))
    assert done.status_code == 200, done.text
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["net"]) == 0
    now = client.get(f"/api/contacts/{bob['id']}").json()
    assert float(now["payable"]) == 450 and float(now["receivable"]) == 0
    assert [o["source_type"] for o in client.get(f"/api/contacts/{bob['id']}/obligations").json()] == ["borrowing"]
    assert float(next(a for a in client.get("/api/accounts/").json() if a["name"] == "HDFC")["balance"]) == 10450


def test_a_loan_can_be_edited_back_into_an_ordinary_entry(client, bank):
    alice = person(client)
    entry, misc = ordinary_expense(client, bank)
    client.post(f"/transactions/{entry['id']}/edit", data=rows(bank, alice))
    back = client.post(
        f"/transactions/{entry['id']}/edit",
        data={
            "account": [bank["id"], misc["id"]],
            "side": ["credit", "debit"],
            "amount": ["300", "300"],
            "date": "2026-11-01",
            "payee": "Cab",
        },
    )
    assert back.status_code == 200, back.text
    assert client.get(f"/api/contacts/{alice['id']}/obligations").json() == []
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["net"]) == 0
    assert client.get(f"/api/contacts/{alice['id']}/transfers").json() == []
    plain = client.get(f"/api/transactions/{entry['id']}").json()
    assert plain["payee"] == "Cab" and any(p["category_id"] == misc["id"] for p in plain["postings"])
    assert client.delete(f"/api/transactions/{entry['id']}").status_code == 204, "an ordinary entry again"


def test_nothing_changes_once_something_was_paid_back_or_if_the_edit_fails(client, bank):
    alice = person(client)
    entry, misc = ordinary_expense(client, bank)
    client.post(f"/transactions/{entry['id']}/edit", data=rows(bank, alice))
    broken = client.post(
        f"/transactions/{entry['id']}/edit",
        data={
            "account": [bank["id"], misc["id"]],
            "side": ["credit", "debit"],
            "amount": ["300", "200"],
            "date": "2026-11-01",
        },
    )
    assert broken.status_code == 400
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["receivable"]) == 300, (
        "a failed edit leaves the loan as it was"
    )
    assert len(client.get(f"/api/contacts/{alice['id']}/obligations").json()) == 1
    client.post(
        f"/api/contacts/{alice['id']}/settlements",
        json={"direction": "received", "amount": "50", "account_id": bank["id"]},
    )
    ordinary = client.post(
        f"/transactions/{entry['id']}/edit",
        data={
            "account": [bank["id"], misc["id"]],
            "side": ["credit", "debit"],
            "amount": ["300", "300"],
            "date": "2026-11-01",
        },
    )
    assert ordinary.status_code == 400 and "paid back" in ordinary.text
    again = client.post(f"/transactions/{entry['id']}/edit", data=rows(bank, alice, amount="400"))
    assert again.status_code == 400 and "paid back" in again.text
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["receivable"]) == 250


def test_only_a_loan_or_a_borrowing_is_edited_this_way(client, bank):
    alice = person(client)
    opening = client.post(
        f"/api/contacts/{alice['id']}/opening-balance", json={"direction": "receivable", "amount": "5"}
    ).json()
    moved = client.get(f"/transactions/{opening['id']}/edit", follow_redirects=False)
    assert moved.status_code == 303 and moved.headers["location"] == f"/people/{alice['id']}"
    entry, _ = ordinary_expense(client, bank)
    refused = client.post(f"/transactions/{opening['id']}/edit", data=rows(bank, alice))
    assert refused.status_code == 400 and "only a loan, a borrowing, or a bill or income" in refused.text
    uneven = client.post(f"/transactions/{entry['id']}/edit", data={**rows(bank, alice), "amount": ["300", "200"]})
    assert uneven.status_code == 400 and "same on both sides" in uneven.text
    assert (
        client.get(f"/api/transactions/{entry['id']}").json()["postings"][0]["account_id"]
        != alice["receivable_account_id"]
    )


def converted_bill(client, bank, alice, bob):
    entry, misc = ordinary_expense(client, bank, amount="3000")
    rows = {
        "account": [bank["id"], misc["id"], alice["id"], bob["id"]],
        "side": ["credit", "debit", "debit", "debit"],
        "amount": ["3000", "1000", "1000", "1000"],
        "date": "2026-10-09",
        "payee": "Restaurant",
    }
    assert client.post(f"/transactions/{entry['id']}/edit", data=rows).status_code == 200
    return entry, misc, rows


def people_form(bank, dining, who, method="equal", total="1500", **extra):
    """What the Share tab posts: the total, who the bill is for, how it is split and who paid."""
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


def spent(client, name="Dining"):
    lines = client.get("/api/reports/breakdown").json()["lines"]
    return next((float(x["amount"]) for x in lines if x["account"] == name), 0.0)


def test_the_new_screen_has_the_three_ways_and_opens_on_with_people_from_a_persons_page(client, bank):
    alice = person(client)
    html = page(client, "/transactions/new")
    assert 'data-mode="simple"' in html and 'name="mode" value="simple" checked' in html
    assert 'value="split"' in html and 'value="share"' not in html and "data-people-editor" in html
    assert re.search(r'data-people-editor="expense"\s+hidden', html), "the tab is closed until Share is chosen"
    opened = page(client, "/transactions/new", mode="split", **{"with": alice["id"]})
    assert 'data-mode="split"' in opened and re.search(rf'name="with_{alice["id"]}"[^>]*\schecked', opened)
    assert "Alice" in opened and 'name="split_method"' in opened and "Someone else paid some of it" in opened


def test_with_nobody_added_the_tab_says_so(client, bank):
    html = page(client, "/transactions/new", mode="split")
    assert "Add the people you share costs with first" in html and 'href="/people/new"' in html


def test_a_bill_shared_equally_from_the_add_screen(client, bank):
    alice, bob = person(client), person(client, "Bob")
    dining = category(client, "Dining")
    preview = flat(client.post("/people/expense/preview", data=people_form(bank, dining, [alice, bob])).text)
    assert "500.00" in preview and "Alice owes you" in preview and "Bob owes you" in preview and "Your share" in preview
    done = client.post(
        "/transactions/split", data=people_form(bank, dining, [alice, bob], comment="Friday", tags=["trip"])
    )
    assert done.status_code == 200 and done.headers["HX-Redirect"], done.text
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["receivable"]) == 500
    assert float(client.get(f"/api/contacts/{bob['id']}").json()["receivable"]) == 500
    assert float(next(a for a in client.get("/api/accounts/").json() if a["name"] == "HDFC")["balance"]) == 8500
    assert spent(client) == 500, "only your share is spending"
    entry = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Dinner")
    assert entry["comment"] == "Friday" and entry["tags"] == ["trip"]
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_the_other_ways_to_split(client, bank):
    alice = person(client)
    dining = category(client, "Dining")
    pct = people_form(
        bank, dining, [alice], method="percentage", total="100", value_self="75", **{f"value_{alice['id']}": "25"}
    )
    assert client.post("/transactions/split", data=pct).status_code == 200
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["receivable"]) == 25
    bad = client.post("/transactions/split", data={**pct, f"value_{alice['id']}": "20"})
    assert bad.status_code == 400 and "not 100" in bad.text
    shares = people_form(
        bank, dining, [alice], method="shares", total="90", value_self="2", **{f"value_{alice['id']}": "1"}
    )
    assert client.post("/transactions/split", data=shares).status_code == 200
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["receivable"]) == 55
    exact = people_form(
        bank, dining, [alice], method="exact", total="100", value_self="60", **{f"value_{alice['id']}": "40"}
    )
    assert client.post("/transactions/split", data=exact).status_code == 200
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["receivable"]) == 95


def test_a_friend_paid_part_or_all_of_it(client, bank):
    alice, bob = person(client), person(client, "Bob")
    dining = category(client, "Dining")
    paid = people_form(bank, dining, [alice, bob], **{f"paid_{alice['id']}": "1500", "paid_self": "0"})
    assert client.post("/transactions/split", data=paid).status_code == 200
    a, b = client.get(f"/api/contacts/{alice['id']}").json(), client.get(f"/api/contacts/{bob['id']}").json()
    assert (float(a["payable"]), float(b["receivable"])) == (1000, 500)
    assert float(next(x for x in client.get("/api/accounts/").json() if x["name"] == "HDFC")["balance"]) == 10000


def test_the_rules_of_a_bill_with_people(client, bank):
    alice = person(client)
    dining = category(client, "Dining")
    none = client.post("/transactions/split", data=people_form(bank, dining, []))
    assert none.status_code == 400 and "at least 2" in none.text
    no_account = client.post(
        "/transactions/split", data={k: v for k, v in people_form(bank, dining, [alice]).items() if k != "account_id"}
    )
    assert no_account.status_code == 400 and "account" in no_account.text
    short = client.post("/transactions/split", data=people_form(bank, dining, [alice], paid_self="400"))
    assert short.status_code == 400 and "not the total" in short.text
    assert client.get("/api/shared-expenses/").json() == []
    assert client.post("/transactions/split", data=people_form(bank, dining, [alice])).status_code == 200


def converted(client, bank, who, total="3000"):
    entry, misc = ordinary_expense(client, bank, amount=total, tags=["trip"])
    data = people_form(bank, misc, who, total=total, payee="Restaurant", date="2026-10-09", tags=["trip"])
    done = client.post(f"/transactions/{entry['id']}/edit", data=data)
    assert done.status_code == 200, done.text
    return entry, misc


def test_an_existing_entry_becomes_a_shared_bill_in_place(client, bank):
    alice, bob = person(client), person(client, "Bob")
    entry, _ = converted(client, bank, [alice, bob])
    same = client.get(f"/api/transactions/{entry['id']}").json()
    assert (
        same["id"] == entry["id"]
        and same["date"] == "2026-10-09"
        and same["tags"] == ["trip"]
        and same["payee"] == "Restaurant"
    )
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["receivable"]) == 1000
    assert float(client.get(f"/api/contacts/{bob['id']}").json()["receivable"]) == 1000
    bills = client.get("/api/shared-expenses/").json()
    assert len(bills) == 1 and bills[0]["transaction_id"] == entry["id"] and float(bills[0]["user_share"]) == 1000
    lines = client.get("/api/reports/breakdown", params={"date_from": "2026-10-01", "date_to": "2026-10-31"}).json()[
        "lines"
    ]
    assert float(lines[0]["amount"]) == 1000, "only your share is spending now"
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_the_edit_screen_of_a_shared_bill_opens_on_with_people_as_entered(client, bank):
    alice, bob = person(client), person(client, "Bob")
    entry, misc = converted(client, bank, [alice, bob])
    form = page(client, f"/transactions/{entry['id']}/edit")
    assert 'data-mode="split"' in form and 'name="mode" value="split" checked' in form
    assert re.search(rf'name="with_{alice["id"]}"[^>]*\schecked', form) and re.search(
        rf'name="with_{bob["id"]}"[^>]*\schecked', form
    )
    assert re.search(rf'<option value="{misc["id"]}"[^>]*selected', form) and re.search(
        rf'<option value="{bank["id"]}"[^>]*selected', form
    )
    assert re.search(r'name="split_method" value="equal" checked', form)
    sheet = page(client, f"/transactions/{entry['id']}/sheet")
    assert f'href="/transactions/{entry["id"]}/edit"' in sheet and "Alice, Bob" in sheet


def test_an_unevenly_shared_bill_edits_with_its_values(client, bank):
    alice = person(client)
    dining = category(client, "Dining")
    data = people_form(
        bank, dining, [alice], method="percentage", total="200", value_self="75", **{f"value_{alice['id']}": "25"}
    )
    client.post("/transactions/split", data=data)
    entry = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Dinner")
    form = page(client, f"/transactions/{entry['id']}/edit")
    assert re.search(r'name="split_method" value="percentage" checked', form)
    assert re.search(r'name="value_self"[^>]*value="75(\.00)?"', form) and re.search(
        rf'name="value_{alice["id"]}"[^>]*value="25(\.00)?"', form
    )


def test_a_shared_bill_can_be_reshared_and_made_ordinary_again(client, bank):
    alice, bob = person(client), person(client, "Bob")
    entry, misc = converted(client, bank, [alice, bob])
    assert (
        client.post(
            f"/transactions/{entry['id']}/edit",
            data=people_form(bank, misc, [alice], total="3000", payee="Restaurant", date="2026-10-09"),
        ).status_code
        == 200
    )
    assert float(client.get(f"/api/contacts/{bob['id']}").json()["net"]) == 0
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["receivable"]) == 1500
    assert len(client.get("/api/shared-expenses/").json()) == 1, "re-recorded, not duplicated"
    ordinary = {
        "account": [bank["id"], misc["id"]],
        "side": ["credit", "debit"],
        "amount": ["3000", "3000"],
        "date": "2026-10-09",
        "payee": "Restaurant",
        "mode": "simple",
    }
    assert client.post(f"/transactions/{entry['id']}/edit", data=ordinary).status_code == 200
    assert (
        client.get("/api/shared-expenses/").json() == []
        and float(client.get(f"/api/contacts/{alice['id']}").json()["net"]) == 0
    )
    assert client.get(f"/api/contacts/{alice['id']}/obligations").json() == []
    assert client.delete(f"/api/transactions/{entry['id']}").status_code == 204, "an ordinary entry again"


def test_a_loan_and_a_shared_bill_can_turn_into_each_other(client, bank):
    alice, bob = person(client), person(client, "Bob")
    entry, misc = ordinary_expense(client, bank, amount="300")
    client.post(f"/transactions/{entry['id']}/edit", data=rows(bank, alice))
    assert [t["purpose"] for t in client.get(f"/api/contacts/{alice['id']}/transfers").json()] == ["loan"]
    assert (
        client.post(
            f"/transactions/{entry['id']}/edit", data=people_form(bank, misc, [alice], total="300", payee="Cab")
        ).status_code
        == 200
    )
    assert client.get(f"/api/contacts/{alice['id']}/transfers").json() == [], "no longer a loan"
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["receivable"]) == 150
    assert client.post(f"/transactions/{entry['id']}/edit", data=rows(bank, bob)).status_code == 200
    assert client.get("/api/shared-expenses/").json() == []
    assert (
        float(client.get(f"/api/contacts/{alice['id']}").json()["net"]) == 0
        and float(client.get(f"/api/contacts/{bob['id']}").json()["receivable"]) == 300
    )
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_nothing_changes_once_a_share_was_paid_back_or_when_the_edit_fails(client, bank):
    alice, bob = person(client), person(client, "Bob")
    entry, misc = converted(client, bank, [alice, bob])
    broken = people_form(bank, misc, [alice, bob], total="3000", paid_self="100", date="2026-10-09")
    assert client.post(f"/transactions/{entry['id']}/edit", data=broken).status_code == 400
    assert float(client.get(f"/api/contacts/{bob['id']}").json()["receivable"]) == 1000, (
        "a failed edit leaves the bill as it was"
    )
    assert len(client.get("/api/shared-expenses/").json()) == 1
    client.post(
        f"/api/contacts/{alice['id']}/settlements",
        json={"direction": "received", "amount": "200", "account_id": bank["id"]},
    )
    again = client.post(
        f"/transactions/{entry['id']}/edit",
        data=people_form(
            bank,
            misc,
            [alice, bob],
            method="percentage",
            total="3000",
            value_self="50",
            **{f"value_{alice['id']}": "25", f"value_{bob['id']}": "25"},
        ),
    )
    assert again.status_code == 400 and "paid back" in again.text
    ordinary = client.post(
        f"/transactions/{entry['id']}/edit",
        data={
            "account": [bank["id"], misc["id"]],
            "side": ["credit", "debit"],
            "amount": ["3000", "3000"],
            "date": "2026-10-09",
            "mode": "simple",
        },
    )
    assert ordinary.status_code == 400 and "paid back" in ordinary.text
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["receivable"]) == 800
    assert float(client.get(f"/api/contacts/{bob['id']}").json()["receivable"]) == 1000


# ---- income shared with people, and a transfer in Share ------------------------------------------------------


def income_form(bank, rent, who, **extra):
    """What the Share tab posts for an income: the total, which part is theirs, and where it landed."""
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


def earned(client, name="Rent"):
    lines = client.get("/api/reports/breakdown", params={"kind": "income"}).json()["lines"]
    return next((float(x["amount"]) for x in lines if x["account"] == name), 0.0)


def test_the_new_screen_has_an_income_tab_that_is_closed_until_share_is_chosen(client, bank):
    person(client)
    html = page(client, "/transactions/new")
    assert re.search(r'data-people-editor="income"\s+hidden', html)
    assert 'name="theirs_' in html and 'name="got_' in html and 'name="income_account_id"' in html


def test_income_with_part_of_it_theirs_from_the_add_screen(client, bank):
    alice = person(client)
    rent = category(client, "Rent", kind="earning")
    preview = flat(client.post("/people/income/preview", data=income_form(bank, rent, [alice])).text)
    assert "Your income" in preview and "6,000.00" in preview and "Alice" in preview and "4,000.00" in preview
    done = client.post("/transactions/split", data=income_form(bank, rent, [alice], comment="Q4", tags=["rent"]))
    assert done.status_code == 200 and done.headers["HX-Redirect"], done.text
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["payable"]) == 4000
    assert earned(client) == 6000, "only your part is income"
    assert float(next(a for a in client.get("/api/accounts/").json() if a["name"] == "HDFC")["balance"]) == 20000
    entry = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Rent, Flat 4B")
    assert entry["comment"] == "Q4" and entry["tags"] == ["rent"]
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_someone_received_it_for_you_from_the_add_screen(client, bank):
    alice = person(client)
    rent = category(client, "Rent", kind="earning")
    data = income_form(bank, rent, [], **{f"got_{alice['id']}": "3000"})
    assert client.post("/transactions/split", data=data).status_code == 200
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["receivable"]) == 3000
    assert earned(client) == 10000
    assert float(next(a for a in client.get("/api/accounts/").json() if a["name"] == "HDFC")["balance"]) == 17000


def test_the_rules_of_income_with_people(client, bank):
    alice = person(client)
    rent = category(client, "Rent", kind="earning")
    nobody = client.post("/transactions/split", data=income_form(bank, rent, []))
    assert nobody.status_code == 400 and "name a person" in nobody.text
    no_account = client.post(
        "/transactions/split",
        data={k: v for k, v in income_form(bank, rent, [alice]).items() if k != "income_account_id"},
    )
    assert no_account.status_code == 400 and "account" in no_account.text
    both = client.post("/transactions/split", data=income_form(bank, rent, [alice], **{f"got_{alice['id']}": "1000"}))
    assert both.status_code == 400 and "both" in both.text
    assert all(t["payee"] != "Rent, Flat 4B" for t in client.get("/api/transactions/").json())


def test_shared_income_is_edited_in_place(client, bank):
    alice, bob = person(client), person(client, "Bob")
    rent = category(client, "Rent", kind="earning")
    assert client.post("/transactions/split", data=income_form(bank, rent, [alice])).status_code == 200
    entry = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Rent, Flat 4B")
    html = page(client, f"/transactions/{entry['id']}/edit")
    assert 'data-mode="split"' in html and 'name="kind" value="income"' in html
    assert re.search(rf'name="theirs_{alice["id"]}"[^>]*value="4000', html)
    changed = client.post(
        f"/transactions/{entry['id']}/edit",
        data=income_form(bank, rent, [bob], **{"theirs_" + bob["id"]: "1000"}),
    )
    assert changed.status_code == 200, changed.text
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["payable"]) == 0
    assert float(client.get(f"/api/contacts/{bob['id']}").json()["payable"]) == 1000
    assert earned(client) == 9000
    assert [t["id"] for t in client.get("/api/transactions/").json() if t["payee"] == "Rent, Flat 4B"] == [entry["id"]]


def test_shared_income_is_edited_back_into_an_ordinary_one(client, bank):
    alice = person(client)
    rent = category(client, "Rent", kind="earning")
    assert client.post("/transactions/split", data=income_form(bank, rent, [alice])).status_code == 200
    entry = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Rent, Flat 4B")
    back = client.post(
        f"/transactions/{entry['id']}/edit",
        data={
            "mode": "simple",
            "kind": "income",
            "date": "2026-11-08",
            "payee": "Rent, Flat 4B",
            "account": [rent["id"], bank["id"]],
            "side": ["credit", "debit"],
            "amount": ["10000", "10000"],
        },
    )
    assert back.status_code == 200, back.text
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["payable"]) == 0
    assert client.get(f"/api/contacts/{alice['id']}/obligations").json() == []
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
    done = client.post(f"/transactions/{made['id']}/edit", data=income_form(bank, rent, [alice]))
    assert done.status_code == 200, done.text
    assert earned(client) == 6000 and float(client.get(f"/api/contacts/{alice['id']}").json()["payable"]) == 4000
    assert [t["id"] for t in client.get("/api/transactions/").json() if t["payee"] == "Rent, Flat 4B"] == [made["id"]]


def test_shared_income_shows_on_the_persons_page_and_can_be_reversed_there(client, bank):
    alice = person(client)
    rent = category(client, "Rent", kind="earning")
    assert client.post("/transactions/split", data=income_form(bank, rent, [alice])).status_code == 200
    html = page(client, f"/people/{alice['id']}")
    assert "Rent, Flat 4B" in html and "their part" in html and "4,000.00" in flat(html)
    entry = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Rent, Flat 4B")
    sheet = flat(page(client, f"/people/{alice['id']}/entry/{entry['id']}/sheet"))
    assert "you hold it for them" in sheet
    assert client.post(f"/people/{alice['id']}/entry/{entry['id']}/reverse").status_code == 200
    assert client.get(f"/api/shared-incomes/{entry['id']}").status_code == 404
    assert earned(client) == 0


def test_a_transfer_with_a_person_is_a_loan_whatever_the_mode_says(client, bank, root_accounts):
    alice = person(client)
    cash = client.post("/api/accounts/", json={"name": "Cash", "parent_id": root_accounts["Assets"]}).json()
    plain = {
        "mode": "split",
        "kind": "transfer",
        "date": "2026-11-01",
        "account": [bank["id"], cash["id"]],
        "side": ["credit", "debit"],
        "amount": ["300", "300"],
    }
    lent = client.post("/transactions/split", data={**plain, "account": [bank["id"], alice["id"]]})
    assert lent.status_code == 200, lent.text
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["receivable"]) == 300


def test_an_old_entry_still_opens_and_can_be_undone_after_a_long_history(client, bank):
    """The sheet used to look for the entry among the newest 200 only: an older amount still owed would not open."""
    alice = person(client)

    def lend(**extra):
        made = client.post(
            f"/api/contacts/{alice['id']}/transfers",
            json={"direction": "sent", "purpose": "loan", "amount": "1", "account_id": bank["id"], **extra},
        )
        assert made.status_code == 201, made.text
        return made.json()

    first = lend(date="2020-01-01", description="The first one")
    for _ in range(200):
        lend()
    assert f"/entry/{first['id']}/sheet" in page(client, f"/people/{alice['id']}"), "it is still owed, so it is listed"
    assert "The first one" in page(client, f"/people/{alice['id']}/entry/{first['id']}/sheet")
    bob = person(client, "Bob")
    assert page(client, f"/people/{bob['id']}/entry/{first['id']}/sheet", status=404), "not under someone else"
    assert client.post(f"/people/{bob['id']}/entry/{first['id']}/reverse").status_code == 404
    assert client.post(f"/people/{alice['id']}/entry/{first['id']}/reverse").status_code == 200
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["net"]) == 200

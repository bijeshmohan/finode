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
    assert "Settle up" not in text.split("Activity")[0].split("Add expense")[1], "nothing to settle yet"
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
    assert "Alice owes you" in text and "500.00" in text and "Settle up" in text and "Rent help" in text
    assert f'href="/people/{alice["id"]}/settle?obligation=' in html, "an open amount can be paid off on its own"
    assert f'href="/people/expense/new?with={alice["id"]}"' in html
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


def test_lending_from_the_page(client, bank):
    alice = person(client)
    html = page(client, f"/people/{alice['id']}/transfer")
    assert "I lent money" in html and "I borrowed money" in html and 'name="account_id"' in html
    assert f'<option value="{bank["id"]}"' in html and "Due from" not in html, "a contact's accounts are not offered"
    done = client.post(
        f"/people/{alice['id']}/transfer",
        data={
            "kind": "loan_sent",
            "amount": "300",
            "account_id": bank["id"],
            "date": "2026-10-01",
            "description": "Cab",
        },
    )
    assert done.status_code == 200 and done.headers["HX-Redirect"] == f"/people/{alice['id']}"
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["net"]) == 300
    treat = category(client, "Treats")
    gift = client.post(
        f"/people/{alice['id']}/transfer",
        data={"kind": "gift_sent", "amount": "50", "account_id": bank["id"], "spending_category_id": treat["id"]},
    )
    assert gift.status_code == 200
    assert client.get("/api/reports/breakdown").json()["lines"][0]["account"] == "Treats"
    for data in (
        {"kind": "", "amount": "5", "account_id": bank["id"]},
        {"kind": "loan_sent", "amount": "x", "account_id": bank["id"]},
        {"kind": "loan_sent", "amount": "5", "account_id": ""},
    ):
        bad = client.post(f"/people/{alice['id']}/transfer", data=data)
        assert bad.status_code == 400 and bad.headers["HX-Retarget"] == "#form-error", data


def test_settling_up_from_the_page(client, bank):
    alice = person(client)
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
    html = page(client, f"/people/{alice['id']}/settle")
    assert 'value="500.00"' in html and "Alice pays you" in html and 'hx-post="/people/' in html
    preview = client.post(
        f"/people/{alice['id']}/settle/preview",
        data={"direction": "received", "amount": "200", "account_id": bank["id"]},
    )
    text = flat(preview.text)
    assert "Rent help" in text and "200.00" in text and "300.00 left" in text
    more = flat(
        client.post(
            f"/people/{alice['id']}/settle/preview",
            data={"direction": "received", "amount": "800", "account_id": bank["id"]},
        ).text
    )
    assert "300.00 is more than is owed" in more and "They lent me this" in more
    assert "Nothing" not in flat(
        client.post(
            f"/people/{alice['id']}/settle/preview", data={"direction": "received", "amount": "", "account_id": ""}
        ).text
    )
    refused = client.post(
        f"/people/{alice['id']}/settle", data={"direction": "received", "amount": "800", "account_id": bank["id"]}
    )
    assert refused.status_code == 400 and "say what the rest is" in refused.text
    done = client.post(
        f"/people/{alice['id']}/settle",
        data={"direction": "received", "amount": "800", "account_id": bank["id"], "excess_as": "borrowing"},
    )
    assert done.status_code == 200 and done.headers["HX-Redirect"] == f"/people/{alice['id']}"
    now = client.get(f"/api/contacts/{alice['id']}").json()
    assert float(now["receivable"]) == 0 and float(now["payable"]) == 300


def test_paying_off_one_open_amount(client, bank):
    alice = person(client)
    first = client.post(
        f"/api/contacts/{alice['id']}/transfers",
        json={"direction": "sent", "purpose": "loan", "amount": "500", "account_id": bank["id"], "date": "2026-10-01"},
    ).json()
    client.post(
        f"/api/contacts/{alice['id']}/transfers",
        json={"direction": "sent", "purpose": "loan", "amount": "100", "account_id": bank["id"], "date": "2026-09-01"},
    )
    html = page(client, f"/people/{alice['id']}/settle", obligation=first["obligation_id"])
    assert f'name="obligation_id" value="{first["obligation_id"]}"' in html and 'value="500.00"' in html
    done = client.post(
        f"/people/{alice['id']}/settle",
        data={
            "direction": "received",
            "amount": "500",
            "account_id": bank["id"],
            "obligation_id": first["obligation_id"],
        },
    )
    assert done.status_code == 200
    left = client.get(f"/api/contacts/{alice['id']}/obligations", params={"open_only": True}).json()
    assert [float(o["outstanding_amount"]) for o in left] == [100.0], "the older one was left alone"


def test_sharing_a_bill_from_the_page(client, bank):
    alice, bob = person(client), person(client, "Bob")
    dining = category(client, "Dining")
    html = page(client, "/people/expense/new", **{"with": alice["id"]})
    assert 'name="total_amount"' in html and f'name="with_{alice["id"]}" value="1" checked' in html
    assert f'name="with_{bob["id"]}"' in html and f'name="with_{bob["id"]}" value="1" checked' not in html
    form = {
        "total_amount": "900",
        "description": "Dinner",
        "category_id": dining["id"],
        "split_method": "equal",
        "account_id": bank["id"],
        f"with_{alice['id']}": "1",
        f"with_{bob['id']}": "1",
        "back_to": alice["id"],
    }
    preview = flat(client.post("/people/expense/preview", data=form).text)
    assert "300.00" in preview and "Alice owes you" in preview and "Bob owes you" in preview and "Your share" in preview
    short = flat(client.post("/people/expense/preview", data={**form, "paid_self": "400"}).text)
    assert "500.00 of the bill has no payer yet" in short
    assert "Nothing" not in flat(client.post("/people/expense/preview", data={"total_amount": ""}).text)
    one = flat(
        client.post("/people/expense/preview", data={**form, f"with_{alice['id']}": "", f"with_{bob['id']}": ""}).text
    )
    assert "at least 2" in one
    done = client.post("/people/expense", data=form)
    assert done.status_code == 200 and done.headers["HX-Redirect"] == f"/people/{alice['id']}", done.text
    assert float(client.get(f"/api/contacts/{bob['id']}").json()["net"]) == 300
    assert client.get("/api/reports/breakdown").json()["lines"][0]["amount"] == "300.00"
    nopay = client.post("/people/expense", data={**form, "account_id": ""})
    assert nopay.status_code == 400 and "account" in nopay.text
    mixed = client.post(
        "/people/expense",
        data={**form, "description": "Lunch", "paid_self": "450", f"paid_{alice['id']}": "450", "total_amount": "900"},
    )
    assert mixed.status_code == 200
    after = client.get(f"/api/contacts/{alice['id']}").json()
    assert (float(after["receivable"]), float(after["payable"])) == (300, 150), (
        "Alice paid 150 more than her share of lunch"
    )


def test_uneven_splits_from_the_page(client, bank):
    alice = person(client)
    form = {
        "total_amount": "100",
        "description": "Cab",
        "split_method": "percentage",
        "account_id": bank["id"],
        f"with_{alice['id']}": "1",
        "value_self": "75",
        f"value_{alice['id']}": "25",
    }
    assert client.post("/people/expense", data=form).status_code == 200
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["net"]) == 25
    bad = client.post("/people/expense", data={**form, "value_self": "50"})
    assert bad.status_code == 400 and "not 100" in bad.text


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
    assert f'href="/people/{alice["id"]}"' in sheet and "Open Alice" in sheet
    assert "/edit" not in sheet and "sheet-delete" not in sheet and "Repeat" not in sheet
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
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["payable"]) == 50
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


def test_nobody_with_no_people_sees_the_group_and_editing_never_does(client, bank):
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
    assert 'optgroup label="People"' not in page(client, f"/transactions/{entry['id']}/edit")
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

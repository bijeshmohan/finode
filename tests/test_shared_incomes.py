"""Income shared with contacts: your part, what you hold for others, who received it for you."""

import pytest

from .books import category

MISSING = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def bank(client, root_accounts):
    return client.post(
        "/api/accounts/", json={"name": "HDFC", "parent_id": root_accounts["Assets"], "balance": "0"}
    ).json()


@pytest.fixture
def rent(client):
    return category(client, "Rent", kind="earning")


@pytest.fixture
def people(client):
    return {name: client.post("/api/contacts/", json={"name": name}).json() for name in ("Alice", "Bob")}


def balance(client, account_id):
    return float(client.get(f"/api/accounts/{account_id}").json()["balance"])


def collected(bank, rent, people, **extra):
    body = {
        "description": "Rent, Flat 4B",
        "total_amount": "10000",
        "category_id": rent["id"],
        "theirs": [{"contact_id": people["Alice"]["id"], "amount": "4000"}],
        "deposits": [{"account_id": bank["id"], "amount": "10000"}],
    }
    body.update(extra)
    return body


def earned(client, name="Rent"):
    lines = client.get("/api/reports/breakdown", params={"kind": "income"}).json()["lines"]
    return next((float(l["amount"]) for l in lines if l["account"] == name), 0.0)


def test_part_of_it_is_theirs(client, bank, rent, people):
    made = client.post("/api/shared-incomes/", json=collected(bank, rent, people))
    assert made.status_code == 201, made.text
    body = made.json()
    assert float(body["your_income"]) == 6000
    assert balance(client, bank["id"]) == 10000
    assert balance(client, people["Alice"]["payable_account_id"]) == 4000
    assert earned(client) == 6000, "only your part is income"
    assert client.get("/api/reports/trial-balance").json()["balanced"]
    owed = client.get(f"/api/contacts/{people['Alice']['id']}/obligations").json()
    assert [(o["source_type"], o["direction"], float(o["outstanding_amount"])) for o in owed] == [
        ("shared_income", "payable", 4000)
    ]
    again = client.get(f"/api/shared-incomes/{body['transaction_id']}").json()
    assert again == body


def test_someone_received_it_for_you(client, bank, rent, people):
    body = collected(
        bank,
        rent,
        people,
        theirs=[],
        received_by=[{"contact_id": people["Alice"]["id"], "amount": "3000"}],
        deposits=[{"account_id": bank["id"], "amount": "7000"}],
    )
    made = client.post("/api/shared-incomes/", json=body)
    assert made.status_code == 201, made.text
    assert float(made.json()["your_income"]) == 10000
    assert balance(client, people["Alice"]["receivable_account_id"]) == 3000
    assert earned(client) == 10000
    owed = client.get(f"/api/contacts/{people['Alice']['id']}/obligations").json()
    assert [(o["direction"], float(o["outstanding_amount"])) for o in owed] == [("receivable", 3000)]
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_both_at_once(client, bank, rent, people):
    body = collected(
        bank,
        rent,
        people,
        received_by=[{"contact_id": people["Bob"]["id"], "amount": "2000"}],
        deposits=[{"account_id": bank["id"], "amount": "8000"}],
    )
    assert client.post("/api/shared-incomes/", json=body).status_code == 201
    assert balance(client, people["Alice"]["payable_account_id"]) == 4000
    assert balance(client, people["Bob"]["receivable_account_id"]) == 2000


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"theirs": []}, "name a person"),
        ({"theirs": [{"contact_id": MISSING, "amount": "1"}]}, "contact not found"),
        ({"deposits": [{"account_id": "x", "amount": "1"}]}, ""),
    ],
)
def test_refusals_that_need_no_money(client, bank, rent, people, change, words):
    response = client.post("/api/shared-incomes/", json=collected(bank, rent, people, **change))
    assert response.status_code in (400, 404, 422)
    assert words in response.text


def test_the_deposits_must_add_up(client, bank, rent, people):
    short = collected(bank, rent, people, deposits=[{"account_id": bank["id"], "amount": "9000"}])
    response = client.post("/api/shared-incomes/", json=short)
    assert response.status_code == 400 and "not the total" in response.text


def test_their_parts_cannot_exceed_the_total(client, bank, rent, people):
    body = collected(bank, rent, people, theirs=[{"contact_id": people["Alice"]["id"], "amount": "11000"}])
    response = client.post("/api/shared-incomes/", json=body)
    assert response.status_code == 400 and "more than the total" in response.text


def test_a_person_is_on_one_side_only(client, bank, rent, people):
    body = collected(
        bank,
        rent,
        people,
        received_by=[{"contact_id": people["Alice"]["id"], "amount": "1000"}],
        deposits=[{"account_id": bank["id"], "amount": "9000"}],
    )
    response = client.post("/api/shared-incomes/", json=body)
    assert response.status_code == 400 and "both" in response.text


def test_the_category_must_be_an_income_one(client, bank, people):
    spending = category(client, "Dining")
    response = client.post("/api/shared-incomes/", json=collected(bank, spending, people))
    assert response.status_code == 400 and "income categories" in response.text


def test_nothing_is_saved_by_a_preview(client, bank, rent, people):
    before = balance(client, bank["id"])
    shown = client.post("/api/shared-incomes/preview", json=collected(bank, rent, people))
    assert shown.status_code == 200 and float(shown.json()["your_income"]) == 6000
    assert balance(client, bank["id"]) == before


def test_the_same_key_gives_the_same_entry(client, bank, rent, people):
    body = collected(bank, rent, people)
    first = client.post("/api/shared-incomes/", json=body, headers={"Idempotency-Key": "k1"}).json()
    second = client.post("/api/shared-incomes/", json=body, headers={"Idempotency-Key": "k1"})
    assert second.status_code == 201 and second.json()["transaction_id"] == first["transaction_id"]
    assert balance(client, bank["id"]) == 10000
    other = client.post("/api/shared-incomes/", json={**body, "total_amount": "5"}, headers={"Idempotency-Key": "k1"})
    assert other.status_code == 409


def test_it_can_be_recorded_again_in_place(client, bank, rent, people):
    made = client.post("/api/shared-incomes/", json=collected(bank, rent, people)).json()
    body = collected(bank, rent, people, theirs=[{"contact_id": people["Bob"]["id"], "amount": "1000"}])
    changed = client.put(f"/api/shared-incomes/{made['transaction_id']}", json=body)
    assert changed.status_code == 200, changed.text
    assert changed.json()["transaction_id"] == made["transaction_id"]
    assert balance(client, people["Alice"]["payable_account_id"]) == 0
    assert balance(client, people["Bob"]["payable_account_id"]) == 1000
    assert earned(client) == 9000
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_an_ordinary_income_entry_becomes_shared(client, bank, rent, people):
    plain = client.post(
        "/api/transactions/",
        json={
            "date": "2026-11-01",
            "payee": "Tenant",
            "postings": [
                {"account_id": bank["id"], "side": "debit", "amount": "10000"},
                {
                    "account_id": next(a["id"] for a in client.get("/api/accounts/").json() if a["name"] == "Income"),
                    "side": "credit",
                    "amount": "10000",
                    "category_id": rent["id"],
                },
            ],
        },
    ).json()
    changed = client.put(f"/api/shared-incomes/{plain['id']}", json=collected(bank, rent, people))
    assert changed.status_code == 200, changed.text
    assert changed.json()["transaction_id"] == plain["id"]
    assert earned(client) == 6000


def test_paying_back_locks_it_and_cancel_goes_for_good(client, bank, rent, people):
    made = client.post("/api/shared-incomes/", json=collected(bank, rent, people)).json()
    tid = made["transaction_id"]
    paid = client.post(
        f"/api/contacts/{people['Alice']['id']}/settlements",
        json={"direction": "sent", "amount": "1000", "account_id": bank["id"]},
    )
    assert paid.status_code == 201, paid.text
    assert client.put(f"/api/shared-incomes/{tid}", json=collected(bank, rent, people)).status_code == 409
    assert client.post(f"/api/shared-incomes/{tid}/cancel").status_code == 409
    assert client.delete(f"/api/settlements/{paid.json()['id']}").status_code == 204
    assert client.post(f"/api/shared-incomes/{tid}/cancel").status_code == 204


def test_cancel_removes_the_entry_and_what_it_left_owed(client, bank, rent, people):
    made = client.post("/api/shared-incomes/", json=collected(bank, rent, people)).json()
    assert client.post(f"/api/shared-incomes/{made['transaction_id']}/cancel").status_code == 204
    assert balance(client, bank["id"]) == 0
    assert client.get(f"/api/contacts/{people['Alice']['id']}/obligations").json() == []
    assert client.get(f"/api/shared-incomes/{made['transaction_id']}").status_code == 404


def test_an_ordinary_entry_is_not_shared_income(client, bank, root_accounts):
    cash = client.post("/api/accounts/", json={"name": "Cash", "parent_id": root_accounts["Assets"]}).json()
    plain = client.post(
        "/api/transactions/",
        json={
            "date": "2026-11-01",
            "postings": [
                {"account_id": cash["id"], "side": "debit", "amount": "5"},
                {"account_id": bank["id"], "side": "credit", "amount": "5"},
            ],
        },
    )
    assert plain.status_code == 201, plain.text
    tid = plain.json()["id"]
    assert client.get(f"/api/shared-incomes/{tid}").status_code == 404
    assert client.post(f"/api/shared-incomes/{tid}/cancel").status_code == 404


def test_the_ordinary_routes_leave_it_alone(client, bank, rent, people):
    made = client.post("/api/shared-incomes/", json=collected(bank, rent, people)).json()
    tid = made["transaction_id"]
    assert client.patch(f"/api/transactions/{tid}", json={"payee": "x"}).status_code in (400, 409)
    assert client.delete(f"/api/transactions/{tid}").status_code in (400, 409)

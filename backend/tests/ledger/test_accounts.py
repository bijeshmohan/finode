from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from tests.books import leg, post_account
from tests.svc import plain, services


def test_create_account(client: TestClient, root_accounts: dict[str, str]):
    response = post_account(
        client,
        {
            "name": "checking",
            "details": "main account",
            "parent_id": root_accounts["Assets"],
            "balance": "100.50",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "checking"
    assert data["details"] == "main account"
    assert data["type"] == "assets.bank"
    assert data["balance"] == "100.50"
    assert "id" in data


def test_create_account_default_balance(client: TestClient, root_accounts: dict[str, str]):
    response = post_account(
        client,
        {
            "name": "wallet",
            "details": None,
            "parent_id": root_accounts["Assets"],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["balance"] == "0.00"


def test_create_account_opening_balance_creates_transaction(client: TestClient, root_accounts: dict[str, str]):
    response = post_account(
        client,
        {
            "name": "wallet",
            "parent_id": root_accounts["Assets"],
            "balance": "75.00",
        },
    )
    assert response.status_code == 201
    account = response.json()

    entries = client.get("/api/transactions/").json()
    assert len(entries) == 1
    assert entries[0]["payee"] == "Opening balance"
    assert entries[0]["comment"] == "Initial account balance"
    postings = entries[0]["postings"]
    assert any(
        posting["account_id"] == account["id"] and posting["side"] == "debit" and posting["amount"] == "75.00"
        for posting in postings
    )


def test_get_account(client: TestClient, account: dict):
    response = client.get(f"/api/accounts/{account['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == account["id"]


def test_get_account_not_found(client: TestClient):
    response = client.get(f"/api/accounts/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "account not found"


def test_list_accounts(client: TestClient, account: dict, other_account: dict):
    response = client.get("/api/accounts/")
    assert response.status_code == 200
    data = response.json()
    # 5 root accounts + 2 created by fixtures
    assert len(data) == 7
    aids = {item["id"] for item in data}
    assert account["id"] in aids
    assert other_account["id"] in aids


def test_filter_accounts_by_type(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    response = client.get("/api/accounts/?type=Expenses")
    assert response.status_code == 200
    data = response.json()
    # Expenses holds categories, not accounts: only the root is an account
    assert [item["name"] for item in data] == ["Expenses"]


def test_filter_accounts_by_invalid_type(client: TestClient):
    response = client.get("/api/accounts/?type=Bogus")
    assert response.status_code == 422


def test_list_accounts_empty(client: TestClient):
    # Empty books list the 5 system root accounts
    response = client.get("/api/accounts/")
    assert response.status_code == 200
    data = response.json()
    names = {item["name"] for item in data}
    assert names == {"Assets", "Expenses", "Equity", "Income", "Liabilities"}


def test_update_account_metadata(client: TestClient, account: dict):
    response = client.patch(
        f"/api/accounts/{account['id']}",
        json={"name": "renamed", "details": None},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "renamed"
    assert data["balance"] == "0.00"


def test_update_account_balance_creates_transaction(
    client: TestClient,
    account: dict,
):
    response = client.patch(
        f"/api/accounts/{account['id']}",
        json={"balance": "175.00"},
    )
    assert response.status_code == 200
    assert response.json()["balance"] == "175.00"

    entries = client.get("/api/transactions/").json()
    assert len(entries) == 1
    assert entries[0]["payee"] == "Balance adjustment"
    assert entries[0]["comment"] == "Result of direct account balance update"
    assert any(
        posting["account_id"] == account["id"] and posting["side"] == "debit" and posting["amount"] == "175.00"
        for posting in entries[0]["postings"]
    )


def test_update_account_not_found(client: TestClient):
    response = client.patch(
        f"/api/accounts/{uuid4()}",
        json={"name": "ghost", "details": None, "balance": "0.00"},
    )
    assert response.status_code == 404


def test_delete_account(client: TestClient, account: dict):
    response = client.delete(f"/api/accounts/{account['id']}")
    assert response.status_code == 204

    follow = client.get(f"/api/accounts/{account['id']}")
    assert follow.status_code == 404


def test_delete_account_with_postings_conflicts(client: TestClient, root_accounts: dict[str, str]):
    create = post_account(client, {"name": "wallet", "parent_id": root_accounts["Assets"], "balance": "10.00"})
    account = create.json()

    response = client.delete(f"/api/accounts/{account['id']}")
    assert response.status_code == 409
    assert response.json()["detail"] == "account has postings"


def test_delete_account_not_found(client: TestClient):
    response = client.delete(f"/api/accounts/{uuid4()}")
    assert response.status_code == 404


def test_system_root_modifications_fail(client: TestClient, root_accounts: dict[str, str]):
    root_id = root_accounts["Assets"]

    # Try to rename root
    r2 = client.patch(f"/api/accounts/{root_id}", json={"name": "New Assets"})
    assert r2.status_code == 400
    assert r2.json()["detail"] == "cannot change name of a system root account!"

    # Try to delete root
    r3 = client.delete(f"/api/accounts/{root_id}")
    assert r3.status_code == 400
    assert r3.json()["detail"] == "cannot delete system root accounts!"


def test_root_accounts_are_provisioned_once(client: TestClient):
    first = client.get("/api/accounts/").json()
    second = client.get("/api/accounts/").json()
    assert len(first) == len(second) == 5
    assert {a["id"] for a in first} == {a["id"] for a in second}


def test_set_balance_of_root_account_fails(client: TestClient, root_accounts: dict[str, str]):
    response = client.patch(f"/api/accounts/{root_accounts['Assets']}", json={"balance": "10.00"})
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot set balance of a root account!"


def _opening_balances(client: TestClient) -> dict:
    return next(a for a in client.get("/api/accounts/").json() if a["name"] == "Opening Balances")


def test_opening_balances_account_is_created_under_equity(client: TestClient, root_accounts: dict[str, str]):
    post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"})
    assert _opening_balances(client)["parent_id"] == root_accounts["Equity"]


def test_set_balance_of_opening_balances_account_fails(client: TestClient, root_accounts: dict[str, str]):
    post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"})
    opening = _opening_balances(client)

    response = client.patch(f"/api/accounts/{opening['id']}", json={"balance": "5000.00"})
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot set balance of system account 'Opening Balances'!"
    assert client.get(f"/api/accounts/{opening['id']}").json()["balance"] == opening["balance"]


def test_opening_balances_account_cannot_be_renamed_moved_or_deleted(client: TestClient, root_accounts: dict[str, str]):
    post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"})
    opening = _opening_balances(client)
    url = f"/api/accounts/{opening['id']}"

    renamed = client.patch(url, json={"name": "Foo"})
    assert renamed.status_code == 400
    assert renamed.json()["detail"] == "cannot change name of system account 'Opening Balances'!"

    deleted = client.delete(url)
    assert deleted.status_code == 400
    assert deleted.json()["detail"] == "cannot delete system account 'Opening Balances'!"


def test_opening_balances_account_allows_metadata_update(client: TestClient, root_accounts: dict[str, str]):
    post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"})
    opening = _opening_balances(client)

    response = client.patch(f"/api/accounts/{opening['id']}", json={"details": "notes"})
    assert response.status_code == 200
    assert response.json()["details"] == "notes"


def _transfer(client: TestClient, debit: dict, credit: dict, amount: str, date: str, payee: str):
    response = client.post(
        "/api/transactions/",
        json={
            "date": date,
            "payee": payee,
            "postings": [
                leg(debit, "debit", amount),
                leg(credit, "credit", amount),
            ],
        },
    )
    assert response.status_code == 201


def test_account_register_has_running_balance(
    client: TestClient, root_accounts: dict[str, str], expense_account: dict, session
):
    bank = post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"}).json()
    today = date.today().isoformat()
    _transfer(client, expense_account, bank, "30.00", today, "shop")
    _transfer(client, expense_account, bank, "10.00", today, "cafe")

    entries = plain(services(session).accounts.register(UUID(bank["id"])))
    assert [e["change"] for e in entries] == ["100.00", "-30.00", "-10.00"]
    assert [e["balance"] for e in entries] == ["100.00", "70.00", "60.00"]
    assert entries[1]["counter_accounts"] == ["groceries"]
    assert entries[-1]["balance"] == client.get(f"/api/accounts/{bank['id']}").json()["balance"]


def test_account_register_not_found(session):
    assert services(session).accounts.register(uuid4()) is None


# Ported from test_web_accounts.py (the old pages' form), step 10.


def test_an_opening_balance_that_is_not_a_number_is_refused_and_nothing_is_made(client, root_accounts):
    made = post_account(client, {"name": "x", "parent_id": root_accounts["Assets"], "balance": "abc"})
    assert made.status_code == 422
    assert all(a["name"] != "x" for a in client.get("/api/accounts/").json())


def test_saving_an_account_unchanged_records_nothing(client, root_accounts, account):
    again = client.patch(
        f"/api/accounts/{account['id']}",
        json={"name": account["name"], "parent_id": root_accounts["Assets"], "balance": "0.00"},
    )
    assert again.status_code == 200, again.text
    assert client.get("/api/transactions/").json() == []


def test_every_new_account_is_in_the_budget_whatever_was_asked(client: TestClient):
    asked = post_account(client, {"name": "Old SBI", "type": "assets.bank", "on_budget": False}).json()
    assert asked["type"] == "assets.bank"
    assert "on_budget" not in asked, "there is no flag left to read"

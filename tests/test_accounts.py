from uuid import uuid4

from fastapi.testclient import TestClient


def test_create_account(client: TestClient):
    response = client.post(
        "/accounts/",
        json={
            "name": "checking",
            "details": "main account",
            "type": "asset",
            "balance": "100.50",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "checking"
    assert data["details"] == "main account"
    assert data["type"] == "asset"
    assert data["balance"] == "100.50"
    assert "aid" in data


def test_create_account_default_balance(client: TestClient):
    response = client.post(
        "/accounts/",
        json={"name": "wallet", "details": None, "type": "asset"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["balance"] == "0.00"


def test_create_account_opening_balance_creates_transaction(client: TestClient):
    response = client.post(
        "/accounts/",
        json={"name": "wallet", "type": "asset", "balance": "75.00"},
    )
    assert response.status_code == 201
    account = response.json()

    entries = client.get("/transactions/").json()
    assert len(entries) == 1
    assert entries[0]["payee"] == "Opening balance"
    assert entries[0]["comment"] == "Initial account balance"
    postings = entries[0]["postings"]
    assert any(
        posting["account"] == account["aid"]
        and posting["side"] == "debit"
        and posting["amount"] == "75.00"
        for posting in postings
    )


def test_get_account(client: TestClient, account: dict):
    response = client.get(f"/accounts/{account['aid']}")
    assert response.status_code == 200
    assert response.json()["aid"] == account["aid"]


def test_get_account_not_found(client: TestClient):
    response = client.get(f"/accounts/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "account not found"


def test_list_accounts(client: TestClient, account: dict, other_account: dict):
    response = client.get("/accounts/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    aids = {item["aid"] for item in data}
    assert account["aid"] in aids
    assert other_account["aid"] in aids


def test_filter_accounts_by_type(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    response = client.get("/accounts/?type=expense")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["aid"] == expense_account["aid"]


def test_list_accounts_empty(client: TestClient):
    response = client.get("/accounts/")
    assert response.status_code == 200
    assert response.json() == []


def test_update_account_metadata(client: TestClient, account: dict):
    response = client.patch(
        f"/accounts/{account['aid']}",
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
        f"/accounts/{account['aid']}",
        json={"balance": "175.00"},
    )
    assert response.status_code == 200
    assert response.json()["balance"] == "175.00"

    entries = client.get("/transactions/").json()
    assert len(entries) == 1
    assert entries[0]["payee"] == "Balance adjustment"
    assert entries[0]["comment"] == "Result of direct account balance update"
    assert any(
        posting["account"] == account["aid"]
        and posting["side"] == "debit"
        and posting["amount"] == "175.00"
        for posting in entries[0]["postings"]
    )


def test_update_account_not_found(client: TestClient):
    response = client.patch(
        f"/accounts/{uuid4()}",
        json={"name": "ghost", "details": None, "balance": "0.00"},
    )
    assert response.status_code == 404


def test_delete_account(client: TestClient, account: dict):
    response = client.delete(f"/accounts/{account['aid']}")
    assert response.status_code == 204

    follow = client.get(f"/accounts/{account['aid']}")
    assert follow.status_code == 404


def test_delete_account_with_postings_conflicts(client: TestClient):
    create = client.post(
        "/accounts/",
        json={"name": "wallet", "type": "asset", "balance": "10.00"},
    )
    account = create.json()

    response = client.delete(f"/accounts/{account['aid']}")
    assert response.status_code == 409
    assert response.json()["detail"] == "account has postings"


def test_delete_account_not_found(client: TestClient):
    response = client.delete(f"/accounts/{uuid4()}")
    assert response.status_code == 404


def test_update_account_type_does_not_create_transaction(client: TestClient):
    create_resp = client.post(
        "/accounts/",
        json={"name": "test_acc", "type": "asset", "balance": "100.00"},
    )
    assert create_resp.status_code == 201
    account = create_resp.json()

    tx_resp = client.get("/transactions/")
    assert tx_resp.status_code == 200
    assert len(tx_resp.json()) == 1

    update_resp = client.patch(
        f"/accounts/{account['aid']}",
        json={"type": "liability"},
    )
    assert update_resp.status_code == 200
    updated_account = update_resp.json()
    assert updated_account["type"] == "liability"
    assert updated_account["balance"] == "-100.00"

    tx_resp_after = client.get("/transactions/")
    assert tx_resp_after.status_code == 200
    assert len(tx_resp_after.json()) == 1


from uuid import uuid4

from fastapi.testclient import TestClient


def test_create_account(client: TestClient):
    response = client.post(
        "/accounts/",
        json={"name": "checking", "details": "main account", "balance": "100.50"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "checking"
    assert data["details"] == "main account"
    assert data["balance"] == "100.50"
    assert "aid" in data


def test_create_account_default_balance(client: TestClient):
    response = client.post(
        "/accounts/",
        json={"name": "wallet", "details": None},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["balance"] == "0.00"


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


def test_list_accounts_empty(client: TestClient):
    response = client.get("/accounts/")
    assert response.status_code == 200
    assert response.json() == []


def test_update_account(client: TestClient, account: dict):
    response = client.patch(
        f"/accounts/{account['aid']}",
        json={"name": "renamed", "details": None, "balance": "200.00"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "renamed"
    assert data["balance"] == "200.00"


def test_update_account_balance_increase_creates_transaction(
    client: TestClient,
    account: dict,
):
    response = client.patch(
        f"/accounts/{account['aid']}",
        json={"balance": "175.00"},
    )
    assert response.status_code == 200

    transactions = client.get("/transactions/").json()
    assert len(transactions) == 1
    assert transactions[0]["amount"] == "75.00"
    assert transactions[0]["destination"] == account["aid"]
    assert transactions[0]["source"] is None


def test_update_account_balance_decrease_creates_transaction(
    client: TestClient,
    account: dict,
):
    response = client.patch(
        f"/accounts/{account['aid']}",
        json={"balance": "40.00"},
    )
    assert response.status_code == 200

    transactions = client.get("/transactions/").json()
    assert len(transactions) == 1
    assert transactions[0]["amount"] == "60.00"
    assert transactions[0]["source"] == account["aid"]
    assert transactions[0]["destination"] is None


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


def test_delete_account_not_found(client: TestClient):
    response = client.delete(f"/accounts/{uuid4()}")
    assert response.status_code == 404

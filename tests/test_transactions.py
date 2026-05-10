from uuid import uuid4

from fastapi.testclient import TestClient


def test_create_expense(
    client: TestClient,
    account: dict,
    expense_category: dict,
):
    response = client.post(
        "/transactions/",
        json={
            "amount": "25.00",
            "category": expense_category["cid"],
            "source": account["aid"],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["amount"] == "25.00"
    assert data["source"] == account["aid"]
    assert "tid" in data


def test_create_income(
    client: TestClient,
    account: dict,
    income_category: dict,
):
    response = client.post(
        "/transactions/",
        json={
            "amount": "1000.00",
            "category": income_category["cid"],
            "destination": account["aid"],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["destination"] == account["aid"]


def test_create_transfer(
    client: TestClient,
    account: dict,
    other_account: dict,
    transfer_category: dict,
):
    response = client.post(
        "/transactions/",
        json={
            "amount": "50.00",
            "category": transfer_category["cid"],
            "source": account["aid"],
            "destination": other_account["aid"],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["source"] == account["aid"]
    assert data["destination"] == other_account["aid"]


def test_create_transaction_zero_amount(
    client: TestClient,
    account: dict,
    expense_category: dict,
):
    response = client.post(
        "/transactions/",
        json={
            "amount": "0.00",
            "category": expense_category["cid"],
            "source": account["aid"],
        },
    )
    assert response.status_code == 422


def test_get_transaction(
    client: TestClient,
    account: dict,
    expense_category: dict,
):
    create = client.post(
        "/transactions/",
        json={
            "amount": "10.00",
            "category": expense_category["cid"],
            "source": account["aid"],
        },
    )
    tid = create.json()["tid"]

    response = client.get(f"/transactions/{tid}")
    assert response.status_code == 200
    assert response.json()["tid"] == tid


def test_get_transaction_not_found(client: TestClient):
    response = client.get(f"/transactions/{uuid4()}")
    assert response.status_code == 404


def test_list_transactions(
    client: TestClient,
    account: dict,
    other_account: dict,
    expense_category: dict,
    income_category: dict,
    transfer_category: dict,
):
    client.post("/transactions/", json={
        "amount": "10.00", "category": expense_category["cid"],
        "source": account["aid"],
    })
    client.post("/transactions/", json={
        "amount": "20.00", "category": income_category["cid"],
        "destination": account["aid"],
    })
    client.post("/transactions/", json={
        "amount": "30.00", "category": transfer_category["cid"],
        "source": account["aid"], "destination": other_account["aid"],
    })

    response = client.get("/transactions/")
    assert response.status_code == 200
    assert len(response.json()) == 3


def test_filter_expense(
    client: TestClient,
    account: dict,
    other_account: dict,
    expense_category: dict,
    income_category: dict,
    transfer_category: dict,
):
    client.post("/transactions/", json={
        "amount": "10.00", "category": expense_category["cid"],
        "source": account["aid"],
    })
    client.post("/transactions/", json={
        "amount": "20.00", "category": income_category["cid"],
        "destination": account["aid"],
    })
    client.post("/transactions/", json={
        "amount": "30.00", "category": transfer_category["cid"],
        "source": account["aid"], "destination": other_account["aid"],
    })

    response = client.get("/transactions/?type=expense")
    data = response.json()
    assert len(data) == 1
    assert data[0]["amount"] == "10.00"


def test_filter_income(
    client: TestClient,
    account: dict,
    other_account: dict,
    expense_category: dict,
    income_category: dict,
    transfer_category: dict,
):
    client.post("/transactions/", json={
        "amount": "10.00", "category": expense_category["cid"],
        "source": account["aid"],
    })
    client.post("/transactions/", json={
        "amount": "20.00", "category": income_category["cid"],
        "destination": account["aid"],
    })
    client.post("/transactions/", json={
        "amount": "30.00", "category": transfer_category["cid"],
        "source": account["aid"], "destination": other_account["aid"],
    })

    response = client.get("/transactions/?type=income")
    data = response.json()
    assert len(data) == 1
    assert data[0]["amount"] == "20.00"


def test_filter_transfer(
    client: TestClient,
    account: dict,
    other_account: dict,
    expense_category: dict,
    income_category: dict,
    transfer_category: dict,
):
    client.post("/transactions/", json={
        "amount": "10.00", "category": expense_category["cid"],
        "source": account["aid"],
    })
    client.post("/transactions/", json={
        "amount": "20.00", "category": income_category["cid"],
        "destination": account["aid"],
    })
    client.post("/transactions/", json={
        "amount": "30.00", "category": transfer_category["cid"],
        "source": account["aid"], "destination": other_account["aid"],
    })

    response = client.get("/transactions/?type=transfer")
    data = response.json()
    assert len(data) == 1
    assert data[0]["amount"] == "30.00"


def test_update_transaction(
    client: TestClient,
    account: dict,
    expense_category: dict,
):
    create = client.post(
        "/transactions/",
        json={
            "amount": "10.00",
            "category": expense_category["cid"],
            "source": account["aid"],
        },
    )
    tid = create.json()["tid"]

    response = client.patch(
        f"/transactions/{tid}",
        json={
            "amount": "15.00",
            "category": expense_category["cid"],
            "source": account["aid"],
        },
    )
    assert response.status_code == 200
    assert response.json()["amount"] == "15.00"


def test_delete_transaction(
    client: TestClient,
    account: dict,
    expense_category: dict,
):
    create = client.post(
        "/transactions/",
        json={
            "amount": "10.00",
            "category": expense_category["cid"],
            "source": account["aid"],
        },
    )
    tid = create.json()["tid"]

    response = client.delete(f"/transactions/{tid}")
    assert response.status_code == 204

    follow = client.get(f"/transactions/{tid}")
    assert follow.status_code == 404

from uuid import uuid4

from fastapi.testclient import TestClient


def test_create_transaction(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    response = client.post(
        "/transactions/",
        json={
            "postings": [
                {
                    "account": expense_account["aid"],
                    "side": "debit",
                    "amount": "25.00",
                },
                {
                    "account": account["aid"],
                    "side": "credit",
                    "amount": "25.00",
                },
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert len(data["postings"]) == 2
    assert "tid" in data

    account_response = client.get(f"/accounts/{account['aid']}")
    assert account_response.json()["balance"] == "-25.00"
    expense_response = client.get(f"/accounts/{expense_account['aid']}")
    assert expense_response.json()["balance"] == "25.00"


def test_create_transaction_must_balance(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    response = client.post(
        "/transactions/",
        json={
            "postings": [
                {
                    "account": expense_account["aid"],
                    "side": "debit",
                    "amount": "25.00",
                },
                {
                    "account": account["aid"],
                    "side": "credit",
                    "amount": "24.00",
                },
            ],
        },
    )
    assert response.status_code == 422


def test_create_transaction_requires_two_postings(
    client: TestClient,
    account: dict,
):
    response = client.post(
        "/transactions/",
        json={
            "postings": [
                {
                    "account": account["aid"],
                    "side": "debit",
                    "amount": "25.00",
                },
            ],
        },
    )
    assert response.status_code == 422


def test_create_transaction_rejects_zero_amount(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    response = client.post(
        "/transactions/",
        json={
            "postings": [
                {
                    "account": expense_account["aid"],
                    "side": "debit",
                    "amount": "0.00",
                },
                {
                    "account": account["aid"],
                    "side": "credit",
                    "amount": "0.00",
                },
            ],
        },
    )
    assert response.status_code == 422


def test_create_transaction_unknown_account(
    client: TestClient,
    account: dict,
):
    response = client.post(
        "/transactions/",
        json={
            "postings": [
                {
                    "account": uuid4().hex,
                    "side": "debit",
                    "amount": "25.00",
                },
                {
                    "account": account["aid"],
                    "side": "credit",
                    "amount": "25.00",
                },
            ],
        },
    )
    assert response.status_code == 404


def test_get_transaction(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    create = client.post(
        "/transactions/",
        json={
            "postings": [
                {
                    "account": expense_account["aid"],
                    "side": "debit",
                    "amount": "10.00",
                },
                {
                    "account": account["aid"],
                    "side": "credit",
                    "amount": "10.00",
                },
            ],
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
):
    for amount in ("10.00", "20.00"):
        client.post(
            "/transactions/",
            json={
                "postings": [
                    {
                        "account": other_account["aid"],
                        "side": "debit",
                        "amount": amount,
                    },
                    {
                        "account": account["aid"],
                        "side": "credit",
                        "amount": amount,
                    },
                ],
            },
        )

    response = client.get("/transactions/")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_update_transaction(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    create = client.post(
        "/transactions/",
        json={
            "postings": [
                {
                    "account": expense_account["aid"],
                    "side": "debit",
                    "amount": "10.00",
                },
                {
                    "account": account["aid"],
                    "side": "credit",
                    "amount": "10.00",
                },
            ],
        },
    )
    tid = create.json()["tid"]

    response = client.patch(
        f"/transactions/{tid}",
        json={
            "payee": "updated payee",
            "comment": "updated comment",
            "postings": [
                {
                    "account": expense_account["aid"],
                    "side": "debit",
                    "amount": "15.00",
                },
                {
                    "account": account["aid"],
                    "side": "credit",
                    "amount": "15.00",
                },
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["payee"] == "updated payee"
    assert response.json()["comment"] == "updated comment"

    account_response = client.get(f"/accounts/{account['aid']}")
    assert account_response.json()["balance"] == "-15.00"


def test_update_transaction_null_date(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    create = client.post(
        "/transactions/",
        json={
            "postings": [
                {
                    "account": expense_account["aid"],
                    "side": "debit",
                    "amount": "10.00",
                },
                {
                    "account": account["aid"],
                    "side": "credit",
                    "amount": "10.00",
                },
            ],
        },
    )
    tid = create.json()["tid"]

    response = client.patch(
        f"/transactions/{tid}",
        json={"date": None},
    )
    assert response.status_code == 422


def test_delete_transaction(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    create = client.post(
        "/transactions/",
        json={
            "postings": [
                {
                    "account": expense_account["aid"],
                    "side": "debit",
                    "amount": "10.00",
                },
                {
                    "account": account["aid"],
                    "side": "credit",
                    "amount": "10.00",
                },
            ],
        },
    )
    tid = create.json()["tid"]

    response = client.delete(f"/transactions/{tid}")
    assert response.status_code == 204

    follow = client.get(f"/transactions/{tid}")
    assert follow.status_code == 404
    account_response = client.get(f"/accounts/{account['aid']}")
    assert account_response.json()["balance"] == "0.00"

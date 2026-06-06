from uuid import uuid4

from fastapi.testclient import TestClient


def test_create_journal_entry(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    response = client.post(
        "/journal-entries/",
        json={
            "lines": [
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
    assert len(data["lines"]) == 2
    assert "jid" in data

    account_response = client.get(f"/accounts/{account['aid']}")
    assert account_response.json()["balance"] == "-25.00"
    expense_response = client.get(f"/accounts/{expense_account['aid']}")
    assert expense_response.json()["balance"] == "25.00"


def test_create_journal_entry_must_balance(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    response = client.post(
        "/journal-entries/",
        json={
            "lines": [
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


def test_create_journal_entry_requires_two_lines(
    client: TestClient,
    account: dict,
):
    response = client.post(
        "/journal-entries/",
        json={
            "lines": [
                {
                    "account": account["aid"],
                    "side": "debit",
                    "amount": "25.00",
                },
            ],
        },
    )
    assert response.status_code == 422


def test_create_journal_entry_rejects_zero_amount(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    response = client.post(
        "/journal-entries/",
        json={
            "lines": [
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


def test_create_journal_entry_unknown_account(
    client: TestClient,
    account: dict,
):
    response = client.post(
        "/journal-entries/",
        json={
            "lines": [
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


def test_get_journal_entry(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    create = client.post(
        "/journal-entries/",
        json={
            "lines": [
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
    jid = create.json()["jid"]

    response = client.get(f"/journal-entries/{jid}")
    assert response.status_code == 200
    assert response.json()["jid"] == jid


def test_get_journal_entry_not_found(client: TestClient):
    response = client.get(f"/journal-entries/{uuid4()}")
    assert response.status_code == 404


def test_list_journal_entries(
    client: TestClient,
    account: dict,
    other_account: dict,
):
    for amount in ("10.00", "20.00"):
        client.post(
            "/journal-entries/",
            json={
                "lines": [
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

    response = client.get("/journal-entries/")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_update_journal_entry(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    create = client.post(
        "/journal-entries/",
        json={
            "lines": [
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
    jid = create.json()["jid"]

    response = client.patch(
        f"/journal-entries/{jid}",
        json={
            "note": "updated",
            "lines": [
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
    assert response.json()["note"] == "updated"

    account_response = client.get(f"/accounts/{account['aid']}")
    assert account_response.json()["balance"] == "-15.00"


def test_update_journal_entry_null_date(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    create = client.post(
        "/journal-entries/",
        json={
            "lines": [
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
    jid = create.json()["jid"]

    response = client.patch(
        f"/journal-entries/{jid}",
        json={"date": None},
    )
    assert response.status_code == 422


def test_delete_journal_entry(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    create = client.post(
        "/journal-entries/",
        json={
            "lines": [
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
    jid = create.json()["jid"]

    response = client.delete(f"/journal-entries/{jid}")
    assert response.status_code == 204

    follow = client.get(f"/journal-entries/{jid}")
    assert follow.status_code == 404
    account_response = client.get(f"/accounts/{account['aid']}")
    assert account_response.json()["balance"] == "0.00"

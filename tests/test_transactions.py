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


def _two_postings(debit: str, credit: str) -> dict:
    return {
        "postings": [
            {"account": debit, "side": "debit", "amount": "10.00"},
            {"account": credit, "side": "credit", "amount": "10.00"},
        ]
    }


def test_create_transaction_rejects_root_account(
    client: TestClient, account: dict, root_accounts: dict[str, str]
):
    response = client.post(
        "/transactions/", json=_two_postings(root_accounts["Expenses"], account["aid"])
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot post to root account 'Expenses'!"
    assert client.get("/transactions/").json() == []


def test_create_transaction_rejects_asset_with_sub_accounts(
    client: TestClient, account: dict, expense_account: dict
):
    client.post("/accounts/", json={"name": "child", "parent_id": account["aid"]})
    response = client.post(
        "/transactions/", json=_two_postings(expense_account["aid"], account["aid"])
    )
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "cannot post to account 'checking' because it has sub-accounts!"
    )


def test_create_transaction_to_expense_group(
    client: TestClient, account: dict, expense_account: dict
):
    client.post("/accounts/", json={"name": "child", "parent_id": expense_account["aid"]})
    response = client.post(
        "/transactions/", json=_two_postings(expense_account["aid"], account["aid"])
    )
    assert response.status_code == 201
    group = client.get(f"/accounts/{expense_account['aid']}").json()
    assert group["balance"] == "10.00"


def test_create_transaction_to_leaf_sub_account(
    client: TestClient, account: dict, expense_account: dict
):
    child = client.post(
        "/accounts/", json={"name": "child", "parent_id": expense_account["aid"]}
    ).json()
    response = client.post(
        "/transactions/", json=_two_postings(child["aid"], account["aid"])
    )
    assert response.status_code == 201
    parent = client.get(f"/accounts/{expense_account['aid']}").json()
    assert parent["balance"] == "10.00"


def test_update_transaction_rejects_root_account(
    client: TestClient, account: dict, expense_account: dict, root_accounts: dict[str, str]
):
    created = client.post(
        "/transactions/", json=_two_postings(expense_account["aid"], account["aid"])
    ).json()
    response = client.patch(
        f"/transactions/{created['tid']}",
        json=_two_postings(root_accounts["Expenses"], account["aid"]),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot post to root account 'Expenses'!"


def _post(client: TestClient, debit: dict, credit: dict, amount: str, date: str, payee: str):
    response = client.post(
        "/transactions/",
        json={
            "date": date,
            "payee": payee,
            "postings": [
                {"account": debit["aid"], "side": "debit", "amount": amount},
                {"account": credit["aid"], "side": "credit", "amount": amount},
            ],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_list_transactions_newest_first(
    client: TestClient, account: dict, expense_account: dict
):
    _post(client, expense_account, account, "1.00", "2026-01-05", "middle")
    _post(client, expense_account, account, "2.00", "2026-01-10", "newest")
    _post(client, expense_account, account, "3.00", "2026-01-01", "oldest")

    payees = [t["payee"] for t in client.get("/transactions/").json()]
    assert payees == ["newest", "middle", "oldest"]


def test_list_transactions_filter_by_date_range(
    client: TestClient, account: dict, expense_account: dict
):
    _post(client, expense_account, account, "1.00", "2026-01-05", "a")
    _post(client, expense_account, account, "2.00", "2026-01-10", "b")
    _post(client, expense_account, account, "3.00", "2026-01-15", "c")

    response = client.get(
        "/transactions/", params={"date_from": "2026-01-06", "date_to": "2026-01-10"}
    )
    assert [t["payee"] for t in response.json()] == ["b"]


def test_list_transactions_filter_by_account_includes_sub_accounts(
    client: TestClient,
    root_accounts: dict[str, str],
    account: dict,
    other_account: dict,
    expense_account: dict,
):
    child = client.post(
        "/accounts/", json={"name": "food", "parent_id": expense_account["aid"]}
    ).json()
    _post(client, child, account, "5.00", "2026-01-05", "food")
    _post(client, other_account, account, "9.00", "2026-01-06", "transfer")

    by_parent = client.get("/transactions/", params={"account": expense_account["aid"]})
    assert [t["payee"] for t in by_parent.json()] == ["food"]

    by_other = client.get("/transactions/", params={"account": other_account["aid"]})
    assert [t["payee"] for t in by_other.json()] == ["transfer"]


def test_list_transactions_filter_by_unknown_account(client: TestClient):
    response = client.get("/transactions/", params={"account": str(uuid4())})
    assert response.status_code == 404


def test_list_transactions_pagination(
    client: TestClient, account: dict, expense_account: dict
):
    for day in range(1, 6):
        _post(client, expense_account, account, "1.00", f"2026-01-0{day}", f"t{day}")

    page = client.get("/transactions/", params={"limit": 2, "offset": 1}).json()
    assert [t["payee"] for t in page] == ["t4", "t3"]


def test_list_transactions_rejects_invalid_pagination(client: TestClient):
    assert client.get("/transactions/", params={"limit": 0}).status_code == 422
    assert client.get("/transactions/", params={"offset": -1}).status_code == 422

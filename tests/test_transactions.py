from uuid import uuid4

from fastapi.testclient import TestClient

from .books import leg, post_account


def test_create_transaction(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    response = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "25.00"),
                leg(account, "credit", "25.00"),
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert len(data["postings"]) == 2
    assert "id" in data

    account_response = client.get(f"/api/accounts/{account['id']}")
    assert account_response.json()["balance"] == "-25.00"
    spent = client.get("/api/reports/breakdown", params={"kind": "expenses"}).json()
    assert spent["total"] == "25.00" and spent["lines"][0]["account"] == "groceries"


def test_create_transaction_must_balance(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    response = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "25.00"),
                leg(account, "credit", "24.00"),
            ],
        },
    )
    assert response.status_code == 422


def test_create_transaction_requires_two_postings(
    client: TestClient,
    account: dict,
):
    response = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(account, "debit", "25.00"),
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
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "0.00"),
                leg(account, "credit", "0.00"),
            ],
        },
    )
    assert response.status_code == 422


def test_create_transaction_unknown_account(
    client: TestClient,
    account: dict,
):
    response = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {
                    "account_id": uuid4().hex,
                    "side": "debit",
                    "amount": "25.00",
                },
                leg(account, "credit", "25.00"),
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
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "10.00"),
                leg(account, "credit", "10.00"),
            ],
        },
    )
    transaction_id = create.json()["id"]

    response = client.get(f"/api/transactions/{transaction_id}")
    assert response.status_code == 200
    assert response.json()["id"] == transaction_id


def test_get_transaction_not_found(client: TestClient):
    response = client.get(f"/api/transactions/{uuid4()}")
    assert response.status_code == 404


def test_list_transactions(
    client: TestClient,
    account: dict,
    other_account: dict,
):
    for amount in ("10.00", "20.00"):
        client.post(
            "/api/transactions/",
            json={
                "postings": [
                    leg(other_account, "debit", amount),
                    leg(account, "credit", amount),
                ],
            },
        )

    response = client.get("/api/transactions/")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_update_transaction(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    create = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "10.00"),
                leg(account, "credit", "10.00"),
            ],
        },
    )
    transaction_id = create.json()["id"]

    response = client.patch(
        f"/api/transactions/{transaction_id}",
        json={
            "payee": "updated payee",
            "comment": "updated comment",
            "postings": [
                leg(expense_account, "debit", "15.00"),
                leg(account, "credit", "15.00"),
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["payee"] == "updated payee"
    assert response.json()["comment"] == "updated comment"

    account_response = client.get(f"/api/accounts/{account['id']}")
    assert account_response.json()["balance"] == "-15.00"


def test_update_transaction_null_date(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    create = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "10.00"),
                leg(account, "credit", "10.00"),
            ],
        },
    )
    transaction_id = create.json()["id"]

    response = client.patch(
        f"/api/transactions/{transaction_id}",
        json={"date": None},
    )
    assert response.status_code == 422


def test_delete_transaction(
    client: TestClient,
    account: dict,
    expense_account: dict,
):
    create = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "10.00"),
                leg(account, "credit", "10.00"),
            ],
        },
    )
    transaction_id = create.json()["id"]

    response = client.delete(f"/api/transactions/{transaction_id}")
    assert response.status_code == 204

    follow = client.get(f"/api/transactions/{transaction_id}")
    assert follow.status_code == 404
    account_response = client.get(f"/api/accounts/{account['id']}")
    assert account_response.json()["balance"] == "0.00"


def _two_postings(debit, credit) -> dict:
    """Two lines; each side is an account id, or the dict of an account or category from a fixture."""

    def side(place, which):
        return (
            {"account_id": place, "side": which, "amount": "10.00"}
            if isinstance(place, str)
            else leg(place, which, "10.00")
        )

    return {"postings": [side(debit, "debit"), side(credit, "credit")]}


def test_create_transaction_rejects_root_account(client: TestClient, account: dict, root_accounts: dict[str, str]):
    response = client.post("/api/transactions/", json=_two_postings(account["id"], root_accounts["Assets"]))
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot post to root account 'Assets'!"
    assert client.get("/api/transactions/").json() == []


def test_create_transaction_rejects_asset_with_sub_accounts(client: TestClient, account: dict, expense_account: dict):
    post_account(client, {"name": "child", "parent_id": account["id"]})
    response = client.post("/api/transactions/", json=_two_postings(expense_account, account))
    assert response.status_code == 400
    assert response.json()["detail"] == ("cannot post to account 'checking' because it has sub-accounts!")


def test_create_transaction_to_expense_group(client: TestClient, account: dict, expense_account: dict):
    post_account(client, {"name": "child", "parent_id": expense_account["id"]})
    response = client.post("/api/transactions/", json=_two_postings(expense_account, account))
    assert response.status_code == 201
    spent = client.get("/api/reports/breakdown", params={"kind": "expenses"}).json()
    assert spent["total"] == "10.00"


def test_create_transaction_to_leaf_sub_account(client: TestClient, account: dict, expense_account: dict):
    child = post_account(client, {"name": "child", "parent_id": expense_account["id"]}).json()
    response = client.post("/api/transactions/", json=_two_postings(child, account))
    assert response.status_code == 201
    spent = client.get("/api/reports/breakdown", params={"kind": "expenses"}).json()
    assert spent["total"] == "10.00" and spent["lines"][0]["account"] == "groceries"


def test_update_transaction_rejects_root_account(
    client: TestClient, account: dict, expense_account: dict, root_accounts: dict[str, str]
):
    created = client.post("/api/transactions/", json=_two_postings(expense_account, account)).json()
    response = client.patch(
        f"/api/transactions/{created['id']}",
        json=_two_postings(account["id"], root_accounts["Assets"]),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot post to root account 'Assets'!"


def _post(client: TestClient, debit: dict, credit: dict, amount: str, date: str, payee: str):
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
    return response.json()


def test_list_transactions_newest_first(client: TestClient, account: dict, expense_account: dict):
    _post(client, expense_account, account, "1.00", "2026-01-05", "middle")
    _post(client, expense_account, account, "2.00", "2026-01-10", "newest")
    _post(client, expense_account, account, "3.00", "2026-01-01", "oldest")

    payees = [t["payee"] for t in client.get("/api/transactions/").json()]
    assert payees == ["newest", "middle", "oldest"]


def test_list_transactions_filter_by_date_range(client: TestClient, account: dict, expense_account: dict):
    _post(client, expense_account, account, "1.00", "2026-01-05", "a")
    _post(client, expense_account, account, "2.00", "2026-01-10", "b")
    _post(client, expense_account, account, "3.00", "2026-01-15", "c")

    response = client.get("/api/transactions/", params={"date_from": "2026-01-06", "date_to": "2026-01-10"})
    assert [t["payee"] for t in response.json()] == ["b"]


def test_list_transactions_filter_by_account_includes_sub_accounts(
    client: TestClient,
    root_accounts: dict[str, str],
    account: dict,
    other_account: dict,
    expense_account: dict,
):
    child = post_account(client, {"name": "food", "parent_id": expense_account["id"]}).json()
    _post(client, child, account, "5.00", "2026-01-05", "food")
    _post(client, other_account, account, "9.00", "2026-01-06", "transfer")

    by_parent = client.get("/api/transactions/", params={"category_id": expense_account["id"]})
    assert [t["payee"] for t in by_parent.json()] == ["food"]

    by_other = client.get("/api/transactions/", params={"account_id": other_account["id"]})
    assert [t["payee"] for t in by_other.json()] == ["transfer"]


def test_list_transactions_filter_by_unknown_account(client: TestClient):
    response = client.get("/api/transactions/", params={"account_id": str(uuid4())})
    assert response.status_code == 404


def test_list_transactions_pagination(client: TestClient, account: dict, expense_account: dict):
    for day in range(1, 6):
        _post(client, expense_account, account, "1.00", f"2026-01-0{day}", f"t{day}")

    page = client.get("/api/transactions/", params={"limit": 2, "offset": 1}).json()
    assert [t["payee"] for t in page] == ["t4", "t3"]


def test_list_transactions_rejects_invalid_pagination(client: TestClient):
    assert client.get("/api/transactions/", params={"limit": 0}).status_code == 422
    assert client.get("/api/transactions/", params={"offset": -1}).status_code == 422

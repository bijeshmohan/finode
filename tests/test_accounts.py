from uuid import uuid4

from fastapi.testclient import TestClient


def test_create_account(client: TestClient):
    response = client.post(
        "/accounts/",
        json={
            "name": "checking",
            "details": "main account",
            "type": "Assets",
            "balance": "100.50",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "checking"
    assert data["details"] == "main account"
    assert data["type"] == "Assets"
    assert data["balance"] == "100.50"
    assert "aid" in data


def test_create_account_default_balance(client: TestClient):
    response = client.post(
        "/accounts/",
        json={"name": "wallet", "details": None, "type": "Assets"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["balance"] == "0.00"


def test_create_account_opening_balance_creates_transaction(client: TestClient):
    response = client.post(
        "/accounts/",
        json={"name": "wallet", "type": "Assets", "balance": "75.00"},
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
    response = client.get("/accounts/?type=Expenses")
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
        json={"name": "wallet", "type": "Assets", "balance": "10.00"},
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
        json={"name": "test_acc", "type": "Assets", "balance": "100.00"},
    )
    assert create_resp.status_code == 201
    account = create_resp.json()

    tx_resp = client.get("/transactions/")
    assert tx_resp.status_code == 200
    assert len(tx_resp.json()) == 1

    update_resp = client.patch(
        f"/accounts/{account['aid']}",
        json={"type": "Liabilities"},
    )
    assert update_resp.status_code == 200
    updated_account = update_resp.json()
    assert updated_account["type"] == "Liabilities"
    assert updated_account["balance"] == "-100.00"

    tx_resp_after = client.get("/transactions/")
    assert tx_resp_after.status_code == 200
    assert len(tx_resp_after.json()) == 1


def test_create_child_account(client: TestClient):
    parent = client.post(
        "/accounts/",
        json={"name": "parent_acc", "type": "Assets", "balance": "100.00"},
    ).json()
    
    child = client.post(
        "/accounts/",
        json={"name": "child_acc", "type": "Assets", "parent_id": parent["aid"], "balance": "50.00"},
    )
    assert child.status_code == 201
    child_data = child.json()
    assert child_data["parent_id"] == parent["aid"]


def test_create_child_account_parent_not_found(client: TestClient):
    child = client.post(
        "/accounts/",
        json={"name": "child_acc", "type": "Assets", "parent_id": str(uuid4())},
    )
    assert child.status_code == 400
    assert child.json()["detail"] == "parent account not found!"


def test_create_child_account_type_mismatch(client: TestClient):
    parent = client.post(
        "/accounts/",
        json={"name": "parent_acc", "type": "Assets"},
    ).json()
    
    child = client.post(
        "/accounts/",
        json={"name": "child_acc", "type": "Liabilities", "parent_id": parent["aid"]},
    )
    assert child.status_code == 400
    assert child.json()["detail"] == "parent account type must match child account type!"


def test_update_parent_id(client: TestClient):
    acc1 = client.post("/accounts/", json={"name": "acc1", "type": "Assets"}).json()
    acc2 = client.post("/accounts/", json={"name": "acc2", "type": "Assets"}).json()
    
    update = client.patch(f"/accounts/{acc2['aid']}", json={"parent_id": acc1["aid"]})
    assert update.status_code == 200
    assert update.json()["parent_id"] == acc1["aid"]


def test_detect_cycle_self(client: TestClient):
    acc = client.post("/accounts/", json={"name": "acc", "type": "Assets"}).json()
    
    update = client.patch(f"/accounts/{acc['aid']}", json={"parent_id": acc["aid"]})
    assert update.status_code == 400
    assert update.json()["detail"] == "an account cannot be its own parent!"


def test_detect_cycle_multi(client: TestClient):
    a = client.post("/accounts/", json={"name": "A", "type": "Assets"}).json()
    b = client.post("/accounts/", json={"name": "B", "type": "Assets", "parent_id": a["aid"]}).json()
    
    # Try setting A's parent to B
    update = client.patch(f"/accounts/{a['aid']}", json={"parent_id": b["aid"]})
    assert update.status_code == 400
    assert update.json()["detail"] == "cyclic parent relationship detected!"


def test_parent_balance_aggregation(client: TestClient):
    parent = client.post(
        "/accounts/",
        json={"name": "parent", "type": "Assets", "balance": "100.00"},
    ).json()
    
    child = client.post(
        "/accounts/",
        json={"name": "child", "type": "Assets", "parent_id": parent["aid"], "balance": "50.00"},
    ).json()
    
    grandchild = client.post(
        "/accounts/",
        json={"name": "grandchild", "type": "Assets", "parent_id": child["aid"], "balance": "20.00"},
    ).json()
    
    # Verify balances
    p_get = client.get(f"/accounts/{parent['aid']}").json()
    assert p_get["balance"] == "170.00"
    
    c_get = client.get(f"/accounts/{child['aid']}").json()
    assert c_get["balance"] == "70.00"
    
    gc_get = client.get(f"/accounts/{grandchild['aid']}").json()
    assert gc_get["balance"] == "20.00"


def test_delete_parent_account_fails(client: TestClient):
    parent = client.post("/accounts/", json={"name": "parent", "type": "Assets"}).json()
    client.post("/accounts/", json={"name": "child", "type": "Assets", "parent_id": parent["aid"]})
    
    response = client.delete(f"/accounts/{parent['aid']}")
    assert response.status_code == 409
    assert response.json()["detail"] == "account has sub-accounts"


def test_update_parent_type_fails(client: TestClient):
    parent = client.post("/accounts/", json={"name": "parent", "type": "Assets"}).json()
    client.post("/accounts/", json={"name": "child", "type": "Assets", "parent_id": parent["aid"]})
    
    response = client.patch(f"/accounts/{parent['aid']}", json={"type": "Liabilities"})
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot change type of account with sub-accounts!"


def test_create_root_account_without_type_fails(client: TestClient):
    response = client.post("/accounts/", json={"name": "no_type_root"})
    assert response.status_code == 400
    assert response.json()["detail"] == "type is required for top-level accounts!"


def test_create_child_account_inherits_type(client: TestClient):
    parent = client.post("/accounts/", json={"name": "parent", "type": "Expenses"}).json()
    
    # Omit type for the child account
    child_resp = client.post(
        "/accounts/",
        json={"name": "child_no_type", "parent_id": parent["aid"]},
    )
    assert child_resp.status_code == 201
    child_data = child_resp.json()
    assert child_data["type"] == "Expenses"
    assert child_data["parent_id"] == parent["aid"]




from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from .books import post_account
from .svc import plain, services


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
    assert data["parent_id"] == root_accounts["Assets"]
    assert data["balance"] == "100.50"
    assert "aid" in data


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
        posting["account"] == account["aid"] and posting["side"] == "debit" and posting["amount"] == "75.00"
        for posting in postings
    )


def test_get_account(client: TestClient, account: dict):
    response = client.get(f"/api/accounts/{account['aid']}")
    assert response.status_code == 200
    assert response.json()["aid"] == account["aid"]


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
    aids = {item["aid"] for item in data}
    assert account["aid"] in aids
    assert other_account["aid"] in aids


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
    # Empty DB lists only the 5 system root accounts
    response = client.get("/api/accounts/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 5
    names = {item["name"] for item in data}
    assert names == {"Assets", "Expenses", "Equity", "Income", "Liabilities"}


def test_update_account_metadata(client: TestClient, account: dict):
    response = client.patch(
        f"/api/accounts/{account['aid']}",
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
        f"/api/accounts/{account['aid']}",
        json={"balance": "175.00"},
    )
    assert response.status_code == 200
    assert response.json()["balance"] == "175.00"

    entries = client.get("/api/transactions/").json()
    assert len(entries) == 1
    assert entries[0]["payee"] == "Balance adjustment"
    assert entries[0]["comment"] == "Result of direct account balance update"
    assert any(
        posting["account"] == account["aid"] and posting["side"] == "debit" and posting["amount"] == "175.00"
        for posting in entries[0]["postings"]
    )


def test_update_account_not_found(client: TestClient):
    response = client.patch(
        f"/api/accounts/{uuid4()}",
        json={"name": "ghost", "details": None, "balance": "0.00"},
    )
    assert response.status_code == 404


def test_delete_account(client: TestClient, account: dict):
    response = client.delete(f"/api/accounts/{account['aid']}")
    assert response.status_code == 204

    follow = client.get(f"/api/accounts/{account['aid']}")
    assert follow.status_code == 404


def test_delete_account_with_postings_conflicts(client: TestClient, root_accounts: dict[str, str]):
    create = post_account(client, {"name": "wallet", "parent_id": root_accounts["Assets"], "balance": "10.00"})
    account = create.json()

    response = client.delete(f"/api/accounts/{account['aid']}")
    assert response.status_code == 409
    assert response.json()["detail"] == "account has postings"


def test_delete_account_not_found(client: TestClient):
    response = client.delete(f"/api/accounts/{uuid4()}")
    assert response.status_code == 404


def test_create_child_account(client: TestClient, root_accounts: dict[str, str]):
    parent = post_account(client, {"name": "parent_acc", "parent_id": root_accounts["Assets"]}).json()

    child = post_account(client, {"name": "child_acc", "parent_id": parent["aid"], "balance": "50.00"})
    assert child.status_code == 201
    child_data = child.json()
    assert child_data["parent_id"] == parent["aid"]


def test_create_child_account_parent_not_found(client: TestClient):
    child = post_account(client, {"name": "child_acc", "parent_id": str(uuid4())})
    assert child.status_code == 400
    assert child.json()["detail"] == "parent account not found!"


def test_create_root_account_without_parent_fails(client: TestClient):
    response = post_account(client, {"name": "no_parent_root"})
    assert response.status_code == 400
    assert response.json()["detail"] == "parent_id is required for all user-created accounts!"


def test_update_parent_id(client: TestClient, root_accounts: dict[str, str]):
    acc1 = post_account(client, {"name": "acc1", "parent_id": root_accounts["Assets"]}).json()
    acc2 = post_account(client, {"name": "acc2", "parent_id": root_accounts["Assets"]}).json()

    update = client.patch(f"/api/accounts/{acc2['aid']}", json={"parent_id": acc1["aid"]})
    assert update.status_code == 200
    assert update.json()["parent_id"] == acc1["aid"]


def test_detect_cycle_self(client: TestClient, root_accounts: dict[str, str]):
    acc = post_account(client, {"name": "acc", "parent_id": root_accounts["Assets"]}).json()

    update = client.patch(f"/api/accounts/{acc['aid']}", json={"parent_id": acc["aid"]})
    assert update.status_code == 400
    assert update.json()["detail"] == "an account cannot be its own parent!"


def test_detect_cycle_multi(client: TestClient, root_accounts: dict[str, str]):
    a = post_account(client, {"name": "A", "parent_id": root_accounts["Assets"]}).json()
    b = post_account(client, {"name": "B", "parent_id": a["aid"]}).json()

    # Try setting A's parent to B
    update = client.patch(f"/api/accounts/{a['aid']}", json={"parent_id": b["aid"]})
    assert update.status_code == 400
    assert update.json()["detail"] == "cyclic parent relationship detected!"


def test_parent_balance_aggregation(client: TestClient, root_accounts: dict[str, str]):
    parent = post_account(client, {"name": "parent", "parent_id": root_accounts["Assets"]}).json()

    child = post_account(client, {"name": "child", "parent_id": parent["aid"]}).json()

    sibling = post_account(client, {"name": "sibling", "parent_id": parent["aid"], "balance": "50.00"}).json()

    client.patch(f"/api/accounts/{child['aid']}", json={"balance": "20.00"})

    p_get = client.get(f"/api/accounts/{parent['aid']}").json()
    assert p_get["balance"] == "70.00"

    c_get = client.get(f"/api/accounts/{child['aid']}").json()
    assert c_get["balance"] == "20.00"

    s_get = client.get(f"/api/accounts/{sibling['aid']}").json()
    assert s_get["balance"] == "50.00"


def test_delete_parent_account_fails(client: TestClient, root_accounts: dict[str, str]):
    parent = post_account(client, {"name": "parent", "parent_id": root_accounts["Assets"]}).json()
    post_account(client, {"name": "child", "parent_id": parent["aid"]})

    response = client.delete(f"/api/accounts/{parent['aid']}")
    assert response.status_code == 409
    assert response.json()["detail"] == "account has sub-accounts"


def test_system_root_modifications_fail(client: TestClient, root_accounts: dict[str, str]):
    root_id = root_accounts["Assets"]

    # Try to change parent of root
    r1 = client.patch(f"/api/accounts/{root_id}", json={"parent_id": root_accounts["Expenses"]})
    assert r1.status_code == 400
    assert r1.json()["detail"] == "cannot change parent of a root account!"

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
    assert {a["aid"] for a in first} == {a["aid"] for a in second}


def test_move_account_to_different_root_fails(client: TestClient, account: dict, root_accounts: dict[str, str]):
    response = client.patch(
        f"/api/accounts/{account['aid']}",
        json={"parent_id": root_accounts["Liabilities"]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot move account under a different root account!"
    assert client.get(f"/api/accounts/{account['aid']}").json()["parent_id"] == root_accounts["Assets"]


def test_move_account_under_account_of_different_root_fails(
    client: TestClient, account: dict, root_accounts: dict[str, str]
):
    card = post_account(client, {"name": "card", "parent_id": root_accounts["Liabilities"]}).json()
    response = client.patch(
        f"/api/accounts/{account['aid']}",
        json={"parent_id": card["aid"]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot move account under a different root account!"


def test_move_account_within_same_root(client: TestClient, account: dict, other_account: dict):
    response = client.patch(
        f"/api/accounts/{account['aid']}",
        json={"parent_id": other_account["aid"]},
    )
    assert response.status_code == 200
    assert response.json()["parent_id"] == other_account["aid"]


def test_set_balance_of_root_account_fails(client: TestClient, root_accounts: dict[str, str]):
    response = client.patch(f"/api/accounts/{root_accounts['Assets']}", json={"balance": "10.00"})
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot set balance of a root account!"


def test_set_balance_of_account_with_sub_accounts_fails(
    client: TestClient, account: dict, root_accounts: dict[str, str]
):
    post_account(client, {"name": "child", "parent_id": account["aid"]})
    response = client.patch(f"/api/accounts/{account['aid']}", json={"balance": "10.00"})
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot set balance of an account with sub-accounts!"


def _opening_balances(client: TestClient) -> dict:
    return next(a for a in client.get("/api/accounts/").json() if a["name"] == "Opening Balances")


def test_create_sub_account_under_account_with_postings_fails(client: TestClient, root_accounts: dict[str, str]):
    parent = post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"}).json()

    response = post_account(client, {"name": "child", "parent_id": parent["aid"]})
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot add sub-accounts to 'bank' because it has postings!"


def test_move_account_under_account_with_postings_fails(client: TestClient, root_accounts: dict[str, str]):
    target = post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"}).json()
    moving = post_account(client, {"name": "cash", "parent_id": root_accounts["Assets"]}).json()

    response = client.patch(f"/api/accounts/{moving['aid']}", json={"parent_id": target["aid"]})
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot add sub-accounts to 'bank' because it has postings!"


def test_opening_balances_account_is_created_under_equity(client: TestClient, root_accounts: dict[str, str]):
    post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"})
    assert _opening_balances(client)["parent_id"] == root_accounts["Equity"]


def test_set_balance_of_opening_balances_account_fails(client: TestClient, root_accounts: dict[str, str]):
    post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"})
    opening = _opening_balances(client)

    response = client.patch(f"/api/accounts/{opening['aid']}", json={"balance": "5000.00"})
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot set balance of system account 'Opening Balances'!"
    assert client.get(f"/api/accounts/{opening['aid']}").json()["balance"] == opening["balance"]


def test_opening_balances_account_cannot_be_renamed_moved_or_deleted(client: TestClient, root_accounts: dict[str, str]):
    post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"})
    opening = _opening_balances(client)
    url = f"/api/accounts/{opening['aid']}"

    renamed = client.patch(url, json={"name": "Foo"})
    assert renamed.status_code == 400
    assert renamed.json()["detail"] == "cannot change name of system account 'Opening Balances'!"

    moved = client.patch(url, json={"parent_id": root_accounts["Assets"]})
    assert moved.status_code == 400
    assert moved.json()["detail"] == "cannot move system account 'Opening Balances'!"

    deleted = client.delete(url)
    assert deleted.status_code == 400
    assert deleted.json()["detail"] == "cannot delete system account 'Opening Balances'!"


def test_opening_balances_account_allows_metadata_update(client: TestClient, root_accounts: dict[str, str]):
    post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"})
    opening = _opening_balances(client)

    response = client.patch(f"/api/accounts/{opening['aid']}", json={"details": "notes"})
    assert response.status_code == 200
    assert response.json()["details"] == "notes"


def test_cannot_add_sub_account_under_opening_balances(client: TestClient, root_accounts: dict[str, str]):
    post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"})
    opening = _opening_balances(client)

    response = post_account(client, {"name": "child", "parent_id": opening["aid"]})
    assert response.status_code == 400
    assert response.json()["detail"] == "cannot add sub-accounts to system account 'Opening Balances'!"


def test_cannot_duplicate_opening_balances_account(client: TestClient, root_accounts: dict[str, str]):
    post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"})
    other = post_account(client, {"name": "reserve", "parent_id": root_accounts["Equity"]}).json()

    created = post_account(client, {"name": "Opening Balances", "parent_id": root_accounts["Equity"]})
    assert created.status_code == 400

    renamed = client.patch(f"/api/accounts/{other['aid']}", json={"name": "Opening Balances"})
    assert renamed.status_code == 400
    assert renamed.json()["detail"] == "system account 'Opening Balances' already exists!"


def _transfer(client: TestClient, debit: dict, credit: dict, amount: str, date: str, payee: str):
    response = client.post(
        "/api/transactions/",
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


def test_account_register_has_running_balance(
    client: TestClient, root_accounts: dict[str, str], expense_account: dict, session
):
    bank = post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"}).json()
    today = date.today().isoformat()
    _transfer(client, expense_account, bank, "30.00", today, "shop")
    _transfer(client, expense_account, bank, "10.00", today, "cafe")

    entries = plain(services(session).accounts.register(UUID(bank["aid"])))
    assert [e["change"] for e in entries] == ["100.00", "-30.00", "-10.00"]
    assert [e["balance"] for e in entries] == ["100.00", "70.00", "60.00"]
    assert entries[1]["counter_accounts"] == ["groceries"]
    assert entries[-1]["balance"] == client.get(f"/api/accounts/{bank['aid']}").json()["balance"]


def test_account_register_uses_normal_side_and_sub_accounts(
    client: TestClient, root_accounts: dict[str, str], account: dict, session
):
    parent = post_account(client, {"name": "food", "parent_id": root_accounts["Expenses"]}).json()
    child = post_account(client, {"name": "dining", "parent_id": parent["aid"]}).json()
    _transfer(client, child, account, "12.50", "2026-02-02", "lunch")

    entries = plain(services(session).categories.register(UUID(parent["aid"])))
    assert len(entries) == 1
    assert entries[0]["change"] == "12.50"
    assert entries[0]["balance"] == "12.50"
    assert entries[0]["counter_accounts"] == ["checking"]


def test_account_register_not_found(session):
    assert services(session).accounts.register(uuid4()) is None

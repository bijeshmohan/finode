from fastapi.testclient import TestClient


def _opening_balances(client: TestClient) -> dict:
    return next(a for a in client.get("/accounts/").json() if a["name"] == "Opening Balances")


def test_accounts_page_lists_roots_and_children(
    client: TestClient, root_accounts: dict[str, str], account: dict
):
    response = client.get("/app/accounts")
    assert response.status_code == 200
    for root in ("Assets", "Liabilities", "Equity", "Income", "Expenses"):
        assert root in response.text
    assert "checking" in response.text
    # root sections come in accounting order
    assert response.text.index("Assets") < response.text.index("Liabilities") < response.text.index("Expenses")


def test_accounts_page_protects_roots_and_system_account(
    client: TestClient, root_accounts: dict[str, str]
):
    client.post(
        "/accounts/",
        json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "10.00"},
    )
    opening = _opening_balances(client)

    page = client.get("/app/accounts").text
    assert f"/app/accounts/{opening['aid']}/edit" not in page
    for aid in root_accounts.values():
        assert f"/app/accounts/{aid}/edit" not in page
    assert "system" in page


def test_create_account_from_form(client: TestClient, root_accounts: dict[str, str]):
    response = client.post(
        "/app/accounts",
        data={
            "name": "wallet",
            "parent_id": root_accounts["Assets"],
            "balance": "1,250.50",
            "details": "pocket",
        },
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/app/accounts"
    created = next(a for a in client.get("/accounts/").json() if a["name"] == "wallet")
    assert created["balance"] == "1250.50"
    assert created["details"] == "pocket"


def test_create_account_shows_service_errors(client: TestClient, root_accounts: dict[str, str]):
    with_postings = client.post(
        "/accounts/",
        json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "5.00"},
    ).json()
    response = client.post(
        "/app/accounts", data={"name": "child", "parent_id": with_postings["aid"]}
    )
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#create-error"
    assert "has postings" in response.text


def test_create_account_rejects_invalid_amount(client: TestClient, root_accounts: dict[str, str]):
    response = client.post(
        "/app/accounts",
        data={"name": "x", "parent_id": root_accounts["Assets"], "balance": "abc"},
    )
    assert response.status_code == 400
    assert "not a valid amount" in response.text


def test_edit_form_and_row_fragments(client: TestClient, account: dict):
    form = client.get(f"/app/accounts/{account['aid']}/edit")
    assert form.status_code == 200
    assert 'value="checking"' in form.text
    row = client.get(f"/app/accounts/{account['aid']}/row")
    assert row.status_code == 200
    assert "checking" in row.text


def test_edit_form_only_offers_parents_from_same_root(
    client: TestClient, root_accounts: dict[str, str], account: dict
):
    form = client.get(f"/app/accounts/{account['aid']}/edit").text
    assert f'value="{root_accounts["Assets"]}"' in form
    assert f'value="{root_accounts["Expenses"]}"' not in form
    assert f'<option value="{account["aid"]}"' not in form


def test_update_account_from_form(client: TestClient, root_accounts: dict[str, str], account: dict):
    response = client.post(
        f"/app/accounts/{account['aid']}/edit",
        data={
            "name": "main checking",
            "parent_id": root_accounts["Assets"],
            "details": "",
            "balance": "75.00",
        },
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/app/accounts"
    updated = client.get(f"/accounts/{account['aid']}").json()
    assert updated["name"] == "main checking"
    assert updated["balance"] == "75.00"


def test_update_account_unchanged_is_a_noop(
    client: TestClient, root_accounts: dict[str, str], account: dict
):
    response = client.post(
        f"/app/accounts/{account['aid']}/edit",
        data={"name": "checking", "parent_id": root_accounts["Assets"], "balance": "0.00"},
    )
    assert response.status_code == 200
    assert client.get("/transactions/").json() == []


def test_update_account_error_targets_its_row(
    client: TestClient, root_accounts: dict[str, str], account: dict
):
    response = client.post(
        f"/app/accounts/{account['aid']}/edit",
        data={"name": "checking", "parent_id": root_accounts["Expenses"]},
    )
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == f"#edit-error-{account['aid']}"
    assert "different root" in response.text


def test_update_missing_account_is_404(client: TestClient, root_accounts: dict[str, str]):
    response = client.post(
        "/app/accounts/00000000-0000-4000-8000-0000000000ff/edit",
        data={"name": "x", "parent_id": root_accounts["Assets"]},
    )
    assert response.status_code == 404


def test_delete_account_from_ui(client: TestClient, account: dict):
    response = client.post(f"/app/accounts/{account['aid']}/delete")
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/app/accounts"
    assert client.get(f"/accounts/{account['aid']}").status_code == 404


def test_delete_account_with_postings_shows_error(
    client: TestClient, root_accounts: dict[str, str]
):
    bank = client.post(
        "/accounts/",
        json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "5.00"},
    ).json()
    response = client.post(f"/app/accounts/{bank['aid']}/delete")
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#page-error"
    assert "has postings" in response.text


def test_error_messages_are_escaped(client: TestClient, root_accounts: dict[str, str]):
    response = client.post(
        "/app/accounts",
        data={"name": "x", "parent_id": root_accounts["Assets"], "balance": "<script>"},
    )
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text

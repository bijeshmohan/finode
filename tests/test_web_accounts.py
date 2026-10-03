from datetime import date

from fastapi.testclient import TestClient


MISSING = "00000000-0000-4000-8000-0000000000ff"


def _opening_balances(client: TestClient) -> dict:
    return next(a for a in client.get("/accounts/").json() if a["name"] == "Opening Balances")


def _bank(client: TestClient, root_accounts: dict[str, str], balance: str = "100.00") -> dict:
    return client.post(
        "/accounts/",
        json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": balance},
    ).json()


# --- accounts list ---------------------------------------------------------


def test_accounts_page_groups_accounts_under_roots_in_order(
    client: TestClient, root_accounts: dict[str, str], account: dict
):
    response = client.get("/app/accounts")
    assert response.status_code == 200
    text = response.text
    assert text.index(">Assets<") < text.index(">Liabilities<") < text.index(">Expenses<")
    assert f'href="/app/accounts/{account["aid"]}"' in text
    assert "checking" in text


def test_accounts_page_suggests_first_account_for_empty_roots(
    client: TestClient, root_accounts: dict[str, str]
):
    text = client.get("/app/accounts").text
    assert f'href="/app/accounts/new?parent={root_accounts["Liabilities"]}"' in text
    assert "Add a credit card or loan" in text


def test_accounts_page_marks_system_account(client: TestClient, root_accounts: dict[str, str]):
    _bank(client, root_accounts)
    assert '<span class="badge">system</span>' in client.get("/app/accounts").text


# --- account page ----------------------------------------------------------


def test_account_page_shows_balance_activity_and_actions(
    client: TestClient, root_accounts: dict[str, str], expense_account: dict
):
    bank = _bank(client, root_accounts)
    client.post(
        "/transactions/",
        json={
            "date": date.today().isoformat(),
            "payee": "lunch",
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "30.00"},
                {"account": bank["aid"], "side": "credit", "amount": "30.00"},
            ],
        },
    )

    text = client.get(f"/app/accounts/{bank['aid']}").text
    assert "70.00" in text
    assert "lunch" in text and "−30.00" in text
    assert f'href="/app/transactions/new?account={bank["aid"]}&back=/app/accounts/{bank["aid"]}"' in text
    assert f'href="/app/accounts/{bank["aid"]}/edit"' in text
    # it has postings, so it cannot gain sub-accounts
    assert f"/app/accounts/new?parent={bank['aid']}" not in text


def test_account_page_for_empty_leaf_offers_sub_account(client: TestClient, account: dict):
    text = client.get(f"/app/accounts/{account['aid']}").text
    assert f"/app/accounts/new?parent={account['aid']}" in text
    assert "No activity yet." in text


def test_root_and_system_account_pages_are_read_only(
    client: TestClient, root_accounts: dict[str, str]
):
    _bank(client, root_accounts)
    for aid in (root_accounts["Assets"], _opening_balances(client)["aid"]):
        assert f"/app/accounts/{aid}/edit" not in client.get(f"/app/accounts/{aid}").text
    root_page = client.get(f"/app/accounts/{root_accounts['Assets']}").text
    assert f"/app/transactions/new?account={root_accounts['Assets']}" not in root_page
    assert client.get(f"/app/accounts/{root_accounts['Assets']}/edit").status_code == 404


def test_account_page_not_found(client: TestClient):
    assert client.get(f"/app/accounts/{MISSING}").status_code == 404


def test_old_register_url_redirects(client: TestClient, account: dict):
    response = client.get(f"/app/accounts/{account['aid']}/register", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == f"/app/accounts/{account['aid']}"


# --- create ----------------------------------------------------------------


def test_new_account_page_preselects_parent(client: TestClient, root_accounts: dict[str, str]):
    text = client.get("/app/accounts/new", params={"parent": root_accounts["Income"]}).text
    assert f'<option value="{root_accounts["Income"]}" selected>' in text
    assert 'name="balance"' in text


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
    created = next(a for a in client.get("/accounts/").json() if a["name"] == "wallet")
    assert response.headers["HX-Redirect"] == f"/app/accounts/{created['aid']}"
    assert created["balance"] == "1250.50"
    assert created["details"] == "pocket"


def test_create_account_requires_parent(client: TestClient):
    response = client.post("/app/accounts", data={"name": "x", "parent_id": ""})
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"


def test_create_account_shows_service_errors(client: TestClient, root_accounts: dict[str, str]):
    bank = _bank(client, root_accounts, "5.00")
    response = client.post("/app/accounts", data={"name": "child", "parent_id": bank["aid"]})
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"
    assert "has postings" in response.text


def test_create_account_rejects_invalid_amount(client: TestClient, root_accounts: dict[str, str]):
    response = client.post(
        "/app/accounts",
        data={"name": "x", "parent_id": root_accounts["Assets"], "balance": "abc"},
    )
    assert response.status_code == 400
    assert "not a valid amount" in response.text


def test_error_messages_are_escaped(client: TestClient, root_accounts: dict[str, str]):
    response = client.post(
        "/app/accounts",
        data={"name": "x", "parent_id": root_accounts["Assets"], "balance": "<script>"},
    )
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text


# --- edit ------------------------------------------------------------------


def test_edit_page_prefills_and_limits_parents_to_same_root(
    client: TestClient, root_accounts: dict[str, str], account: dict
):
    response = client.get(f"/app/accounts/{account['aid']}/edit")
    assert response.status_code == 200
    text = response.text
    assert 'value="checking"' in text
    assert f'value="{root_accounts["Assets"]}" selected' in text
    assert f'value="{root_accounts["Expenses"]}"' not in text
    assert f'<option value="{account["aid"]}"' not in text
    assert f'hx-post="/app/accounts/{account["aid"]}/delete"' in text


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
    assert response.headers["HX-Redirect"] == f"/app/accounts/{account['aid']}"
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


def test_update_account_shows_service_errors(
    client: TestClient, root_accounts: dict[str, str], account: dict
):
    response = client.post(
        f"/app/accounts/{account['aid']}/edit",
        data={"name": "checking", "parent_id": root_accounts["Expenses"]},
    )
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"
    assert "different root" in response.text


def test_update_missing_account_is_404(client: TestClient, root_accounts: dict[str, str]):
    response = client.post(
        f"/app/accounts/{MISSING}/edit",
        data={"name": "x", "parent_id": root_accounts["Assets"]},
    )
    assert response.status_code == 404


# --- delete ----------------------------------------------------------------


def test_delete_account_from_ui(client: TestClient, account: dict):
    response = client.post(f"/app/accounts/{account['aid']}/delete")
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/app/accounts"
    assert client.get(f"/accounts/{account['aid']}").status_code == 404


def test_delete_account_with_postings_shows_error(
    client: TestClient, root_accounts: dict[str, str]
):
    bank = _bank(client, root_accounts, "5.00")
    response = client.post(f"/app/accounts/{bank['aid']}/delete")
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#page-error"
    assert "has postings" in response.text

from datetime import date

from fastapi.testclient import TestClient


def _post(client: TestClient, debit: dict, credit: dict, amount: str, on: str, payee: str):
    response = client.post(
        "/transactions/",
        json={
            "date": on,
            "payee": payee,
            "postings": [
                {"account": debit["aid"], "side": "debit", "amount": amount},
                {"account": credit["aid"], "side": "credit", "amount": amount},
            ],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_account_register_page(
    client: TestClient, root_accounts: dict[str, str], expense_account: dict
):
    bank = client.post(
        "/accounts/",
        json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"},
    ).json()
    today = date.today().isoformat()
    _post(client, expense_account, bank, "30.00", today, "lunch")

    response = client.get(f"/app/accounts/{bank['aid']}/register")
    assert response.status_code == 200
    assert "lunch" in response.text
    assert "-30.00" in response.text
    assert "70.00" in response.text
    # newest activity first
    assert response.text.index("lunch") < response.text.index("Opening balance")


def test_account_register_page_not_found(client: TestClient):
    response = client.get("/app/accounts/00000000-0000-4000-8000-0000000000ff/register")
    assert response.status_code == 404


def test_account_names_link_to_register(client: TestClient, account: dict):
    text = client.get("/app/accounts").text
    assert f"/app/accounts/{account['aid']}/register" in text

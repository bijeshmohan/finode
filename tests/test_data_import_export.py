from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.repositories import AccountRepository, ProfileRepository, TransactionRepository
from app.services import AccountService, DataService
from app.services.data import ImportRejected


JOURNAL = """\
account Assets:Bank:HDFC
    note Salary account
2026-09-01 Opening
    Assets:Bank:HDFC        10000.00
    Equity:Opening Balances
2026-09-03 DMart
    ; weekly groceries
    Expenses:Food           1250.50
    Assets:Bank:HDFC
2026-09-30 Salary
    Assets:Bank:HDFC        5000.00
    Income:Salary
"""


def _import(client: TestClient, text: str, **params):
    return client.post("/api/import", files={"file": ("a.ledger", text.encode())}, params=params)


def _balances(client: TestClient) -> dict[str, str]:
    return {a["name"]: a["balance"] for a in client.get("/api/accounts/").json()}


def test_dry_run_reports_without_saving(client: TestClient):
    response = _import(client, JOURNAL, dry_run="true")
    assert response.status_code == 200
    body = response.json()
    assert body["errors"] == [] and body["transactions"] == 3
    assert body["date_from"] == "2026-09-01" and body["date_to"] == "2026-09-30"
    assert "Assets:Bank:HDFC" in body["new_accounts"]
    assert client.get("/api/transactions/").json() == []


def test_import_creates_accounts_and_transactions(client: TestClient):
    response = _import(client, JOURNAL)
    assert response.status_code == 200
    balances = _balances(client)
    assert balances["HDFC"] == "13749.50"
    assert balances["Food"] == "1250.50"
    assert balances["Salary"] == "5000.00"
    accounts = {a["name"]: a for a in client.get("/api/accounts/").json()}
    assert accounts["HDFC"]["details"] == "Salary account"
    transactions = client.get("/api/transactions/").json()
    assert len(transactions) == 3
    assert any(t["comment"] == "weekly groceries" and t["payee"] == "DMart" for t in transactions)


def test_import_maps_top_level_aliases_and_opening_balances(client: TestClient):
    text = "2026-01-01 x\n    asset:Cash  50\n    equity:opening balances\n"
    assert _import(client, text).status_code == 200
    equity = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Opening Balances")
    assert equity["balance"] == "50.00"


def test_import_rejected_when_transactions_exist(client: TestClient, account, expense_account):
    client.post("/api/transactions/", json={"postings": [
        {"account": expense_account["aid"], "side": "debit", "amount": "1.00"},
        {"account": account["aid"], "side": "credit", "amount": "1.00"},
    ]})
    response = _import(client, JOURNAL)
    assert response.status_code == 400
    assert "no transactions" in response.json()["detail"]["errors"][0]


def test_failed_import_saves_nothing(client: TestClient):
    bad = JOURNAL + "2026-10-01 oops\n    Expenses:Food  5\n    Assets:Bank:HDFC  -4\n"
    response = _import(client, bad)
    assert response.status_code == 400
    assert any("does not balance" in e for e in response.json()["detail"]["errors"])
    assert client.get("/api/transactions/").json() == []
    assert not [a for a in client.get("/api/accounts/").json() if a["parent_id"] and a["name"] == "HDFC"]


def test_unknown_top_level_account_rejected(client: TestClient):
    text = "2026-01-01 x\n    Savings:Pot  5\n    Assets:Cash\n"
    errors = _import(client, text).json()["detail"]["errors"]
    assert "must start with Assets" in errors[0]


def test_posting_to_asset_group_rejected_but_expense_group_allowed(client: TestClient):
    asset_group = "2026-01-01 x\n    Assets:Bank  5\n    Assets:Bank:HDFC  -5\n"
    assert "has sub-accounts" in _import(client, asset_group).json()["detail"]["errors"][0]
    expense_group = "2026-01-01 x\n    Expenses:Food  5\n    Expenses:Food:Dining  3\n    Assets:Cash  -8\n"
    assert _import(client, expense_group).status_code == 200


def test_long_payee_moves_to_note_and_zero_postings_skipped(client: TestClient):
    payee = "P" * 50
    text = f"2026-01-01 {payee}\n    Expenses:A  5\n    Assets:B  -5\n    Assets:C  0\n2026-01-02 nothing\n    Assets:B  0\n    Assets:C  0\n"
    body = _import(client, text, dry_run="true").json()
    assert body["errors"] == [] and body["transactions"] == 1 and body["skipped_empty"] == 1
    assert _import(client, text).status_code == 200
    [t] = client.get("/api/transactions/").json()
    assert t["payee"] == "P" * 40 and t["comment"] == payee


def test_empty_and_oversized_and_binary_files(client: TestClient):
    assert _import(client, "; nothing here\n", dry_run="true").json()["errors"] == ["The file has no transactions to import."]
    big = client.post("/api/import", files={"file": ("a", b"x" * (5 * 1024 * 1024 + 1))})
    assert big.status_code == 400 and "5 MB" in big.json()["detail"]
    bad = client.post("/api/import", files={"file": ("a", b"\xff\xfe\x00")})
    assert bad.status_code == 400 and "UTF-8" in bad.json()["detail"]


def test_export_formats_and_headers(client: TestClient):
    _import(client, JOURNAL)
    response = client.get("/api/export")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith('attachment; filename="finode-')
    assert response.headers["content-disposition"].endswith('.ledger"')
    text = response.text
    assert "account Assets:Bank:HDFC\n    note Salary account" in text
    assert "2026-09-03 DMart\n    ; weekly groceries\n" in text
    assert "Expenses:Food" in text and "-1250.50" in text

    csv_response = client.get("/api/export", params={"format": "csv"})
    assert csv_response.headers["content-disposition"].endswith('.csv"')
    lines = csv_response.content.decode("utf-8-sig").splitlines()
    assert lines[0] == "date,payee,note,account,debit,credit"
    assert "2026-09-03,DMart,weekly groceries,Expenses:Food,1250.50," in lines
    assert client.get("/api/export", params={"format": "xml"}).status_code == 422


def test_csv_neutralises_spreadsheet_formulas(client: TestClient):
    _import(client, "2026-01-01 =HYPERLINK(1)\n    Expenses:A  5\n    Assets:B\n")
    lines = client.get("/api/export", params={"format": "csv"}).text.splitlines()
    assert any(line.startswith("2026-01-01,'=HYPERLINK(1),") for line in lines)


def test_export_sanitises_colons_and_spaces_in_names(client: TestClient, root_accounts):
    client.post("/api/accounts/", json={"name": "Rent  Flat", "parent_id": root_accounts["Expenses"]})
    text = client.get("/api/export").text
    assert "account Expenses:Rent Flat" in text


def test_colon_in_account_name_rejected(client: TestClient, root_accounts):
    response = client.post("/api/accounts/", json={"name": "a:b", "parent_id": root_accounts["Assets"]})
    assert response.status_code == 422


def test_export_then_import_round_trips_for_another_user(client: TestClient, session: Session):
    _import(client, JOURNAL)
    client.post("/api/accounts/", json={"name": "Empty", "parent_id": next(
        a["aid"] for a in client.get("/api/accounts/").json() if a["name"] == "Assets")})
    exported = client.get("/api/export").text

    other = UUID("00000000-0000-4000-8000-000000000002")
    ar, tr, pr = AccountRepository(session, other), TransactionRepository(session, other), ProfileRepository(session, other)
    data = DataService(AccountService(ar, tr, pr), ar, tr, pr)
    summary = data.run_import(exported)
    assert summary.errors == [] and summary.transactions == 3
    assert data.export_ledger().split("\n", 1)[1] == exported.split("\n", 1)[1]
    with pytest.raises(ImportRejected):
        data.run_import(exported)  # no longer empty

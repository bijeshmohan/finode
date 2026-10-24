"""The toast after saving or deleting an entry carries Undo (and deleting asks nothing first)."""

from uuid import uuid4

from fastapi.testclient import TestClient

from .test_web_transactions import _post


def _cookie(response) -> str:
    return response.cookies.get("finode_flash", "")


def test_deleting_an_entry_offers_undo_that_brings_it_back(client: TestClient, account: dict, expense_account: dict):
    made = _post(client, expense_account, account, "5.00", "2026-01-01", "coffee")
    gone = client.post(
        f"/transactions/{made['tid']}/delete",
        headers={"HX-Current-URL": "http://testserver/transactions?month=2026-01"},
    )
    assert gone.headers["HX-Redirect"] == "/transactions?month=2026-01"
    flash = gone.headers["set-cookie"].split(";")[0].split("=", 1)[1]
    assert flash.startswith("transaction-deleted|restore|")

    client.cookies.set("finode_flash", flash)
    page = client.get("/transactions", params={"month": "2026-01"}).text
    hid = flash.rsplit("|", 1)[1]
    assert f'hx-post="/transactions/deleted/{hid}/restore"' in page and ">Undo<" in page

    back = client.post(
        f"/transactions/deleted/{hid}/restore",
        headers={"HX-Current-URL": "http://testserver/transactions?month=2026-01"},
    )
    assert back.headers["HX-Redirect"] == "/transactions?month=2026-01"
    assert client.get(f"/api/transactions/{made['tid']}").status_code == 200


def test_saving_an_entry_offers_undo_that_deletes_it(client: TestClient, account: dict, expense_account: dict):
    saved = client.post(
        "/transactions/split",
        data={
            "account": [expense_account["aid"], account["aid"]],
            "side": ["debit", "credit"],
            "amount": ["9.00", "9.00"],
            "date": "2026-01-02",
            "payee": "tea",
        },
    )
    flash = saved.headers["set-cookie"].split(";")[0].split("=", 1)[1]
    kind, tid = flash.split("|")[1:]
    assert kind == "delete"

    client.cookies.set("finode_flash", flash)
    assert f'hx-post="/transactions/{tid}/delete"' in client.get("/").text
    client.post(f"/transactions/{tid}/delete", headers={"HX-Current-URL": "http://testserver/"})
    assert client.get(f"/api/transactions/{tid}").status_code == 404


def test_a_tampered_cookie_never_renders_an_undo(client: TestClient):
    for value in (
        "transaction-deleted|restore|not-a-uuid",
        f"transaction-deleted|evil|{uuid4()}",
        f"nope|restore|{uuid4()}",
        "transaction-deleted|restore",
    ):
        client.cookies.set("finode_flash", value)
        page = client.get("/").text
        assert "toast-undo" not in page and 'hx-post="/transactions/deleted' not in page


def test_deleting_an_entry_asks_nothing_first(client: TestClient, account: dict, expense_account: dict):
    made = _post(client, expense_account, account, "5.00", "2026-01-01", "coffee")
    assert "hx-confirm" not in client.get(f"/transactions/{made['tid']}/edit").text

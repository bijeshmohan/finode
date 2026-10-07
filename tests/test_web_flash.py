import pytest
from fastapi.testclient import TestClient

from app.flash import FLASH_COOKIE, MESSAGES, set_flash


def test_saving_a_transaction_sets_a_flash(client: TestClient, account: dict, expense_account: dict):
    response = client.post(
        "/transactions",
        data={"amount": "1", "from_account": account["aid"], "to_account": expense_account["aid"]},
    )
    assert f"{FLASH_COOKIE}=transaction-saved" in response.headers["set-cookie"]


def test_flash_is_shown_once_on_the_next_page(client: TestClient):
    client.cookies.set(FLASH_COOKIE, "account-created", path="/")
    first = client.get("/accounts")
    assert '<div class="toast" role="status">Account added</div>' in first.text
    assert f'{FLASH_COOKIE}=""' in first.headers["set-cookie"] or "Max-Age=0" in first.headers["set-cookie"]

    client.cookies.delete(FLASH_COOKIE, path="/")
    assert 'class="toast"' not in client.get("/accounts").text


def test_htmx_fragments_do_not_consume_the_flash(client: TestClient, account: dict):
    client.cookies.set(FLASH_COOKIE, "account-created", path="/")
    fragment = client.get("/transactions/rows/new", headers={"HX-Request": "true"})
    assert "set-cookie" not in fragment.headers


def test_unknown_flash_keys_render_nothing(client: TestClient):
    client.cookies.set(FLASH_COOKIE, "<script>alert(1)</script>", path="/")
    page = client.get("/accounts").text
    assert 'class="toast"' not in page
    assert "alert(1)" not in page


def test_set_flash_only_accepts_known_messages():
    from fastapi import Response

    with pytest.raises(ValueError):
        set_flash(Response(), "anything")
    response = Response()
    set_flash(response, "account-deleted")
    assert "account-deleted" in response.headers["set-cookie"]
    assert set(MESSAGES) >= {"transaction-saved", "account-deleted"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [("delete-account", "account-deleted"), ("delete-transaction", "transaction-deleted")],
)
def test_deletes_set_flash(client: TestClient, account: dict, expense_account: dict, path, expected):
    if path == "delete-account":
        response = client.post(f"/accounts/{account['aid']}/delete")
    else:
        tx = client.post(
            "/api/transactions/",
            json={
                "postings": [
                    {"account": expense_account["aid"], "side": "debit", "amount": "1.00"},
                    {"account": account["aid"], "side": "credit", "amount": "1.00"},
                ]
            },
        ).json()
        response = client.post(f"/transactions/{tx['tid']}/delete")
    assert f"{FLASH_COOKIE}={expected}" in response.headers["set-cookie"]

"""Pinned accounts: a flag the person sets from an account's page; the Accounts page lists pinned accounts again in a
Pinned row at its top, and each stays in its own group row."""

import re

import pytest

from app.services import account as account_service

from .books import post_account
from .test_account_groups import in_group, make_group


@pytest.fixture(autouse=True)
def new_person(monkeypatch):
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)


def group(client, key):
    return next(a for a in client.get("/api/accounts/").json() if a["system_key"] == key)


def bank(client, name="HDFC"):
    return post_account(client, {"name": name, "parent_id": group(client, "assets.bank")["id"]}).json()


def pin(client, account, value=True):
    return client.patch(f"/api/accounts/{account['id']}", json={"pinned": value})


def test_an_account_is_pinned_and_unpinned(client):
    account = bank(client)
    assert account["pinned"] is False
    assert pin(client, account).json()["pinned"] is True
    assert client.get(f"/api/accounts/{account['id']}").json()["pinned"] is True
    assert pin(client, account, False).json()["pinned"] is False


def test_only_an_open_account_can_be_pinned_never_a_group_or_a_root(client, root_accounts):
    mine = make_group(client).json()
    inside = in_group(client, mine, "Wallet").json()
    assert pin(client, mine).status_code == 400
    assert pin(client, group(client, "assets.cash")).status_code == 400
    assert client.patch(f"/api/accounts/{root_accounts['Assets']}", json={"pinned": True}).status_code == 400
    assert pin(client, inside).status_code == 200
    assert client.patch(f"/api/accounts/{inside['id']}", json={"pinned": None}).status_code == 400
    assert client.post(f"/api/accounts/{inside['id']}/close").status_code == 200
    assert pin(client, inside, False).status_code == 200, "a pin can always come off"
    assert pin(client, inside).status_code == 400, "a closed account cannot be pinned"


def test_the_accounts_page_lists_pinned_ones_in_a_row_at_the_top_and_keeps_them_in_their_group(client):
    first, second = bank(client, "HDFC"), bank(client, "ICICI")
    assert "Pinned" not in client.get("/accounts").text.split("data-accounts", 1)[1].split("</h2>", 1)[0]
    assert ">Pinned<" not in client.get("/accounts").text
    pin(client, second)
    page = client.get("/accounts").text
    top, rest = page.split("<h2>Pinned</h2>", 1)[1].split("</section>", 1)
    assert "1 account<" in top and "ICICI" in top and "HDFC" not in top and "Add account" not in top
    assert "ICICI" in rest and "HDFC" in rest, "also in its own group's row"
    assert top.count("pin-mark") == 0 and rest.count("pin-mark") == 1, "the mark is on the copy in the group row"
    assert re.search(r'<h2><a href="[^"]+">Bank Accounts</a></h2>', rest)
    pin(client, first)
    heads = re.findall(r"<h2>(?:<a [^>]*>)?([^<]+)(?:</a>)?</h2>", client.get("/accounts").text)
    assert heads[0] == "Pinned"


def test_a_closed_account_leaves_the_pinned_row_and_comes_back_on_reopening(client):
    account = bank(client)
    pin(client, account)
    client.post(f"/api/accounts/{account['id']}/close")
    assert ">Pinned<" not in client.get("/accounts").text
    client.post(f"/api/accounts/{account['id']}/reopen")
    assert ">Pinned<" in client.get("/accounts").text


def test_the_account_page_menu_pins_and_unpins(client):
    account = bank(client)
    page = client.get(f"/accounts/{account['id']}").text
    assert f"/accounts/{account['id']}/pin" in page and "Pin to top" in page and "Unpin" not in page
    done = client.post(f"/accounts/{account['id']}/pin")
    assert done.headers["HX-Redirect"] == f"/accounts/{account['id']}"
    page = client.get(f"/accounts/{account['id']}").text
    assert "Unpin" in page and 'class="pin-mark"' in page and "Pin to top" not in page
    client.post(f"/accounts/{account['id']}/unpin")
    assert (
        client.get(f"/accounts/{account['id']}").json
        if False
        else "Pin to top" in client.get(f"/accounts/{account['id']}").text
    )


def test_a_group_or_a_closed_account_has_no_pin_item(client):
    mine = make_group(client).json()
    assert "Pin to top" not in client.get(f"/accounts/{mine['id']}").text
    account = bank(client)
    client.post(f"/api/accounts/{account['id']}/close")
    assert "Pin to top" not in client.get(f"/accounts/{account['id']}").text
    refused = client.post(f"/accounts/{mine['id']}/pin")
    assert refused.headers.get("HX-Retarget") == "#page-error"


def test_a_pinned_card_carries_the_mark_on_its_groups_page_too(client):
    account = bank(client)
    pin(client, account)
    page = client.get(f"/accounts/{group(client, 'assets.bank')['id']}").text
    assert page.count("pin-mark") == 1

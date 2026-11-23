"""Pinned accounts: a flag the person sets from an account's page; the Accounts page lists pinned accounts again in a
Pinned row at its top, and each stays in its own group row."""

from tests.books import post_account


def group(client, key):
    """Where an account of the type `key` goes: its root (there are no type accounts)."""
    root = "Liabilities" if key.startswith("liabilities") else "Assets"
    return next(a for a in client.get("/api/accounts/").json() if a["parent_id"] is None and a["name"] == root)


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
    inside = post_account(client, {"name": "Wallet", "parent_id": group(client, "assets.cash")["id"]}).json()
    assert pin(client, group(client, "assets.cash")).status_code == 400
    assert client.patch(f"/api/accounts/{root_accounts['Assets']}", json={"pinned": True}).status_code == 400
    assert pin(client, inside).status_code == 200
    assert client.patch(f"/api/accounts/{inside['id']}", json={"pinned": None}).status_code == 400
    assert client.post(f"/api/accounts/{inside['id']}/close").status_code == 200
    assert pin(client, inside, False).status_code == 200, "a pin can always come off"
    assert pin(client, inside).status_code == 400, "a closed account cannot be pinned"


def accounts_view(client) -> dict:
    return client.get("/api/views/accounts").json()


def card_of(view, name):
    return next(c for k in view["kinds"] for c in k["cards"] if c["name"] == name)


def test_the_accounts_page_lists_pinned_ones_at_the_top_and_keeps_them_in_their_group(client):
    first, second = bank(client, "HDFC"), bank(client, "ICICI")
    assert accounts_view(client)["pinned"] == []
    pin(client, second)
    seen = accounts_view(client)
    assert [c["name"] for c in seen["pinned"]] == ["ICICI"]
    assert card_of(seen, "ICICI")["pinned"] is True and card_of(seen, "HDFC")["pinned"] is False, "also in its group"
    pin(client, first)
    assert [c["name"] for c in accounts_view(client)["pinned"]] == ["HDFC", "ICICI"]


def test_a_closed_account_leaves_the_pinned_row_and_comes_back_on_reopening(client):
    account = bank(client)
    pin(client, account)
    client.post(f"/api/accounts/{account['id']}/close")
    assert accounts_view(client)["pinned"] == []
    client.post(f"/api/accounts/{account['id']}/reopen")
    assert [c["name"] for c in accounts_view(client)["pinned"]] == ["HDFC"]


def test_an_accounts_page_says_whether_it_is_pinned_and_can_be(client):
    account = bank(client)
    page = client.get(f"/api/views/accounts/{account['id']}").json()
    assert page["can_pin"] is True and page["pinned"] is False
    pin(client, account)
    assert client.get(f"/api/views/accounts/{account['id']}").json()["pinned"] is True


def test_a_group_or_a_closed_account_cannot_be_pinned(client):
    mine = group(client, "assets.wallet")
    assert client.get(f"/api/views/accounts/{mine['id']}").json()["can_pin"] is False
    assert pin(client, mine).status_code == 400
    account = bank(client)
    client.post(f"/api/accounts/{account['id']}/close")
    assert client.get(f"/api/views/accounts/{account['id']}").json()["can_pin"] is False


def test_a_pinned_card_is_marked_on_its_groups_page_too(client):
    account = bank(client)
    pin(client, account)
    cards = client.get(f"/api/views/accounts/{group(client, 'assets.bank')['id']}").json()["cards"]
    assert [c["pinned"] for c in cards if c["name"] == "HDFC"] == [True]

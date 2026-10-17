"""Placing accounts by hand, and the list of recently used ones."""

import re

import pytest

from .test_budget import budget


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))


@pytest.fixture
def books(client, root_accounts):
    def make(name, parent, **extra):
        response = client.post("/api/accounts/", json={"name": name, "parent_id": parent, **extra})
        assert response.status_code == 201, response.text
        return response.json()

    banks = make("Banks", root_accounts["Assets"])
    return {
        "banks": banks,
        "axis": make("Axis", banks["aid"], balance="100"),
        "hdfc": make("HDFC", banks["aid"], balance="100"),
        "sbi": make("SBI", banks["aid"], balance="100"),
        "wallet": make("Wallet", root_accounts["Assets"]),
        "cash": make("Cash", root_accounts["Assets"]),
        "gold": make("Gold", root_accounts["Assets"]),
        "rent": make("Rent", root_accounts["Expenses"]),
        "food": make("Food", root_accounts["Expenses"]),
        "travel": make("Travel", root_accounts["Expenses"]),
        "salary": make("Salary", root_accounts["Income"]),
        "roots": root_accounts,
    }


def move(client, account, direction):
    response = client.post(f"/api/accounts/{account['aid']}/move", params={"direction": direction})
    assert response.status_code == 200, response.text
    return response.json()


def spend(client, debit, credit, amount="10"):
    response = client.post(
        "/api/transactions/",
        json={"postings": [
            {"account": debit["aid"], "side": "debit", "amount": amount},
            {"account": credit["aid"], "side": "credit", "amount": amount},
        ]},
    )
    assert response.status_code == 201, response.text


# ---- pinning is gone ------------------------------------------------------------------------------------------------


def test_accounts_can_no_longer_be_pinned(client, books):
    aid = books["hdfc"]["aid"]
    assert "pinned" not in client.get(f"/api/accounts/{aid}").json()
    assert client.post(f"/api/accounts/{aid}/pin").status_code in (404, 405)
    assert client.post(f"/accounts/{aid}/pin").status_code in (404, 405)
    assert "Pinned" not in squash(client.get("/accounts").text) and "/pin" not in client.get(f"/accounts/{aid}").text


# ---- ordering ------------------------------------------------------------------------------------------------------


def names_in_budget(client):
    return [l["name"] for l in budget(client)["lines"]]


def test_siblings_start_alphabetical_and_move_by_one_place(client, books):
    spend(client, books["rent"], books["wallet"])  # categories with activity show in the budget
    spend(client, books["food"], books["wallet"])
    spend(client, books["travel"], books["wallet"])
    assert names_in_budget(client) == ["Food", "Rent", "Travel"]
    moved = move(client, books["travel"], "up")
    assert moved["position"] == 1
    assert names_in_budget(client) == ["Food", "Travel", "Rent"]
    move(client, books["travel"], "up")
    assert names_in_budget(client) == ["Travel", "Food", "Rent"]
    move(client, books["travel"], "up")  # already first: nothing happens
    assert names_in_budget(client) == ["Travel", "Food", "Rent"]
    move(client, books["travel"], "down")
    move(client, books["travel"], "down")
    move(client, books["travel"], "down")  # and last
    assert names_in_budget(client) == ["Food", "Rent", "Travel"]
    move(client, books["rent"], "down")
    assert names_in_budget(client) == ["Food", "Travel", "Rent"]


def test_the_accounts_page_and_pickers_follow_the_order(client, books):
    move(client, books["sbi"], "up")
    move(client, books["sbi"], "up")
    page = client.get("/accounts").text
    assert page.index(">SBI<") < page.index(">Axis<") < page.index(">HDFC<")
    form = client.get("/transactions/new").text
    assert form.index(">Banks › SBI<") < form.index(">Banks › Axis<") < form.index(">Banks › HDFC<")


def test_other_groups_are_not_touched_and_new_accounts_come_last(client, books):
    move(client, books["sbi"], "up")
    assert client.get(f"/api/accounts/{books['wallet']['aid']}").json()["position"] is None
    assert client.get(f"/api/accounts/{books['rent']['aid']}").json()["position"] is None
    added = client.post("/api/accounts/", json={"name": "AAA first alphabetically", "parent_id": books["banks"]["aid"]}).json()
    assert added["position"] is None
    page = client.get("/accounts").text
    assert page.index(">SBI<") < page.index(">AAA first alphabetically<")  # placed ones first


def test_moving_to_another_group_forgets_the_place(client, books):
    move(client, books["sbi"], "up")
    other = client.post("/api/accounts/", json={"name": "Cards", "parent_id": books["roots"]["Assets"]}).json()
    moved = client.patch(f"/api/accounts/{books['sbi']['aid']}", json={"parent_id": other["aid"]})
    assert moved.status_code == 200 and moved.json()["position"] is None


def test_back_to_alphabetical(client, books):
    move(client, books["sbi"], "up")
    move(client, books["sbi"], "up")
    reset = client.post(f"/api/accounts/{books['sbi']['aid']}/reset-order")
    assert reset.status_code == 200 and reset.json()["position"] is None
    assert all(client.get(f"/api/accounts/{books[n]['aid']}").json()["position"] is None for n in ("axis", "hdfc", "sbi"))
    page = client.get("/accounts").text
    assert page.index(">Axis<") < page.index(">HDFC<") < page.index(">SBI<")


def test_roots_and_the_system_account_cannot_be_placed(client, books):
    assert client.post(f"/api/accounts/{books['roots']['Assets']}/move").status_code == 400
    assert client.post(f"/api/accounts/{books['roots']['Assets']}/reset-order").status_code == 400
    assert client.post(f"/api/accounts/{books['hdfc']['aid']}/move", params={"direction": "sideways"}).status_code == 422


# ---- recently used -------------------------------------------------------------------------------------------------


def cards(page: str) -> list[str]:
    return re.findall(r'<span class="ca-name">(\w+)</span>', page)


def test_recently_used_accounts_are_cards_on_top(client, books):
    assert "Recently used" not in squash(client.get("/accounts").text)  # nothing recorded yet
    spend(client, books["cash"], books["hdfc"])
    spend(client, books["gold"], books["wallet"])
    spend(client, books["axis"], books["sbi"])
    text = client.get("/accounts").text
    assert text.index("Recently used") < text.index("acc-section"), "above the accounts"
    names = cards(text)
    # newest entry first (the two accounts of one entry are equally recent), each account once, five at most
    assert len(names) == 5 and len(set(names)) == 5
    assert set(names[:2]) == {"Axis", "SBI"} and set(names[2:4]) == {"Gold", "Wallet"}
    assert 'class="ca-cap">Banks<' in text, "each card says which group it is in"


def test_recent_leaves_out_closed_and_the_systems_accounts(client, books):
    spend(client, books["cash"], books["hdfc"])
    spend(client, books["gold"], books["wallet"], "5")
    spend(client, books["wallet"], books["gold"], "5")  # back to nothing in it, so it can be closed
    assert client.post(f"/api/accounts/{books['wallet']['aid']}/close").status_code == 200
    names = cards(client.get("/accounts").text)
    assert "Wallet" not in names and "Gold" in names and "Opening" not in " ".join(names)


def test_recent_ignores_what_recurring_rules_and_imports_made(client, books):
    rule = client.post("/api/recurring/", json={
        "from_account": books["wallet"]["aid"], "to_account": books["rent"]["aid"], "amount": "5",
        "frequency": "daily", "start_date": "2020-01-01"})
    assert rule.status_code == 201
    made = client.get("/api/transactions/").json()  # opening the list records what is due
    assert any(t["created_via"] == "recurring" for t in made)
    assert "Recently used" not in squash(client.get("/accounts").text)


def test_recent_shows_at_most_five(client, books, root_accounts):
    extra = [client.post("/api/accounts/", json={"name": f"Spare{i}", "parent_id": root_accounts["Assets"]}).json() for i in range(4)]
    for account in [books["cash"], books["gold"], books["axis"], *extra]:
        spend(client, account, books["wallet"], "1")
    assert len(cards(client.get("/accounts").text)) == 5


# ---- the web pages -------------------------------------------------------------------------------------------------


def test_the_order_controls_on_the_account_page(client, books):
    first = client.get(f"/accounts/{books['axis']['aid']}").text
    assert "Move down" in first and "Move up" not in first and "A–Z" not in first
    response = client.post(f"/accounts/{books['sbi']['aid']}/move", data={"direction": "up"})  # Axis, SBI, HDFC
    assert response.headers["HX-Redirect"] == f"/accounts/{books['sbi']['aid']}" and "account-moved" in response.headers["set-cookie"]
    page = client.get(f"/accounts/{books['sbi']['aid']}").text
    assert "Move down" in page and "Move up" in page and "A–Z" in page and "in the order you chose" in squash(page)
    assert "the budget lists categories the same way" not in squash(page)
    assert "the budget lists categories the same way" in squash(client.get(f"/accounts/{books['rent']['aid']}").text)
    reset = client.post(f"/accounts/{books['sbi']['aid']}/reset-order")
    assert "account-order-reset" in reset.headers["set-cookie"]
    assert "A–Z" not in client.get(f"/accounts/{books['sbi']['aid']}").text


def test_a_lone_account_has_nothing_to_move(client, books):
    page = client.get(f"/accounts/{books['salary']['aid']}").text
    assert "Move up" not in page and "Move down" not in page and "order-card" not in page


def test_errors_are_shown_in_place(client, books):
    assert client.post(f"/accounts/{books['roots']['Assets']}/move", data={"direction": "up"}).status_code in (400, 404)

"""Categories are one flat list: no groups, no group budgets, no group screens. Names are unique per kind."""

from tests.books import leg
from tests.budget.test_budget import assign, budget


def made(client, name, kind="spending", **extra):
    response = client.post("/api/categories/", json={"name": name, "kind": kind, "icon": "tag", **extra})
    assert response.status_code == 201, response.text
    return response.json()


def bank(client, balance="1000"):
    response = client.post("/api/accounts/", json={"name": "HDFC", "type": "assets.bank", "balance": balance})
    assert response.status_code == 201, response.text
    return response.json()


def spend(client, account, category, amount):
    body = {"postings": [leg(category, "debit", amount), leg(account, "credit", amount)]}
    assert client.post("/api/transactions/", json=body).status_code == 201


def test_a_category_has_no_parent(client):
    food = made(client, "Food")
    dairy = made(client, "Dairy", parent_id=food["id"])  # an old client's parent is not read
    assert "parent_id" not in dairy
    assert {c["name"] for c in client.get("/api/categories/").json()} >= {"Food", "Dairy"}


def test_names_are_unique_per_kind(client):
    made(client, "Rent")
    again = client.post("/api/categories/", json={"name": "rent", "kind": "spending", "icon": "tag"})
    assert again.status_code == 400
    made(client, "Rent", kind="earning")


def test_budget_is_one_ranked_list(client):
    bank(client)
    for name, amount in (("Small", "100"), ("Big", "300"), ("Middle", "200")):
        assign(client, made(client, name), amount)
    lines = budget(client)["lines"]
    assert [line["name"] for line in lines if line["name"] in ("Big", "Middle", "Small")] == ["Big", "Middle", "Small"]
    assert all("group" not in line and "depth" not in line for line in lines)


def test_group_routes_are_gone(client):
    food = made(client, "Food")
    assert client.get(f"/api/views/budget/groups/{food['id']}").status_code == 404
    assert client.put(f"/api/budget/groups/{food['id']}", json={"total": "10"}).status_code in (404, 405)


def test_close_and_reopen_touch_one_category(client):
    a, b = made(client, "A"), made(client, "B")
    assert client.post(f"/api/categories/{a['id']}/close").status_code == 200
    closed = {
        c["name"] for c in client.get("/api/categories/", params={"include_closed": True}).json() if c["closed_on"]
    }
    assert closed == {"A"}
    assert client.post(f"/api/categories/{a['id']}/reopen").status_code == 200
    assert b["id"] in {c["id"] for c in client.get("/api/categories/").json()}


def test_figures_are_the_categories_own(client):
    hdfc = bank(client)
    groceries, dairy = made(client, "Groceries"), made(client, "Dairy")
    assign(client, groceries, "300")
    assign(client, dairy, "100")
    spend(client, hdfc, groceries, "120")
    spend(client, hdfc, dairy, "40")
    data = budget(client)
    by_name = {line["name"]: line for line in data["lines"]}
    assert by_name["Groceries"]["available"] == "180.00" and by_name["Dairy"]["available"] == "60.00"
    assert data["ready_to_assign"] == "600.00", "1000 - 160 spent - 240 left in the two"

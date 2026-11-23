"""Every category has an icon from finode's fixed set (finode/category_icons.py): a new one must name it, the built-in
Uncategorised keeps its own, and merging keeps the icon of the category that stays."""

from tests.svc import services


def made(client, name, icon="tag", kind="spending"):
    response = client.post("/api/categories/", json={"name": name, "kind": kind, "icon": icon})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_with_icon(client):
    groceries = made(client, "Groceries", "shopping-cart")
    assert groceries["icon"] == "shopping-cart"
    listed = {c["name"]: c["icon"] for c in client.get("/api/categories/").json()}
    assert listed["Groceries"] == "shopping-cart"


def test_create_without_icon_is_422(client):
    response = client.post("/api/categories/", json={"name": "Groceries", "kind": "spending"})
    assert response.status_code == 422
    assert "icon" in response.text
    assert not [c for c in client.get("/api/categories/").json() if c["name"] == "Groceries"]


def test_unknown_or_system_icon_is_refused(client):
    for bad in ("rocket", "layers"):
        response = client.post("/api/categories/", json={"name": "Groceries", "kind": "spending", "icon": bad})
        assert response.status_code == 422
        assert f"'{bad}' is not one of finode's category icons" in response.text


def test_update_icon(client):
    food = made(client, "Food", "pizza")
    changed = client.patch(f"/api/categories/{food['id']}", json={"icon": "utensils"})
    assert changed.status_code == 200 and changed.json()["icon"] == "utensils"
    renamed = client.patch(f"/api/categories/{food['id']}", json={"name": "Eating out"})
    assert renamed.json()["icon"] == "utensils"
    bad = client.patch(f"/api/categories/{food['id']}", json={"icon": "rocket"})
    assert bad.status_code == 422


def test_uncategorised_keeps_its_icon(client, session):
    s = services(session)
    s.accounts.ensure_roots()
    uncategorised = s.categories.uncategorised("spending")
    assert uncategorised.icon == "circle-dashed"
    response = client.patch(f"/api/categories/{uncategorised.id}", json={"icon": "gift"})
    assert response.status_code == 400
    assert response.json()["detail"] == "the built-in Uncategorised keeps its icon"


def test_merge_keeps_the_survivors_icon(client):
    gifts = made(client, "Gifts", "gift")
    fees = made(client, "Fees", "receipt")
    response = client.post(f"/api/categories/{gifts['id']}/merge", json={"into": fees["id"]})
    assert response.status_code == 200, response.text
    assert client.get(f"/api/categories/{fees['id']}").json()["icon"] == "receipt"

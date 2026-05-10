from uuid import uuid4

from fastapi.testclient import TestClient


def test_create_category(client: TestClient):
    response = client.post(
        "/categories/",
        json={"type": "expense", "name": "groceries"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "expense"
    assert data["name"] == "groceries"
    assert "cid" in data


def test_create_category_invalid_type(client: TestClient):
    response = client.post(
        "/categories/",
        json={"type": "bogus", "name": "x"},
    )
    assert response.status_code == 422


def test_get_category(client: TestClient, expense_category: dict):
    response = client.get(f"/categories/{expense_category['cid']}")
    assert response.status_code == 200
    assert response.json()["cid"] == expense_category["cid"]


def test_get_category_not_found(client: TestClient):
    response = client.get(f"/categories/{uuid4()}")
    assert response.status_code == 404


def test_list_categories(
    client: TestClient,
    expense_category: dict,
    income_category: dict,
):
    response = client.get("/categories/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


def test_update_category(client: TestClient, expense_category: dict):
    response = client.patch(
        f"/categories/{expense_category['cid']}",
        json={"type": "expense", "name": "renamed"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "renamed"


def test_delete_category(client: TestClient, expense_category: dict):
    response = client.delete(f"/categories/{expense_category['cid']}")
    assert response.status_code == 204

    follow = client.get(f"/categories/{expense_category['cid']}")
    assert follow.status_code == 404

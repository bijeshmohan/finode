from fastapi.testclient import TestClient


def test_profile_is_created_empty_on_first_read(client: TestClient):
    response = client.get("/api/profile/")
    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] is None and body["last_name"] is None
    assert client.get("/api/profile/").json()["created"] == body["created"]


def test_update_profile_names(client: TestClient):
    response = client.patch("/api/profile/", json={"first_name": " Bijesh ", "last_name": "Mohan"})
    assert response.status_code == 200
    assert response.json()["first_name"] == "Bijesh"
    assert client.get("/api/profile/").json()["last_name"] == "Mohan"


def test_partial_update_keeps_other_fields(client: TestClient):
    client.patch("/api/profile/", json={"first_name": "A", "last_name": "B"})
    body = client.patch("/api/profile/", json={"last_name": "C"}).json()
    assert body["first_name"] == "A" and body["last_name"] == "C"


def test_blank_name_clears_it(client: TestClient):
    client.patch("/api/profile/", json={"first_name": "A"})
    assert client.patch("/api/profile/", json={"first_name": "   "}).json()["first_name"] is None


def test_name_too_long_is_rejected(client: TestClient):
    assert client.patch("/api/profile/", json={"first_name": "x" * 41}).status_code == 422

from fastapi.testclient import TestClient


def test_profile_page_shows_form_and_email(client: TestClient):
    response = client.get("/app/profile")
    assert response.status_code == 200
    assert 'name="first_name"' in response.text and 'name="last_name"' in response.text
    assert "test@example.com" in response.text


def test_profile_page_shows_saved_names(client: TestClient):
    client.patch("/profile/", json={"first_name": "Bijesh", "last_name": "Mohan"})
    text = client.get("/app/profile").text
    assert 'value="Bijesh"' in text and 'value="Mohan"' in text


def test_saving_profile_redirects_with_flash(client: TestClient):
    response = client.post("/app/profile", data={"first_name": "Bijesh", "last_name": ""})
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/app/profile"
    profile = client.get("/profile/").json()
    assert profile["first_name"] == "Bijesh" and profile["last_name"] is None


def test_saving_too_long_name_reports_error(client: TestClient):
    response = client.post("/app/profile", data={"first_name": "x" * 41})
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"


def test_navigation_links_to_profile(client: TestClient):
    text = client.get("/app/").text
    assert text.count('href="/app/profile"') == 2  # top bar and tab bar

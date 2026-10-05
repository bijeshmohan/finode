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




def test_top_bar_has_profile_link_and_no_sign_out(client: TestClient):
    text = client.get("/app/").text
    assert text.count('href="/app/profile"') == 1
    assert "/app/logout" not in text


def test_tab_bar_has_only_three_tabs(client: TestClient):
    text = client.get("/app/").text
    tabbar = text[text.index('<nav class="tabbar"'):]
    tabbar = tabbar[: tabbar.index("</nav>")]
    assert tabbar.count("<a ") == 3 and "/app/profile" not in tabbar


def test_profile_page_has_sign_out(client: TestClient):
    text = client.get("/app/profile").text
    assert 'action="/app/logout"' in text and "Sign out" in text
    assert "Signed in as test@example.com" in text

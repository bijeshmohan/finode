from fastapi.testclient import TestClient


def test_profile_page_shows_form_and_email(client: TestClient):
    response = client.get("/profile")
    assert response.status_code == 200
    assert 'name="first_name"' in response.text and 'name="last_name"' in response.text
    assert "test@example.com" in response.text


def test_profile_page_shows_saved_names(client: TestClient):
    client.patch("/api/profile/", json={"first_name": "Bijesh", "last_name": "Mohan"})
    text = client.get("/profile").text
    assert 'value="Bijesh"' in text and 'value="Mohan"' in text


def test_saving_profile_redirects_with_flash(client: TestClient):
    response = client.post("/profile", data={"first_name": "Bijesh", "last_name": ""})
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/profile"
    profile = client.get("/api/profile/").json()
    assert profile["first_name"] == "Bijesh" and profile["last_name"] is None


def test_saving_too_long_name_reports_error(client: TestClient):
    response = client.post("/profile", data={"first_name": "x" * 41})
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"




def test_top_bar_has_profile_link_and_no_sign_out(client: TestClient):
    text = client.get("/").text
    assert text.count('href="/profile"') == 1
    assert "/logout" not in text


def test_tab_bar_has_five_tabs(client: TestClient):
    text = client.get("/").text
    tabbar = text[text.index('<nav class="tabbar"'):]
    tabbar = tabbar[: tabbar.index("</nav>")]
    assert tabbar.count("<a ") == 5 and "Budget" in tabbar and "Settings" in tabbar and "/profile" not in tabbar


def test_profile_page_has_sign_out(client: TestClient):
    text = client.get("/profile").text
    assert 'action="/logout"' in text and "Sign out" in text
    assert text.count("test@example.com") >= 1 and "Signed in as" not in text


def test_header_shows_initials_and_name(client: TestClient):
    client.patch("/api/profile/", json={"first_name": "Bijesh", "last_name": "Mohan"})
    text = client.get("/profile").text
    assert '<span class="avatar" aria-hidden="true">BM</span>' in text and "<h1>Bijesh Mohan</h1>" in text


def test_header_falls_back_to_email_initial(client: TestClient):
    text = client.get("/profile").text
    assert '>T</span>' in text and "Your profile" in text


def test_sections_are_collapsible_and_summarise_values(client: TestClient):
    assert '<details id="name" class="setting">' in client.get("/profile").text
    text = client.get("/settings").text
    for section in ("currency", "depth", "appearance"):
        assert f'<details id="{section}" class="setting">' in text
    assert "Default currency</span><span class=\"setting-value\">INR" in text


def test_theme_cookie_sets_data_theme(client: TestClient):
    assert "data-theme" not in client.get("/profile").text.split("<head>")[0]
    client.cookies.set("finode_theme", "dark")
    assert '<html lang="en" data-theme="dark">' in client.get("/profile").text
    client.cookies.set("finode_theme", "<script>")
    assert "data-theme" not in client.get("/profile").text.split("<head>")[0]


def test_settings_page_holds_application_settings_not_profile(client: TestClient):
    settings = client.get("/settings").text
    for title in ("Default currency", "Account depth", "Appearance", "Recurring transactions", "Assets &amp; prices"):
        assert title in settings, title
    assert "First name" not in settings and "MCP tokens" not in settings
    profile = client.get("/profile").text
    for title in ("Default currency", "Account depth", "Appearance"):
        assert title not in profile, title
    assert "AI assistants" in profile and "Your data" in profile and "First name" in profile


def test_gear_icon_only_in_the_tab_bar(client: TestClient):
    text = client.get("/").text
    assert text.count('href="/settings"') == 2, "desktop text link and phone tab"
    top = text[: text.index("</header>")]
    assert "<circle cx=\"12\" cy=\"12\" r=\"3\"/>" not in top, "no gear icon beside the profile icon"
    assert 'aria-current="page"' in client.get("/settings").text.split('href="/settings"')[1][:80]


def test_old_profile_setting_routes_are_gone(client: TestClient):
    assert client.post("/profile/currency", data={"currency": "USD"}).status_code in (404, 405)


def test_each_settings_entry_appears_once(client: TestClient):
    text = client.get("/settings").text
    for ident in ("name", "currency", "depth", "appearance", "recurring", "assets"):
        assert text.count(f'id="{ident}"') <= 1, ident
    assert text.count("Recurring transactions</span>") == 1 and text.count("Assets &amp; prices</span>") == 1

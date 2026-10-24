from fastapi.testclient import TestClient


def test_settings_page_shows_the_name_form_and_email(client: TestClient):
    response = client.get("/settings")
    assert response.status_code == 200
    assert 'name="first_name"' in response.text and 'name="last_name"' in response.text
    assert "test@example.com" in response.text


def test_settings_page_shows_saved_names(client: TestClient):
    client.patch("/api/profile/", json={"first_name": "Bijesh", "last_name": "Mohan"})
    text = client.get("/settings").text
    assert 'value="Bijesh"' in text and 'value="Mohan"' in text


def test_saving_profile_redirects_with_flash(client: TestClient):
    response = client.post("/profile", data={"first_name": "Bijesh", "last_name": ""})
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/settings"
    profile = client.get("/api/profile/").json()
    assert profile["first_name"] == "Bijesh" and profile["last_name"] is None


def test_saving_too_long_name_reports_error(client: TestClient):
    response = client.post("/profile", data={"first_name": "x" * 41})
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"




def test_top_bar_leads_to_settings_and_has_no_sign_out(client: TestClient):
    text = client.get("/").text
    assert 'class="icon-button avatar-link" href="/settings"' in text
    assert 'href="/profile"' not in text
    assert "/logout" not in text
    assert 'href="/profile"' not in client.get("/settings").text, "there is one page now: the name is edited on Settings"


def test_tab_bar_has_four_tabs_and_the_docked_plus(client: TestClient):
    text = client.get("/").text
    tabbar = text[text.index('<nav class="tabbar'):]
    tabbar = tabbar[: tabbar.index("</nav>")]
    assert tabbar.count("<a ") == 5 and tabbar.count('class="fab"') == 1, "four tabs and the docked +"
    assert all(name in tabbar for name in ("Home", "Budgets", "Accounts", "Categories"))
    assert "Transactions" not in tabbar and "Settings" not in tabbar and "/profile" not in tabbar
    assert "search-link" not in text and "focus=search" not in text, "no search icon in the top bar"
    assert 'href="/transactions"' in text, "Transactions is reached from the sidebar on wide screens (and 'View all' on Home once there is something)"


def test_settings_page_has_sign_out(client: TestClient):
    text = client.get("/settings").text
    assert 'action="/logout"' in text and "Sign out" in text
    assert text.count("test@example.com") >= 1 and "Signed in as" not in text


def test_the_profile_row_shows_the_name(client: TestClient):
    client.patch("/api/profile/", json={"first_name": "Bijesh", "last_name": "Mohan"})
    text = client.get("/settings").text
    assert '<span class="setting-title">Bijesh Mohan</span>' in text


def test_the_profile_row_falls_back_to_a_plain_label(client: TestClient):
    text = client.get("/settings").text
    assert "Your profile" in text


def test_sections_are_collapsible_and_summarise_values(client: TestClient):
    text = client.get("/settings").text
    for section in ("name", "currency", "appearance"):
        assert f'<details id="{section}" class="setting">' in text
    assert "Currency</span><span class=\"setting-value\">INR" in text


def test_theme_cookie_sets_data_theme(client: TestClient):
    assert "data-theme" not in client.get("/settings").text.split("<head>")[0]
    client.cookies.set("finode_theme", "dark")
    assert '<html lang="en" data-grouping="indian" data-places="2" data-theme="dark">' in client.get("/settings").text
    client.cookies.set("finode_theme", "<script>")
    assert "data-theme" not in client.get("/settings").text.split("<head>")[0]


def test_settings_page_holds_application_settings_not_profile(client: TestClient):
    settings = client.get("/settings").text
    for title in ("Currency", "Appearance", "Recurring transactions", "AI assistants"):
        assert title in settings, title
    assert "Advanced" not in settings, "the Advanced switch is gone"
    assert "MCP tokens" not in settings
    assert "First name" in settings and "Sign out" in settings, "the name and sign-out are on this page too"


def test_settings_is_reached_from_the_avatar_and_the_sidebar(client: TestClient):
    text = client.get("/").text
    assert text.count('href="/settings"') == 2, "the avatar on phones and the sidebar link on wide screens"
    top = text[: text.index("</header>")]
    assert "<circle cx=\"12\" cy=\"12\" r=\"3\"/>" not in top, "no gear icon in the top bar"
    assert 'aria-current="page"' in client.get("/settings").text.split('href="/settings"')[1][:80]


def test_old_profile_setting_routes_are_gone(client: TestClient):
    assert client.post("/profile/currency", data={"currency": "USD"}).status_code in (404, 405)


def test_each_settings_entry_appears_once(client: TestClient):
    text = client.get("/settings").text
    for ident in ("currency", "appearance", "recurring", "lock", "assistants"):
        assert text.count(f'id="{ident}"') <= 1, ident
    assert text.count("Recurring transactions</span>") == 1

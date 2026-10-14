from fastapi.testclient import TestClient


def test_app_shell_has_desktop_nav_mobile_tabbar_and_new_button(client: TestClient):
    page = client.get("/").text
    assert 'class="topnav"' in page
    assert 'class="tabbar"' in page
    assert 'class="fab" href="/transactions/new"' in page
    assert 'aria-current="page">Dashboard' in page
    assert 'rel="icon" href="/static/favicon.svg?v=' in page
    assert "viewport-fit=cover" in page


def test_current_section_is_marked_in_nav(client: TestClient):
    page = client.get("/accounts").text
    assert 'href="/accounts" aria-current="page"' in page
    assert 'href="/" aria-current="page"' not in page


def test_new_transaction_shortcuts_hidden_on_transaction_form(client: TestClient):
    page = client.get("/transactions/new").text
    assert 'class="fab"' not in page
    assert "topbar-new" not in page


def test_login_page_has_no_app_chrome(client: TestClient):
    page = client.get("/login").text
    assert 'class="tabbar"' not in page
    assert 'class="topbar"' not in page


def test_favicon_is_served(client: TestClient):
    response = client.get("/static/favicon.svg")
    assert response.status_code == 200
    assert response.text.startswith("<svg")

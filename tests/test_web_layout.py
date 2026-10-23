from fastapi.testclient import TestClient


def test_app_shell_has_desktop_sidebar_mobile_tabbar_and_new_button(client: TestClient):
    page = client.get("/accounts").text
    assert 'class="sidebar"' in page
    assert 'class="tabbar has-plus"' in page
    assert 'class="fab" href="/transactions/new"' in page
    assert 'class="button secondary sidebar-new" href="/transactions/new"' in page
    assert 'href="/accounts" aria-current="page"' in page


def test_home_has_the_docked_plus_and_no_chat_style_bar(client: TestClient):
    page = client.get("/").text
    assert 'class="fab" href="/transactions/new"' in page and "composer" not in page
    assert 'href="/" aria-current="page"' in page
    assert 'class="button secondary sidebar-new"' in page, "wide screens also have the sidebar's button"
    assert 'rel="icon" href="/static/favicon.svg?v=' in page
    assert "viewport-fit=cover" in page


def test_current_section_is_marked_in_nav(client: TestClient):
    page = client.get("/accounts").text
    assert 'href="/accounts" aria-current="page"' in page
    assert 'href="/" aria-current="page"' not in page


def test_new_transaction_shortcuts_hidden_on_transaction_form(client: TestClient):
    page = client.get("/transactions/new").text
    assert 'class="fab"' not in page
    assert "sidebar-new" not in page


def test_login_page_has_no_app_chrome(client: TestClient):
    page = client.get("/login").text
    assert 'class="tabbar"' not in page
    assert 'class="topbar"' not in page
    assert 'class="sidebar"' not in page


def test_favicon_is_served(client: TestClient):
    response = client.get("/static/favicon.svg")
    assert response.status_code == 200
    assert response.text.startswith("<svg")


def test_dark_theme_defines_the_same_tokens_in_both_dark_blocks():
    """The automatic dark block and the manual `data-theme=dark` block must stay in step."""
    from pathlib import Path

    css = (Path(__file__).parent.parent / "app" / "static" / "style.css").read_text()
    auto = css[css.index("@media (prefers-color-scheme: dark)"):css.index(':root[data-theme="dark"]')]
    manual = css[css.index(':root[data-theme="dark"]'):css.index("/* ---------- Base")]
    names = lambda block: {line.split(":")[0].strip() for line in block.splitlines() if line.strip().startswith("--")}
    assert names(auto) == names(manual) and "--field-border" in names(auto)


def test_the_logo_follows_the_ink_palette_in_light_and_dark(client: TestClient):
    svg = client.get("/static/favicon.svg").text
    assert "#2563eb" not in svg and "prefers-color-scheme:dark" in svg


def test_every_page_has_the_banner_and_the_loading_bar_but_the_banner_starts_hidden(client: TestClient):
    page = client.get("/").text
    assert '<div id="net-banner" class="net-banner" role="status" aria-live="polite" hidden></div>' in page
    assert 'class="loadbar"' in page


def test_the_sidebar_lists_home_plan_accounts_categories_then_transactions(client: TestClient):
    page = client.get("/accounts").text
    side = page[page.index('class="sidenav"'):page.index("sidebar-foot")]
    order = [side.index(f'href="{path}"') for path in ("/", "/budget", "/accounts", "/categories", "/transactions")]
    assert order == sorted(order), "Home, Budgets, Accounts, Categories, Transactions"
    bar = page[page.index('class="tabbar'):page.index("</nav>", page.index('class="tabbar'))]
    assert 'href="/transactions"' not in bar, "phones keep their four tabs (and the docked +)"

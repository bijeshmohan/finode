from fastapi.testclient import TestClient


def test_app_shell_has_desktop_sidebar_mobile_tabbar_and_new_button(client: TestClient):
    page = client.get("/accounts").text
    assert 'class="sidebar"' in page
    assert 'class="tabbar"' in page
    assert 'class="fab" href="/transactions/new"' in page
    assert 'class="button secondary sidebar-new" href="/transactions/new"' in page
    assert 'href="/accounts" aria-current="page"' in page


def test_home_has_the_normal_floating_button_and_no_chat_style_bar(client: TestClient):
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


def test_the_chart_colours_never_look_like_the_money_colours():
    """Green and red mean money in and out in finode; the share bar's categories must not borrow them."""
    import colorsys
    import re
    from pathlib import Path

    css = (Path(__file__).parent.parent / "app" / "static" / "style.css").read_text()
    light = css[:css.index("@media (prefers-color-scheme: dark)")]
    auto = css[css.index("@media (prefers-color-scheme: dark)"):css.index(':root[data-theme="dark"]')]
    manual = css[css.index(':root[data-theme="dark"]'):css.index("/* ---------- Base")]
    for theme, block in (("light", light), ("auto dark", auto), ("manual dark", manual)):
        colours = re.findall(r"--chart-(\d): #([0-9a-fA-F]{6});", block)
        assert [n for n, _ in colours] == ["1", "2", "3", "4", "5", "6"], f"{theme} defines all six chart colours"
        for n, hex_ in colours:
            r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (0, 2, 4))
            hue, _, saturation = colorsys.rgb_to_hls(r, g, b)
            hue *= 360
            if saturation < 0.2:
                continue  # a grey is neither
            assert not 75 <= hue <= 170, f"{theme} --chart-{n} #{hex_} is green, the colour of money coming in"
            assert not (hue <= 15 or hue >= 345), f"{theme} --chart-{n} #{hex_} is red, the colour of money going out"
    assert re.findall(r"--chart-\d: #([0-9a-fA-F]{6});", auto) == re.findall(r"--chart-\d: #([0-9a-fA-F]{6});", manual)

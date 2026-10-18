from fastapi.testclient import TestClient


def test_the_site_root_is_the_web_app(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200 and "text/html" in response.headers["content-type"]


def test_the_old_app_prefix_is_gone(client: TestClient):
    """The web UI left /app long ago; the redirects that kept old links alive were removed once nothing pointed there."""
    for old in ("/app", "/app/", "/app/accounts", "/app/oauth/consent?authorization_id=x"):
        assert client.get(old, follow_redirects=False).status_code == 404, old


def test_the_json_api_moved_to_api(client: TestClient):
    assert client.get("/api/accounts/").status_code == 200


def test_settings_ignore_unrelated_dotenv_keys(tmp_path):
    from app.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text("FINODE_DATABASE_ECHO=false\nAPP_DOMAIN=finode.example.com\n")
    settings = Settings(_env_file=env_file)
    assert settings.database_echo is False


def test_pages_and_styles_are_compressed_but_fonts_are_not(client):
    page = client.get("/login", headers={"Accept-Encoding": "gzip"})
    assert page.headers.get("content-encoding") == "gzip" and page.status_code == 200 and "<form" in page.text
    plain = client.get("/login", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers and plain.text == page.text

    css = client.get("/static/style.css", headers={"Accept-Encoding": "gzip"})
    assert css.headers.get("content-encoding") == "gzip" and css.num_bytes_downloaded < len(css.content) // 3

    font = client.get("/static/fonts/figtree-rupee.woff2", headers={"Accept-Encoding": "gzip"})
    assert font.status_code == 200 and "content-encoding" not in font.headers

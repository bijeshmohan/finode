import re

from fastapi.testclient import TestClient

from app.templating import asset_url


def test_asset_urls_are_fingerprinted(client: TestClient):
    page = client.get("/").text
    for name in ("style.css", "app.js", "htmx.min.js", "favicon.svg", "apple-touch-icon.png"):
        assert re.search(rf'/static/{re.escape(name)}\?v=[0-9a-f]{{12}}"', page), name
    assert asset_url("style.css") == asset_url("style.css")


def test_fingerprinted_assets_are_cached_for_a_year(client: TestClient):
    response = client.get(asset_url("style.css"))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_unversioned_assets_must_revalidate(client: TestClient):
    assert client.get("/static/style.css").headers["cache-control"] == "no-cache"


def test_app_pages_are_private_and_revalidated(client: TestClient):
    assert client.get("/").headers["cache-control"] == "private, no-cache"
    assert client.get("/login").headers["cache-control"] == "private, no-cache"


def test_json_api_cache_headers_are_unchanged(client: TestClient):
    assert "cache-control" not in client.get("/api/accounts/").headers


def test_home_screen_metadata(client: TestClient):
    page = client.get("/").text
    assert 'rel="apple-touch-icon"' in page
    assert 'rel="manifest"' in page
    manifest = client.get("/static/manifest.webmanifest")
    assert manifest.status_code == 200
    assert '"start_url": "/"' in manifest.text
    icon = client.get("/static/apple-touch-icon.png")
    assert icon.status_code == 200
    assert icon.content[:8] == b"\x89PNG\r\n\x1a\n"

"""The API answers only its own addresses: /api, /mcp, /.well-known and (when switched on) the docs. Every other path on
the address is the finode app's, served by the web container (compose.yaml routes them; step 10)."""

import re
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.routing import Mount, Route

from app.main import app

OWN = ("/api/", "/mcp", "/.well-known/", "/docs", "/redoc", "/openapi.json")


def test_every_route_is_under_the_apis_own_addresses():
    paths = [r.path for r in app.routes if isinstance(r, (Route, Mount))]
    strays = [p for p in paths if p != "/api" and not p.startswith(OWN)]
    assert strays == [], strays


def test_an_address_of_the_app_is_not_the_apis(client):
    for path in ("/", "/login", "/accounts", "/reset?token_hash=x", "/oauth/consent?authorization_id=a"):
        assert client.get(path, follow_redirects=False).status_code == 404, path


def test_the_images_health_check_asks_for_an_address_the_api_answers():
    """Docker marks the container unhealthy when its health check fails, and Traefik routes nothing to an unhealthy
    container: the address it asks for must answer 200 without signing in (the site root is the app's, not the API's)."""
    dockerfile = (Path(__file__).parent.parent / "Dockerfile").read_text()
    found = re.search(r"HEALTHCHECK[^\n]*\n[^\n]*urlopen\('http://127\.0\.0\.1:8000(/[^']*)'", dockerfile)
    assert found, "the Dockerfile's health check asks no address"
    with TestClient(app) as anyone:  # no sign-in, as Docker asks
        assert anyone.get(found.group(1)).status_code == 200, found.group(1)

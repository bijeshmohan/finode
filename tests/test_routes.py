"""The API answers only its own addresses: /api, /mcp, /.well-known and (when switched on) the docs. Every other path on
the address is the finode app's, served by the web container (compose.yaml routes them; step 10)."""

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

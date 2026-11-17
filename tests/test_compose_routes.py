"""Traefik's two routers on one address (compose.yaml, step 10): the API's own paths go to the app container and every
other path to the web container, so the app and the API share an origin."""

import re
from pathlib import Path

import yaml

COMPOSE = yaml.safe_load((Path(__file__).parent.parent / "compose.yaml").read_text())


def labels(service: str) -> dict:
    return COMPOSE["services"][service]["labels"]


def matches(rule: str, path: str) -> bool:
    """Whether a path matches the PathPrefix/Path parts of a Traefik rule (the Host part is the same for both)."""
    prefixes = re.findall(r"PathPrefix\(`([^`]+)`\)", rule)
    exact = re.findall(r"Path\(`([^`]+)`\)", rule)
    return path in exact or any(path.startswith(p) for p in prefixes)


def test_the_apis_router_takes_only_its_own_paths():
    rule = labels("app")["traefik.http.routers.finode.rule"]
    assert rule.startswith("Host(`${APP_DOMAIN")
    for path in (
        "/api",
        "/api/accounts/",
        "/mcp",
        "/mcp/",
        "/.well-known/oauth-protected-resource/mcp",
        "/docs",
        "/redoc",
        "/openapi.json",
    ):
        assert matches(rule, path), path
    for path in ("/", "/accounts", "/login", "/apiary", "/mcpx", "/reset", "/oauth/consent", "/assets/x.js"):
        assert not matches(rule, path), path
    assert int(labels("app")["traefik.http.routers.finode.priority"]) > int(
        labels("web")["traefik.http.routers.finode-web.priority"]
    )


def test_the_web_router_takes_the_rest_of_the_same_address():
    assert labels("web")["traefik.http.routers.finode-web.rule"] == "Host(`${APP_DOMAIN:?set APP_DOMAIN in .env}`)"
    web = COMPOSE["services"]["web"]
    assert "VITE_API_URL" not in str(web.get("build", {})), "the app calls /api on its own address"
    assert "WEB_DOMAIN" not in (Path(__file__).parent.parent / "compose.yaml").read_text()


def test_the_browser_tests_server_splits_the_paths_as_traefik_does():
    from .browser.spa import API_PATHS, API_PREFIXES

    rule = labels("app")["traefik.http.routers.finode.rule"]
    for path in (*API_PATHS, *(p + "x" for p in API_PREFIXES), "/", "/accounts", "/apiary", "/mcpx", "/assets/x.js"):
        test_server = path in API_PATHS or path.startswith(API_PREFIXES)
        assert test_server == matches(rule, path), path


def test_the_service_worker_leaves_every_api_path_to_the_network():
    """The installed app's service worker answers a page load with the app, except on the paths it is told to leave
    alone: those must be every path Traefik sends to the API, or /docs or /mcp in a browser would open the app."""
    config = (Path(__file__).parent.parent / "frontend" / "vite.config.ts").read_text()
    listed = re.search(r"navigateFallbackDenylist: \[([^\]]*)\]", config)
    assert listed, "vite.config.ts names no navigateFallbackDenylist"
    denied = [re.compile(p) for p in re.findall(r"/(\^[^,]*?)/(?=,|\s*$)", listed.group(1).strip())]
    rule = labels("app")["traefik.http.routers.finode.rule"]
    paths = re.findall(r"Path(?:Prefix)?\(`([^`]+)`\)", rule)
    for path in paths + [p + "x" for p in re.findall(r"PathPrefix\(`([^`]+)`\)", rule)]:
        assert any(d.search(path) for d in denied), f"{path} would be answered by the app's page"
    for path in ("/", "/accounts", "/apiary", "/mcpx", "/docsy", "/reset"):
        assert not any(d.search(path) for d in denied), path

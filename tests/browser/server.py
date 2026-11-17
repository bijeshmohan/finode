"""The app for the browser tests: the built app (frontend/dist) and the API on one address, as in production, where
Traefik sends the API's paths to the API and everything else to the web container (compose.yaml)."""

from pathlib import Path

from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from app.main import app as api

# The same paths as the app's router rule in compose.yaml (tests/test_compose_routes.py holds the two together).
API_PATHS = {"/api", "/mcp", "/docs", "/redoc", "/openapi.json"}
API_PREFIXES = ("/api/", "/mcp/", "/.well-known/")
DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def app_and_api(dist: Path = DIST) -> ASGIApp:
    """The API's paths go to the API (as Traefik sends them); any other path is a file of the build, or index.html (the
    app routes it itself)."""
    index = dist / "index.html"
    if not index.is_file():
        raise RuntimeError("build the app first: npm --prefix frontend run build")
    files = StaticFiles(directory=dist)

    async def serve(scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or (path in API_PATHS or path.startswith(API_PREFIXES)):
            await api(scope, receive, send)
            return
        if path != "/" and (dist / path.lstrip("/")).is_file():
            await files(scope, receive, send)
            return
        await FileResponse(index)(scope, receive, send)

    return serve

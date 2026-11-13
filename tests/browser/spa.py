"""The React app for the browser tests: the built app (frontend/dist) and the API on one address, as a person's browser
sees them in production (app.<domain> and api.<domain> are one site). Test-only: production serves them apart."""

from pathlib import Path

from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from app.main import app as api

DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def spa_app(dist: Path = DIST) -> ASGIApp:
    """/api/... goes to the API; any other path is a file of the build, or index.html (the app routes it itself)."""
    index = dist / "index.html"
    if not index.is_file():
        raise RuntimeError("build the app first: npm --prefix frontend run build")
    files = StaticFiles(directory=dist)

    async def serve(scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or path.startswith("/api/"):
            await api(scope, receive, send)
            return
        if path != "/" and (dist / path.lstrip("/")).is_file():
            await files(scope, receive, send)
            return
        await FileResponse(index)(scope, receive, send)

    return serve

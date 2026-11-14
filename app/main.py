"""Wires the application: routers, middleware and the background work run in the lifespan (see docs/architecture/overview.md)."""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

from . import recurring_runner
from .caching import Compression, cache_headers_middleware
from .config import settings
from .flash import clear_shown_flash_middleware
from .mcp_server import transport as mcp_transport
from .routers import (
    accounts,
    assistants,
    auth,
    budget,
    categories,
    contacts,
    data,
    profile,
    recurring,
    reports,
    settlements,
    shared_expenses,
    shared_incomes,
    tags,
    todo,
    transactions,
    transfers,
    views,
    web,
)
from .templating import BASE_DIR
from .web_auth import LoginRequired, login_required_handler, refreshed_cookies_middleware


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp_transport.lifespan(), recurring_runner.lifespan():
        yield


app = FastAPI(
    title="finode",
    lifespan=lifespan,
    docs_url="/docs" if settings.api_docs else None,
    redoc_url="/redoc" if settings.api_docs else None,
    openapi_url="/openapi.json" if settings.api_docs else None,
)
# The MCP server for AI assistants (personal access tokens; see app/mcp_server).
app.router.routes.append(Route("/mcp", endpoint=mcp_transport.MCPEndpoint(), methods=["GET", "POST", "DELETE"]))


@app.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
@app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
def protected_resource(request: Request):
    return mcp_transport.protected_resource_metadata(request.scope)


# The JSON API lives under /api; the web UI owns the site root.
for api_router in (
    auth,
    accounts,
    categories,
    contacts,
    transfers,
    shared_expenses,
    shared_incomes,
    settlements,
    budget,
    recurring,
    transactions,
    tags,
    todo,
    data,
    profile,
    reports,
    views,
):
    app.include_router(api_router.router, prefix="/api")
app.include_router(assistants.router, prefix="/api")
app.include_router(assistants.consent_router, prefix="/api")
app.include_router(web.router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
# Starlette types a handler as taking any Exception; ours takes the one it is registered for.
app.add_exception_handler(LoginRequired, login_required_handler)  # pyrefly: ignore[bad-argument-type]
app.middleware("http")(refreshed_cookies_middleware)
app.middleware("http")(clear_shown_flash_middleware)
app.middleware("http")(cache_headers_middleware)


def cors_options() -> dict[str, Any]:
    """Only the finode app may call /api from a browser, with its cookies (none when FINODE_FRONTEND_ORIGIN is empty)."""
    return {
        "allow_origins": [settings.frontend_origin] if settings.frontend_origin else [],
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE"],
        "allow_headers": ["Content-Type", "X-Finode"],
    }


app.add_middleware(CORSMiddleware, **cors_options())
app.add_middleware(Compression, minimum_size=1000, compresslevel=5)  # outermost: it compresses what the others return

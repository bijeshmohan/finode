"""Wires the application: routers, middleware and the background work run in the lifespan (see docs/architecture/overview.md)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

from . import recurring_runner
from .caching import Compression, cache_headers_middleware
from .config import settings
from .flash import clear_shown_flash_middleware
from .mcp_server import transport as mcp_transport
from .routers import accounts, budget, categories, data, profile, recurring, reports, tags, transactions, web
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
for api_router in (accounts, categories, budget, recurring, transactions, tags, data, profile, reports):
    app.include_router(api_router.router, prefix="/api")
app.include_router(web.router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
# Starlette types a handler as taking any Exception; ours takes the one it is registered for.
app.add_exception_handler(LoginRequired, login_required_handler)  # pyrefly: ignore[bad-argument-type]
app.middleware("http")(refreshed_cookies_middleware)
app.middleware("http")(clear_shown_flash_middleware)
app.middleware("http")(cache_headers_middleware)
app.add_middleware(Compression, minimum_size=1000, compresslevel=5)  # outermost: it compresses what the others return

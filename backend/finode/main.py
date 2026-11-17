"""Wires the application: routers, middleware and the background work run in the lifespan (see docs/architecture/overview.md)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.middleware.gzip import GZipMiddleware
from starlette.routing import Route

from . import recurring_runner
from .auth.session import refreshed_cookies_middleware
from .config import settings
from .framing import NoFraming
from .mcp_server import transport as mcp_transport
from .routers import (
    accounts,
    assistants,
    auth,
    budget,
    categories,
    contacts,
    data,
    entries,
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
)


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
# The MCP server for AI assistants (personal access tokens; see finode/mcp_server).
app.router.routes.append(Route("/mcp", endpoint=mcp_transport.MCPEndpoint(), methods=["GET", "POST", "DELETE"]))


@app.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
@app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
def protected_resource(request: Request):
    return mcp_transport.protected_resource_metadata(request.scope)


# The JSON API lives under /api; every other path on the address is the finode app's (the web container, compose.yaml).
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
    entries,
    profile,
    reports,
    views,
):
    app.include_router(api_router.router, prefix="/api")
app.include_router(assistants.router, prefix="/api")
app.include_router(assistants.consent_router, prefix="/api")
app.middleware("http")(refreshed_cookies_middleware)
app.add_middleware(NoFraming)
app.add_middleware(
    GZipMiddleware, minimum_size=1000, compresslevel=5
)  # outermost: it compresses what the others return

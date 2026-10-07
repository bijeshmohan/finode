from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

from .routers import accounts, commodities, data, prices, profile, recurring, reports, transactions, web
from . import recurring_runner
from .caching import cache_headers_middleware
from .flash import clear_shown_flash_middleware
from .mcp_server import transport as mcp_transport
from .templating import BASE_DIR
from .web_auth import LoginRequired, login_required_handler, refreshed_cookies_middleware


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp_transport.lifespan(), recurring_runner.lifespan():
        yield


app = FastAPI(title="finode", lifespan=lifespan)
# The MCP server for AI assistants (personal access tokens; see app/mcp_server).
app.router.routes.append(Route("/mcp", endpoint=mcp_transport.MCPEndpoint(), methods=["GET", "POST", "DELETE"]))


@app.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
@app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
def protected_resource(request: Request):
    return mcp_transport.protected_resource_metadata(request.scope)
# The JSON API lives under /api; the web UI owns the site root.
for api_router in (accounts, commodities, prices, recurring, transactions, data, profile, reports):
    app.include_router(api_router.router, prefix="/api")
app.include_router(web.router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.add_exception_handler(LoginRequired, login_required_handler)
app.middleware("http")(refreshed_cookies_middleware)
app.middleware("http")(clear_shown_flash_middleware)
app.middleware("http")(cache_headers_middleware)


@app.get("/app", include_in_schema=False)
@app.get("/app/{rest:path}", include_in_schema=False)
def moved_from_app(request: Request, rest: str = ""):
    """The web UI used to live under /app: keep old bookmarks, the installed app and OAuth consent links working."""
    target = "/" + rest
    query = request.url.query
    return RedirectResponse(target + (f"?{query}" if query else ""), status_code=301)

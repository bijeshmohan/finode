"""Cache headers (long-lived for fingerprinted assets, revalidate everything else) and compression."""

from fastapi import Request
from starlette.middleware.gzip import GZipMiddleware


async def cache_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    if "cache-control" in response.headers:
        return response
    path = request.url.path
    if path.startswith("/static/"):
        if request.query_params.get("v"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
    elif response.headers.get("content-type", "").startswith("text/html"):
        # Pages show live balances; always revalidate and never share between users.
        response.headers["Cache-Control"] = "private, no-cache"
    return response


class Compression(GZipMiddleware):
    """Gzip for text (pages, styles, scripts, JSON): a page shrinks to about a fifth. Fonts and images are already
    compressed, so they pass through untouched. The MCP event stream is excluded by Starlette itself."""

    ALREADY_COMPRESSED = (".woff2", ".png", ".jpg", ".jpeg", ".webp", ".ico")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].endswith(self.ALREADY_COMPRESSED):
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)

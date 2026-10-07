"""Cache headers: long-lived for fingerprinted assets, revalidate everything else."""
from fastapi import Request


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

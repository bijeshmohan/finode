"""Serving the MCP servers at /mcp: personal access tokens, scopes and a rate limit."""

import json
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from uuid import UUID

import anyio.to_thread
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import Receive, Scope, Send

from fastapi import HTTPException

from .. import oauth
from ..auth import verify_supabase_jwt
from ..config import settings
from ..models.api_token import TokenScope
from ..services.api_token import ApiTokenService, TokenOwner
from ..services.oauth_grant import OAuthGrantService
from . import context
from .tools import build_server


# One server per scope, so a read-only token never even sees the tools that write.
SERVERS = {TokenScope.READ: build_server(write=False), TokenScope.WRITE: build_server(write=True)}

# Requests carry a bearer token, which a browser never adds by itself, so DNS rebinding
# protection (aimed at servers on localhost) is not needed and would reject the public host.
TRANSPORT_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)

RATE_WINDOW_SECONDS = 60.0
_calls: dict[UUID, deque[float]] = {}


def _allow(tkid: UUID, now: float | None = None) -> bool:
    """A sliding one-minute window per token (per process: approximate with several workers)."""
    now = time.monotonic() if now is None else now
    calls = _calls.setdefault(tkid, deque())
    while calls and now - calls[0] >= RATE_WINDOW_SECONDS:
        calls.popleft()
    if len(calls) >= settings.mcp_rate_limit:
        return False
    calls.append(now)
    return True


def _authenticate(secret: str) -> TokenOwner | None:
    """Who the bearer is: a personal access token (fin_…), or an access token Supabase issued to an app
    the user connected with OAuth (a JWT whose grant says what the app may do)."""
    if secret.startswith("fin_"):
        with context.session_factory() as db:
            return ApiTokenService.authenticate(db, secret)
    try:
        claims = verify_supabase_jwt(secret)
        user = UUID(claims["sub"])
    except (HTTPException, ValueError, KeyError):
        return None
    client_id = claims.get("client_id")
    if not client_id:
        return None  # an ordinary sign-in token: not meant for assistants
    with context.session_factory() as db:
        return OAuthGrantService.authenticate(db, user, str(client_id))


def resource_url(scope: Scope) -> str:
    """The public address of this endpoint, e.g. https://finode.bijesh.me/mcp (honours the proxy's headers)."""
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    host = headers.get("host", "localhost")
    return f"{scope.get('scheme', 'http')}://{host}/mcp"


def metadata_url(scope: Scope) -> str:
    root = resource_url(scope).removesuffix("/mcp")
    return f"{root}/.well-known/oauth-protected-resource/mcp"


def protected_resource_metadata(scope: Scope) -> dict:
    """RFC 9728: tells an MCP client which authorization server to send the user to."""
    return {
        "resource": resource_url(scope),
        "authorization_servers": [oauth.issuer()],
        "bearer_methods_supported": ["header"],
        "resource_name": "finode",
    }


async def _reply(send: Send, status: int, message: str, headers: dict[str, str] | None = None) -> None:
    body = json.dumps({"error": message}).encode()
    raw = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    raw += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": raw})
    await send({"type": "http.response.body", "body": body})


class MCPEndpoint:
    """ASGI app for /mcp: checks the token, then hands the request to the server for its scope."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        kind, _, secret = headers.get("authorization", "").partition(" ")
        if kind.lower() != "bearer" or not secret.strip():
            await _reply(
                send,
                401,
                "missing token: connect through your assistant's connector settings (OAuth), or create a token in finode "
                "under Profile, AI assistants, and send it as 'Authorization: Bearer <token>'",
                {"WWW-Authenticate": f'Bearer realm="finode", resource_metadata="{metadata_url(scope)}"'},
            )
            return
        owner = await anyio.to_thread.run_sync(_authenticate, secret.strip())
        if owner is None:
            await _reply(
                send,
                401,
                "invalid, expired or revoked token (an app you disconnected must be connected again)",
                {
                    "WWW-Authenticate": f'Bearer realm="finode", error="invalid_token", '
                    f'resource_metadata="{metadata_url(scope)}"'
                },
            )
            return
        if not _allow(owner.tkid):
            await _reply(send, 429, "too many requests: slow down", {"Retry-After": str(int(RATE_WINDOW_SECONDS))})
            return
        reset = context.current_owner.set(owner)
        try:
            await SERVERS[owner.scope].session_manager.handle_request(scope, receive, send)
        finally:
            context.current_owner.reset(reset)


@asynccontextmanager
async def lifespan() -> AsyncIterator[None]:
    """Run the servers' session managers; a fresh one each time the app starts (tests start it often)."""
    async with AsyncExitStack() as stack:
        for server in SERVERS.values():
            # Stateless and plain JSON: every request stands alone, so any worker can answer it.
            server.streamable_http_app(stateless_http=True, json_response=True, transport_security=TRANSPORT_SECURITY)
            await stack.enter_async_context(server.session_manager.run())
        yield

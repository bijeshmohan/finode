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

from ..config import settings
from ..models.api_token import TokenScope
from ..services.api_token import ApiTokenService, TokenOwner
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
    with context.session_factory() as db:
        return ApiTokenService.authenticate(db, secret)


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
                "missing token: create one in finode under Profile, AI assistants, and send it as 'Authorization: Bearer <token>'",
                {"WWW-Authenticate": 'Bearer realm="finode"'},
            )
            return
        owner = await anyio.to_thread.run_sync(_authenticate, secret.strip())
        if owner is None:
            await _reply(
                send,
                401,
                "invalid or revoked token",
                {"WWW-Authenticate": 'Bearer realm="finode", error="invalid_token"'},
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

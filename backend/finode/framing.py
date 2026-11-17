"""No other site may show finode inside a frame (clickjacking: a hidden finode page under a decoy button). Every
answer says so, in the old header and the current one. Pure ASGI, so a streamed answer (/mcp) passes untouched."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADERS = [(b"x-frame-options", b"DENY"), (b"content-security-policy", b"frame-ancestors 'none'")]


class NoFraming:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *HEADERS]
            await send(message)

        await self.app(scope, receive, with_headers)

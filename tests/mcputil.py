"""Helpers for talking to the MCP server in tests, over HTTP through the real /mcp endpoint."""

import json
from contextlib import asynccontextmanager, nullcontext
from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlmodel import Session

from app.main import app
from app.mcp_server import context
from app.repositories.api_token import ApiTokenRepository
from app.schemas.api_token import ApiTokenCreate
from app.services.api_token import ApiTokenService


def make_token(session: Session, user, name: str = "Claude", scope: str = "write") -> str:
    return ApiTokenService(ApiTokenRepository(session, user)).create(ApiTokenCreate(name=name, scope=scope)).secret


@asynccontextmanager
async def running_app(session: Session):
    original = context.session_factory
    context.session_factory = lambda: nullcontext(session)
    try:
        async with app.router.lifespan_context(app):
            yield
    finally:
        context.session_factory = original


@asynccontextmanager
async def mcp_client(secret: str):
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {secret}"},
    )
    async with http:
        async with Client(streamable_http_client("http://testserver/mcp", http_client=http)) as client:
            yield client


def payload(result) -> Any:
    """A tool result's data, or raise with the error text."""
    if result.is_error:
        raise ToolFailed(result.content[0].text)
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


class ToolFailed(Exception):
    pass

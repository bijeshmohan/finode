"""What the finode app's Assistants page and consent screen get from /api: tokens, connected apps, consent."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from .api_token import ApiTokenRead


class ConnectedAppRead(BaseModel):
    """An assistant that signed in through Supabase, and what the person let it do."""

    id: UUID
    client_name: str
    scope: str
    created: datetime
    last_used: datetime | None = None


class AssistantsRead(BaseModel):
    mcp_url: str
    tokens: list[ApiTokenRead]
    apps: list[ConnectedAppRead]


class AccessChange(BaseModel):
    scope: str


class ConsentRead(BaseModel):
    """The app asking to connect, as Supabase describes it. `redirect_url` is set when the person already decided and
    the app only needs them sent back."""

    authorization_id: str
    client_name: str
    client_uri: str | None
    scopes: list[str]
    redirect_url: str | None


class ConsentDecision(BaseModel):
    decision: Literal["allow", "deny"]
    access: Literal["read", "write", "manage"] = "read"


class ConsentResult(BaseModel):
    """Where to send the person next: back to the app."""

    redirect_url: str

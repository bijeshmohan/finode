from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from ..models.api_token import TokenScope


class ApiTokenCreate(BaseModel):
    name: str = Field(max_length=40)
    scope: str = TokenScope.READ

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("give the token a name, for example the assistant you use it in!")
        return v

    @field_validator("scope")
    @classmethod
    def scope_must_be_known(cls, v: str) -> str:
        if v not in TokenScope.ALL:
            raise ValueError("scope must be 'read' or 'write'!")
        return v


class ApiTokenRead(BaseModel):
    tkid: UUID
    name: str
    scope: str
    prefix: str
    created: datetime
    last_used: datetime | None = None
    revoked: datetime | None = None


class ApiTokenCreated(ApiTokenRead):
    # Shown once: only a hash is kept.
    secret: str

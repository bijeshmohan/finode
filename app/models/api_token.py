from datetime import datetime
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime
from sqlmodel import Field

from .utils import TimestampMixin


class TokenScope:
    """What a connection may do, from least to most: read; read & write; read, write & manage accounts."""

    READ = "read"
    WRITE = "write"
    # Everything in write, and changing accounts (rename, move, close, reopen, merge). Never deleting them.
    MANAGE = "manage"

    ALL = (READ, WRITE, MANAGE)
    LABELS: ClassVar[dict[str, str]] = {
        READ: "read only",
        WRITE: "read & write",
        MANAGE: "read, write & manage accounts",
    }

    @classmethod
    def can_write(cls, scope: str) -> bool:
        return scope in (cls.WRITE, cls.MANAGE)

    @classmethod
    def can_manage(cls, scope: str) -> bool:
        return scope == cls.MANAGE


class ApiToken(TimestampMixin, table=True):
    """A personal access token for the MCP server. Only a hash of the secret is stored."""

    __tablename__ = "api_tokens"
    __table_args__ = (CheckConstraint("scope IN ('read', 'write', 'manage')", name="ck_api_tokens_scope"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="auth.users.id")
    name: str = Field(max_length=40)
    scope: str = Field(max_length=10)
    # sha256 of the secret, hex; the secret itself is shown once and never stored.
    token_hash: str = Field(max_length=64, unique=True)
    # The start of the secret, so the user can tell tokens apart ("fin_a1b2c3").
    prefix: str = Field(max_length=16)
    last_used: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    revoked: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))

"""Persistence for personal access tokens, always filtered by the user's id."""

import builtins
from datetime import datetime
from uuid import UUID

from sqlmodel import Session, col, select

from ..models.api_token import ApiToken


class ApiTokenRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def list(self) -> builtins.list[ApiToken]:
        statement = select(ApiToken).where(ApiToken.user_id == self.uid).order_by(col(ApiToken.created).desc())
        return self.db.exec(statement).all()

    def read(self, token_id: UUID) -> ApiToken | None:
        return self.db.exec(select(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == self.uid)).first()

    def create(self, name: str, scope: str, token_hash: str, prefix: str) -> ApiToken:
        token = ApiToken(user_id=self.uid, name=name, scope=scope, token_hash=token_hash, prefix=prefix)
        self.db.add(token)
        self.db.flush()
        return token

    def revoke(self, token_id: UUID, when: datetime) -> ApiToken | None:
        token = self.read(token_id)
        if token and token.revoked is None:
            token.revoked = when
            self.db.add(token)
            self.db.flush()
        return token

    def set_scope(self, token_id: UUID, scope: str) -> ApiToken | None:
        token = self.read(token_id)
        if token and token.revoked is None:
            token.scope = scope
            self.db.add(token)
            self.db.flush()
            return token
        return None

    @staticmethod
    def by_hash(db: Session, token_hash: str) -> ApiToken | None:
        """Any user's token: used to find out who is calling, before there is a user."""
        return db.exec(select(ApiToken).where(ApiToken.token_hash == token_hash)).first()

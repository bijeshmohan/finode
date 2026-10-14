from datetime import datetime
from uuid import UUID

from sqlmodel import Session, select

from ..models.api_token import ApiToken


class ApiTokenRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def list(self) -> list[ApiToken]:
        statement = select(ApiToken).where(ApiToken.user == self.uid).order_by(ApiToken.created.desc())
        return self.db.exec(statement).all()

    def read(self, tkid: UUID) -> ApiToken | None:
        return self.db.exec(select(ApiToken).where(ApiToken.tkid == tkid, ApiToken.user == self.uid)).first()

    def create(self, name: str, scope: str, token_hash: str, prefix: str) -> ApiToken:
        token = ApiToken(user=self.uid, name=name, scope=scope, token_hash=token_hash, prefix=prefix)
        self.db.add(token)
        self.db.flush()
        return token

    def revoke(self, tkid: UUID, when: datetime) -> ApiToken | None:
        token = self.read(tkid)
        if token and token.revoked is None:
            token.revoked = when
            self.db.add(token)
            self.db.flush()
        return token

    def set_scope(self, tkid: UUID, scope: str) -> ApiToken | None:
        token = self.read(tkid)
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

from datetime import datetime
from uuid import UUID

from sqlmodel import Session, select

from ..models.oauth_grant import OAuthGrant


class OAuthGrantRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def list(self) -> list[OAuthGrant]:
        statement = select(OAuthGrant).where(OAuthGrant.user == self.uid).order_by(OAuthGrant.created.desc())
        return self.db.exec(statement).all()

    def read(self, gid: UUID) -> OAuthGrant | None:
        return self.db.exec(select(OAuthGrant).where(OAuthGrant.gid == gid, OAuthGrant.user == self.uid)).first()

    def by_client(self, client_id: str) -> OAuthGrant | None:
        return self.db.exec(
            select(OAuthGrant).where(OAuthGrant.user == self.uid, OAuthGrant.client_id == client_id)
        ).first()

    def save(self, client_id: str, client_name: str, scope: str) -> OAuthGrant:
        """Create the grant, or replace the level of an earlier one (also bringing a revoked one back)."""
        grant = self.by_client(client_id)
        if grant is None:
            grant = OAuthGrant(user=self.uid, client_id=client_id, client_name=client_name, scope=scope)
        else:
            grant.client_name, grant.scope, grant.revoked = client_name, scope, None
        self.db.add(grant)
        self.db.flush()
        return grant

    def revoke(self, gid: UUID, when: datetime) -> OAuthGrant | None:
        grant = self.read(gid)
        if grant and grant.revoked is None:
            grant.revoked = when
            self.db.add(grant)
            self.db.flush()
        return grant

    @staticmethod
    def for_token(db: Session, user: UUID, client_id: str) -> OAuthGrant | None:
        """Find a grant from a verified token's claims, before there is a repository for the user."""
        return db.exec(select(OAuthGrant).where(OAuthGrant.user == user, OAuthGrant.client_id == client_id)).first()

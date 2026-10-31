"""Persistence for connected-app grants, always filtered by the user's id."""

import builtins
from datetime import datetime
from uuid import UUID

from sqlmodel import Session, col, select

from ..models.oauth_grant import OAuthGrant


class OAuthGrantRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def list(self) -> builtins.list[OAuthGrant]:
        statement = select(OAuthGrant).where(OAuthGrant.user_id == self.uid).order_by(col(OAuthGrant.created).desc())
        return self.db.exec(statement).all()

    def read(self, grant_id: UUID) -> OAuthGrant | None:
        return self.db.exec(select(OAuthGrant).where(OAuthGrant.id == grant_id, OAuthGrant.user_id == self.uid)).first()

    def by_client(self, client_id: str) -> OAuthGrant | None:
        return self.db.exec(
            select(OAuthGrant).where(OAuthGrant.user_id == self.uid, OAuthGrant.client_id == client_id)
        ).first()

    def save(self, client_id: str, client_name: str, scope: str) -> OAuthGrant:
        """Create the grant, or replace the level of an earlier one (also bringing a revoked one back)."""
        grant = self.by_client(client_id)
        if grant is None:
            grant = OAuthGrant(user_id=self.uid, client_id=client_id, client_name=client_name, scope=scope)
        else:
            grant.client_name, grant.scope, grant.revoked = client_name, scope, None
        self.db.add(grant)
        self.db.flush()
        return grant

    def revoke(self, grant_id: UUID, when: datetime) -> OAuthGrant | None:
        grant = self.read(grant_id)
        if grant and grant.revoked is None:
            grant.revoked = when
            self.db.add(grant)
            self.db.flush()
        return grant

    def set_scope(self, grant_id: UUID, scope: str) -> OAuthGrant | None:
        grant = self.read(grant_id)
        if grant and grant.revoked is None:
            grant.scope = scope
            self.db.add(grant)
            self.db.flush()
            return grant
        return None

    @staticmethod
    def for_token(db: Session, user_id: UUID, client_id: str) -> OAuthGrant | None:
        """Find a grant from a verified token's claims, before there is a repository for the user."""
        return db.exec(
            select(OAuthGrant).where(OAuthGrant.user_id == user_id, OAuthGrant.client_id == client_id)
        ).first()

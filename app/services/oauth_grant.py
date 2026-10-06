from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session

from ..models.api_token import TokenScope
from ..models.oauth_grant import OAuthGrant
from ..models.utils import utc_now
from ..repositories.oauth_grant import OAuthGrantRepository
from .api_token import LAST_USED_RESOLUTION, TokenOwner


class OAuthGrantService:
    def __init__(self, repo: OAuthGrantRepository):
        self.repo = repo

    def list(self) -> list[OAuthGrant]:
        return [g for g in self.repo.list() if g.revoked is None]

    def allow(self, client_id: str, client_name: str, scope: str) -> OAuthGrant:
        if scope not in TokenScope.ALL:
            raise ValueError("access must be 'read' or 'write'!")
        if not client_id:
            raise ValueError("the app did not identify itself!")
        grant = self.repo.save(client_id, client_name.strip()[:80] or "An app", scope)
        self.repo.db.commit()
        self.repo.db.refresh(grant)
        return grant

    def revoke(self, gid: UUID) -> OAuthGrant:
        grant = self.repo.revoke(gid, utc_now())
        if grant is None:
            raise LookupError("app not found")
        self.repo.db.commit()
        return grant

    @staticmethod
    def authenticate(db: Session, user: UUID, client_id: str) -> TokenOwner | None:
        """Who a verified OAuth token acts as and what it may do; None if the user never allowed that app,
        or took the permission back."""
        grant = OAuthGrantRepository.for_token(db, user, client_id)
        if grant is None or grant.revoked is not None:
            return None
        now = utc_now()
        last: datetime | None = grant.last_used
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)  # SQLite drops the zone
        if last is None or now - last >= LAST_USED_RESOLUTION:
            grant.last_used = now
            db.add(grant)
            db.commit()
        return TokenOwner(user=grant.user, tkid=grant.gid, name=grant.client_name, scope=grant.scope)

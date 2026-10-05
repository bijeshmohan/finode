import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlmodel import Session

from ..models.api_token import ApiToken
from ..models.utils import utc_now
from ..repositories.api_token import ApiTokenRepository
from ..schemas.api_token import ApiTokenCreate, ApiTokenCreated, ApiTokenRead


SECRET_PREFIX = "fin_"
# A user can have this many tokens that are not revoked.
MAX_ACTIVE_TOKENS = 20
# "Last used" is written at most this often per token, not on every call.
LAST_USED_RESOLUTION = timedelta(minutes=1)


def hash_secret(secret: str) -> str:
    # The secret is 256 random bits, so a plain hash is enough (no salt or slow hash needed).
    return hashlib.sha256(secret.encode()).hexdigest()


@dataclass(frozen=True)
class TokenOwner:
    user: UUID
    tkid: UUID
    name: str
    scope: str


class ApiTokenService:
    def __init__(self, repo: ApiTokenRepository):
        self.repo = repo

    @staticmethod
    def _to_read(token: ApiToken) -> ApiTokenRead:
        return ApiTokenRead(
            tkid=token.tkid,
            name=token.name,
            scope=token.scope,
            prefix=token.prefix,
            created=token.created,
            last_used=token.last_used,
            revoked=token.revoked,
        )

    def list(self) -> list[ApiTokenRead]:
        return [self._to_read(t) for t in self.repo.list()]

    def create(self, data: ApiTokenCreate) -> ApiTokenCreated:
        active = [t for t in self.repo.list() if t.revoked is None]
        if len(active) >= MAX_ACTIVE_TOKENS:
            raise ValueError(f"you can have at most {MAX_ACTIVE_TOKENS} tokens: revoke one you no longer use first!")
        if any(t.name.casefold() == data.name.casefold() for t in active):
            raise ValueError(f"you already have a token named '{data.name}': pick another name!")
        secret = SECRET_PREFIX + secrets.token_urlsafe(32)
        token = self.repo.create(data.name, data.scope, hash_secret(secret), secret[: len(SECRET_PREFIX) + 6])
        self.repo.db.commit()
        self.repo.db.refresh(token)
        return ApiTokenCreated(**self._to_read(token).model_dump(), secret=secret)

    def revoke(self, tkid: UUID) -> ApiTokenRead:
        token = self.repo.revoke(tkid, utc_now())
        if token is None:
            raise LookupError("token not found")
        self.repo.db.commit()
        return self._to_read(token)

    @staticmethod
    def authenticate(db: Session, secret: str) -> TokenOwner | None:
        """Who a secret belongs to, or None if it is unknown or revoked. Notes when it was used."""
        if not secret.startswith(SECRET_PREFIX):
            return None
        token = ApiTokenRepository.by_hash(db, hash_secret(secret))
        if token is None or token.revoked is not None:
            return None
        now = utc_now()
        last = token.last_used
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=now.tzinfo)  # SQLite drops the zone
        if last is None or now - last >= LAST_USED_RESOLUTION:
            token.last_used = now
            db.add(token)
            db.commit()
        return TokenOwner(user=token.user, tkid=token.tkid, name=token.name, scope=token.scope)

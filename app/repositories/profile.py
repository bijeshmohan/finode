from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..commodity_seed import DEFAULT_CURRENCY_CODE, seed_id
from ..models.commodity import Commodity
from ..models.profile import Profile
from ..schemas.profile import ProfileUpdate


class ProfileRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def read(self) -> Profile | None:
        return self.db.exec(select(Profile).where(Profile.user == self.uid)).first()

    def get_or_create(self) -> Profile:
        """The user's profile, created empty on first access (race-safe via the primary key)."""
        profile = self.read()
        if profile:
            return profile
        try:
            profile = Profile(user=self.uid, default_commodity_id=self._default_currency_id())
            self.db.add(profile)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            profile = self.read()
            if profile is None:
                raise
        self.db.refresh(profile)
        return profile

    def _default_currency_id(self) -> UUID | None:
        found = self.db.exec(
            select(Commodity.cid).where(Commodity.cid == seed_id(DEFAULT_CURRENCY_CODE), Commodity.user.is_(None))
        ).first()
        return found

    def update(self, data: ProfileUpdate, default_commodity_id: UUID | None = None) -> Profile:
        profile = self.get_or_create()
        for key, value in data.model_dump(exclude_unset=True, exclude={"default_currency"}).items():
            setattr(profile, key, value)
        if default_commodity_id is not None:
            profile.default_commodity_id = default_commodity_id
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(profile)
        return profile

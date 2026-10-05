from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

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
            profile = Profile(user=self.uid)
            self.db.add(profile)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            profile = self.read()
            if profile is None:
                raise
        self.db.refresh(profile)
        return profile

    def update(self, data: ProfileUpdate) -> Profile:
        profile = self.get_or_create()
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(profile, key, value)
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(profile)
        return profile

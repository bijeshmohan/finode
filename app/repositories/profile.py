"""Persistence for the profile row (created lazily on first access)."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..currencies import DEFAULT_CURRENCY
from ..models.profile import Profile
from ..schemas.profile import ProfileUpdate
from .cache import remembered


# New people start with the rarely used features hidden (tests switch this on so they see everything).
NEW_PROFILE_ADVANCED = False
# ...and with the Plan showing only Spend (the sliders button adds Build and Earn; tests switch both on).
NEW_PROFILE_PLAN_BUILD = False
NEW_PROFILE_PLAN_EARN = False


class ProfileRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def read(self) -> Profile | None:
        return remembered(
            self.db, ("profile", self.uid), lambda: self.db.exec(select(Profile).where(Profile.user == self.uid)).first()
        )

    def advanced(self) -> bool:
        """Whether the rarely used features are shown; a person with no profile row yet gets the default."""
        profile = self.read()
        return profile.advanced if profile is not None else NEW_PROFILE_ADVANCED

    def plan_sections(self) -> tuple[bool, bool]:
        """Whether the Plan shows its Build and Earn sections."""
        profile = self.read()
        return (profile.plan_build, profile.plan_earn) if profile is not None else (NEW_PROFILE_PLAN_BUILD, NEW_PROFILE_PLAN_EARN)

    def currency(self) -> str:
        """The code of the currency the ledger is kept in; a person with no profile row yet gets the default."""
        profile = self.read()
        return profile.currency if profile is not None else DEFAULT_CURRENCY

    def get_or_create(self) -> Profile:
        """The user's profile, created empty on first access (race-safe via the primary key)."""
        profile = self.read()
        if profile:
            return profile
        try:
            profile = Profile(user=self.uid, currency=DEFAULT_CURRENCY, advanced=NEW_PROFILE_ADVANCED,
                              plan_build=NEW_PROFILE_PLAN_BUILD, plan_earn=NEW_PROFILE_PLAN_EARN)
            self.db.add(profile)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            profile = self.read()
            if profile is None:
                raise
        self.db.refresh(profile)
        return profile

    def update(self, data: ProfileUpdate, currency: str | None = None) -> Profile:
        profile = self.get_or_create()
        for key, value in data.model_dump(exclude_unset=True, exclude={"default_currency"}).items():
            setattr(profile, key, value)
        if currency is not None:
            profile.currency = currency
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(profile)
        return profile

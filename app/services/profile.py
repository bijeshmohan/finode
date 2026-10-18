"""The person's profile and settings: names, currency, the Advanced switch and the period lock."""

from datetime import timedelta

from ..clock import local_today
from ..config import settings
from ..currencies import find as find_currency
from ..repositories import ProfileRepository
from ..schemas.profile import ProfileRead, ProfileUpdate
from .account import AccountService


class ProfileService:
    def __init__(self, pr: ProfileRepository, accounts: AccountService):
        self.pr = pr
        self.accounts = accounts

    def _to_read(self, profile) -> ProfileRead:
        return ProfileRead(
            first_name=profile.first_name,
            last_name=profile.last_name,
            default_currency=profile.currency,
            locked_through=profile.locked_through,
            advanced=profile.advanced,
            created=profile.created,
            updated=profile.updated,
        )

    def read(self) -> ProfileRead:
        return self._to_read(self.pr.get_or_create())

    def advanced(self) -> bool:
        """Whether the rarely used features are shown (one cheap query; a person with no profile row yet gets the default)."""
        return self.pr.advanced()

    @staticmethod
    def _resolve_currency(data: ProfileUpdate) -> str | None:
        if "default_currency" not in data.model_fields_set:
            return None
        currency = find_currency(data.default_currency)
        if currency is None:
            raise ValueError(f"unknown currency '{data.default_currency}'!")
        return currency.code

    @staticmethod
    def _validate_lock(data: ProfileUpdate) -> None:
        if data.locked_through is not None and data.locked_through >= local_today():
            raise ValueError(
                f"the books can be locked up to yesterday ({local_today() - timedelta(days=1):%d %b %Y}) at the latest!"
            )

    def update(self, data: ProfileUpdate) -> ProfileRead:
        self._validate_lock(data)
        currency = self._resolve_currency(data)
        profile = self.pr.update(data, currency)
        self.accounts.reset_defaults()
        return self._to_read(profile)

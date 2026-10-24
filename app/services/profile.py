"""The person's profile and settings: names and currency."""

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
            created=profile.created,
            updated=profile.updated,
        )

    def read(self) -> ProfileRead:
        return self._to_read(self.pr.get_or_create())

    @staticmethod
    def _resolve_currency(data: ProfileUpdate) -> str | None:
        if "default_currency" not in data.model_fields_set:
            return None
        currency = find_currency(data.default_currency)
        if currency is None:
            raise ValueError(f"unknown currency '{data.default_currency}'!")
        return currency.code

    def update(self, data: ProfileUpdate) -> ProfileRead:
        currency = self._resolve_currency(data)
        profile = self.pr.update(data, currency)
        self.accounts.reset_defaults()
        return self._to_read(profile)

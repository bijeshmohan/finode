from ..config import settings
from ..repositories import ProfileRepository
from ..schemas.profile import ProfileRead, ProfileUpdate
from .account import AccountService
from .depth import ROOT_DEPTH_FIELDS, depth_limits


MAX_NAMED_ACCOUNTS = 3


class ProfileService:
    def __init__(self, pr: ProfileRepository, accounts: AccountService):
        self.pr = pr
        self.accounts = accounts

    @staticmethod
    def _to_read(profile) -> ProfileRead:
        return ProfileRead(
            first_name=profile.first_name,
            last_name=profile.last_name,
            created=profile.created,
            updated=profile.updated,
            **{field: getattr(profile, field) for field in ROOT_DEPTH_FIELDS.values()},
        )

    def read(self) -> ProfileRead:
        return self._to_read(self.pr.get_or_create())

    def depth_limits(self) -> dict[str, int]:
        """Effective depth limit per top-level account (does not create the profile)."""
        return depth_limits(self.pr.read())

    def deepest(self) -> dict[str, int]:
        """How deep the existing accounts go under each top-level account; the lowest limit that fits."""
        deepest = {root: 0 for root in ROOT_DEPTH_FIELDS}
        for root, depth, _ in self.accounts.account_depths():
            deepest[root] = max(deepest[root], depth)
        return deepest

    def _validate_depths(self, data: ProfileUpdate) -> None:
        depths = None
        for root, field in ROOT_DEPTH_FIELDS.items():
            value = getattr(data, field)
            if field not in data.model_fields_set or value is None:
                continue
            if value > settings.max_account_depth:
                raise ValueError(
                    f"{root} can be at most {settings.max_account_depth} levels deep (the application maximum)!"
                )
            if value == 0:
                continue
            if depths is None:
                depths = self.accounts.account_depths()
            too_deep = sorted(path for r, depth, path in depths if r == root and depth > value)
            if too_deep:
                shown = ", ".join(too_deep[:MAX_NAMED_ACCOUNTS])
                more = len(too_deep) - MAX_NAMED_ACCOUNTS
                raise ValueError(
                    f"cannot limit {root} to {value} level{'' if value == 1 else 's'}: "
                    f"{shown}{f' and {more} more' if more > 0 else ''} "
                    f"{'is' if len(too_deep) == 1 else 'are'} deeper. Move or delete "
                    f"{'it' if len(too_deep) == 1 else 'them'} first, or choose at least "
                    f"{max(depth for r, depth, _ in depths if r == root)}."
                )

    def update(self, data: ProfileUpdate) -> ProfileRead:
        self._validate_depths(data)
        return self._to_read(self.pr.update(data))

"""How deep each top-level account's hierarchy may go.

Depth counts levels below the top-level account: `Expenses › Food` is level 1.
A user setting of 0 means "no limit of my own"; the application maximum
(`settings.max_account_depth`) always applies.
"""
from ..config import settings
from ..models.profile import Profile


ROOT_DEPTH_FIELDS = {
    "Assets": "max_depth_assets",
    "Liabilities": "max_depth_liabilities",
    "Equity": "max_depth_equity",
    "Income": "max_depth_income",
    "Expenses": "max_depth_expenses",
}


def depth_limit(profile: Profile | None, root_name: str) -> int:
    chosen = getattr(profile, ROOT_DEPTH_FIELDS[root_name], 0) if profile else 0
    return min(chosen, settings.max_account_depth) if chosen > 0 else settings.max_account_depth


def depth_limits(profile: Profile | None) -> dict[str, int]:
    return {root: depth_limit(profile, root) for root in ROOT_DEPTH_FIELDS}

"""The four kinds of account a person can add (`accounts.type`), in their starting order, and the two built-in groups
that cash flow retired in older books (see services/cash_flow.py)."""

from typing import Protocol

TYPE_KEYS: tuple[str, ...] = ("assets.bank", "assets.cash", "liabilities.cards", "assets.wallet")
TYPE_NAMES: dict[str, str] = {
    "assets.bank": "Bank Account",
    "assets.cash": "Cash",
    "liabilities.cards": "Credit Card",
    "assets.wallet": "Prepaid Wallet",
}
# The root each type sits under: what an account of that type holds (Assets) or owes (Liabilities).
TYPE_ROOTS: dict[str, str] = {
    "assets.bank": "Assets",
    "assets.cash": "Assets",
    "liabilities.cards": "Liabilities",
    "assets.wallet": "Assets",
}
# Investments and Loans: their accounts are converted into categories and the groups go.
RETIRED_KEYS: tuple[str, ...] = ("assets.investments", "liabilities.loans")


class _Typed(Protocol):
    @property
    def type(self) -> str | None: ...


def type_key(account: _Typed) -> str | None:
    """The account's type (`TYPE_KEYS`), or None for anything else: a root, Opening Balances, a person's account."""
    return account.type if account.type in TYPE_KEYS else None


def in_budget(account: _Typed) -> bool:
    """Whether the account's money is part of the budget: every account of the four types is."""
    return type_key(account) is not None


def type_order(saved: str | None) -> list[str]:
    """The person's order of the four types from what the profile keeps; the starting order when it says otherwise."""
    keys = [k for k in (saved or "").split(",") if k]
    return keys if sorted(keys) == sorted(TYPE_KEYS) else list(TYPE_KEYS)

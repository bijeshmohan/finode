"""The four kinds of account a person can add (the built-in groups, by `accounts.system_key`), in their starting order,
and the two built-in groups that cash flow retired (see services/cash_flow.py)."""

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

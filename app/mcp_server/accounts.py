"""Finding accounts by the names people (and assistants) use for them."""

import difflib
import re
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from ..schemas import AccountRead
from ..schemas.category import CategoryRead
from ..services.account import GROUP_POSTING_ROOT_NAMES
from .categories import CategoryIndex

SEPARATORS = re.compile(r"\s*(?::|›|>|/)\s*")
ROOT_ALIASES = {
    "asset": "assets",
    "liability": "liabilities",
    "expense": "expenses",
    "revenue": "income",
    "revenues": "income",
    "incomes": "income",
}


@dataclass
class Entry:
    account: AccountRead
    segments: list[str]  # names from the top-level account down
    root: str
    has_children: bool

    @property
    def path(self) -> str:
        return ":".join(self.segments)

    @property
    def is_root(self) -> bool:
        return self.account.parent_id is None

    @property
    def postable(self) -> bool:
        return not self.is_root and (not self.has_children or self.root in GROUP_POSTING_ROOT_NAMES)


class AccountIndex:
    def __init__(self, accounts: list[AccountRead], categories: list[CategoryRead] | None = None):
        by_id = {a.id: a for a in accounts}
        parents = {a.parent_id for a in accounts if a.parent_id is not None}
        self.entries: dict[UUID, Entry] = {}
        for account in accounts:
            segments = [account.name]
            current = account
            while current.parent_id is not None:
                current = by_id[current.parent_id]
                segments.insert(0, current.name)
            self.entries[account.id] = Entry(account, segments, segments[0], account.id in parents)
        # Categories are not accounts; they are only named here, as the journal would write them (Expenses:Food).
        self.category_paths: dict[UUID, str] = {
            c.id: ("Expenses" if c.kind == "spending" else "Income") + ":" + c.path for c in categories or []
        }

    def where(self, account: UUID, category: UUID | None) -> tuple[str, UUID]:
        """What a line is called to an assistant: a line on Expenses or Income by its category (Expenses:Food:Groceries
        and the category's id), any other line by its account."""
        entry = self.entries.get(account)
        if (
            entry is not None
            and entry.is_root
            and entry.root in ("Expenses", "Income")
            and category in self.category_paths
        ):
            return self.category_paths[cast(UUID, category)], cast(UUID, category)
        return self.path(account), account

    def path(self, account_id: UUID) -> str:
        entry = self.entries.get(account_id)
        return entry.path if entry else "?"

    def sorted(self) -> list[Entry]:
        order = ["Assets", "Liabilities", "Equity", "Income", "Expenses"]
        return sorted(
            self.entries.values(),
            key=lambda e: (order.index(e.root) if e.root in order else 9, [s.casefold() for s in e.segments]),
        )

    def find(self, text: str, *, postable: bool = False, allow_root: bool = False) -> Entry:
        """The one account `text` names: a full path ("Expenses:Food"), the end of one
        ("Food", "Travel:Food") or an id. Raises ValueError naming the choices when it is not one."""
        text = (text or "").strip()
        if not text:
            raise ValueError("an account is required: give its path, for example Assets:Bank:HDFC!")
        try:
            by_id = self.entries.get(UUID(text))
        except ValueError:
            by_id = None
        if by_id:
            return self._check(by_id, postable, allow_root)
        wanted = [s.casefold() for s in SEPARATORS.split(text) if s]
        if wanted and len(wanted) > 1:
            wanted[0] = ROOT_ALIASES.get(wanted[0], wanted[0])

        def folded(entry: Entry) -> list[str]:
            return [s.casefold() for s in entry.segments]

        # Top-level accounts can match too, so naming one gets a clear "use a sub-account" message.
        candidates = list(self.entries.values())
        exact = [e for e in candidates if folded(e) == wanted]
        matches = exact or [e for e in candidates if folded(e)[-len(wanted) :] == wanted]
        if len(matches) > 1:
            matches = [
                e for e in matches if e.account.closed_on is None
            ] or matches  # a closed twin is not the one meant
        if postable and len(matches) > 1:
            # "Food" under Expenses and a group "Food" under Assets: prefer what can take postings.
            matches = [e for e in matches if e.postable] or matches
        if len(matches) == 1:
            return self._check(matches[0], postable, allow_root)
        if matches:
            listed = ", ".join(sorted(e.path for e in matches))
            raise ValueError(f"'{text}' matches {len(matches)} accounts: {listed}. Use the full path!")
        paths = [e.path for e in candidates]
        close = difflib.get_close_matches(text, paths, n=3, cutoff=0.5) or difflib.get_close_matches(
            wanted[-1] if wanted else text, [e.segments[-1] for e in candidates], n=3, cutoff=0.6
        )
        hint = f" Did you mean {', '.join(close)}?" if close else ""
        raise ValueError(f"no account matches '{text}'.{hint} Call list_accounts to see them all.")

    @staticmethod
    def _check(entry: Entry, postable: bool, allow_root: bool) -> Entry:
        if entry.is_root and not allow_root:
            raise ValueError(f"'{entry.path}' is a top-level account: use one of its sub-accounts!")
        if postable and entry.account.closed_on is not None:
            raise ValueError(f"'{entry.path}' is closed: the user can reopen it in finode to use it!")
        if postable and not entry.postable:
            raise ValueError(
                f"'{entry.path}' has sub-accounts, so post to one of them instead "
                "(only Income and Expenses groups take postings directly)!"
            )
        return entry


@dataclass(frozen=True)
class Place:
    """Where one side of an entry goes: an account, or for spending and income the Expenses or Income account with the
    category it was for."""

    path: str
    account: UUID
    category: UUID | None = None


def _is_id(text: str) -> bool:
    try:
        UUID(text)
    except ValueError:
        return False
    return True


class Places:
    """Finds the account or the category a name (or id) means, for the tools that record money moving."""

    def __init__(self, accounts: AccountIndex, categories: CategoryIndex):
        self.accounts, self.categories = accounts, categories
        self.roots = {e.account.name: e.account.id for e in accounts.entries.values() if e.is_root}

    def find(self, text: str) -> Place:
        text = (text or "").strip()
        found: list[Place] = []
        problems: list[str] = []
        try:
            entry = self.accounts.find(text, postable=True)
            found.append(Place(entry.path, entry.account.id))
        except ValueError as e:
            problems.append(str(e))
        try:
            kind, name = self._category_text(text)
            category = self.categories.find(name, kind=kind, open_only=True)
            if kind is None:  # no Expenses:/Income: in front: the end of a path must name just one category
                wanted = [s.casefold() for s in SEPARATORS.split(name) if s]
                ends = [
                    c
                    for c in self.categories.categories.values()
                    if [s.casefold() for s in c.path.split(":")][-len(wanted) :] == wanted and c.closed_on is None
                ]
                if len(ends) > 1 and not _is_id(name):
                    listed = ", ".join(
                        sorted(("Expenses:" if c.kind == "spending" else "Income:") + c.path for c in ends)
                    )
                    raise ValueError(f"'{text}' matches {len(ends)} places: {listed}. Use the full path!")
            root = "Expenses" if category.kind == "spending" else "Income"
            found.append(Place(f"{root}:{category.path}", self.roots[root], category.id))
        except ValueError as e:
            problems.append(str(e))
        if len(found) == 1:
            return found[0]
        if found:
            listed = ", ".join(sorted(p.path for p in found))
            raise ValueError(f"'{text}' matches {len(found)} places: {listed}. Use the full path!")
        # Prefer the message that says more than "nothing matches" (an ambiguous name, a closed or top-level one).
        informative = [p for p in problems if "no account matches" not in p and "no category matches" not in p]
        if informative:
            raise ValueError(informative[0])
        hints = [m.group(0) for p in problems if (m := re.search(r"Did you mean [^?]*\?", p))]
        suggestion = f" {' '.join(hints)}" if hints else ""
        raise ValueError(
            f"nothing matches '{text}'.{suggestion} Give an account path (list_accounts) or a category (list_categories)!"
        )

    @staticmethod
    def _category_text(text: str) -> tuple[str | None, str]:
        """A category named like a journal account (Expenses:Food, Income:Salary) is the category below that root."""
        parts = [s for s in SEPARATORS.split(text) if s]
        if len(parts) > 1:
            root = ROOT_ALIASES.get(parts[0].casefold(), parts[0].casefold())
            if root in ("expenses", "income"):
                return ("spending" if root == "expenses" else "earning"), ":".join(parts[1:])
        return None, text

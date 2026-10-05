"""Finding accounts by the names people (and assistants) use for them."""

import difflib
import re
from dataclasses import dataclass
from uuid import UUID

from ..schemas import AccountRead
from ..services.account import GROUP_POSTING_ROOT_NAMES


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
    def __init__(self, accounts: list[AccountRead]):
        by_id = {a.aid: a for a in accounts}
        parents = {a.parent_id for a in accounts if a.parent_id is not None}
        self.entries: dict[UUID, Entry] = {}
        for account in accounts:
            segments = [account.name]
            current = account
            while current.parent_id is not None:
                current = by_id[current.parent_id]
                segments.insert(0, current.name)
            self.entries[account.aid] = Entry(account, segments, segments[0], account.aid in parents)

    def path(self, aid: UUID) -> str:
        entry = self.entries.get(aid)
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
        matches = exact or [e for e in candidates if folded(e)[-len(wanted):] == wanted]
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
        if postable and not entry.postable:
            raise ValueError(
                f"'{entry.path}' has sub-accounts, so post to one of them instead "
                "(only Income and Expenses groups take postings directly)!"
            )
        return entry

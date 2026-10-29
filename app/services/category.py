"""Budget categories: what money was for (Groceries, EMI, Salary), kept apart from the books' accounts.

A category has a books account behind it (an Income or Expenses account with the same id, kept in step by
`AccountRepository`), so the rules of accounts (two levels deep, names unique among siblings, closing, merging, the
limits) are the rules of categories, and this service is the one door the budget and the pages use. The account
side stays out of sight."""

from uuid import UUID

from ..models.account import Account
from ..models.category import BudgetCategory
from ..repositories import AccountRepository, CategoryRepository
from ..schemas.account import AccountCreate, AccountUpdate
from ..schemas.category import CategoryCreate, CategoryDeleteResult, CategoryRead, CategoryUpdate
from .account import AccountInUseError, AccountService

ROOT_NAMES = {"spending": "Expenses", "earning": "Income"}
UNCATEGORISED = "Uncategorised"


class CategoryService:
    def __init__(self, accounts: AccountService, cr: CategoryRepository | None = None):
        self.accounts = accounts
        self.ar: AccountRepository = accounts.ar
        self.cr = cr or CategoryRepository(self.ar.db, self.ar.uid)

    # ---- reading -----------------------------------------------------------------------------------

    def _path(self, category: BudgetCategory, by_id: dict[UUID, BudgetCategory]) -> str:
        names: list[str] = []
        seen: set[UUID] = set()
        current: BudgetCategory | None = category
        while current is not None and current.bcid not in seen:
            seen.add(current.bcid)
            names.append(current.name)
            current = by_id.get(current.parent_id) if current.parent_id else None
        return ":".join(reversed(names))

    def _to_read(self, category: BudgetCategory, by_id: dict[UUID, BudgetCategory]) -> CategoryRead:
        return CategoryRead(
            bcid=category.bcid,
            name=category.name,
            kind="spending" if category.kind == "spending" else "earning",
            parent_id=category.parent_id,
            details=category.details,
            closed_on=category.closed_on,
            system_key=category.system_key,
            path=self._path(category, by_id),
        )

    def list(self, kind: str | None = None, include_closed: bool = False) -> list[CategoryRead]:
        self.accounts.ensure_roots()
        every = self.cr.list()
        by_id = {c.bcid: c for c in every}
        return sorted(
            (
                self._to_read(c, by_id)
                for c in every
                if (kind is None or c.kind == kind) and (include_closed or c.closed_on is None)
            ),
            key=lambda c: (c.kind, c.path.lower()),
        )

    def read(self, bcid: UUID) -> CategoryRead | None:
        category = self.cr.read(bcid)
        return self._to_read(category, {c.bcid: c for c in self.cr.list()}) if category is not None else None

    def _get(self, bcid: UUID) -> BudgetCategory:
        category = self.cr.read(bcid)
        if category is None:
            raise ValueError(f"category with bcid '{bcid}' not found!")
        return category

    # ---- changing ----------------------------------------------------------------------------------

    def _root(self, kind: str) -> Account:
        roots = self.accounts.ensure_roots()
        return next(a for a in roots if a.parent_id is None and a.name == ROOT_NAMES[kind])

    def create(self, data: CategoryCreate) -> CategoryRead:
        """Make a group or a category: its books account is made with it, under its group's."""
        root = self._root(data.kind)
        if data.parent_id is None:
            parent_account = root.aid
        else:
            parent = self._get(data.parent_id)
            if parent.kind != data.kind:
                raise ValueError(f"'{parent.name}' is a {parent.kind} group: it cannot hold {data.kind} categories!")
            parent_account = parent.bcid
        self.accounts.create(AccountCreate(name=data.name, details=data.details, parent_id=parent_account))
        return self._read(self._by_name(data.name, parent_account))

    def _by_name(self, name: str, parent_account: UUID) -> UUID:
        account = next(
            a
            for a in self.ar.list()
            if a.parent_id == parent_account and a.name.casefold() == name.casefold() and a.category_id == a.aid
        )
        return account.aid

    def _read(self, bcid: UUID) -> CategoryRead:
        read = self.read(bcid)
        if read is None:
            raise RuntimeError(f"category '{bcid}' should exist!")
        return read

    def update(self, bcid: UUID, data: CategoryUpdate) -> CategoryRead:
        """Rename it, change its note or move it into another group (or out of its group)."""
        category = self._get(bcid)
        changes: dict = {}
        for key in data.model_fields_set:
            if key == "parent_id":
                if data.parent_id is None:
                    changes["parent_id"] = self._root(category.kind).aid
                else:
                    parent = self._get(data.parent_id)
                    if parent.kind != category.kind:
                        raise ValueError("a category cannot move into a group of the other kind!")
                    changes["parent_id"] = parent.bcid
            else:
                changes[key] = getattr(data, key)
        if changes:
            self.accounts.update(bcid, AccountUpdate(**changes))
        return self._read(bcid)

    def close(self, bcid: UUID) -> CategoryRead:
        self._get(bcid)
        self.accounts.close(bcid)
        return self._read(bcid)

    def reopen(self, bcid: UUID) -> CategoryRead:
        self._get(bcid)
        self.accounts.reopen(bcid)
        return self._read(bcid)

    def delete(self, bcid: UUID) -> CategoryDeleteResult:
        """Remove an unused category for good; one with history (entries, labelled lines, sub-categories or a rule)
        is closed instead, so nothing that was recorded loses its meaning."""
        self._get(bcid)
        before = self._read(bcid)
        try:
            self.accounts.delete(bcid)
        except AccountInUseError:
            return CategoryDeleteResult(outcome="closed", category=self.close(bcid))
        return CategoryDeleteResult(outcome="deleted", category=before)

    def merge(self, source: UUID, target: UUID, dry_run: bool = False):
        """Fold one category into another of the same kind: its entries, lines, planned amounts and rules become the
        target's. Same rules as merging the accounts behind them."""
        self._get(source)
        self._get(target)
        return self.accounts.merge(source, target, dry_run)

    # ---- the books side ----------------------------------------------------------------------------

    def books_account(self, bcid: UUID) -> UUID:
        """The account an entry posts to for this category: its own books account."""
        category = self._get(bcid)
        if category.closed_on is not None:
            raise ValueError(f"category '{category.name}' is closed: reopen it to use it!")
        return category.bcid

    def uncategorised(self, kind: str) -> CategoryRead:
        """The built-in Uncategorised of a kind, made the first time it is needed (a person has one of each at most)."""
        key = f"uncategorised.{kind}"
        found = self.cr.by_system_key(key)
        if found is not None:
            if found.closed_on is not None:
                return self.reopen(found.bcid)
            return self._read(found.bcid)
        root = self._root(kind)
        taken = {a.name.casefold() for a in self.ar.list() if a.parent_id == root.aid}
        name = UNCATEGORISED if UNCATEGORISED.casefold() not in taken else f"{UNCATEGORISED} (built-in)"
        made = self.create(CategoryCreate(name=name, kind="spending" if kind == "spending" else "earning"))
        self.cr.set_system_key(made.bcid, key)
        self.ar.db.commit()
        return self._read(made.bcid)

"""Budget categories: what money was for (Groceries, EMI, Salary), kept apart from the books' accounts.

A category stands alone. The books post an expense to the root Expenses account and an income to the root Income
account; the line carries the category. A category sits at most two levels deep (a group and the categories in it), its
name is unique among its siblings (capitals aside), and the built-in Uncategorised of each kind is made on demand."""

import builtins
from datetime import date
from decimal import Decimal
from uuid import UUID

from ..clock import local_today
from ..config import settings
from ..limits import ensure_room
from ..models.category import BudgetCategory
from ..models.transaction import PostingSide
from ..repositories import BudgetRepository, CategoryRepository
from ..repositories.recurring import RecurringRepository
from ..schemas.account import MergeResult, RegisterEntry
from ..schemas.category import CategoryCreate, CategoryDeleteResult, CategoryRead, CategoryUpdate
from .account import GROUP_POSTING_ROOT_NAMES, AccountService


class CategoryInUseError(ValueError):
    """A category cannot be removed or closed because something still depends on it."""


class CategoryService:
    def __init__(self, accounts: AccountService, cr: CategoryRepository | None = None):
        self.accounts = accounts
        self.ar = accounts.ar
        self.tr = accounts.tr
        self.cr = cr or CategoryRepository(self.ar.db, self.ar.uid)
        self.origin = self.ar.origin
        self.db = self.ar.db
        self.uid = self.ar.uid

    # ---- reading -----------------------------------------------------------------------------------

    @staticmethod
    def _path(category: BudgetCategory, by_id: dict[UUID, BudgetCategory]) -> str:
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

    def list(self, kind: str | None = None, include_closed: bool = False) -> builtins.list[CategoryRead]:
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

    def _read(self, bcid: UUID) -> CategoryRead:
        read = self.read(bcid)
        if read is None:
            raise RuntimeError(f"category '{bcid}' should exist!")
        return read

    # ---- rules -------------------------------------------------------------------------------------

    def _check_name_free(self, name: str, parent_id: UUID | None, kind: str, exclude: UUID | None = None) -> None:
        wanted = name.casefold()
        for other in self.cr.list():
            same_place = other.parent_id == parent_id and other.kind == kind and other.bcid != exclude
            if same_place and other.name.casefold() == wanted:
                where = "there" if parent_id is None else repr(self._get(parent_id).name)
                raise ValueError(f"{where} already has a category called '{other.name}'!")

    def _check_parent(self, parent_id: UUID | None, kind: str, moving: UUID | None = None) -> None:
        """A parent is a top-level category of the same kind that is open and is not the one being moved (a category
        goes two levels deep: a group and the categories in it)."""
        if parent_id is None:
            return
        parent = self._get(parent_id)
        if parent.kind != kind:
            raise ValueError(f"'{parent.name}' is a {parent.kind} group: it cannot hold {kind} categories!")
        if parent.parent_id is not None:
            raise ValueError("categories can be at most two levels deep (a group and the categories in it)!")
        if parent.closed_on is not None:
            raise ValueError(f"'{parent.name}' is closed: reopen it to add categories to it!")
        if moving is not None:
            if parent.bcid == moving:
                raise ValueError("a category cannot be moved into itself!")
            if self.cr.has_children(moving):
                raise ValueError("a group that holds categories cannot become part of another group!")

    # ---- changing ----------------------------------------------------------------------------------

    def create(self, data: CategoryCreate) -> CategoryRead:
        ensure_room(len(self.cr.list()), settings.max_categories, "categories")
        self._check_parent(data.parent_id, data.kind)
        self._check_name_free(data.name, data.parent_id, data.kind)
        made = self.cr.add(
            BudgetCategory(
                user=self.uid, name=data.name, details=data.details, kind=data.kind, parent_id=data.parent_id
            )
        )
        self.db.commit()
        return self._read(made.bcid)

    def update(self, bcid: UUID, data: CategoryUpdate) -> CategoryRead:
        """Rename it, change its note or move it into another group (or out of its group)."""
        category = self._get(bcid)
        if category.system_key is not None and (
            "name" in data.model_fields_set or "parent_id" in data.model_fields_set
        ):
            raise ValueError(f"'{category.name}' is built in and can't be renamed or moved!")
        name = data.name if "name" in data.model_fields_set and data.name is not None else category.name
        parent = data.parent_id if "parent_id" in data.model_fields_set else category.parent_id
        if parent != category.parent_id:
            self._check_parent(parent, category.kind, moving=bcid)
        if name != category.name or parent != category.parent_id:
            self._check_name_free(name, parent, category.kind, exclude=bcid)
        category.name, category.parent_id = name, parent
        if "details" in data.model_fields_set:
            category.details = data.details
        self.cr.save(category)
        self.db.commit()
        return self._read(bcid)

    def _branch(self, bcid: UUID) -> builtins.list[BudgetCategory]:
        return [c for c in self.cr.list() if c.bcid == bcid or c.parent_id == bcid]

    def close(self, bcid: UUID, today: date | None = None) -> CategoryRead:
        """No longer offered, history kept: closes the category and the categories in it. Refused while a running
        recurring transaction still records into it."""
        category = self._get(bcid)
        branch = self._branch(bcid)
        for member in branch:
            rules = RecurringRepository.active_rules_for_category(self.db, self.uid, member.bcid)
            if rules:
                label = rules[0].payee or "a recurring transaction"
                raise CategoryInUseError(f"'{label}' still records into it: stop that recurring transaction first!")
        for member in branch:
            self.ar.clear_payment_category(member.bcid)
        self.cr.set_closed([m.bcid for m in branch if m.closed_on is None], today or local_today())
        self.db.commit()
        return self._read(category.bcid)

    def reopen(self, bcid: UUID) -> CategoryRead:
        """Reopen a category with the categories in it, and the group it is in (an open one sits in an open group)."""
        category = self._get(bcid)
        ids = [m.bcid for m in self._branch(bcid)]
        if category.parent_id is not None:
            ids.append(category.parent_id)
        self.cr.set_closed(ids, None)
        self.db.commit()
        return self._read(bcid)

    def _unused(self, category: BudgetCategory) -> bool:
        return not (
            self.cr.has_children(category.bcid)
            or self.cr.used_by_lines(category.bcid)
            or RecurringRepository.uses_category(self.db, self.uid, category.bcid)
            or BudgetRepository(self.db, self.uid).uses_category(category.bcid)
            or category.system_key is not None
        )

    def delete(self, bcid: UUID) -> CategoryDeleteResult:
        """Remove an unused category for good; one with history (lines, categories inside it, a rule or a planned
        amount) is closed instead, so nothing that was recorded loses its meaning."""
        category = self._get(bcid)
        before = self._read(bcid)
        if not self._unused(category):
            return CategoryDeleteResult(outcome="closed", category=self.close(bcid))
        self.ar.clear_payment_category(bcid)
        self.cr.delete(category)
        self.db.commit()
        return CategoryDeleteResult(outcome="deleted", category=before)

    def merge(self, source: UUID, target: UUID, dry_run: bool = False) -> MergeResult:
        """Fold one category into another of the same kind: its lines, planned amounts, recurring rules and payment
        links become the target's, and the source is deleted. All or nothing."""
        origin, into = self._get(source), self._get(target)
        if source == target:
            raise ValueError("a category cannot be merged into itself!")
        if origin.system_key is not None or into.system_key is not None:
            raise ValueError("the built-in Uncategorised cannot be merged: merge a category into it instead.")
        if origin.kind != into.kind:
            raise ValueError("cannot merge a spending category into an earning one!")
        if self.cr.has_children(source):
            raise ValueError(f"'{origin.name}' holds categories: merge or move them first!")
        if into.closed_on is not None:
            raise ValueError(f"'{into.name}' is closed: reopen it first!")
        by_id = {c.bcid: c for c in self.cr.list()}
        budget = BudgetRepository(self.db, self.uid)
        tids = self.tr.labelled(source)
        result = MergeResult(
            dry_run=dry_run,
            merged=not dry_run,
            source=self._path(origin, by_id),
            into=self._path(into, by_id),
            balance_moved=0,
            entries_moved=len(tids),
            plan_months_moved=budget.months_for_category(source),
            recurring_rules_moved=0,
            payment_links_moved=self.ar.count_payment_links(source),
        )
        if dry_run:
            return result
        try:
            self.tr.relabel_category(source, target, self.origin)
            budget.merge_category(source, target)
            result.recurring_rules_moved = RecurringRepository.repoint_category(self.db, self.uid, source, target)
            self.ar.repoint_payment_category(source, target)
            self.cr.delete(origin)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return result

    def register(self, bcid: UUID, own_only: bool = False) -> builtins.list[RegisterEntry]:
        """The entries that have a line labelled with the category (and with the categories in it, unless `own_only`),
        oldest first. Each one's change is signed by the kind's normal side (spending adds with a debit, earning with a
        credit), so the running balance adds up to what the category came to."""
        category = self._get(bcid)
        ids = {bcid} if own_only else {m.bcid for m in self._branch(bcid)}
        normal = PostingSide.DEBIT if category.kind == "spending" else PostingSide.CREDIT
        lines = self.tr.postings_for_categories(ids)
        changes: dict[UUID, Decimal] = {}
        for line in lines:
            changes[line.transaction] = changes.get(line.transaction, Decimal("0.00")) + (
                line.amount if line.side == normal else -line.amount
            )
        loaded = self.tr.read_many(builtins.list(changes))
        postings_of = self.tr.postings_for_transactions(builtins.list(changes))
        accounts = {a.aid: a for a in self.ar.list()}
        transactions = sorted((loaded[t] for t in changes if t in loaded), key=lambda t: (t.date, t.created))
        entries: builtins.list[RegisterEntry] = []
        balance = Decimal("0.00")
        for transaction in transactions:
            balance += changes[transaction.tid]
            counters: builtins.list[str] = []
            for posting in postings_of.get(transaction.tid, []):
                account = accounts[posting.account]
                if AccountService.root_name(account, accounts) in GROUP_POSTING_ROOT_NAMES:
                    continue
                if account.name not in counters:
                    counters.append(account.name)
            entries.append(
                RegisterEntry(
                    tid=transaction.tid,
                    date=transaction.date,
                    payee=transaction.payee,
                    comment=transaction.comment,
                    counter_accounts=counters,
                    change=changes[transaction.tid],
                    balance=balance,
                )
            )
        return entries

    def uncategorised(self, kind: str) -> CategoryRead:
        """The built-in Uncategorised of a kind, made the first time it is needed."""
        made = self.cr.ensure_uncategorised(kind)
        self.db.commit()
        return self._read(made.bcid)

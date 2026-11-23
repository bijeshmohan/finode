"""Budget categories: what money was for (Groceries, EMI, Salary), kept apart from the books' accounts.

A category stands alone. The books post an expense to the root Expenses account and an income to the root Income
account; the line carries the category. Categories are one flat list: a name is unique among the categories of its kind
(capitals aside), and the built-in Uncategorised of each kind is made on demand."""

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
from ..repositories.shared_expense import SharedExpenseRepository
from ..schemas.account import RegisterEntry
from ..schemas.category import (
    CategoryCreate,
    CategoryDeleteResult,
    CategoryMergeResult,
    CategoryRead,
    CategoryUpdate,
)
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
    def _to_read(category: BudgetCategory) -> CategoryRead:
        return CategoryRead(
            id=category.id,
            name=category.name,
            kind="spending" if category.kind == "spending" else "earning",
            details=category.details,
            closed_on=category.closed_on,
            system_key=category.system_key,
        )

    def list(self, kind: str | None = None, include_closed: bool = False) -> builtins.list[CategoryRead]:
        return sorted(
            (
                self._to_read(c)
                for c in self.cr.list()
                if (kind is None or c.kind == kind) and (include_closed or c.closed_on is None)
            ),
            key=lambda c: (c.kind, c.name.lower()),
        )

    def read(self, category_id: UUID) -> CategoryRead | None:
        category = self.cr.read(category_id)
        return self._to_read(category) if category is not None else None

    def _get(self, category_id: UUID) -> BudgetCategory:
        category = self.cr.read(category_id)
        if category is None:
            raise ValueError(f"category '{category_id}' not found!")
        return category

    def _read(self, category_id: UUID) -> CategoryRead:
        read = self.read(category_id)
        if read is None:
            raise RuntimeError(f"category '{category_id}' should exist!")
        return read

    # ---- rules -------------------------------------------------------------------------------------

    def _check_name_free(self, name: str, kind: str, exclude: UUID | None = None) -> None:
        wanted = name.casefold()
        for other in self.cr.list():
            if other.kind == kind and other.id != exclude and other.name.casefold() == wanted:
                raise ValueError(f"you already have a category called '{other.name}'!")

    # ---- changing ----------------------------------------------------------------------------------

    def create(self, data: CategoryCreate) -> CategoryRead:
        ensure_room(len(self.cr.list()), settings.max_categories, "categories")
        self._check_name_free(data.name, data.kind)
        made = self.cr.add(BudgetCategory(user_id=self.uid, name=data.name, details=data.details, kind=data.kind))
        self.db.commit()
        return self._read(made.id)

    def update(self, category_id: UUID, data: CategoryUpdate) -> CategoryRead:
        """Rename it or change its note."""
        category = self._get(category_id)
        name = data.name if "name" in data.model_fields_set and data.name is not None else category.name
        if name != category.name:
            self._check_name_free(name, category.kind, exclude=category_id)
        category.name = name
        if "details" in data.model_fields_set:
            category.details = data.details
        self.cr.save(category)
        self.db.commit()
        return self._read(category_id)

    def close(self, category_id: UUID, today: date | None = None) -> CategoryRead:
        """No longer offered, history kept. Refused while a running recurring transaction still records into it."""
        category = self._get(category_id)
        rules = RecurringRepository.active_rules_for_categories(self.db, self.uid, {category.id})
        if rules:
            label = rules[0].payee or "a recurring transaction"
            raise CategoryInUseError(f"'{label}' still records into it: stop that recurring transaction first!")
        if category.closed_on is None:
            self.cr.set_closed([category.id], today or local_today())
        self.db.commit()
        return self._read(category.id)

    def reopen(self, category_id: UUID) -> CategoryRead:
        """Offer it again."""
        category = self._get(category_id)
        self.cr.set_closed([category.id], None)
        self.db.commit()
        return self._read(category_id)

    def _unused(self, category: BudgetCategory) -> bool:
        return not (
            self.cr.used_by_lines(category.id)
            or RecurringRepository.uses_category(self.db, self.uid, category.id)
            or SharedExpenseRepository(self.db, self.uid).uses_category(category.id)
            or category.system_key is not None
        )

    def delete(self, category_id: UUID) -> CategoryDeleteResult:
        """Remove an unused category for good (its planned amounts go with it); one with history (lines, categories
        inside it, a rule or a shared expense) is closed instead, so nothing that was recorded loses its meaning."""
        category = self._get(category_id)
        before = self._read(category_id)
        if not self._unused(category):
            return CategoryDeleteResult(outcome="closed", category=self.close(category_id))
        BudgetRepository(self.db, self.uid).delete_for_category(category_id)  # only a plan: it goes with the category
        self.cr.delete(category)
        self.db.commit()
        return CategoryDeleteResult(outcome="deleted", category=before)

    def merge(self, source: UUID, target: UUID, dry_run: bool = False) -> CategoryMergeResult:
        """Fold one category into another of the same kind: its lines, planned amounts, recurring rules and shared
        expenses become the target's, and the source is deleted. All or nothing."""
        origin, into = self._get(source), self._get(target)
        if source == target:
            raise ValueError("a category cannot be merged into itself!")
        if origin.system_key is not None or into.system_key is not None:
            raise ValueError("the built-in Uncategorised cannot be merged: merge a category into it instead.")
        if origin.kind != into.kind:
            raise ValueError("cannot merge a spending category into an earning one!")
        if into.closed_on is not None:
            raise ValueError(f"'{into.name}' is closed: reopen it first!")
        budget = BudgetRepository(self.db, self.uid)
        transaction_ids = self.tr.labelled(source)
        entries = self.register(source)
        result = CategoryMergeResult(
            dry_run=dry_run,
            merged=not dry_run,
            source=origin.name,
            into=into.name,
            balance_moved=entries[-1].balance if entries else Decimal("0.00"),
            entries_moved=len(transaction_ids),
            plan_months_moved=budget.months_for_category(source),
            recurring_rules_moved=RecurringRepository.rules_for_category(self.db, self.uid, source),
        )
        if dry_run:
            return result
        try:
            self.tr.relabel_category(source, target, self.origin)
            budget.merge_category(source, target)
            RecurringRepository.repoint_category(self.db, self.uid, source, target)
            SharedExpenseRepository(self.db, self.uid).repoint_category(source, target)
            self.cr.delete(origin)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return result

    def register(self, category_id: UUID) -> builtins.list[RegisterEntry]:
        """The entries that have a line labelled with the category, oldest first. Each one's change is signed by the kind's normal side (spending adds with a debit, earning with a
        credit), so the running balance adds up to what the category came to."""
        category = self._get(category_id)
        ids = {category_id}
        normal = PostingSide.DEBIT if category.kind == "spending" else PostingSide.CREDIT
        lines = self.tr.postings_for_categories(ids)
        changes: dict[UUID, Decimal] = {}
        for line in lines:
            changes[line.transaction_id] = changes.get(line.transaction_id, Decimal("0.00")) + (
                line.amount if line.side == normal else -line.amount
            )
        loaded = self.tr.read_many(builtins.list(changes))
        postings_of = self.tr.postings_for_transactions(builtins.list(changes))
        accounts = {a.id: a for a in self.ar.list()}
        transactions = sorted((loaded[t] for t in changes if t in loaded), key=lambda t: (t.date, t.created))
        related = self.tr.related_refs([t.related_id for t in transactions])
        entries: builtins.list[RegisterEntry] = []
        balance = Decimal("0.00")
        for transaction in transactions:
            balance += changes[transaction.id]
            counters: builtins.list[str] = []
            for posting in postings_of.get(transaction.id, []):
                account = accounts[posting.account_id]
                if AccountService.root_name(account, accounts) in GROUP_POSTING_ROOT_NAMES:
                    continue
                if account.name not in counters:
                    counters.append(account.name)
            entries.append(
                RegisterEntry(
                    transaction_id=transaction.id,
                    date=transaction.date,
                    payee=transaction.payee,
                    comment=transaction.comment,
                    counter_accounts=counters,
                    change=changes[transaction.id],
                    balance=balance,
                    related=related.get(transaction.related_id) if transaction.related_id else None,
                )
            )
        return entries

    def uncategorised(self, kind: str) -> CategoryRead:
        """The built-in Uncategorised of a kind, made the first time it is needed."""
        made = self.cr.ensure_uncategorised(kind)
        self.db.commit()
        return self._read(made.id)

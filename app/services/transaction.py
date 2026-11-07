"""Transactions and postings: the one place that validates and writes them (balanced, the person's own open accounts, limits)."""

import builtins
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from ..clock import local_midnight_utc
from ..config import settings
from ..currencies import Currency
from ..currencies import find as find_currency
from ..limits import ensure_room
from ..models import Account
from ..models.transaction import Posting, PostingSide, Transaction
from ..repositories import AccountRepository, CategoryRepository, ProfileRepository, TransactionRepository
from ..schemas.transaction import (
    MAX_BATCH,
    BatchEntryResult,
    BatchResult,
    PayeeDefaultRead,
    PayeeRouteRead,
    PostingCreate,
    PostingRead,
    RouteAccount,
    TagRead,
    TransactionCreate,
    TransactionPreview,
    TransactionRead,
    TransactionUpdate,
)
from ..tags import clean_name, clean_tag
from .account import GROUP_POSTING_ROOT_NAMES, AccountService

# How many recent entries the payee suggestions look at.
PAYEE_HISTORY = 300


@dataclass
class PayeeRoute:
    """How someone was paid (or paid you) the last time: the accounts of the newest entry with one account on each
    side, how many such entries there are, and the other routes seen."""

    payee: str
    count: int
    from_id: UUID
    to_id: UUID
    # The payee was typed in full (capitals aside), not just a part of it.
    exact: bool = False
    # Other (from, to, count) routes this payee was booked on, most used first.
    others: builtins.list[tuple[UUID, UUID, int]] = field(default_factory=list)


class InvalidPostingError(ValueError): ...


class InvalidPostingAccountError(InvalidPostingError): ...


class BatchError(InvalidPostingError):
    """A batch was refused as a whole: nothing was saved."""


class DuplicateReferenceError(InvalidPostingError):
    """A source's reference is already used by another entry."""


def _rows(postings) -> list[tuple[str, str, Decimal]]:
    return sorted((str(p.account_id), PostingSide(p.side).value, p.amount) for p in postings)


def _different_content(data: TransactionCreate, transaction_id: UUID) -> str:
    return (
        f"source '{data.source}' reference '{data.external_id}' is already recorded as the entry {transaction_id} "
        "with a different date or rows: change that entry, or use another reference!"
    )


def _same_content(existing: TransactionRead, data: TransactionCreate) -> bool:
    """Whether recording `data` again would only repeat `existing`: the same day and the same rows."""
    return existing.date == data.date and _rows(existing.postings) == _rows(data.postings)


def decimal_places(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


class TransactionService:
    def __init__(
        self,
        tr: TransactionRepository,
        ar: AccountRepository,
        pr: ProfileRepository | None = None,
        origin: str | None = None,
        contacts: bool = False,
    ):
        # Recorded on what this service creates or changes: "web", "api" or "mcp:<token name>".
        self.origin = origin
        # Only the contact services may post to a contact's accounts and change the entries they made: anything else
        # would leave a debt in the books without its obligation.
        self.contacts = contacts
        self.tr = tr
        self.ar = ar
        self.pr = pr or ProfileRepository(tr.db, tr.uid)
        self.cr = CategoryRepository(tr.db, tr.uid)
        self._currency: Currency | None = None

    def currency(self) -> Currency:
        if self._currency is None:
            self._currency = find_currency(self.pr.currency())
            if self._currency is None:
                raise RuntimeError("the profile names a currency finode does not know")
        return self._currency

    def _fill_accounts(self, postings, accounts: builtins.list[Account]) -> None:
        """Where a line posts: a line that names only its category posts to Expenses (a spending category) or Income
        (an earning one)."""
        roots = {a.name: a.id for a in accounts if a.parent_id is None}
        categories = {c.id: c for c in self.cr.list()}
        for posting in postings:
            if posting.account_id is not None:
                continue
            category = categories.get(posting.category_id)
            if category is None:
                raise InvalidPostingError(f"category '{posting.category_id}' not found!")
            posting.account_id = roots["Expenses" if category.kind == "spending" else "Income"]

    def _check_categories(
        self, postings, accounts_by_id: dict[UUID, Account], keep_categories: Collection[UUID] = frozenset()
    ) -> None:
        """A category named on a line is the person's own, open (unless the entry already used it) and fits the line:
        a spending category goes on Expenses (or an expense account) or on a payment out of the budget into an account
        outside it, an earning category on Income, and nothing goes on Equity."""
        named = [p for p in postings if p.category_id is not None]
        if not named:
            return
        categories = {c.id: c for c in self.cr.list()}
        for posting in named:
            category = categories.get(posting.category_id)
            if category is None:
                raise InvalidPostingError(f"category '{posting.category_id}' not found!")
            if category.closed_on is not None and category.id not in keep_categories:
                raise InvalidPostingError(f"category '{category.name}' is closed: reopen it to use it!")
            account = accounts_by_id[posting.account_id]
            root = AccountService.root_name(account, accounts_by_id)
            if root in GROUP_POSTING_ROOT_NAMES:
                wanted = "spending" if root == "Expenses" else "earning"
                if category.kind != wanted:
                    raise InvalidPostingError(
                        f"'{category.name}' is a {category.kind} category: it cannot go on a line to {root}!"
                    )
            elif root == "Equity":
                raise InvalidPostingError("a category cannot go on a line to an equity account!")
            elif account.on_budget:
                raise InvalidPostingError(
                    f"'{account.name}' is part of the budget: a category goes on the other side of the entry, "
                    "the account the money was spent on!"
                )
            elif category.kind != "spending":
                raise InvalidPostingError(
                    f"'{category.name}' is an earning category: it can only go on a line to Income!"
                )

    def _resolve(
        self,
        data: TransactionCreate | TransactionUpdate,
        keep_closed: Collection[UUID] = frozenset(),
        keep_categories: Collection[UUID] = frozenset(),
        on: date | None = None,
    ) -> None:
        """Check the postings: the accounts can be posted to, the amounts fit the currency and the entry balances.
        `on` is the entry's date, which no line may post before."""
        postings = data.postings
        if postings is None:
            return
        for posting in postings:
            if on is not None and posting.posted_on is not None and posting.posted_on < on:
                raise InvalidPostingError("an account cannot post a line before the entry's own date!")

        if settings.max_postings_per_transaction and len(postings) > settings.max_postings_per_transaction:
            raise InvalidPostingError(
                f"a transaction can have at most {settings.max_postings_per_transaction} postings: split it into several!"
            )
        currency = self.currency()
        # One read of the account list serves every posting (it is remembered for the session), instead of two
        # queries per posting: a split of 20 rows used to cost 40 round trips.
        every_account = self.ar.list()
        accounts_by_id = {a.id: a for a in every_account}
        self._fill_accounts(postings, every_account)
        has_children = {a.parent_id for a in accounts_by_id.values() if a.parent_id is not None}
        contact_accounts = self.ar.contact_account_ids()
        for posting in postings:
            account = accounts_by_id.get(posting.target)
            if not account:
                raise ValueError(f"account '{posting.account_id}' not found!")
            if account.parent_id is None and account.name not in GROUP_POSTING_ROOT_NAMES:
                raise InvalidPostingAccountError(f"cannot post to root account '{account.name}'!")
            if not self.contacts and account.id in contact_accounts:
                raise InvalidPostingAccountError(
                    f"'{account.name}' belongs to a contact: lend, borrow, share an expense or settle up "
                    "from the contact instead!"
                )
            if account.closed_on is not None and account.id not in keep_closed:
                raise InvalidPostingAccountError(f"account '{account.name}' is closed: reopen it to use it!")
            if (
                account.id in has_children
                and AccountService.root_name(account, accounts_by_id) not in GROUP_POSTING_ROOT_NAMES
            ):
                raise InvalidPostingAccountError(
                    f"cannot post to account '{account.name}' because it has sub-accounts!"
                )
            if decimal_places(posting.amount) > currency.decimals:
                raise InvalidPostingError(
                    f"{currency.code} amounts can have at most {currency.decimals} "
                    f"decimal place{'' if currency.decimals == 1 else 's'}!"
                )

        self._check_categories(postings, accounts_by_id, keep_categories)

        # Expenses and Income take many lines (one per category), so on them it is the same category on both sides that
        # moves money from itself to itself; any other account may not be on both sides at all.
        def whole(p) -> tuple:
            books = AccountService.root_name(accounts_by_id[p.account_id], accounts_by_id) in GROUP_POSTING_ROOT_NAMES
            return (p.account_id, p.category_id if books else None)

        both = {whole(p) for p in postings if p.side == PostingSide.DEBIT} & {
            whole(p) for p in postings if p.side == PostingSide.CREDIT
        }
        if both:
            account_id, category_id = min(both, key=str)
            named = {c.id: c.name for c in self.cr.list()}
            name = named.get(category_id) if category_id in named else accounts_by_id[account_id].name
            raise InvalidPostingError(
                f"'{name}' is on both sides of the entry: money cannot move from an account to itself. "
                "Leave it out, or enter only the difference!"
            )

        debits = sum((p.amount for p in postings if p.side == PostingSide.DEBIT), Decimal(0))
        credits = sum((p.amount for p in postings if p.side == PostingSide.CREDIT), Decimal(0))
        if debits != credits:
            raise InvalidPostingError(f"debits and credits must balance (debits {debits:f}, credits {credits:f})!")

    def _posting_to_read(self, posting: Posting) -> PostingRead:
        return PostingRead(
            id=posting.id,
            transaction_id=posting.transaction_id,
            account_id=posting.account_id,
            side=posting.side,
            amount=posting.amount,
            category_id=posting.category_id,
            posted_on=posting.posted_on,
            created=posting.created,
            updated=posting.updated,
        )

    def _to_read(
        self,
        transaction: Transaction,
        postings: list[Posting] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> TransactionRead:
        return TransactionRead(
            tags=tags if tags is not None else self.tr.tag_names(transaction.id),
            id=transaction.id,
            date=transaction.date,
            payee=transaction.payee,
            comment=transaction.comment,
            created_via=transaction.created_via,
            updated_via=transaction.updated_via,
            recurring_id=transaction.recurring_id,
            related_id=transaction.related_id,
            source=transaction.source,
            external_id=transaction.external_id,
            source_url=transaction.source_url,
            postings=[
                self._posting_to_read(posting)
                for posting in (postings if postings is not None else self.tr.postings(transaction.id))
            ],
            created=transaction.created,
            updated=transaction.updated,
        )

    def _category_paths(self) -> dict[UUID, str]:
        """Each category as the journal account it stands for: Expenses:Food:Groceries, Income:Salary."""
        found = {c.id: c for c in self.cr.list()}
        paths: dict[UUID, str] = {}
        for category_id, category in found.items():
            chain, current = [], category
            while current is not None:
                chain.append(current.name)
                current = found.get(current.parent_id) if current.parent_id else None
            paths[category_id] = (
                ("Expenses" if category.kind == "spending" else "Income") + ":" + ":".join(reversed(chain))
            )
        return paths

    def _account_paths(self) -> dict[UUID, str]:
        accounts = {a.id: a for a in self.ar.list()}
        paths: dict[UUID, str] = {}
        for account_id, account in accounts.items():
            chain: builtins.list[str] = []
            seen: set[UUID] = set()
            current: Account | None = account
            while current is not None and current.id not in seen:
                seen.add(current.id)
                chain.append(current.name)
                current = accounts.get(current.parent_id) if current.parent_id else None
            paths[account_id] = ":".join(reversed(chain))
        return paths

    def validate(self, data: TransactionCreate) -> None:
        """Raise what create would raise, without saving anything."""
        self._resolve(data, on=data.date)

    def _check_related(self, related_id: UUID | None, transaction_id: UUID | None = None) -> None:
        """The entry this one is related to must be the person's own, and following the links must never lead back here."""
        if related_id is None:
            return
        if transaction_id is not None and related_id == transaction_id:
            raise InvalidPostingError("an entry cannot be related to itself!")
        seen: set[UUID] = set()
        link: UUID | None = related_id
        while link is not None and link not in seen:
            found = self.tr.read(link)
            if found is None:
                raise InvalidPostingError("the related transaction was not found!")
            if transaction_id is not None and found.related_id == transaction_id:
                raise InvalidPostingError("that entry is already related to this one!")
            seen.add(link)
            link = found.related_id

    def _check_limits(self) -> None:
        ensure_room(self.tr.count(), settings.max_transactions, "transactions")
        if settings.max_transactions_per_day and self.origin not in ("recurring", "import"):
            midnight = local_midnight_utc()
            made = self.tr.count_since(midnight, leaving_out=("recurring", "import"))
            ensure_room(made, settings.max_transactions_per_day, "new transactions a day")

    def recorded_today(self) -> int:
        """New transactions today, counted as the daily limit counts them (not recurring rules or imports)."""
        return self.tr.count_since(local_midnight_utc(), leaving_out=("recurring", "import"))

    def count(self) -> int:
        return self.tr.count()

    def last_change(self) -> datetime | None:
        return self.tr.last_change()

    def _check_reference(self, source: str | None, external_id: str | None, transaction_id: UUID | None = None) -> None:
        """A source's reference is used once: another entry with it (not the one being changed) is refused."""
        if not external_id:
            return
        if not source:
            raise InvalidPostingError("a reference (external_id) needs a source, for example 'gmail' or 'upi'!")
        found = self.tr.find_by_reference(source, external_id)
        if found is not None and found.id != transaction_id:
            raise DuplicateReferenceError(
                f"source '{source}' reference '{external_id}' is already used by the entry {found.id}!"
            )

    def _refuse_contact_entry(self, transaction_id: UUID, what: str) -> None:
        if not self.contacts and self.tr.owned_by_contacts(transaction_id):
            raise InvalidPostingError(
                f"this entry belongs to a contact and can't be {what} here: reverse it from the contact's page!"
            )

    def _check_new(self, data: TransactionCreate) -> None:
        """Everything creating an entry checks before it saves."""
        self._check_limits()
        self._resolve(data, on=data.date)
        self._check_related(data.related_id)
        self._check_reference(data.source, data.external_id)
        self._check_tags(data.tags)

    def preview_create(self, data: TransactionCreate) -> TransactionPreview:
        """What `create_once` would do, with nothing saved: the same checks, the same refusals."""
        found = None
        if data.source and data.external_id:
            found = self.tr.find_by_reference(data.source, data.external_id)
            if found is not None:
                self._fill_accounts(data.postings, self.ar.list())
                existing = self._to_read(found)
                if not _same_content(existing, data):
                    raise DuplicateReferenceError(_different_content(data, found.id))
        if found is None:
            self._check_new(data)
        return TransactionPreview(
            id=found.id if found else None,
            already_recorded=found.id if found else None,
            **data.model_dump(exclude={"postings"}),
            postings=data.postings,
        )

    def record_batch(self, items: Sequence[TransactionCreate], dry_run: bool = False) -> BatchResult:
        """Record several entries as one: either all of them are saved or none is. An entry whose source and
        reference are already recorded with the same date and rows is skipped (it is not an error, so retrying a
        batch is safe). Every problem is collected and reported by its place in the batch."""
        if not items:
            raise BatchError("a batch needs at least one entry!")
        if len(items) > MAX_BATCH:
            raise BatchError(f"a batch can hold at most {MAX_BATCH} entries: send it in parts!")
        problems: list[str] = []
        previews: list[TransactionPreview | None] = []
        seen: dict[tuple[str, str], int] = {}
        for number, item in enumerate(items, start=1):
            try:
                if item.source and item.external_id:
                    key = (item.source, item.external_id)
                    if key in seen:
                        raise InvalidPostingError(
                            f"it repeats the reference '{item.external_id}' of source '{item.source}' that "
                            f"entry {seen[key]} has!"
                        )
                    seen[key] = number
                previews.append(self.preview_create(item))
            except (ValueError, LookupError) as e:
                problems.append(f"entry {number}: {e}")
                previews.append(None)
        new = sum(1 for p in previews if p is not None and p.already_recorded is None)
        if not problems and new:
            try:
                ensure_room(self.tr.count(), settings.max_transactions, "transactions", adding=new)
                if settings.max_transactions_per_day and self.origin not in ("recurring", "import"):
                    ensure_room(
                        self.recorded_today(), settings.max_transactions_per_day, "new transactions a day", adding=new
                    )
            except ValueError as e:
                problems.append(str(e))
        if problems:
            raise BatchError("nothing was saved. " + " ".join(problems))
        if dry_run:
            entries = [
                BatchEntryResult(
                    item=number,
                    status="already_recorded" if preview.already_recorded else "would_record",
                    transaction=preview,
                )
                for number, preview in enumerate(cast(list[TransactionPreview], previews), start=1)
            ]
            return BatchResult(dry_run=True, saved=False, created=0, already_recorded=len(items) - new, entries=entries)
        made: dict[int, Transaction] = {}
        try:
            for number, (item, preview) in enumerate(
                zip(items, cast(list[TransactionPreview], previews), strict=True), start=1
            ):
                if preview.already_recorded is None:
                    made[number] = self.tr.create(item, self.origin)
            self.tr.db.commit()
        except Exception:
            self.tr.db.rollback()
            raise
        entries = []
        for number, preview in enumerate(cast(list[TransactionPreview], previews), start=1):
            if number in made:
                self.tr.db.refresh(made[number])
                entries.append(
                    BatchEntryResult(item=number, status="recorded", transaction=self._to_read(made[number]))
                )
            else:
                existing = self.read(cast(UUID, preview.already_recorded))
                entries.append(
                    BatchEntryResult(
                        item=number, status="already_recorded", transaction=cast(TransactionRead, existing)
                    )
                )
        return BatchResult(
            dry_run=False, saved=True, created=len(made), already_recorded=len(items) - len(made), entries=entries
        )

    def preview_update(self, transaction_id: UUID, data: TransactionUpdate) -> TransactionPreview:
        """What `update` would save, with nothing saved: the entry as it would read afterwards."""
        existing = self._check_update(transaction_id, data)
        changes = data.model_dump(exclude_unset=True, exclude={"postings", "tags"})
        merged: dict[str, Any] = {
            key: changes[key] if key in changes else getattr(existing, key)
            for key in ("date", "payee", "comment", "related_id", "source", "external_id", "source_url")
        }
        merged["tags"] = data.tags if data.tags is not None else self.tr.tag_names(transaction_id)
        postings = (
            data.postings
            if data.postings is not None
            else [
                PostingCreate(account_id=p.account_id, side=p.side, amount=p.amount, posted_on=p.posted_on)
                for p in self.tr.postings(transaction_id)
            ]
        )
        return TransactionPreview(id=transaction_id, **merged, postings=postings)

    def preview_delete(self, transaction_id: UUID) -> TransactionPreview:
        """The entry a delete would remove (nothing is deleted)."""
        existing = self.read(transaction_id)
        if existing is None:
            raise ValueError(f"transaction '{transaction_id}' not found!")
        return TransactionPreview(
            id=transaction_id,
            date=existing.date,
            payee=existing.payee,
            comment=existing.comment,
            related_id=existing.related_id,
            source=existing.source,
            external_id=existing.external_id,
            source_url=existing.source_url,
            postings=[
                PostingCreate(account_id=p.account_id, side=p.side, amount=p.amount, posted_on=p.posted_on)
                for p in existing.postings
            ],
        )

    def create_once(
        self, data: TransactionCreate, recurring: tuple[UUID, date] | None = None
    ) -> tuple[TransactionRead, bool]:
        """Record an entry, or, when its source and reference are already recorded with the same date and rows,
        return that entry and change nothing. The flag is True when a new entry was made. The same reference with
        different content is an error (the reference is for one entry)."""
        if data.source and data.external_id:
            found = self.tr.find_by_reference(data.source, data.external_id)
            if found is not None:
                self._fill_accounts(data.postings, self.ar.list())
                existing = self._to_read(found)
                if _same_content(existing, data):
                    return existing, False
                raise DuplicateReferenceError(_different_content(data, found.id))
        return self.create(data, recurring), True

    def create(
        self, data: TransactionCreate, recurring: tuple[UUID, date] | None = None, *, commit: bool = True
    ) -> TransactionRead:
        """Record an entry. `commit=False` leaves the commit to the caller (a workflow that saves more with it)."""
        self._check_new(data)
        transaction = self.tr.create(data, self.origin, recurring)
        if commit:
            self.tr.db.commit()
            self.tr.db.refresh(transaction)
        return self._to_read(transaction)

    def read(self, transaction_id: UUID) -> TransactionRead | None:
        transaction = self.tr.read(transaction_id)
        if not transaction:
            return None
        return self._to_read(transaction)

    def related(self, transaction_id: UUID) -> list[TransactionRead]:
        """The entries that are related to this one, oldest first."""
        rows = self.tr.related_to(transaction_id)
        tids = [t.id for t in rows]
        postings, tags = self.tr.postings_for_transactions(tids), self.tr.tag_map(tids)
        return [self._to_read(t, postings.get(t.id, []), tags.get(t.id, [])) for t in rows]

    def _account_subtree(self, account_id: UUID) -> list[UUID]:
        accounts = self.ar.list()
        if not any(a.id == account_id for a in accounts):
            raise ValueError(f"account '{account_id}' not found!")
        children: dict[UUID, list[UUID]] = {}
        for a in accounts:
            if a.parent_id is not None:
                children.setdefault(a.parent_id, []).append(a.id)
        subtree = [account_id]
        to_visit = [account_id]
        while to_visit:
            for child in children.get(to_visit.pop(), []):
                subtree.append(child)
                to_visit.append(child)
        return subtree

    def _category_subtree(self, category_id: UUID) -> builtins.list[UUID]:
        """A category and the categories inside it."""
        categories = self.cr.list()
        if not any(c.id == category_id for c in categories):
            raise ValueError(f"category '{category_id}' not found!")
        return [c.id for c in categories if c.id == category_id or c.parent_id == category_id]

    def _args(self, account, kind, also):
        account_ids = self._account_subtree(account) if account else None
        also_ids = self._category_subtree(also) if also else None
        if kind not in (None, "", "expense", "income", "transfer"):
            raise ValueError("the kind must be expense, income or transfer!")
        kind_accounts = None
        if kind:
            roots = {a.name: a.id for a in self.ar.list() if a.parent_id is None}
            kind_accounts = tuple(
                self._account_subtree(roots[name]) if name in roots else [] for name in ("Expenses", "Income")
            )
        return account_ids, kind_accounts, also_ids

    def list(
        self,
        account: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
        offset: int = 0,
        text: str | None = None,
        kind: str | None = None,
        also: UUID | None = None,
        payee: str | None = None,
        source: str | None = None,
        external_id: str | None = None,
        tag: str | None = None,
    ) -> builtins.list[TransactionRead]:
        account_ids, kind_accounts, also_ids = self._args(account, kind, also)
        transactions = self.tr.list(
            account_ids,
            date_from,
            date_to,
            limit,
            offset,
            (text or "").strip() or None,
            kind or None,
            kind_accounts,
            also_ids,
            (payee or "").strip() or None,
            (source or "").strip().lower() or None,
            (external_id or "").strip() or None,
            clean_tag(tag or "") or None,
        )
        tids = [t.id for t in transactions]
        postings, tags = (
            self.tr.postings_for_transactions(tids),
            self.tr.tag_map(tids),
        )  # one query each, not one per row
        return [
            self._to_read(transaction, postings.get(transaction.id, []), tags.get(transaction.id, []))
            for transaction in transactions
        ]

    def page(
        self,
        offset: int,
        size: int,
        account: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        text: str | None = None,
        kind: str | None = None,
        also: UUID | None = None,
        payee: str | None = None,
        tag: str | None = None,
    ) -> tuple[builtins.list[TransactionRead], int]:
        """A chunk of the list for "Show more" and how many entries match in all. A day is never split between two
        chunks: the chunk runs on to the end of the day its last entry falls on."""
        account_ids, kind_accounts, also_ids = self._args(account, kind, also)
        text, payee = (text or "").strip() or None, (payee or "").strip() or None

        def read(first, last, limit, start):
            return self.tr.list(
                account_ids, first, last, limit, start, text, kind or None, kind_accounts, also_ids, payee, tag=tag
            )

        found = read(date_from, date_to, size + 1, offset)
        more_exist = len(found) > size
        if more_exist and found[size].date == found[size - 1].date:
            day = found[size - 1].date  # the day goes on: take all of it
            found = [t for t in found[:size] if t.date != day] + read(
                max(day, date_from) if date_from else day, day, None, 0
            )
        else:
            found = found[:size]
        if more_exist:
            total = self.tr.count_matching(
                account_ids, date_from, date_to, text, kind or None, kind_accounts, also_ids, payee, tag=tag
            )
        else:
            total = offset + len(found)  # nothing is left, so there is no need to count
        tids = [t.id for t in found]
        postings, tags = (
            self.tr.postings_for_transactions(tids),
            self.tr.tag_map(tids),
        )  # one query each, not one per row
        found = [self._to_read(t, postings.get(t.id, []), tags.get(t.id, [])) for t in found]
        return found, total

    def tagged(self) -> builtins.list[TransactionRead]:
        """Every entry that carries at least one tag, newest first, with its postings (three queries however many)."""
        found = self.tr.tagged()
        tids = [t.id for t in found]
        postings, tags = self.tr.postings_for_transactions(tids), self.tr.tag_map(tids)
        return [self._to_read(t, postings.get(t.id, []), tags.get(t.id, [])) for t in found]

    def tags(self) -> builtins.list[TagRead]:
        """The person's tags, the most used first, each with how many entries carry it and its last day."""
        return [TagRead(tag=name, uses=uses, last_used=last) for name, uses, last in self.tr.tag_stats()]

    def _check_tags(self, names: builtins.list[str]) -> None:
        """A person may have only so many different tags; the ones an entry names that do not exist yet count."""
        new = [name for name in names if not self.tr.tag_exists(name)]
        if new:
            ensure_room(self.tr.count_tags(), settings.max_tags, "tags", adding=len(new))

    def rename_tag(self, old: str, new: str) -> int:
        """Give a tag a new name; when the new name is another tag of the person's the two become one. Returns how many
        entries now carry it."""
        old, new = clean_name(old), clean_name(new)
        if old == new:
            raise ValueError("that is already the tag's name!")
        self.tr.rename_tag(old, new)
        self.tr.db.commit()
        return next((uses for name, uses, _ in self.tr.tag_stats() if name == new), 0)

    def merge_tags(self, source: str, target: str) -> int:
        """Put the entries of one tag under another existing tag and remove the first. Returns how many entries carry the
        target now."""
        source, target = clean_name(source), clean_name(target)
        if not self.tr.tag_exists(target):
            raise LookupError(f"no tag is called '{target}'! Rename the tag instead.")
        return self.rename_tag(source, target)

    def delete_tag(self, name: str) -> int:
        """Take a tag off every entry and remove it (the entries stay as they are); returns how many entries had it."""
        removed = self.tr.delete_tag(clean_name(name))
        self.tr.db.commit()
        return removed

    def payee_routes(self, query: str = "", limit: int = 6, history: int = PAYEE_HISTORY) -> builtins.list[PayeeRoute]:
        """Who the person pays (or is paid by) most, each with the accounts of the newest entry to repeat.

        Only entries with one account on each side count (a split has no single route), only accounts that can
        still be used, and not opening balances. Payees used often come first; a query narrows them to those
        starting with, then containing, what was typed (an exact match first)."""
        accounts = {a.id: a for a in self.ar.list()}
        usable = {account_id for account_id, a in accounts.items() if a.parent_id is not None and a.closed_on is None}
        categories = {c.id: c for c in self.cr.list()}
        usable |= {category_id for category_id, c in categories.items() if c.closed_on is None}

        def route_id(p: PostingRead) -> UUID:
            """What the Add screen picks for a line: the category on a line to Expenses or Income, else the account."""
            on_books = AccountService.root_name(accounts[p.account_id], accounts) in GROUP_POSTING_ROOT_NAMES
            return p.category_id if on_books and p.category_id is not None else p.account_id

        wanted = query.strip().lower()
        seen: dict[str, dict] = {}
        for position, t in enumerate(self.list(limit=history)):
            credits = [p for p in t.postings if p.side == PostingSide.CREDIT]
            debits = [p for p in t.postings if p.side == PostingSide.DEBIT]
            payee = (t.payee or "").strip()
            if not payee or len(credits) != 1 or len(debits) != 1:
                continue
            source, target = route_id(credits[0]), route_id(debits[0])
            if source not in usable or target not in usable:
                continue
            if "Equity" in (
                AccountService.root_name(accounts[credits[0].account_id], accounts),
                AccountService.root_name(accounts[debits[0].account_id], accounts),
            ):
                continue  # opening balances are not a payee
            entry = seen.setdefault(
                payee.lower(),
                {"payee": payee, "count": 0, "route": (source, target), "order": position, "routes": Counter()},
            )
            entry["count"] += 1  # the first one seen is the newest: its route is the one repeated
            entry["routes"][(source, target)] += 1
        ranked = []
        for key, entry in seen.items():
            if wanted and wanted not in key:
                continue
            others = [(f, to, n) for (f, to), n in entry["routes"].most_common() if (f, to) != entry["route"]]
            ranked.append(
                (
                    0 if wanted and key == wanted else 1 if key.startswith(wanted) else 2,
                    -entry["count"],
                    entry["order"],
                    PayeeRoute(
                        entry["payee"],
                        entry["count"],
                        *entry["route"],
                        exact=bool(wanted) and key == wanted,
                        others=others,
                    ),
                )
            )
        ranked.sort(key=lambda r: r[:3])
        return [r[3] for r in ranked[:limit]]

    def payee_defaults(self, query: str = "", limit: int = 5) -> builtins.list[PayeeDefaultRead]:
        """`payee_routes` with account paths and the kind of entry, for the API and the assistants."""
        paths = self._account_paths()
        categories = {c.id: c for c in self.cr.list()}
        paths.update(self._category_paths())  # a category reads like the journal's account: Expenses:Food:Groceries

        def side(account_id: UUID) -> RouteAccount:
            return RouteAccount(id=account_id, path=paths.get(account_id, "?"))

        found = []
        for r in self.payee_routes(query, limit):
            if r.to_id in categories and categories[r.to_id].kind == "spending":
                kind = "expense"
            elif r.from_id in categories and categories[r.from_id].kind == "earning":
                kind = "income"
            else:
                kind = "transfer"
            found.append(
                PayeeDefaultRead(
                    payee=r.payee,
                    uses=r.count,
                    exact=r.exact,
                    kind=kind,
                    from_account=side(r.from_id),
                    to_account=side(r.to_id),
                    other_routes=[
                        PayeeRouteRead(from_account=side(f), to_account=side(t), uses=n) for f, t, n in r.others[:3]
                    ],
                )
            )
        return found

    def payees(self) -> builtins.list[tuple[str, int]]:
        """Who you have paid or been paid by, most used first, for the transactions filter."""
        return self.tr.payees()

    def _check_update(self, transaction_id: UUID, data: TransactionUpdate) -> Transaction:
        """Everything changing an entry checks before it saves; returns the entry as it stands."""
        existing = self.tr.read(transaction_id)
        if not existing:
            raise ValueError(f"transaction '{transaction_id}' not found!")
        self._refuse_contact_entry(transaction_id, "changed")
        # Postings an entry already has on an account that was closed since stay allowed, so it can still be edited.
        existing_lines = self.tr.postings(transaction_id)
        kept = {p.account_id for p in existing_lines}
        kept_categories = {p.category_id for p in existing_lines if p.category_id is not None}
        day = data.date if "date" in data.model_fields_set and data.date is not None else existing.date
        self._resolve(data, kept, kept_categories, on=day)
        if data.postings is None and "date" in data.model_fields_set:
            for line in existing_lines:
                if line.posted_on is not None and line.posted_on < day:
                    raise InvalidPostingError(
                        "move the lines' posting dates too: one would post before the entry's date!"
                    )
        if "related_id" in data.model_fields_set:
            self._check_related(data.related_id, transaction_id)
        if data.tags:
            self._check_tags(data.tags)
        if data.model_fields_set & {"source", "external_id"}:
            self._check_reference(
                data.source if "source" in data.model_fields_set else existing.source,
                data.external_id if "external_id" in data.model_fields_set else existing.external_id,
                transaction_id,
            )
        return existing

    def update(
        self,
        transaction_id: UUID,
        data: TransactionUpdate,
        *,
        commit: bool = True,
    ) -> TransactionRead | None:
        self._check_update(transaction_id, data)
        transaction = self.tr.update(transaction_id, data, self.origin)
        if not transaction:
            raise RuntimeError(f"failed to update transaction '{transaction_id}'!")
        if commit:
            self.tr.db.commit()
            self.tr.db.refresh(transaction)
        return self._to_read(transaction)

    def label_payment(self, transaction_id: UUID, category_id: UUID) -> TransactionRead:
        """Give an entry's unlabelled payments into accounts outside the budget (a loan, a fund) a category."""
        entry = self.read(transaction_id)
        if entry is None:
            raise ValueError(f"transaction '{transaction_id}' not found!")
        accounts = {a.id: a for a in self.ar.list()}
        rows, changed = [], False
        for p in entry.postings:
            account = accounts[p.account_id]
            waiting = (
                p.side == PostingSide.DEBIT
                and p.category_id is None
                and not account.on_budget
                and AccountService.root_name(account, accounts) in ("Assets", "Liabilities")
            )
            changed = changed or waiting
            rows.append(
                PostingCreate(
                    account_id=p.account_id,
                    side=p.side,
                    amount=p.amount,
                    category_id=category_id if waiting else p.category_id,
                    posted_on=p.posted_on,
                )
            )
        if not changed:
            raise ValueError("this entry has no payment waiting for a category!")
        updated = self.update(transaction_id, TransactionUpdate(postings=rows))
        if updated is None:
            raise ValueError(f"transaction '{transaction_id}' not found!")
        return updated

    def delete(self, transaction_id: UUID, *, commit: bool = True) -> TransactionRead | None:
        self._refuse_contact_entry(transaction_id, "deleted")
        transaction = self.read(transaction_id)
        deleted = self.tr.delete(transaction_id, self.origin)
        if not deleted:
            raise ValueError(f"transaction '{transaction_id}' not found!")
        if commit:
            self.tr.db.commit()
        return transaction

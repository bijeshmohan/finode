"""Transactions and postings: the one place that validates and writes them (balanced, the person's own open accounts, limits), plus history, deleted entries and restoring."""

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
from ..repositories.transaction import comparable_snapshot
from ..schemas.transaction import (
    MAX_BATCH,
    BatchEntryResult,
    BatchResult,
    ChangeRead,
    HistoryPosting,
    HistoryRead,
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
from ..tags import clean_name, clean_names, clean_tag
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


# How many deleted entries the recently-deleted page lists.
RESTORABLE_LIMIT = 50


class InvalidPostingError(ValueError): ...


class InvalidPostingAccountError(InvalidPostingError): ...


class BatchError(InvalidPostingError):
    """A batch was refused as a whole: nothing was saved."""


class DuplicateReferenceError(InvalidPostingError):
    """A source's reference is already used by another entry."""


def _rows(postings) -> list[tuple[str, str, Decimal]]:
    return sorted((str(p.account), PostingSide(p.side).value, p.amount) for p in postings)


def _where(p: dict, paths: dict[UUID, str], categories: dict[UUID, str]) -> str:
    """Where a snapshot's line posted, as a journal would write it: a line on Expenses or Income by its category
    (Expenses:Food:Groceries), any other line by its account."""
    path = paths.get(UUID(p["account"]), p["account"])
    if path in ("Expenses", "Income") and p.get("category") and UUID(p["category"]) in categories:
        return categories[UUID(p["category"])]
    return path


def _diff(before: dict, after: dict, paths: dict[UUID, str], categories: dict[UUID, str] | None = None) -> dict:
    """What an update changed between two snapshots: fields as {"from", "to"}, rows added, removed or changed."""
    categories = categories or {}
    before, after = comparable_snapshot(before), comparable_snapshot(after)
    changes: dict = {}
    for key, label in (("date", "date"), ("payee", "payee"), ("comment", "note")):
        if before.get(key) != after.get(key):
            changes[label] = {"from": before.get(key), "to": after.get(key)}
    keys = ("source", "external_id", "source_url")
    if any(before.get(k) != after.get(k) for k in keys):
        changes["reference"] = {
            "from": {k: before.get(k) for k in keys},
            "to": {k: after.get(k) for k in keys},
        }

    def rows(snapshot: dict) -> dict[tuple[str, str], Decimal]:
        found: dict[tuple[str, str], Decimal] = {}
        for p in snapshot.get("postings", []):
            key = (_where(p, paths, categories), p["side"])
            found[key] = found.get(key, Decimal(0)) + Decimal(p["amount"])
        return found

    def labels(snapshot: dict) -> dict[tuple[str, str], tuple[str | None, ...]]:
        found: dict[tuple[str, str], list[str | None]] = {}
        for p in snapshot.get("postings", []):
            key = (_where(p, paths, categories), p["side"])
            found.setdefault(key, []).append(p.get("category"))
        return {key: tuple(sorted(value, key=str)) for key, value in found.items()}

    old, new = rows(before), rows(after)
    old_labels, new_labels = labels(before), labels(after)
    added = [{"account": a, "side": s, "amount": new[a, s]} for a, s in new if (a, s) not in old]
    removed = [{"account": a, "side": s, "amount": old[a, s]} for a, s in old if (a, s) not in new]
    changed = [
        {"account": a, "side": s, "from": old[a, s], "to": new[a, s]}
        for a, s in new
        if (a, s) in old and old[a, s] != new[a, s]
    ]
    # A line moved to another category (only when both snapshots recorded categories at all).
    relabelled = [
        {"account": a, "side": s, "category_from": old_labels[a, s], "category_to": new_labels[a, s]}
        for a, s in new
        if (a, s) in old
        and old[a, s] == new[a, s]
        and old_labels[a, s] != new_labels[a, s]
        and all(c is not None for c in old_labels[a, s] + new_labels[a, s])
    ]
    if added or removed or changed or relabelled:
        rows_changed: dict[str, Any] = {"added": added, "removed": removed, "changed": changed}
        if relabelled:
            rows_changed["relabelled"] = relabelled
        changes["postings"] = rows_changed
    return changes


def _different_content(data: TransactionCreate, tid: UUID) -> str:
    return (
        f"source '{data.source}' reference '{data.external_id}' is already recorded as the entry {tid} "
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
    ):
        # Recorded on what this service creates or changes: "web", "api" or "mcp:<token name>".
        self.origin = origin
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
        roots = {a.name: a.aid for a in accounts if a.parent_id is None}
        categories = {c.bcid: c for c in self.cr.list()}
        for posting in postings:
            if posting.account is not None:
                continue
            category = categories.get(posting.category)
            if category is None:
                raise InvalidPostingError(f"category with bcid '{posting.category}' not found!")
            posting.account = roots["Expenses" if category.kind == "spending" else "Income"]

    def _check_categories(
        self, postings, accounts_by_id: dict[UUID, Account], keep_categories: Collection[UUID] = frozenset()
    ) -> None:
        """A category named on a line is the person's own, open (unless the entry already used it) and fits the line:
        a spending category goes on Expenses (or an expense account) or on a payment out of the budget into an account
        outside it, an earning category on Income, and nothing goes on Equity."""
        named = [p for p in postings if p.category is not None]
        if not named:
            return
        categories = {c.bcid: c for c in self.cr.list()}
        for posting in named:
            category = categories.get(posting.category)
            if category is None:
                raise InvalidPostingError(f"category with bcid '{posting.category}' not found!")
            if category.closed_on is not None and category.bcid not in keep_categories:
                raise InvalidPostingError(f"category '{category.name}' is closed: reopen it to use it!")
            account = accounts_by_id[posting.account]
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
    ) -> None:
        """Check the postings: the accounts can be posted to, the amounts fit the currency and the entry balances."""
        postings = data.postings
        if postings is None:
            return

        if settings.max_postings_per_transaction and len(postings) > settings.max_postings_per_transaction:
            raise InvalidPostingError(
                f"a transaction can have at most {settings.max_postings_per_transaction} postings: split it into several!"
            )
        currency = self.currency()
        # One read of the account list serves every posting (it is remembered for the session), instead of two
        # queries per posting: a split of 20 rows used to cost 40 round trips.
        every_account = self.ar.list()
        accounts_by_id = {a.aid: a for a in every_account}
        self._fill_accounts(postings, every_account)
        has_children = {a.parent_id for a in accounts_by_id.values() if a.parent_id is not None}
        for posting in postings:
            account = accounts_by_id.get(posting.target)
            if not account:
                raise ValueError(f"account with aid '{posting.account}' not found!")
            if account.parent_id is None and account.name not in GROUP_POSTING_ROOT_NAMES:
                raise InvalidPostingAccountError(f"cannot post to root account '{account.name}'!")
            if account.closed_on is not None and account.aid not in keep_closed:
                raise InvalidPostingAccountError(f"account '{account.name}' is closed: reopen it to use it!")
            if (
                account.aid in has_children
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
            books = AccountService.root_name(accounts_by_id[p.account], accounts_by_id) in GROUP_POSTING_ROOT_NAMES
            return (p.account, p.category if books else None)

        both = {whole(p) for p in postings if p.side == PostingSide.DEBIT} & {
            whole(p) for p in postings if p.side == PostingSide.CREDIT
        }
        if both:
            account_id, category_id = min(both, key=str)
            named = {c.bcid: c.name for c in self.cr.list()}
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
            pid=posting.pid,
            transaction=posting.transaction,
            account=posting.account,
            side=posting.side,
            amount=posting.amount,
            category=posting.category_id,
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
            tags=tags if tags is not None else self.tr.tag_names(transaction.tid),
            tid=transaction.tid,
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
                for posting in (postings if postings is not None else self.tr.postings(transaction.tid))
            ],
            created=transaction.created,
            updated=transaction.updated,
        )

    def _category_paths(self) -> dict[UUID, str]:
        """Each category as the journal account it stands for: Expenses:Food:Groceries, Income:Salary."""
        found = {c.bcid: c for c in self.cr.list()}
        paths: dict[UUID, str] = {}
        for bcid, category in found.items():
            chain, current = [], category
            while current is not None:
                chain.append(current.name)
                current = found.get(current.parent_id) if current.parent_id else None
            paths[bcid] = ("Expenses" if category.kind == "spending" else "Income") + ":" + ":".join(reversed(chain))
        return paths

    def _history_read(self, row, paths: dict[UUID, str]) -> HistoryRead:
        snap = row.snapshot
        names = {c.bcid: c.name for c in self.cr.list()}
        where = self._category_paths()
        return HistoryRead(
            hid=row.hid,
            transaction=row.transaction_id,
            action=row.action,
            at=row.at,
            via=row.via,
            date=date.fromisoformat(snap["date"]),
            payee=snap.get("payee"),
            comment=snap.get("comment"),
            source=snap.get("source"),
            external_id=snap.get("external_id"),
            source_url=snap.get("source_url"),
            postings=[
                HistoryPosting(
                    account=_where(p, paths, where),
                    side=p["side"],
                    amount=Decimal(p["amount"]),
                    category=names.get(UUID(p["category"])) if p.get("category") else None,
                )
                for p in snap["postings"]
            ],
        )

    def _account_paths(self) -> dict[UUID, str]:
        accounts = {a.aid: a for a in self.ar.list()}
        paths: dict[UUID, str] = {}
        for aid, account in accounts.items():
            chain: builtins.list[str] = []
            seen: set[UUID] = set()
            current: Account | None = account
            while current is not None and current.aid not in seen:
                seen.add(current.aid)
                chain.append(current.name)
                current = accounts.get(current.parent_id) if current.parent_id else None
            paths[aid] = ":".join(reversed(chain))
        return paths

    def history(self, tid: UUID) -> list[HistoryRead]:
        """What happened to a transaction, oldest first; works for a deleted one too."""
        paths = self._account_paths()
        return [self._history_read(row, paths) for row in self.tr.history(tid)]

    def changes(self, tid: UUID) -> builtins.list[ChangeRead]:
        """An entry's history, oldest first, each step with what it changed (works for a deleted entry too)."""
        paths = self._account_paths()
        rows = self.tr.history(tid)
        return [self._change(row, rows[i - 1] if i else None, paths) for i, row in enumerate(rows)]

    def recent_changes(
        self, since: datetime | None = None, via: str | None = None, limit: int = 50
    ) -> builtins.list[ChangeRead]:
        """The latest steps across every entry, newest first, each with what it changed."""
        newest = self.tr.history_since(since, via, limit)
        paths = self._account_paths()
        by_entry: dict[UUID, builtins.list] = {}
        for row in self.tr.histories_for(list({r.transaction_id for r in newest})):
            by_entry.setdefault(row.transaction_id, []).append(row)
        result = []
        for row in newest:
            steps = by_entry[row.transaction_id]
            position = next(i for i, step in enumerate(steps) if step.hid == row.hid)
            result.append(self._change(row, steps[position - 1] if position else None, paths))
        return result

    def _change(self, row, before, paths: dict[UUID, str]) -> ChangeRead:
        return ChangeRead(
            hid=row.hid,
            transaction=row.transaction_id,
            action=row.action,
            at=row.at,
            via=row.via,
            entry=self._history_read(row, paths),
            changes=_diff(before.snapshot, row.snapshot, paths, self._category_paths())
            if before is not None and row.action == "updated"
            else {},
        )

    def deleted(self) -> list[HistoryRead]:
        """Transactions that were deleted, as they were when deleted, newest first."""
        paths = self._account_paths()
        return [self._history_read(row, paths) for row in self.tr.deleted()]

    def restorable(self, limit: int = RESTORABLE_LIMIT) -> list[HistoryRead]:
        """Entries that were deleted and are not back, newest deletion first (one per entry, as it stood when it went)."""
        latest: dict[UUID, object] = {}
        for row in self.tr.deleted():
            latest.setdefault(row.transaction_id, row)
        alive = self.tr.read_many(list(latest))
        paths = self._account_paths()
        rows = [row for tid, row in latest.items() if tid not in alive]
        return [self._history_read(row, paths) for row in rows[:limit]]

    def restore(self, hid: UUID) -> TransactionRead:
        """Bring a deleted entry back as it was, with its old id (so its history carries on). It becomes an
        ordinary entry: the link to a recurring rule is not restored, so the rule cannot record the day twice. Its
        related links come back (to an earlier entry that is still there, and from the entries that were linked to it)."""
        row = self.tr.deleted_row(hid)
        if row is None:
            raise LookupError("deleted transaction not found!")
        if self.tr.read(row.transaction_id) is not None:
            raise ValueError("this transaction is already back!")
        if self.tr.history(row.transaction_id)[-1].hid != row.hid:
            raise ValueError("this transaction was changed after it was deleted; restore the latest deletion!")
        snapshot = row.snapshot
        known = {a.aid for a in self.ar.list()}
        if any(UUID(p["account"]) not in known for p in snapshot["postings"]):
            raise ValueError("an account this transaction used no longer exists, so it cannot be restored!")
        data = TransactionCreate(
            date=date.fromisoformat(snapshot["date"]),
            payee=snapshot.get("payee"),
            comment=snapshot.get("comment"),
            source=snapshot.get("source"),
            external_id=snapshot.get("external_id"),
            source_url=snapshot.get("source_url"),
            postings=[
                {
                    "account": UUID(p["account"]),
                    "side": p["side"],
                    "amount": Decimal(p["amount"]),
                    "category": self._known_category(p.get("category")),
                }
                for p in snapshot["postings"]
            ],
            related_id=self._restorable_link(snapshot.get("related_id")),
            tags=clean_names(snapshot.get("tags", [])),
        )
        self._check_limits()
        self._resolve(data)
        self._check_reference(data.source, data.external_id)
        transaction = self.tr.create(data, self.origin, None, tid=row.transaction_id)
        self._relink(transaction.tid, snapshot.get("related_from", []))
        self.tr.db.commit()
        self.tr.db.refresh(transaction)
        return self._to_read(transaction)

    def _known_category(self, value: str | None) -> UUID | None:
        """The category a restored line had, if it is still there and open (otherwise the account decides)."""
        if not value:
            return None
        category = self.cr.read(UUID(value))
        return category.bcid if category is not None and category.closed_on is None else None

    def _restorable_link(self, value: str | None) -> UUID | None:
        """The entry a restored one was related to, if it is still there (otherwise the link is simply not restored)."""
        if not value:
            return None
        target = UUID(value)
        return target if self.tr.read(target) is not None else None

    def _relink(self, restored: UUID, former: list[str]) -> None:
        """Point the entries that were related to a restored one at it again, unless they have a link of their own by
        now or it would make a circle."""
        for value in former:
            other = self.tr.read(UUID(value))
            if other is None or other.related_id is not None:
                continue
            try:
                self._check_related(restored, other.tid)
            except InvalidPostingError:
                continue
            other.related_id = restored
            self.tr.db.add(other)

    def validate(self, data: TransactionCreate) -> None:
        """Raise what create would raise, without saving anything."""
        self._resolve(data)

    def _check_related(self, related_id: UUID | None, tid: UUID | None = None) -> None:
        """The entry this one is related to must be the person's own, and following the links must never lead back here."""
        if related_id is None:
            return
        if tid is not None and related_id == tid:
            raise InvalidPostingError("an entry cannot be related to itself!")
        seen: set[UUID] = set()
        link: UUID | None = related_id
        while link is not None and link not in seen:
            found = self.tr.read(link)
            if found is None:
                raise InvalidPostingError("the related transaction was not found!")
            if tid is not None and found.related_id == tid:
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

    def _check_reference(self, source: str | None, external_id: str | None, tid: UUID | None = None) -> None:
        """A source's reference is used once: another entry with it (not the one being changed) is refused."""
        if not external_id:
            return
        if not source:
            raise InvalidPostingError("a reference (external_id) needs a source, for example 'gmail' or 'upi'!")
        found = self.tr.find_by_reference(source, external_id)
        if found is not None and found.tid != tid:
            raise DuplicateReferenceError(
                f"source '{source}' reference '{external_id}' is already used by the entry {found.tid}!"
            )

    def _check_new(self, data: TransactionCreate) -> None:
        """Everything creating an entry checks before it saves."""
        self._check_limits()
        self._resolve(data)
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
                    raise DuplicateReferenceError(_different_content(data, found.tid))
        if found is None:
            self._check_new(data)
        return TransactionPreview(
            tid=found.tid if found else None,
            already_recorded=found.tid if found else None,
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

    def preview_update(self, tid: UUID, data: TransactionUpdate) -> TransactionPreview:
        """What `update` would save, with nothing saved: the entry as it would read afterwards."""
        existing = self._check_update(tid, data)
        changes = data.model_dump(exclude_unset=True, exclude={"postings", "tags"})
        merged: dict[str, Any] = {
            key: changes[key] if key in changes else getattr(existing, key)
            for key in ("date", "payee", "comment", "related_id", "source", "external_id", "source_url")
        }
        merged["tags"] = data.tags if data.tags is not None else self.tr.tag_names(tid)
        postings = (
            data.postings
            if data.postings is not None
            else [PostingCreate(account=p.account, side=p.side, amount=p.amount) for p in self.tr.postings(tid)]
        )
        return TransactionPreview(tid=tid, **merged, postings=postings)

    def preview_delete(self, tid: UUID) -> TransactionPreview:
        """The entry a delete would remove (nothing is deleted)."""
        existing = self.read(tid)
        if existing is None:
            raise ValueError(f"transaction with tid '{tid}' not found!")
        return TransactionPreview(
            tid=tid,
            date=existing.date,
            payee=existing.payee,
            comment=existing.comment,
            related_id=existing.related_id,
            source=existing.source,
            external_id=existing.external_id,
            source_url=existing.source_url,
            postings=[PostingCreate(account=p.account, side=p.side, amount=p.amount) for p in existing.postings],
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
                raise DuplicateReferenceError(_different_content(data, found.tid))
        return self.create(data, recurring), True

    def create(self, data: TransactionCreate, recurring: tuple[UUID, date] | None = None) -> TransactionRead:
        self._check_new(data)
        transaction = self.tr.create(data, self.origin, recurring)
        self.tr.db.commit()
        self.tr.db.refresh(transaction)
        return self._to_read(transaction)

    def read(self, tid: UUID) -> TransactionRead | None:
        transaction = self.tr.read(tid)
        if not transaction:
            return None
        return self._to_read(transaction)

    def related(self, tid: UUID) -> list[TransactionRead]:
        """The entries that are related to this one, oldest first."""
        rows = self.tr.related_to(tid)
        tids = [t.tid for t in rows]
        postings, tags = self.tr.postings_for_transactions(tids), self.tr.tag_map(tids)
        return [self._to_read(t, postings.get(t.tid, []), tags.get(t.tid, [])) for t in rows]

    def _account_subtree(self, aid: UUID) -> list[UUID]:
        accounts = self.ar.list()
        if not any(a.aid == aid for a in accounts):
            raise ValueError(f"account with aid '{aid}' not found!")
        children: dict[UUID, list[UUID]] = {}
        for a in accounts:
            if a.parent_id is not None:
                children.setdefault(a.parent_id, []).append(a.aid)
        subtree = [aid]
        to_visit = [aid]
        while to_visit:
            for child in children.get(to_visit.pop(), []):
                subtree.append(child)
                to_visit.append(child)
        return subtree

    def _category_subtree(self, bcid: UUID) -> builtins.list[UUID]:
        """A category and the categories inside it."""
        categories = self.cr.list()
        if not any(c.bcid == bcid for c in categories):
            raise ValueError(f"category with bcid '{bcid}' not found!")
        return [c.bcid for c in categories if c.bcid == bcid or c.parent_id == bcid]

    def _args(self, account, kind, also):
        account_ids = self._account_subtree(account) if account else None
        also_ids = self._category_subtree(also) if also else None
        if kind not in (None, "", "expense", "income", "transfer"):
            raise ValueError("the kind must be expense, income or transfer!")
        kind_accounts = None
        if kind:
            roots = {a.name: a.aid for a in self.ar.list() if a.parent_id is None}
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
        tids = [t.tid for t in transactions]
        postings, tags = (
            self.tr.postings_for_transactions(tids),
            self.tr.tag_map(tids),
        )  # one query each, not one per row
        return [
            self._to_read(transaction, postings.get(transaction.tid, []), tags.get(transaction.tid, []))
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
        tids = [t.tid for t in found]
        postings, tags = (
            self.tr.postings_for_transactions(tids),
            self.tr.tag_map(tids),
        )  # one query each, not one per row
        found = [self._to_read(t, postings.get(t.tid, []), tags.get(t.tid, [])) for t in found]
        return found, total

    def tagged(self) -> builtins.list[TransactionRead]:
        """Every entry that carries at least one tag, newest first, with its postings (three queries however many)."""
        found = self.tr.tagged()
        tids = [t.tid for t in found]
        postings, tags = self.tr.postings_for_transactions(tids), self.tr.tag_map(tids)
        return [self._to_read(t, postings.get(t.tid, []), tags.get(t.tid, [])) for t in found]

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
        accounts = {a.aid: a for a in self.ar.list()}
        usable = {aid for aid, a in accounts.items() if a.parent_id is not None and a.closed_on is None}
        categories = {c.bcid: c for c in self.cr.list()}
        usable |= {bcid for bcid, c in categories.items() if c.closed_on is None}

        def route_id(p: PostingRead) -> UUID:
            """What the Add screen picks for a line: the category on a line to Expenses or Income, else the account."""
            on_books = AccountService.root_name(accounts[p.account], accounts) in GROUP_POSTING_ROOT_NAMES
            return p.category if on_books and p.category is not None else p.account

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
                AccountService.root_name(accounts[credits[0].account], accounts),
                AccountService.root_name(accounts[debits[0].account], accounts),
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
        categories = {c.bcid: c for c in self.cr.list()}
        paths.update(self._category_paths())  # a category reads like the journal's account: Expenses:Food:Groceries

        def side(aid: UUID) -> RouteAccount:
            return RouteAccount(id=aid, path=paths.get(aid, "?"))

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

    def _check_update(self, tid: UUID, data: TransactionUpdate) -> Transaction:
        """Everything changing an entry checks before it saves; returns the entry as it stands."""
        existing = self.tr.read(tid)
        if not existing:
            raise ValueError(f"transaction with tid '{tid}' not found!")
        # Postings an entry already has on an account that was closed since stay allowed, so it can still be edited.
        existing_lines = self.tr.postings(tid)
        kept = {p.account for p in existing_lines}
        kept_categories = {p.category_id for p in existing_lines if p.category_id is not None}
        self._resolve(data, kept, kept_categories)
        if "related_id" in data.model_fields_set:
            self._check_related(data.related_id, tid)
        if data.tags:
            self._check_tags(data.tags)
        if data.model_fields_set & {"source", "external_id"}:
            self._check_reference(
                data.source if "source" in data.model_fields_set else existing.source,
                data.external_id if "external_id" in data.model_fields_set else existing.external_id,
                tid,
            )
        return existing

    def update(
        self,
        tid: UUID,
        data: TransactionUpdate,
    ) -> TransactionRead | None:
        self._check_update(tid, data)
        transaction = self.tr.update(tid, data, self.origin)
        if not transaction:
            raise RuntimeError(f"failed to update transaction with tid '{tid}'!")
        self.tr.db.commit()
        self.tr.db.refresh(transaction)
        return self._to_read(transaction)

    def label_payment(self, tid: UUID, category_id: UUID) -> TransactionRead:
        """Give an entry's unlabelled payments into accounts outside the budget (a loan, a fund) a category."""
        entry = self.read(tid)
        if entry is None:
            raise ValueError(f"transaction with tid '{tid}' not found!")
        accounts = {a.aid: a for a in self.ar.list()}
        rows, changed = [], False
        for p in entry.postings:
            account = accounts[p.account]
            waiting = (
                p.side == PostingSide.DEBIT
                and p.category is None
                and not account.on_budget
                and AccountService.root_name(account, accounts) in ("Assets", "Liabilities")
            )
            changed = changed or waiting
            rows.append(
                PostingCreate(
                    account=p.account, side=p.side, amount=p.amount, category=category_id if waiting else p.category
                )
            )
        if not changed:
            raise ValueError("this entry has no payment waiting for a category!")
        updated = self.update(tid, TransactionUpdate(postings=rows))
        if updated is None:
            raise ValueError(f"transaction with tid '{tid}' not found!")
        return updated

    def delete(self, tid: UUID) -> TransactionRead | None:
        transaction = self.read(tid)
        deleted = self.tr.delete(tid, self.origin)
        if not deleted:
            raise ValueError(f"transaction with tid '{tid}' not found!")
        self.tr.db.commit()
        return transaction

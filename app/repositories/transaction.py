"""Persistence for transactions and postings, always filtered by the user's id."""

import builtins
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import and_, not_, or_, update
from sqlalchemy.orm import aliased
from sqlmodel import Session, col, func, select

from ..models.account import Account
from ..models.category import BudgetCategory
from ..models.contact import PartyTransaction
from ..models.recurring import RecurringTransaction
from ..models.tag import Tag, TransactionTag
from ..models.transaction import Posting, PostingSide, Transaction
from ..models.utils import without_nul
from ..schemas.transaction import PostingCreate, RelatedRef, TransactionCreate, TransactionUpdate
from ..tags import clean_tag
from .account import AccountRepository
from .cache import remember, remembered
from .category import ROOT_KINDS, CategoryRepository

# What the application writes itself (an opening balance, an adjustment): not a merchant to filter by.
SYSTEM_PAYEES = ("Opening balance", "Balance adjustment")


@dataclass(frozen=True)
class NewEntry:
    """An entry to write, with what only its writer knows: who made it and last changed it (differing only in a
    restore, which brings both back) and the recurring transaction and day it was recorded for, if any."""

    data: TransactionCreate
    created_via: str | None = None
    updated_via: str | None = None
    recurring: tuple[UUID, date] | None = None


class TransactionRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def create(
        self,
        data: TransactionCreate,
        origin: str | None = None,
        recurring: tuple[UUID, date] | None = None,
    ) -> Transaction:
        return self.write([NewEntry(data, origin, origin, recurring)])[0]

    def create_many(self, items: Sequence[TransactionCreate], origin: str | None = None) -> builtins.list[Transaction]:
        """Several entries written together."""
        return self.write([NewEntry(data, origin, origin) for data in items])

    def write(self, entries: Sequence[NewEntry]) -> builtins.list[Transaction]:
        """The entries go in one insert, their lines in another and their tags in a third, however many there are: a
        batch, an import and a restore cost the same few round trips for ten entries as for ten thousand."""
        # Before anything is written: the account list the checks read is still remembered, so this asks nothing more.
        categories = self._line_categories([entry.data.postings for entry in entries])
        made: builtins.list[Transaction] = []
        for entry in entries:
            fields = entry.data.model_dump(exclude={"postings", "tags"})
            transaction = Transaction(
                **fields, user_id=self.uid, created_via=entry.created_via, updated_via=entry.updated_via
            )
            if entry.recurring is not None:
                transaction.recurring_id, transaction.recurring_date = entry.recurring
            self.db.add(transaction)
            made.append(transaction)
        self.db.flush()
        for entry, transaction, lines in zip(entries, made, categories, strict=True):
            for posting, category in zip(entry.data.postings, lines, strict=True):
                values = posting.model_dump(exclude={"category_id"})
                self.db.add(Posting(**values, category_id=category, transaction_id=transaction.id, user_id=self.uid))
        self.db.flush()
        self._tag_new({transaction.id: entry.data.tags for entry, transaction in zip(entries, made, strict=True)})
        return made

    def _line_categories(self, entries: Sequence[Sequence[PostingCreate]]) -> builtins.list[builtins.list[UUID | None]]:
        """The category of each line of each entry: the one given, else (on Expenses or Income) Uncategorised. Nothing
        else is filled in for the person: a payment into a loan or fund keeps the label it was given, or none."""
        every = {a.id: a for a in AccountRepository(self.db, self.uid).list()}
        fallback: dict[UUID, UUID | None] = {}  # by account: the Uncategorised of its root, or none off Expenses/Income

        def uncategorised(account_id: UUID) -> UUID | None:
            if account_id not in fallback:
                root = every.get(account_id)
                while root is not None and root.parent_id is not None and root.parent_id in every:
                    root = every[root.parent_id]
                kind = ROOT_KINDS.get(root.name) if root is not None and root.parent_id is None else None
                fallback[account_id] = (
                    CategoryRepository(self.db, self.uid).ensure_uncategorised(kind).id if kind else None
                )
            return fallback[account_id]

        return [
            [p.category_id if p.category_id is not None else uncategorised(p.account_id) for p in postings]
            for postings in entries
        ]

    def read(self, transaction_id: UUID) -> Transaction | None:
        statement = select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.user_id == self.uid,
        )
        transaction = self.db.exec(statement).first()
        return transaction

    def owned_by_contacts(self, transaction_id: UUID) -> bool:
        """Whether a contact's activity (a loan, a shared expense, a settlement) is built on this entry. A gift is an
        ordinary entry that only names the person, so it is not."""
        return (
            self.db.exec(
                select(PartyTransaction.id).where(
                    PartyTransaction.user_id == self.uid,
                    PartyTransaction.transaction_id == transaction_id,
                    PartyTransaction.purpose != "gift",
                )
            ).first()
            is not None
        )

    def related_to(self, transaction_id: UUID) -> list[Transaction]:
        """The entries that point at this one, oldest first."""
        return self.db.exec(
            select(Transaction)
            .where(Transaction.related_id == transaction_id, Transaction.user_id == self.uid)
            .order_by(Transaction.date, Transaction.created)
        ).all()

    def read_many(self, transaction_ids: list[UUID]) -> dict[UUID, Transaction]:
        """Several transactions in one query."""
        if not transaction_ids:
            return {}
        rows = self.db.exec(
            select(Transaction).where(col(Transaction.id).in_(list(transaction_ids)), Transaction.user_id == self.uid)
        ).all()
        return {t.id: t for t in rows}

    def related_refs(self, ids: builtins.list[UUID | None]) -> dict[UUID, RelatedRef]:
        """For each earlier entry that others are related to: its date and what it came to (its debits). Two queries
        however many, none when nothing is related."""
        found = self.read_many(builtins.list({i for i in ids if i is not None}))
        postings = self.postings_for_transactions(builtins.list(found))
        return {
            transaction_id: RelatedRef(
                id=transaction_id,
                date=t.date,
                amount=sum(
                    (p.amount for p in postings.get(transaction_id, []) if p.side == PostingSide.DEBIT), Decimal("0.00")
                ),
            )
            for transaction_id, t in found.items()
        }

    def _matching(
        self,
        account_ids: list[UUID] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        text: str | None = None,
        kind: str | None = None,
        kind_accounts: tuple[list[UUID], list[UUID]] | None = None,
        also_ids: list[UUID] | None = None,
        payee: str | None = None,
        source: str | None = None,
        external_id: str | None = None,
        tag: str | None = None,
    ):
        """The transactions that match, unordered (what `list` pages through and `count` counts)."""
        statement = select(Transaction).where(Transaction.user_id == self.uid)
        if text:
            text = without_nul(text)
            named = (
                select(Posting.transaction_id)
                .join(Account, Account.id == Posting.account_id)
                .where(Posting.user_id == self.uid, col(Account.name).icontains(text, autoescape=True))
            )
            labelled = (
                select(Posting.transaction_id)
                .join(BudgetCategory, BudgetCategory.id == Posting.category_id)
                .where(Posting.user_id == self.uid, col(BudgetCategory.name).icontains(text, autoescape=True))
            )
            statement = statement.where(
                or_(
                    col(Transaction.payee).icontains(text, autoescape=True),
                    col(Transaction.comment).icontains(text, autoescape=True),
                    col(Transaction.id).in_(named),
                    col(Transaction.id).in_(labelled),
                )
            )
        if kind and kind_accounts is not None:
            expense_ids, income_ids = kind_accounts
            spends = col(Transaction.id).in_(
                select(Posting.transaction_id).where(
                    Posting.user_id == self.uid,
                    Posting.side == PostingSide.DEBIT,
                    col(Posting.account_id).in_(expense_ids),
                )
            )
            earns = col(Transaction.id).in_(
                select(Posting.transaction_id).where(
                    Posting.user_id == self.uid,
                    Posting.side == PostingSide.CREDIT,
                    col(Posting.account_id).in_(income_ids),
                )
            )
            # The same order as the rows are told apart in the list: spending first, then income, else a transfer.
            statement = statement.where(
                {
                    "expense": spends,
                    "income": and_(earns, not_(spends)),
                    "transfer": and_(not_(spends), not_(earns)),
                }[kind]
            )
        if account_ids is not None:
            statement = statement.where(
                col(Transaction.id).in_(
                    select(Posting.transaction_id).where(
                        col(Posting.account_id).in_(account_ids),
                        Posting.user_id == self.uid,
                    )
                )
            )
        if also_ids is not None:  # the entry must have a line labelled with one of these categories
            statement = statement.where(
                col(Transaction.id).in_(
                    select(Posting.transaction_id).where(
                        col(Posting.category_id).in_(also_ids), Posting.user_id == self.uid
                    )
                )
            )
        if payee:  # exactly this payee, capitals aside
            statement = statement.where(func.lower(Transaction.payee) == without_nul(payee).strip().lower())
        if tag:
            statement = statement.where(
                col(Transaction.id).in_(
                    select(TransactionTag.transaction_id)
                    .join(Tag, Tag.id == TransactionTag.tag_id)
                    .where(Tag.user_id == self.uid, Tag.name == clean_tag(tag))
                )
            )
        if source:
            statement = statement.where(Transaction.source == without_nul(source).strip().lower())
        if external_id:
            statement = statement.where(Transaction.external_id == without_nul(external_id).strip())
        if date_from is not None:
            statement = statement.where(Transaction.date >= date_from)
        if date_to is not None:
            statement = statement.where(Transaction.date <= date_to)
        return statement

    def count_matching(self, *args, **kwargs) -> int:
        """How many transactions match (the same filters as `list`, which has no paging here)."""
        statement = self._matching(*args, **kwargs)
        return self.db.exec(select(func.count()).select_from(statement.subquery())).one()

    def list(
        self,
        account_ids: builtins.list[UUID] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
        offset: int = 0,
        text: str | None = None,
        kind: str | None = None,
        kind_accounts: tuple[builtins.list[UUID], builtins.list[UUID]] | None = None,
        also_ids: builtins.list[UUID] | None = None,
        payee: str | None = None,
        source: str | None = None,
        external_id: str | None = None,
        tag: str | None = None,
    ) -> builtins.list[Transaction]:
        """Transactions, newest first. `text` matches the payee, the note or the name of an account used; `kind`
        (expense, income or transfer) is told by `kind_accounts`, the Expenses account and the Income account."""
        statement = self._matching(
            account_ids, date_from, date_to, text, kind, kind_accounts, also_ids, payee, source, external_id, tag
        )
        statement = statement.order_by(col(Transaction.date).desc(), col(Transaction.created).desc())
        statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        transactions = self.db.exec(statement).all()
        return transactions

    # ---- tags ------------------------------------------------------------------------------------------------------

    def tag_names(self, transaction_id: UUID) -> builtins.list[str]:
        """The names of the tags on one entry, A to Z."""
        return self.tag_map([transaction_id]).get(transaction_id, [])

    def tag_map(self, transaction_ids: builtins.list[UUID]) -> dict[UUID, builtins.list[str]]:
        """The tag names of several entries in one query (a list must not ask once per row)."""
        found: dict[UUID, builtins.list[str]] = {}
        if not transaction_ids:
            return found
        rows = self.db.exec(
            select(TransactionTag.transaction_id, Tag.name)
            .join(Tag, Tag.id == TransactionTag.tag_id)
            .where(col(TransactionTag.transaction_id).in_(transaction_ids), TransactionTag.user_id == self.uid)
            .order_by(Tag.name)
        ).all()
        for transaction_id, name in rows:
            found.setdefault(transaction_id, []).append(name)
        return found

    def all_tag_map(self) -> dict[UUID, builtins.list[str]]:
        """The tag names of every entry (for a backup: no list of ids, so any number of entries is fine)."""
        found: dict[UUID, builtins.list[str]] = {}
        for transaction_id, name in self.db.exec(
            select(TransactionTag.transaction_id, Tag.name)
            .join(Tag, Tag.id == TransactionTag.tag_id)
            .where(TransactionTag.user_id == self.uid)
            .order_by(Tag.name)
        ).all():
            found.setdefault(transaction_id, []).append(name)
        return found

    def count_tags(self) -> int:
        return self.db.exec(select(func.count()).select_from(Tag).where(Tag.user_id == self.uid)).one()

    def existing_tags(self, names: builtins.list[str]) -> set[str]:
        """Which of these names are tags of the person's already (one query however many names)."""
        if not names:
            return set()
        return set(self.db.exec(select(Tag.name).where(Tag.user_id == self.uid, col(Tag.name).in_(names))).all())

    def _tags_named(self, names: set[str]) -> dict[str, Tag]:
        """The person's tags of these names, the ones that do not exist yet made: one read and one write."""
        if not names:
            return {}
        tags = {
            row.name: row for row in self.db.exec(select(Tag).where(Tag.user_id == self.uid, col(Tag.name).in_(names)))
        }
        for name in names - tags.keys():
            tags[name] = Tag(user_id=self.uid, name=name)
            self.db.add(tags[name])
        self.db.flush()
        return tags

    def _tag_new(self, tags: dict[UUID, builtins.list[str]]) -> None:
        """Tag entries that have just been made (so have no tags to take off): asked and written once for all of them."""
        named = self._tags_named({name for names in tags.values() for name in names})
        for transaction_id, names in tags.items():
            for name in names:
                self.db.add(TransactionTag(transaction_id=transaction_id, tag_id=named[name].id, user_id=self.uid))
        self.db.flush()

    def set_tags(self, transaction_id: UUID, names: builtins.list[str]) -> None:
        """Make the entry's tags exactly these (already cleaned) names: tags that do not exist yet are made, tags no entry
        carries any more are removed."""
        existing = self._tags_named(set(names))
        wanted = {existing[name].id for name in names}
        links = self.db.exec(
            select(TransactionTag).where(
                TransactionTag.transaction_id == transaction_id, TransactionTag.user_id == self.uid
            )
        ).all()
        have = {link.tag_id for link in links}
        dropped = [link for link in links if link.tag_id not in wanted]
        for link in dropped:
            self.db.delete(link)
        for tag_id in wanted - have:
            self.db.add(TransactionTag(transaction_id=transaction_id, tag_id=tag_id, user_id=self.uid))
        self.db.flush()
        if dropped:  # only taking a tag off an entry can leave it unused
            self.drop_unused_tags()

    def drop_unused_tags(self) -> None:
        """A tag exists only while an entry carries it."""
        used = select(TransactionTag.tag_id).where(TransactionTag.user_id == self.uid)
        for tag in self.db.exec(select(Tag).where(Tag.user_id == self.uid, col(Tag.id).not_in(used))).all():
            self.db.delete(tag)
        self.db.flush()

    def tag_stats(self) -> builtins.list[tuple[str, int, date]]:
        """Every tag with how many entries carry it and the day of the latest, the most used first."""
        rows = self.db.exec(
            select(Tag.name, func.count(), func.max(Transaction.date))
            .join(TransactionTag, TransactionTag.tag_id == Tag.id)
            .join(Transaction, Transaction.id == TransactionTag.transaction_id)
            .where(Tag.user_id == self.uid)
            .group_by(Tag.name)
            .order_by(func.count().desc(), Tag.name)
        ).all()
        return [(name, count, last) for name, count, last in rows]

    def tagged(self) -> builtins.list[Transaction]:
        """The entries that carry at least one tag, newest first."""
        statement = (
            select(Transaction)
            .where(
                Transaction.user_id == self.uid,
                col(Transaction.id).in_(
                    select(TransactionTag.transaction_id).where(TransactionTag.user_id == self.uid)
                ),
            )
            .order_by(col(Transaction.date).desc(), col(Transaction.created).desc())
        )
        return self.db.exec(statement).all()

    def _retag_rules(self, old: str, new: str | None) -> None:
        """Recurring rules keep their own list of tag names: follow a rename or a merge (`new`), or drop the tag (None)."""
        for rule in self.db.exec(select(RecurringTransaction).where(RecurringTransaction.user_id == self.uid)).all():
            if old not in (rule.tags or []):
                continue
            names = [new if name == old else name for name in rule.tags]
            rule.tags = [name for name in dict.fromkeys(names) if name is not None]
            self.db.add(rule)
        self.db.flush()

    def rename_tag(self, old: str, new: str) -> None:
        """Give a tag a new name. When the new name is another tag of the person's, the two become one."""
        tag = self.db.exec(select(Tag).where(Tag.user_id == self.uid, Tag.name == old)).first()
        if tag is None:
            raise LookupError(f"no tag is called '{old}'!")
        self._retag_rules(old, new)
        target = self.db.exec(select(Tag).where(Tag.user_id == self.uid, Tag.name == new)).first()
        if target is None:
            tag.name = new
            self.db.add(tag)
            self.db.flush()
            return
        already = set(
            self.db.exec(
                select(TransactionTag.transaction_id).where(
                    TransactionTag.user_id == self.uid, TransactionTag.tag_id == target.id
                )
            ).all()
        )
        for link in self.db.exec(
            select(TransactionTag).where(TransactionTag.tag_id == tag.id, TransactionTag.user_id == self.uid)
        ).all():
            if link.transaction_id not in already:
                self.db.add(TransactionTag(transaction_id=link.transaction_id, tag_id=target.id, user_id=self.uid))
            self.db.delete(link)
        self.db.flush()
        self.db.delete(tag)
        self.db.flush()

    def delete_tag(self, name: str) -> int:
        """Take a tag off every entry and remove it; returns how many entries had it."""
        tag = self.db.exec(select(Tag).where(Tag.user_id == self.uid, Tag.name == name)).first()
        if tag is None:
            raise LookupError(f"no tag is called '{name}'!")
        self._retag_rules(name, None)
        links = self.db.exec(
            select(TransactionTag).where(TransactionTag.user_id == self.uid, TransactionTag.tag_id == tag.id)
        ).all()
        for link in links:
            self.db.delete(link)
        self.db.flush()
        self.db.delete(tag)
        self.db.flush()
        return len(links)

    def payees(self, limit: int = 300) -> builtins.list[tuple[str, int]]:
        """The payees used, the most used first (one spelling each: the newest entry's)."""
        rows = self.db.exec(
            select(func.lower(Transaction.payee), func.max(Transaction.payee), func.count())
            .where(
                Transaction.user_id == self.uid,
                col(Transaction.payee).is_not(None),
                col(Transaction.payee).not_in(SYSTEM_PAYEES),
            )
            .group_by(func.lower(Transaction.payee))
            .order_by(func.count().desc(), func.lower(Transaction.payee))
            .limit(limit)
        ).all()
        return [(name, count) for _, name, count in rows if name]

    def postings(self, transaction_id: UUID) -> builtins.list[Posting]:
        statement = select(Posting).where(
            Posting.transaction_id == transaction_id,
            Posting.user_id == self.uid,
        )
        postings = self.db.exec(statement).all()
        return postings

    def postings_for_transactions(self, transaction_ids: builtins.list[UUID]) -> dict[UUID, builtins.list[Posting]]:
        """The postings of several transactions in one query (a list of transactions must not ask once per row)."""
        grouped: dict[UUID, builtins.list[Posting]] = {}
        if not transaction_ids:
            return grouped
        for posting in self.db.exec(
            select(Posting).where(col(Posting.transaction_id).in_(transaction_ids), Posting.user_id == self.uid)
        ).all():
            grouped.setdefault(posting.transaction_id, []).append(posting)
        return grouped

    def posting_rows(self, date_to: date):
        """Every posting of transactions dated up to a day, as (transaction, account, side, amount, date) rows: what the
        budget is worked out from, without payees, notes or timestamps. One query, remembered for the request."""
        statement = (
            select(
                Posting.transaction_id,
                Posting.account_id,
                Posting.side,
                Posting.amount,
                Transaction.date,
                Posting.category_id,
            )
            .join(Transaction, Transaction.id == Posting.transaction_id)
            .where(Posting.user_id == self.uid, Transaction.user_id == self.uid, Transaction.date <= date_to)
        )
        return list(remembered(self.db, ("posting_rows", self.uid, date_to), lambda: self.db.exec(statement).all()))

    def all_postings(self) -> builtins.list[Posting]:
        return self.db.exec(select(Posting).where(Posting.user_id == self.uid)).all()

    def count(self) -> int:
        return self.db.exec(select(func.count()).select_from(Transaction).where(Transaction.user_id == self.uid)).one()

    def find_by_reference(self, source: str, external_id: str) -> Transaction | None:
        """The person's entry that a source gave this reference, if there is one. Remembered for the request: recording
        asks once whether the reference is taken, not once for each check."""
        statement = select(Transaction).where(
            Transaction.user_id == self.uid, Transaction.source == source, Transaction.external_id == external_id
        )
        return remembered(
            self.db, ("reference", self.uid, source, external_id), lambda: self.db.exec(statement).first()
        )

    def find_by_references(self, references: Sequence[tuple[str, str]]) -> dict[tuple[str, str], Transaction]:
        """The person's entries that carry any of these (source, reference) pairs, in one query; every pair asked
        about is remembered, found or not, so `find_by_reference` asks nothing more for them."""
        found: dict[tuple[str, str], Transaction] = {}
        if not references:
            return found
        statement = select(Transaction).where(
            Transaction.user_id == self.uid,
            col(Transaction.source).in_({source for source, _ in references}),
            col(Transaction.external_id).in_({external_id for _, external_id in references}),
        )
        wanted = set(references)
        for transaction in self.db.exec(statement).all():
            key = (cast(str, transaction.source), cast(str, transaction.external_id))
            if key in wanted:
                found[key] = transaction
        for source, external_id in wanted:
            remember(self.db, ("reference", self.uid, source, external_id), found.get((source, external_id)))
        return found

    def transactions_touching(self, account_id: UUID) -> builtins.list[UUID]:
        """The entries that have a posting on the account."""
        return list(
            self.db.exec(
                select(Posting.transaction_id)
                .where(Posting.user_id == self.uid, Posting.account_id == account_id)
                .distinct()
            ).all()
        )

    def opposite_sides(self, a: UUID, b: UUID) -> int:
        """How many entries have one account on one side and the other on the opposite side."""
        first, second = aliased(Posting), aliased(Posting)
        return self.db.exec(
            select(func.count(func.distinct(first.transaction_id)))
            .select_from(first)
            .join(second, second.transaction_id == first.transaction_id)
            .where(
                first.user_id == self.uid,
                second.user_id == self.uid,
                first.account_id == a,
                second.account_id == b,
                first.side != second.side,
            )
        ).one()

    def category_sums(
        self, kind: str, date_from: date, date_to: date
    ) -> builtins.list[tuple[UUID, PostingSide, Decimal]]:
        """What the lines labelled with a category of one kind add up to in a period: (category, side, total). One query."""
        statement = (
            select(Posting.category_id, Posting.side, func.sum(Posting.amount))
            .join(Transaction, Transaction.id == Posting.transaction_id)
            .join(BudgetCategory, BudgetCategory.id == Posting.category_id)
            .where(
                Posting.user_id == self.uid,
                Transaction.date >= date_from,
                Transaction.date <= date_to,
                BudgetCategory.kind == kind,
            )
            .group_by(col(Posting.category_id), col(Posting.side))
        )
        return [(c, s, Decimal(total)) for c, s, total in self.db.exec(statement).all()]

    def postings_for_categories(self, category_ids: builtins.list[UUID] | set[UUID]) -> builtins.list[Posting]:
        """The lines labelled with any of these categories."""
        if not category_ids:
            return []
        return builtins.list(
            self.db.exec(
                select(Posting).where(
                    Posting.user_id == self.uid, col(Posting.category_id).in_(builtins.list(category_ids))
                )
            ).all()
        )

    def labelled(self, category: UUID) -> builtins.list[UUID]:
        """The entries that have a line labelled with a category."""
        return builtins.list(
            self.db.exec(
                select(Posting.transaction_id)
                .where(Posting.user_id == self.uid, Posting.category_id == category)
                .distinct()
            ).all()
        )

    def repoint_account(
        self,
        source: UUID,
        target: UUID,
        origin: str | None,
        categories: tuple[UUID, UUID] | None = None,
    ) -> builtins.list[UUID]:
        """Move every posting from one account to another (a merge). With `categories` (source's, target's) every
        line labelled with the first takes the second. Each entry it touches records who did it
        (`updated_via`). Returns the entries that moved. Nothing is committed."""
        transaction_ids = self.transactions_touching(source)
        if categories is not None:
            transaction_ids = builtins.list(dict.fromkeys([*transaction_ids, *self.labelled(categories[0])]))
        if not transaction_ids:
            return []
        self.db.exec(
            update(Posting).where(Posting.user_id == self.uid, Posting.account_id == source).values(account_id=target)
        )
        if categories is not None:
            self.db.exec(
                update(Posting)
                .where(Posting.user_id == self.uid, Posting.category_id == categories[0])
                .values(category_id=categories[1])
            )
        self.db.exec(
            update(Transaction)
            .where(Transaction.user_id == self.uid, col(Transaction.id).in_(transaction_ids))
            .values(updated_via=origin)
        )
        self.db.expire_all()  # the bulk updates above changed rows the session may hold
        return transaction_ids

    def relabel_category(self, old: UUID, new: UUID, origin: str | None) -> builtins.list[UUID]:
        """Every line labelled with one category takes another (a merge). Each entry records who did it.
        Returns the entries that changed. Nothing is committed."""
        transaction_ids = self.labelled(old)
        if not transaction_ids:
            return []
        self.db.exec(
            update(Posting).where(Posting.user_id == self.uid, Posting.category_id == old).values(category_id=new)
        )
        self.db.exec(
            update(Transaction)
            .where(Transaction.user_id == self.uid, col(Transaction.id).in_(transaction_ids))
            .values(updated_via=origin)
        )
        self.db.expire_all()  # the bulk updates above changed rows the session may hold
        return transaction_ids

    def last_change(self) -> datetime | None:
        """When any transaction was last made or changed."""
        return self.db.exec(select(func.max(Transaction.updated)).where(Transaction.user_id == self.uid)).one()

    def count_since(self, since: datetime, leaving_out: tuple[str, ...] = ()) -> int:
        """Transactions created since a moment, not counting those made by the given origins (a recurring rule)."""
        statement = (
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.user_id == self.uid, Transaction.created >= since)
        )
        for origin in leaving_out:
            statement = statement.where(or_(col(Transaction.created_via).is_(None), Transaction.created_via != origin))
        return self.db.exec(statement).one()

    def account_ids_with_postings(self) -> set[UUID]:
        return set(self.db.exec(select(Posting.account_id).where(Posting.user_id == self.uid).distinct()).all())

    def postings_for_account(self, account_id: UUID) -> builtins.list[Posting]:
        statement = select(Posting).where(
            Posting.account_id == account_id,
            Posting.user_id == self.uid,
        )
        postings = self.db.exec(statement).all()
        return postings

    def posting_facts(self, account_ids: builtins.list[UUID]):
        """What an account's running balance needs from its postings (transaction, side, amount, date, created, account): no
        payees, notes or other accounts, so a long history costs little to read."""
        if not account_ids:
            return []
        statement = (
            select(
                Posting.transaction_id,
                Posting.side,
                Posting.amount,
                Posting.posted_on,
                Transaction.date,
                Transaction.created,
                Posting.account_id,
            )
            .join(Transaction, Transaction.id == Posting.transaction_id)
            .where(
                col(Posting.account_id).in_(account_ids), Posting.user_id == self.uid, Transaction.user_id == self.uid
            )
        )
        return self.db.exec(statement).all()

    def last_entry_dates(self, account_ids: builtins.list[UUID], date_to: date) -> dict[UUID, date]:
        """The day of each account's newest entry up to `date_to`, in one query (an account with none is left out)."""
        if not account_ids:
            return {}
        statement = (
            select(Posting.account_id, func.max(Transaction.date))
            .join(Transaction, Transaction.id == Posting.transaction_id)
            .where(
                col(Posting.account_id).in_(account_ids),
                Posting.user_id == self.uid,
                Transaction.user_id == self.uid,
                Transaction.date <= date_to,
            )
            .group_by(Posting.account_id)
        )
        return dict(self.db.exec(statement).all())

    def postings_for_accounts(
        self,
        account_ids: builtins.list[UUID],
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> builtins.list[Posting]:
        if not account_ids:
            return []
        statement = select(Posting).where(
            col(Posting.account_id).in_(account_ids),
            Posting.user_id == self.uid,
        )
        if date_from is not None or date_to is not None:
            statement = statement.join(Transaction, Transaction.id == Posting.transaction_id)
            if date_from is not None:
                statement = statement.where(Transaction.date >= date_from)
            if date_to is not None:
                statement = statement.where(Transaction.date <= date_to)
        return list(
            remembered(
                self.db,
                ("postings", self.uid, tuple(account_ids), date_from, date_to),
                lambda: self.db.exec(statement).all(),
            )
        )

    def update(
        self,
        transaction_id: UUID,
        data: TransactionUpdate,
        origin: str | None = None,
    ) -> Transaction | None:
        transaction = self.read(transaction_id)
        if not transaction:
            return None

        fields = data.model_dump(exclude_unset=True, exclude={"postings", "tags"})
        for key, value in fields.items():
            setattr(transaction, key, value)
        if origin is not None:
            transaction.updated_via = origin

        if data.postings is not None:
            self._replace_postings(transaction, data.postings)
        if data.tags is not None:
            self.set_tags(transaction_id, data.tags)

        self.db.add(transaction)
        self.db.flush()
        return transaction

    def _replace_postings(self, transaction: Transaction, postings: Iterable[PostingCreate]) -> None:
        """Make the transaction's postings the given ones, keeping a posting's id when it lives on.

        A new posting takes over an existing one on the same account and side (then on the same
        account); what is left over is added or removed. So correcting an amount never replaces the posting.
        """
        postings = builtins.list(postings)
        categories = self._line_categories([postings])[0]
        remaining = list(self.postings(transaction.id))
        taken: builtins.list[Posting | None] = [None] * len(postings)
        for exact in (True, False):
            for index, data in enumerate(postings):
                if taken[index] is not None:
                    continue
                for old in remaining:
                    if old.account_id == data.account_id and (not exact or old.side == data.side):
                        taken[index] = old
                        remaining.remove(old)
                        break
        for posting in remaining:
            self.db.delete(posting)
        for data, old, category in zip(postings, taken, categories, strict=True):
            if old is None:
                values = data.model_dump(exclude={"category_id"})
                self.db.add(Posting(**values, category_id=category, transaction_id=transaction.id, user_id=self.uid))
            else:
                old.account_id, old.side, old.amount, old.category_id, old.posted_on = (
                    data.account_id,
                    data.side,
                    data.amount,
                    category,
                    data.posted_on,
                )
                self.db.add(old)
        self.db.flush()

    def delete(self, transaction_id: UUID, origin: str | None = None) -> Transaction | None:
        transaction = self.read(transaction_id)
        if not transaction:
            return None
        for other in self.related_to(transaction_id):  # what pointed at it is no longer related to anything
            other.related_id = None
            self.db.add(other)
        for posting in self.postings(transaction_id):
            self.db.delete(posting)
        for link in self.db.exec(  # the person a gift named
            select(PartyTransaction).where(
                PartyTransaction.user_id == self.uid, PartyTransaction.transaction_id == transaction_id
            )
        ).all():
            self.db.delete(link)
        self.set_tags(transaction_id, [])
        self.db.delete(transaction)
        self.db.flush()
        return transaction

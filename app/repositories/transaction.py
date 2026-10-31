"""Persistence for transactions and postings, always filtered by the user's id; appends the history row on every create, update and delete."""

import builtins
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, not_, or_, update
from sqlalchemy.orm import aliased
from sqlmodel import Session, col, func, select

from ..models.account import Account
from ..models.category import BudgetCategory
from ..models.recurring import RecurringTransaction
from ..models.tag import Tag, TransactionTag
from ..models.transaction import Posting, PostingSide, Transaction
from ..models.transaction_history import TransactionHistory
from ..models.utils import without_nul
from ..schemas.transaction import TransactionCreate, TransactionUpdate
from ..tags import clean_tag
from .cache import remembered
from .category import ROOT_KINDS, CategoryRepository


def comparable_snapshot(snapshot: dict) -> dict:
    """A stored snapshot without what entries made before finode kept one currency also recorded (the currency, each worth)."""
    return {
        "source": None,  # snapshots written before references existed have none
        "external_id": None,
        "source_url": None,
        "related_id": None,  # snapshots written before the link was kept have no such key
        "tags": [],  # and before tags were their own thing (then they were #words in the note)
        **{key: value for key, value in snapshot.items() if key != "currency_id"},
        "postings": [{key: value for key, value in p.items() if key != "value"} for p in snapshot.get("postings", [])],
    }


# What the application writes itself (an opening balance, an adjustment): not a merchant to filter by.
SYSTEM_PAYEES = ("Opening balance", "Balance adjustment")


class TransactionRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def create(
        self,
        data: TransactionCreate,
        origin: str | None = None,
        recurring: tuple[UUID, date] | None = None,
        transaction_id: UUID | None = None,
    ) -> Transaction:
        fields = data.model_dump(exclude={"postings", "tags"})
        transaction = Transaction(**fields, user_id=self.uid, created_via=origin, updated_via=origin)
        if transaction_id is not None:  # bringing a deleted entry back keeps its id
            transaction.id = transaction_id
        if recurring is not None:
            transaction.recurring_id, transaction.recurring_date = recurring
        self.db.add(transaction)
        self.db.flush()
        self._add_postings(transaction, data.postings)
        self.db.flush()
        self.set_tags(transaction.id, data.tags)
        self._record(transaction, "created", origin)
        return transaction

    @staticmethod
    def _snapshot(
        transaction: Transaction, postings: builtins.list[Posting], tags: builtins.list[str]
    ) -> dict[str, Any]:
        return {
            "date": transaction.date.isoformat(),
            "payee": transaction.payee,
            "comment": transaction.comment,
            "recurring_id": str(transaction.recurring_id) if transaction.recurring_id else None,
            "source": transaction.source,
            "external_id": transaction.external_id,
            "source_url": transaction.source_url,
            "related_id": str(transaction.related_id) if transaction.related_id else None,
            "tags": sorted(tags),
            "postings": [
                {
                    "account": str(p.account_id),
                    "side": p.side.value,
                    "amount": str(p.amount),
                    "category": str(p.category_id) if p.category_id else None,
                }
                for p in sorted(postings, key=lambda p: (p.created, str(p.id)))
            ],
        }

    def _record(self, transaction: Transaction, action: str, origin: str | None) -> None:
        """Append what the transaction looks like now to its history."""
        snapshot = self._snapshot(transaction, self.postings(transaction.id), self.tag_names(transaction.id))
        if action == "deleted":
            # What pointed at it is unlinked below; remember which entries, so restoring it can link them again.
            snapshot["related_from"] = [str(other.id) for other in self.related_to(transaction.id)]
        if action == "updated":
            previous = self.history(transaction.id)
            if previous:
                before = comparable_snapshot(previous[-1].snapshot)
                if any("category" not in p for p in previous[-1].snapshot.get("postings", [])):
                    # Written before lines carried a category: compare without it, so a save that changed nothing adds nothing.
                    after = {
                        **snapshot,
                        "postings": [{k: v for k, v in p.items() if k != "category"} for p in snapshot["postings"]],
                    }
                else:
                    after = snapshot
                if before == after:
                    return  # saved without changing anything
        self.db.add(
            TransactionHistory(
                user_id=self.uid, transaction_id=transaction.id, action=action, via=origin, snapshot=snapshot
            )
        )
        self.db.flush()

    def history(self, transaction_id: UUID) -> list[TransactionHistory]:
        statement = (
            select(TransactionHistory)
            .where(TransactionHistory.transaction_id == transaction_id, TransactionHistory.user_id == self.uid)
            .order_by(TransactionHistory.at, TransactionHistory.id)
        )
        return self.db.exec(statement).all()

    def history_since(self, since: datetime | None, via: str | None, limit: int) -> builtins.list[TransactionHistory]:
        """The newest history rows of every entry (deleted ones too), optionally from a moment on and by one origin.
        `via` is an origin ("web", "api", "import", "recurring", "mcp:<name>") or "assistant" for any assistant."""
        statement = select(TransactionHistory).where(TransactionHistory.user_id == self.uid)
        if since is not None:
            statement = statement.where(TransactionHistory.at >= since)
        if via == "assistant":
            statement = statement.where(col(TransactionHistory.via).startswith("mcp:"))
        elif via:
            statement = statement.where(TransactionHistory.via == via)
        return self.db.exec(
            statement.order_by(col(TransactionHistory.at).desc(), col(TransactionHistory.id)).limit(limit)
        ).all()

    def histories_for(self, tids: builtins.list[UUID]) -> builtins.list[TransactionHistory]:
        """Every history row of the given entries, oldest first."""
        if not tids:
            return []
        return self.db.exec(
            select(TransactionHistory)
            .where(TransactionHistory.user_id == self.uid, col(TransactionHistory.transaction_id).in_(tids))
            .order_by(TransactionHistory.at, TransactionHistory.id)
        ).all()

    def deleted(self) -> list[TransactionHistory]:
        """The deletion record of every transaction that no longer exists, newest first."""
        statement = (
            select(TransactionHistory)
            .where(TransactionHistory.user_id == self.uid, TransactionHistory.action == "deleted")
            .order_by(col(TransactionHistory.at).desc())
        )
        return self.db.exec(statement).all()

    def deleted_row(self, history_id: UUID) -> TransactionHistory | None:
        return self.db.exec(
            select(TransactionHistory).where(
                TransactionHistory.id == history_id,
                TransactionHistory.user_id == self.uid,
                TransactionHistory.action == "deleted",
            )
        ).first()

    def _line_categories(self, postings) -> builtins.list[UUID | None]:
        """The category of each line: the one given, else (on Expenses or
        Income) Uncategorised or, for a payment into a loan or fund outside the budget that has a payment category,
        that category (only in an entry that touches the budget, which is when the budget counts it as spending)."""
        ids = {p.account_id for p in postings}
        accounts: dict[UUID, Account] = {
            a.id: a for a in self.db.exec(select(Account).where(Account.user_id == self.uid, col(Account.id).in_(ids)))
        }
        touches_budget = any(a.on_budget for a in accounts.values())
        every: dict[UUID, Account] | None = None
        found: builtins.list[UUID | None] = []
        for p in postings:
            account = accounts.get(p.account_id)
            category = p.category_id
            if category is None and account is not None:
                if (
                    touches_budget
                    and not account.on_budget
                    and account.payment_category_id is not None
                    and p.side == PostingSide.DEBIT
                ):
                    category = account.payment_category_id
                else:
                    if every is None:
                        every = {a.id: a for a in self.db.exec(select(Account).where(Account.user_id == self.uid))}
                    root = account
                    while root.parent_id is not None and root.parent_id in every:
                        root = every[root.parent_id]
                    if root.name in ROOT_KINDS and root.parent_id is None:
                        category = CategoryRepository(self.db, self.uid).ensure_uncategorised(ROOT_KINDS[root.name]).id
            found.append(category)
        return found

    def _add_postings(self, transaction: Transaction, postings) -> None:
        postings = builtins.list(postings)
        for posting_data, category in zip(postings, self._line_categories(postings), strict=True):
            values = posting_data.model_dump(exclude={"category_id"})
            self.db.add(Posting(**values, category_id=category, transaction_id=transaction.id, user_id=self.uid))

    def read(self, transaction_id: UUID) -> Transaction | None:
        statement = select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.user_id == self.uid,
        )
        transaction = self.db.exec(statement).first()
        return transaction

    def related_to(self, transaction_id: UUID) -> list[Transaction]:
        """The entries that point at this one, oldest first."""
        return self.db.exec(
            select(Transaction)
            .where(Transaction.related_id == transaction_id, Transaction.user_id == self.uid)
            .order_by(Transaction.date, Transaction.created)
        ).all()

    def read_many(self, tids: list[UUID]) -> dict[UUID, Transaction]:
        """Several transactions in one query."""
        if not tids:
            return {}
        rows = self.db.exec(
            select(Transaction).where(col(Transaction.id).in_(list(tids)), Transaction.user_id == self.uid)
        ).all()
        return {t.id: t for t in rows}

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
        (expense, income or transfer) is told by `kind_accounts`, the ids under Expenses and under Income."""
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

    def tag_map(self, tids: builtins.list[UUID]) -> dict[UUID, builtins.list[str]]:
        """The tag names of several entries in one query (a list must not ask once per row)."""
        found: dict[UUID, builtins.list[str]] = {}
        if not tids:
            return found
        rows = self.db.exec(
            select(TransactionTag.transaction_id, Tag.name)
            .join(Tag, Tag.id == TransactionTag.tag_id)
            .where(col(TransactionTag.transaction_id).in_(tids), TransactionTag.user_id == self.uid)
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

    def tag_exists(self, name: str) -> bool:
        return self.db.exec(select(Tag.id).where(Tag.user_id == self.uid, Tag.name == name)).first() is not None

    def set_tags(self, transaction_id: UUID, names: builtins.list[str]) -> None:
        """Make the entry's tags exactly these (already cleaned) names: tags that do not exist yet are made, tags no entry
        carries any more are removed."""
        existing = {
            row.name: row
            for row in self.db.exec(select(Tag).where(Tag.user_id == self.uid, col(Tag.name).in_(names or [""]))).all()
        }
        for name in names:
            if name not in existing:
                existing[name] = Tag(user_id=self.uid, name=name)
                self.db.add(existing[name])
        self.db.flush()
        wanted = {existing[name].id for name in names}
        links = self.db.exec(
            select(TransactionTag).where(
                TransactionTag.transaction_id == transaction_id, TransactionTag.user_id == self.uid
            )
        ).all()
        have = {link.tag_id for link in links}
        for link in links:
            if link.tag_id not in wanted:
                self.db.delete(link)
        for tag_id in wanted - have:
            self.db.add(TransactionTag(transaction_id=transaction_id, tag_id=tag_id, user_id=self.uid))
        self.db.flush()
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
            self.db.exec(select(TransactionTag.transaction_id).where(TransactionTag.tag_id == target.id)).all()
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
        links = self.db.exec(select(TransactionTag).where(TransactionTag.tag_id == tag.id)).all()
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

    def postings_for_transactions(self, tids: builtins.list[UUID]) -> dict[UUID, builtins.list[Posting]]:
        """The postings of several transactions in one query (a list of transactions must not ask once per row)."""
        grouped: dict[UUID, builtins.list[Posting]] = {}
        if not tids:
            return grouped
        for posting in self.db.exec(
            select(Posting).where(col(Posting.transaction_id).in_(tids), Posting.user_id == self.uid)
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
        """The person's entry that a source gave this reference, if there is one."""
        return self.db.exec(
            select(Transaction).where(
                Transaction.user_id == self.uid, Transaction.source == source, Transaction.external_id == external_id
            )
        ).first()

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

    def postings_for_categories(self, bcids: builtins.list[UUID] | set[UUID]) -> builtins.list[Posting]:
        """The lines labelled with any of these categories."""
        if not bcids:
            return []
        return builtins.list(
            self.db.exec(
                select(Posting).where(Posting.user_id == self.uid, col(Posting.category_id).in_(builtins.list(bcids)))
            ).all()
        )

    def refresh_payment_labels(self, account_id: UUID, previous: UUID | None) -> None:
        """A loan's payment category (or the budget an account is in) changed: payments into loans outside the budget
        that name a category carry it again. The loan's own lines that carried the old one (or none) take the new
        one; lines the person labelled otherwise are left alone. Nothing is committed."""
        touching = (
            select(Posting.transaction_id)
            .join(Account, Account.id == Posting.account_id)
            .where(Posting.user_id == self.uid, col(Account.on_budget).is_(True))
        )
        loan = self.db.get(Account, account_id)
        if loan is not None and loan.user_id == self.uid:
            new = loan.payment_category_id if not loan.on_budget else None
            stale = Posting.category_id.is_(None) if previous is None else col(Posting.category_id).in_([previous])
            self.db.exec(
                update(Posting)
                .where(
                    Posting.user_id == self.uid,
                    Posting.account_id == account_id,
                    Posting.side == PostingSide.DEBIT,
                    or_(Posting.category_id.is_(None), stale),
                    col(Posting.transaction_id).in_(touching),
                )
                .values(category_id=new)
            )
        # Any other loan with a payment category: its unlabelled payments in entries that touch the budget.
        for other in self.db.exec(
            select(Account).where(
                Account.user_id == self.uid,
                col(Account.payment_category_id).is_not(None),
                col(Account.on_budget).is_(False),
                Account.id != account_id,
            )
        ).all():
            category = other.payment_category_id
            self.db.exec(
                update(Posting)
                .where(
                    Posting.user_id == self.uid,
                    Posting.account_id == other.id,
                    Posting.side == PostingSide.DEBIT,
                    Posting.category_id.is_(None),
                    col(Posting.transaction_id).in_(touching),
                )
                .values(category_id=category)
            )
        self.db.expire_all()

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
        line labelled with the first takes the second. Each entry it touches gets an "updated" history row saying
        who did it. Returns the entries that moved. Nothing is committed."""
        tids = self.transactions_touching(source)
        if categories is not None:
            tids = builtins.list(dict.fromkeys([*tids, *self.labelled(categories[0])]))
        if not tids:
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
            .where(Transaction.user_id == self.uid, col(Transaction.id).in_(tids))
            .values(updated_via=origin)
        )
        self._record_updated(tids, origin)
        return tids

    def _record_updated(self, tids: builtins.list[UUID], origin: str | None) -> None:
        """An "updated" history row for each entry that was changed in bulk (a merge, a relabelling)."""
        self.db.expire_all()
        moved = self.read_many(tids)
        postings = self.postings_for_transactions(tids)
        tag_names = self.tag_map(tids)
        for transaction_id in tids:
            self.db.add(
                TransactionHistory(
                    user_id=self.uid,
                    transaction_id=transaction_id,
                    action="updated",
                    via=origin,
                    snapshot=self._snapshot(
                        moved[transaction_id], postings.get(transaction_id, []), tag_names.get(transaction_id, [])
                    ),
                )
            )
        self.db.flush()

    def relabel_category(self, old: UUID, new: UUID, origin: str | None) -> builtins.list[UUID]:
        """Every line labelled with one category takes another (a merge). Each entry gets an "updated" history row.
        Returns the entries that changed. Nothing is committed."""
        tids = self.labelled(old)
        if not tids:
            return []
        self.db.exec(
            update(Posting).where(Posting.user_id == self.uid, Posting.category_id == old).values(category_id=new)
        )
        self.db.exec(
            update(Transaction)
            .where(Transaction.user_id == self.uid, col(Transaction.id).in_(tids))
            .values(updated_via=origin)
        )
        self._record_updated(tids, origin)
        return tids

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

    def posting_facts(self, aids: builtins.list[UUID]):
        """What an account's running balance needs from its postings (transaction, side, amount, date, created): no
        payees, notes or other accounts, so a long history costs little to read."""
        if not aids:
            return []
        statement = (
            select(Posting.transaction_id, Posting.side, Posting.amount, Transaction.date, Transaction.created)
            .join(Transaction, Transaction.id == Posting.transaction_id)
            .where(col(Posting.account_id).in_(aids), Posting.user_id == self.uid, Transaction.user_id == self.uid)
        )
        return self.db.exec(statement).all()

    def postings_for_accounts(
        self,
        aids: builtins.list[UUID],
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> builtins.list[Posting]:
        if not aids:
            return []
        statement = select(Posting).where(
            col(Posting.account_id).in_(aids),
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
                ("postings", self.uid, tuple(aids), date_from, date_to),
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
        self._record(transaction, "updated", origin)
        return transaction

    def _replace_postings(self, transaction: Transaction, postings) -> None:
        """Make the transaction's postings the given ones, keeping a posting's id when it lives on.

        A new posting takes over an existing one on the same account and side (then on the same
        account); what is left over is added or removed. So correcting an amount never replaces the posting.
        """
        postings = builtins.list(postings)
        categories = self._line_categories(postings)
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
                old.account_id, old.side, old.amount, old.category_id = (
                    data.account_id,
                    data.side,
                    data.amount,
                    category,
                )
                self.db.add(old)
        self.db.flush()

    def delete(self, transaction_id: UUID, origin: str | None = None) -> Transaction | None:
        transaction = self.read(transaction_id)
        if not transaction:
            return None
        self._record(transaction, "deleted", origin)
        for other in self.related_to(transaction_id):  # what pointed at it is no longer related to anything
            other.related_id = None
            self.db.add(other)
        for posting in self.postings(transaction_id):
            self.db.delete(posting)
        self.set_tags(transaction_id, [])
        self.db.delete(transaction)
        self.db.flush()
        return transaction

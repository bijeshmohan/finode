"""Persistence for transactions and postings, always filtered by the user's id; appends the history row on every create, update and delete."""

import builtins
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, not_, or_, update
from sqlalchemy.orm import aliased
from sqlmodel import Session, col, func, select

from ..models.account import Account
from ..models.recurring import RecurringTransaction
from ..models.tag import Tag, TransactionTag
from ..models.transaction import Posting, PostingSide, Transaction
from ..models.transaction_history import TransactionHistory
from ..models.utils import without_nul
from ..schemas.transaction import TransactionCreate, TransactionUpdate
from ..tags import clean_tag
from .cache import remembered


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
        tid: UUID | None = None,
    ) -> Transaction:
        fields = data.model_dump(exclude={"postings", "tags"})
        transaction = Transaction(**fields, user=self.uid, created_via=origin, updated_via=origin)
        if tid is not None:  # bringing a deleted entry back keeps its id
            transaction.tid = tid
        if recurring is not None:
            transaction.recurring_id, transaction.recurring_date = recurring
        self.db.add(transaction)
        self.db.flush()
        self._add_postings(transaction, data.postings)
        self.db.flush()
        self.set_tags(transaction.tid, data.tags)
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
                {"account": str(p.account), "side": p.side.value, "amount": str(p.amount)}
                for p in sorted(postings, key=lambda p: (p.created, str(p.pid)))
            ],
        }

    def _record(self, transaction: Transaction, action: str, origin: str | None) -> None:
        """Append what the transaction looks like now to its history."""
        snapshot = self._snapshot(transaction, self.postings(transaction.tid), self.tag_names(transaction.tid))
        if action == "deleted":
            # What pointed at it is unlinked below; remember which entries, so restoring it can link them again.
            snapshot["related_from"] = [str(other.tid) for other in self.related_to(transaction.tid)]
        if action == "updated":
            previous = self.history(transaction.tid)
            if previous and comparable_snapshot(previous[-1].snapshot) == snapshot:
                return  # saved without changing anything
        self.db.add(
            TransactionHistory(
                user=self.uid, transaction_id=transaction.tid, action=action, via=origin, snapshot=snapshot
            )
        )
        self.db.flush()

    def history(self, tid: UUID) -> list[TransactionHistory]:
        statement = (
            select(TransactionHistory)
            .where(TransactionHistory.transaction_id == tid, TransactionHistory.user == self.uid)
            .order_by(TransactionHistory.at, TransactionHistory.hid)
        )
        return self.db.exec(statement).all()

    def history_since(self, since: datetime | None, via: str | None, limit: int) -> builtins.list[TransactionHistory]:
        """The newest history rows of every entry (deleted ones too), optionally from a moment on and by one origin.
        `via` is an origin ("web", "api", "import", "recurring", "mcp:<name>") or "assistant" for any assistant."""
        statement = select(TransactionHistory).where(TransactionHistory.user == self.uid)
        if since is not None:
            statement = statement.where(TransactionHistory.at >= since)
        if via == "assistant":
            statement = statement.where(col(TransactionHistory.via).startswith("mcp:"))
        elif via:
            statement = statement.where(TransactionHistory.via == via)
        return self.db.exec(
            statement.order_by(col(TransactionHistory.at).desc(), col(TransactionHistory.hid)).limit(limit)
        ).all()

    def histories_for(self, tids: builtins.list[UUID]) -> builtins.list[TransactionHistory]:
        """Every history row of the given entries, oldest first."""
        if not tids:
            return []
        return self.db.exec(
            select(TransactionHistory)
            .where(TransactionHistory.user == self.uid, col(TransactionHistory.transaction_id).in_(tids))
            .order_by(TransactionHistory.at, TransactionHistory.hid)
        ).all()

    def deleted(self) -> list[TransactionHistory]:
        """The deletion record of every transaction that no longer exists, newest first."""
        statement = (
            select(TransactionHistory)
            .where(TransactionHistory.user == self.uid, TransactionHistory.action == "deleted")
            .order_by(col(TransactionHistory.at).desc())
        )
        return self.db.exec(statement).all()

    def deleted_row(self, hid: UUID) -> TransactionHistory | None:
        return self.db.exec(
            select(TransactionHistory).where(
                TransactionHistory.hid == hid,
                TransactionHistory.user == self.uid,
                TransactionHistory.action == "deleted",
            )
        ).first()

    def _add_postings(self, transaction: Transaction, postings) -> None:
        for posting_data in postings:
            self.db.add(Posting(**posting_data.model_dump(), transaction=transaction.tid, user=self.uid))

    def read(self, tid: UUID) -> Transaction | None:
        statement = select(Transaction).where(
            Transaction.tid == tid,
            Transaction.user == self.uid,
        )
        transaction = self.db.exec(statement).first()
        return transaction

    def related_to(self, tid: UUID) -> list[Transaction]:
        """The entries that point at this one, oldest first."""
        return self.db.exec(
            select(Transaction)
            .where(Transaction.related_id == tid, Transaction.user == self.uid)
            .order_by(Transaction.date, Transaction.created)
        ).all()

    def read_many(self, tids: list[UUID]) -> dict[UUID, Transaction]:
        """Several transactions in one query."""
        if not tids:
            return {}
        rows = self.db.exec(
            select(Transaction).where(col(Transaction.tid).in_(list(tids)), Transaction.user == self.uid)
        ).all()
        return {t.tid: t for t in rows}

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
        statement = select(Transaction).where(Transaction.user == self.uid)
        if text:
            text = without_nul(text)
            named = (
                select(Posting.transaction)
                .join(Account, Account.aid == Posting.account)
                .where(Posting.user == self.uid, col(Account.name).icontains(text, autoescape=True))
            )
            statement = statement.where(
                or_(
                    col(Transaction.payee).icontains(text, autoescape=True),
                    col(Transaction.comment).icontains(text, autoescape=True),
                    col(Transaction.tid).in_(named),
                )
            )
        if kind and kind_accounts is not None:
            expense_ids, income_ids = kind_accounts
            spends = col(Transaction.tid).in_(
                select(Posting.transaction).where(
                    Posting.user == self.uid, Posting.side == PostingSide.DEBIT, col(Posting.account).in_(expense_ids)
                )
            )
            earns = col(Transaction.tid).in_(
                select(Posting.transaction).where(
                    Posting.user == self.uid, Posting.side == PostingSide.CREDIT, col(Posting.account).in_(income_ids)
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
                col(Transaction.tid).in_(
                    select(Posting.transaction).where(
                        col(Posting.account).in_(account_ids),
                        Posting.user == self.uid,
                    )
                )
            )
        if also_ids is not None:  # a second account the entry must touch as well (the web filter's category)
            statement = statement.where(
                col(Transaction.tid).in_(
                    select(Posting.transaction).where(col(Posting.account).in_(also_ids), Posting.user == self.uid)
                )
            )
        if payee:  # exactly this payee, capitals aside
            statement = statement.where(func.lower(Transaction.payee) == without_nul(payee).strip().lower())
        if tag:
            statement = statement.where(
                col(Transaction.tid).in_(
                    select(TransactionTag.transaction_id)
                    .join(Tag, Tag.tgid == TransactionTag.tag_id)
                    .where(Tag.user == self.uid, Tag.name == clean_tag(tag))
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

    def tag_names(self, tid: UUID) -> builtins.list[str]:
        """The names of the tags on one entry, A to Z."""
        return self.tag_map([tid]).get(tid, [])

    def tag_map(self, tids: builtins.list[UUID]) -> dict[UUID, builtins.list[str]]:
        """The tag names of several entries in one query (a list must not ask once per row)."""
        found: dict[UUID, builtins.list[str]] = {}
        if not tids:
            return found
        rows = self.db.exec(
            select(TransactionTag.transaction_id, Tag.name)
            .join(Tag, Tag.tgid == TransactionTag.tag_id)
            .where(col(TransactionTag.transaction_id).in_(tids), TransactionTag.user == self.uid)
            .order_by(Tag.name)
        ).all()
        for tid, name in rows:
            found.setdefault(tid, []).append(name)
        return found

    def all_tag_map(self) -> dict[UUID, builtins.list[str]]:
        """The tag names of every entry (for a backup: no list of ids, so any number of entries is fine)."""
        found: dict[UUID, builtins.list[str]] = {}
        for tid, name in self.db.exec(
            select(TransactionTag.transaction_id, Tag.name)
            .join(Tag, Tag.tgid == TransactionTag.tag_id)
            .where(TransactionTag.user == self.uid)
            .order_by(Tag.name)
        ).all():
            found.setdefault(tid, []).append(name)
        return found

    def count_tags(self) -> int:
        return self.db.exec(select(func.count()).select_from(Tag).where(Tag.user == self.uid)).one()

    def tag_exists(self, name: str) -> bool:
        return self.db.exec(select(Tag.tgid).where(Tag.user == self.uid, Tag.name == name)).first() is not None

    def set_tags(self, tid: UUID, names: builtins.list[str]) -> None:
        """Make the entry's tags exactly these (already cleaned) names: tags that do not exist yet are made, tags no entry
        carries any more are removed."""
        existing = {
            row.name: row
            for row in self.db.exec(select(Tag).where(Tag.user == self.uid, col(Tag.name).in_(names or [""]))).all()
        }
        for name in names:
            if name not in existing:
                existing[name] = Tag(user=self.uid, name=name)
                self.db.add(existing[name])
        self.db.flush()
        wanted = {existing[name].tgid for name in names}
        links = self.db.exec(
            select(TransactionTag).where(TransactionTag.transaction_id == tid, TransactionTag.user == self.uid)
        ).all()
        have = {link.tag_id for link in links}
        for link in links:
            if link.tag_id not in wanted:
                self.db.delete(link)
        for tag_id in wanted - have:
            self.db.add(TransactionTag(transaction_id=tid, tag_id=tag_id, user=self.uid))
        self.db.flush()
        self.drop_unused_tags()

    def drop_unused_tags(self) -> None:
        """A tag exists only while an entry carries it."""
        used = select(TransactionTag.tag_id).where(TransactionTag.user == self.uid)
        for tag in self.db.exec(select(Tag).where(Tag.user == self.uid, col(Tag.tgid).not_in(used))).all():
            self.db.delete(tag)
        self.db.flush()

    def tag_stats(self) -> builtins.list[tuple[str, int, date]]:
        """Every tag with how many entries carry it and the day of the latest, the most used first."""
        rows = self.db.exec(
            select(Tag.name, func.count(), func.max(Transaction.date))
            .join(TransactionTag, TransactionTag.tag_id == Tag.tgid)
            .join(Transaction, Transaction.tid == TransactionTag.transaction_id)
            .where(Tag.user == self.uid)
            .group_by(Tag.name)
            .order_by(func.count().desc(), Tag.name)
        ).all()
        return [(name, count, last) for name, count, last in rows]

    def tagged(self) -> builtins.list[Transaction]:
        """The entries that carry at least one tag, newest first."""
        statement = (
            select(Transaction)
            .where(
                Transaction.user == self.uid,
                col(Transaction.tid).in_(select(TransactionTag.transaction_id).where(TransactionTag.user == self.uid)),
            )
            .order_by(col(Transaction.date).desc(), col(Transaction.created).desc())
        )
        return self.db.exec(statement).all()

    def _retag_rules(self, old: str, new: str | None) -> None:
        """Recurring rules keep their own list of tag names: follow a rename or a merge (`new`), or drop the tag (None)."""
        for rule in self.db.exec(select(RecurringTransaction).where(RecurringTransaction.user == self.uid)).all():
            if old not in (rule.tags or []):
                continue
            names = [new if name == old else name for name in rule.tags]
            rule.tags = [name for name in dict.fromkeys(names) if name is not None]
            self.db.add(rule)
        self.db.flush()

    def rename_tag(self, old: str, new: str) -> None:
        """Give a tag a new name. When the new name is another tag of the person's, the two become one."""
        tag = self.db.exec(select(Tag).where(Tag.user == self.uid, Tag.name == old)).first()
        if tag is None:
            raise LookupError(f"no tag is called '{old}'!")
        self._retag_rules(old, new)
        target = self.db.exec(select(Tag).where(Tag.user == self.uid, Tag.name == new)).first()
        if target is None:
            tag.name = new
            self.db.add(tag)
            self.db.flush()
            return
        already = set(
            self.db.exec(select(TransactionTag.transaction_id).where(TransactionTag.tag_id == target.tgid)).all()
        )
        for link in self.db.exec(
            select(TransactionTag).where(TransactionTag.tag_id == tag.tgid, TransactionTag.user == self.uid)
        ).all():
            if link.transaction_id not in already:
                self.db.add(TransactionTag(transaction_id=link.transaction_id, tag_id=target.tgid, user=self.uid))
            self.db.delete(link)
        self.db.flush()
        self.db.delete(tag)
        self.db.flush()

    def delete_tag(self, name: str) -> int:
        """Take a tag off every entry and remove it; returns how many entries had it."""
        tag = self.db.exec(select(Tag).where(Tag.user == self.uid, Tag.name == name)).first()
        if tag is None:
            raise LookupError(f"no tag is called '{name}'!")
        self._retag_rules(name, None)
        links = self.db.exec(select(TransactionTag).where(TransactionTag.tag_id == tag.tgid)).all()
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
                Transaction.user == self.uid,
                col(Transaction.payee).is_not(None),
                col(Transaction.payee).not_in(SYSTEM_PAYEES),
            )
            .group_by(func.lower(Transaction.payee))
            .order_by(func.count().desc(), func.lower(Transaction.payee))
            .limit(limit)
        ).all()
        return [(name, count) for _, name, count in rows if name]

    def postings(self, tid: UUID) -> builtins.list[Posting]:
        statement = select(Posting).where(
            Posting.transaction == tid,
            Posting.user == self.uid,
        )
        postings = self.db.exec(statement).all()
        return postings

    def postings_for_transactions(self, tids: builtins.list[UUID]) -> dict[UUID, builtins.list[Posting]]:
        """The postings of several transactions in one query (a list of transactions must not ask once per row)."""
        grouped: dict[UUID, builtins.list[Posting]] = {}
        if not tids:
            return grouped
        for posting in self.db.exec(
            select(Posting).where(col(Posting.transaction).in_(tids), Posting.user == self.uid)
        ).all():
            grouped.setdefault(posting.transaction, []).append(posting)
        return grouped

    def posting_rows(self, date_to: date):
        """Every posting of transactions dated up to a day, as (transaction, account, side, amount, date) rows: what the
        budget is worked out from, without payees, notes or timestamps. One query, remembered for the request."""
        statement = (
            select(Posting.transaction, Posting.account, Posting.side, Posting.amount, Transaction.date)
            .join(Transaction, Transaction.tid == Posting.transaction)
            .where(Posting.user == self.uid, Transaction.user == self.uid, Transaction.date <= date_to)
        )
        return list(remembered(self.db, ("posting_rows", self.uid, date_to), lambda: self.db.exec(statement).all()))

    def all_postings(self) -> builtins.list[Posting]:
        return self.db.exec(select(Posting).where(Posting.user == self.uid)).all()

    def count(self) -> int:
        return self.db.exec(select(func.count()).select_from(Transaction).where(Transaction.user == self.uid)).one()

    def find_by_reference(self, source: str, external_id: str) -> Transaction | None:
        """The person's entry that a source gave this reference, if there is one."""
        return self.db.exec(
            select(Transaction).where(
                Transaction.user == self.uid, Transaction.source == source, Transaction.external_id == external_id
            )
        ).first()

    def transactions_touching(self, aid: UUID) -> builtins.list[UUID]:
        """The entries that have a posting on the account."""
        return list(
            self.db.exec(
                select(Posting.transaction).where(Posting.user == self.uid, Posting.account == aid).distinct()
            ).all()
        )

    def opposite_sides(self, a: UUID, b: UUID) -> int:
        """How many entries have one account on one side and the other on the opposite side."""
        first, second = aliased(Posting), aliased(Posting)
        return self.db.exec(
            select(func.count(func.distinct(first.transaction)))
            .select_from(first)
            .join(second, second.transaction == first.transaction)
            .where(
                first.user == self.uid,
                second.user == self.uid,
                first.account == a,
                second.account == b,
                first.side != second.side,
            )
        ).one()

    def repoint_account(self, source: UUID, target: UUID, origin: str | None) -> builtins.list[UUID]:
        """Move every posting from one account to another (a merge). Each entry it touches gets an "updated" history
        row saying who did it. Returns the entries that moved. Nothing is committed."""
        tids = self.transactions_touching(source)
        if not tids:
            return []
        self.db.exec(update(Posting).where(Posting.user == self.uid, Posting.account == source).values(account=target))
        self.db.exec(
            update(Transaction)
            .where(Transaction.user == self.uid, col(Transaction.tid).in_(tids))
            .values(updated_via=origin)
        )
        self.db.expire_all()
        moved = self.read_many(tids)
        postings = self.postings_for_transactions(tids)
        tag_names = self.tag_map(tids)
        for tid in tids:
            self.db.add(
                TransactionHistory(
                    user=self.uid,
                    transaction_id=tid,
                    action="updated",
                    via=origin,
                    snapshot=self._snapshot(moved[tid], postings.get(tid, []), tag_names.get(tid, [])),
                )
            )
        self.db.flush()
        return tids

    def last_change(self) -> datetime | None:
        """When any transaction was last made or changed."""
        return self.db.exec(select(func.max(Transaction.updated)).where(Transaction.user == self.uid)).one()

    def count_since(self, since: datetime, leaving_out: tuple[str, ...] = ()) -> int:
        """Transactions created since a moment, not counting those made by the given origins (a recurring rule)."""
        statement = (
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.user == self.uid, Transaction.created >= since)
        )
        for origin in leaving_out:
            statement = statement.where(or_(col(Transaction.created_via).is_(None), Transaction.created_via != origin))
        return self.db.exec(statement).one()

    def account_ids_with_postings(self) -> set[UUID]:
        return set(self.db.exec(select(Posting.account).where(Posting.user == self.uid).distinct()).all())

    def postings_for_account(self, aid: UUID) -> builtins.list[Posting]:
        statement = select(Posting).where(
            Posting.account == aid,
            Posting.user == self.uid,
        )
        postings = self.db.exec(statement).all()
        return postings

    def posting_facts(self, aids: builtins.list[UUID]):
        """What an account's running balance needs from its postings (transaction, side, amount, date, created): no
        payees, notes or other accounts, so a long history costs little to read."""
        if not aids:
            return []
        statement = (
            select(Posting.transaction, Posting.side, Posting.amount, Transaction.date, Transaction.created)
            .join(Transaction, Transaction.tid == Posting.transaction)
            .where(col(Posting.account).in_(aids), Posting.user == self.uid, Transaction.user == self.uid)
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
            col(Posting.account).in_(aids),
            Posting.user == self.uid,
        )
        if date_from is not None or date_to is not None:
            statement = statement.join(Transaction, Transaction.tid == Posting.transaction)
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
        tid: UUID,
        data: TransactionUpdate,
        origin: str | None = None,
    ) -> Transaction | None:
        transaction = self.read(tid)
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
            self.set_tags(tid, data.tags)

        self.db.add(transaction)
        self.db.flush()
        self._record(transaction, "updated", origin)
        return transaction

    def _replace_postings(self, transaction: Transaction, postings) -> None:
        """Make the transaction's postings the given ones, keeping a posting's id when it lives on.

        A new posting takes over an existing one on the same account and side (then on the same
        account); what is left over is added or removed. So correcting an amount never replaces the posting.
        """
        remaining = list(self.postings(transaction.tid))
        taken: builtins.list[Posting | None] = [None] * len(postings)
        for exact in (True, False):
            for index, data in enumerate(postings):
                if taken[index] is not None:
                    continue
                for old in remaining:
                    if old.account == data.account and (not exact or old.side == data.side):
                        taken[index] = old
                        remaining.remove(old)
                        break
        for posting in remaining:
            self.db.delete(posting)
        for data, old in zip(postings, taken, strict=False):
            if old is None:
                self.db.add(Posting(**data.model_dump(), transaction=transaction.tid, user=self.uid))
            else:
                old.account, old.side, old.amount = data.account, data.side, data.amount
                self.db.add(old)
        self.db.flush()

    def delete(self, tid: UUID, origin: str | None = None) -> Transaction | None:
        transaction = self.read(tid)
        if not transaction:
            return None
        self._record(transaction, "deleted", origin)
        for other in self.related_to(tid):  # what pointed at it is no longer related to anything
            other.related_id = None
            self.db.add(other)
        for posting in self.postings(tid):
            self.db.delete(posting)
        self.set_tags(tid, [])
        self.db.delete(transaction)
        self.db.flush()
        return transaction

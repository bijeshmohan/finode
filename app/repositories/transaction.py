"""Persistence for transactions and postings, always filtered by the user's id; appends the history row on every create, update and delete."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import and_, not_, or_
from sqlmodel import Session, func, select

from ..models.account import Account
from ..models.transaction import Posting, PostingSide, Transaction
from ..models.transaction_history import TransactionHistory
from ..schemas.transaction import TransactionCreate, TransactionUpdate
from ..models.utils import without_nul
from .cache import remembered


def _comparable(snapshot: dict) -> dict:
    """A stored snapshot without what entries made before finode kept one currency also recorded (the currency, each worth)."""
    return {
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
        fields = data.model_dump(exclude={"postings"})
        transaction = Transaction(**fields, user=self.uid, created_via=origin, updated_via=origin)
        if tid is not None:  # bringing a deleted entry back keeps its id
            transaction.tid = tid
        if recurring is not None:
            transaction.recurring_id, transaction.recurring_date = recurring
        self.db.add(transaction)
        self.db.flush()
        self._add_postings(transaction, data.postings)
        self.db.flush()
        self._record(transaction, "created", origin)
        return transaction

    def _record(self, transaction: Transaction, action: str, origin: str | None) -> None:
        """Append what the transaction looks like now to its history."""
        snapshot = {
            "date": transaction.date.isoformat(),
            "payee": transaction.payee,
            "comment": transaction.comment,
            "recurring_id": str(transaction.recurring_id) if transaction.recurring_id else None,
            "postings": [
                {"account": str(p.account), "side": p.side.value, "amount": str(p.amount)}
                for p in sorted(self.postings(transaction.tid), key=lambda p: (p.created, str(p.pid)))
            ],
        }
        if action == "updated":
            previous = self.history(transaction.tid)
            if previous and _comparable(previous[-1].snapshot) == snapshot:
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

    def deleted(self) -> list[TransactionHistory]:
        """The deletion record of every transaction that no longer exists, newest first."""
        statement = (
            select(TransactionHistory)
            .where(TransactionHistory.user == self.uid, TransactionHistory.action == "deleted")
            .order_by(TransactionHistory.at.desc())
        )
        return self.db.exec(statement).all()

    def deleted_row(self, hid: UUID) -> TransactionHistory | None:
        return self.db.exec(
            select(TransactionHistory).where(
                TransactionHistory.hid == hid, TransactionHistory.user == self.uid, TransactionHistory.action == "deleted"
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

    def read_many(self, tids: list[UUID]) -> dict[UUID, Transaction]:
        """Several transactions in one query."""
        if not tids:
            return {}
        rows = self.db.exec(select(Transaction).where(Transaction.tid.in_(list(tids)), Transaction.user == self.uid)).all()
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
    ):
        """The transactions that match, unordered (what `list` pages through and `count` counts)."""
        statement = select(Transaction).where(Transaction.user == self.uid)
        if text:
            text = without_nul(text)
            named = (
                select(Posting.transaction)
                .join(Account, Account.aid == Posting.account)
                .where(Posting.user == self.uid, Account.name.icontains(text, autoescape=True))
            )
            statement = statement.where(or_(
                Transaction.payee.icontains(text, autoescape=True),
                Transaction.comment.icontains(text, autoescape=True),
                Transaction.tid.in_(named),
            ))
        if kind and kind_accounts is not None:
            expense_ids, income_ids = kind_accounts
            spends = Transaction.tid.in_(select(Posting.transaction).where(
                Posting.user == self.uid, Posting.side == PostingSide.DEBIT, Posting.account.in_(expense_ids)))
            earns = Transaction.tid.in_(select(Posting.transaction).where(
                Posting.user == self.uid, Posting.side == PostingSide.CREDIT, Posting.account.in_(income_ids)))
            # The same order as the rows are told apart in the list: spending first, then income, else a transfer.
            statement = statement.where({
                "expense": spends,
                "income": and_(earns, not_(spends)),
                "transfer": and_(not_(spends), not_(earns)),
            }[kind])
        if account_ids is not None:
            statement = statement.where(
                Transaction.tid.in_(
                    select(Posting.transaction).where(
                        Posting.account.in_(account_ids),
                        Posting.user == self.uid,
                    )
                )
            )
        if also_ids is not None:  # a second account the entry must touch as well (the web filter's category)
            statement = statement.where(Transaction.tid.in_(
                select(Posting.transaction).where(Posting.account.in_(also_ids), Posting.user == self.uid)))
        if payee:  # exactly this payee, capitals aside
            statement = statement.where(func.lower(Transaction.payee) == without_nul(payee).strip().lower())
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
        account_ids: list[UUID] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
        offset: int = 0,
        text: str | None = None,
        kind: str | None = None,
        kind_accounts: tuple[list[UUID], list[UUID]] | None = None,
        also_ids: list[UUID] | None = None,
        payee: str | None = None,
    ) -> list[Transaction]:
        """Transactions, newest first. `text` matches the payee, the note or the name of an account used; `kind`
        (expense, income or transfer) is told by `kind_accounts`, the ids under Expenses and under Income."""
        statement = self._matching(account_ids, date_from, date_to, text, kind, kind_accounts, also_ids, payee)
        statement = statement.order_by(
            Transaction.date.desc(),
            Transaction.created.desc(),
        ).offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        transactions = self.db.exec(statement).all()
        return transactions

    def payees(self, limit: int = 300) -> list[tuple[str, int]]:
        """The payees used, the most used first (one spelling each: the newest entry's)."""
        rows = self.db.exec(
            select(func.lower(Transaction.payee), func.max(Transaction.payee), func.count())
            .where(Transaction.user == self.uid, Transaction.payee.is_not(None), Transaction.payee.not_in(SYSTEM_PAYEES))
            .group_by(func.lower(Transaction.payee))
            .order_by(func.count().desc(), func.lower(Transaction.payee))
            .limit(limit)
        ).all()
        return [(name, count) for _, name, count in rows if name]

    def postings(self, tid: UUID) -> list[Posting]:
        statement = select(Posting).where(
            Posting.transaction == tid,
            Posting.user == self.uid,
        )
        postings = self.db.exec(statement).all()
        return postings

    def postings_for_transactions(self, tids: list[UUID]) -> dict[UUID, list[Posting]]:
        """The postings of several transactions in one query (a list of transactions must not ask once per row)."""
        grouped: dict[UUID, list[Posting]] = {}
        if not tids:
            return grouped
        for posting in self.db.exec(select(Posting).where(Posting.transaction.in_(tids), Posting.user == self.uid)).all():
            grouped.setdefault(posting.transaction, []).append(posting)
        return grouped

    def all_postings(self) -> list[Posting]:
        return self.db.exec(select(Posting).where(Posting.user == self.uid)).all()

    def count(self) -> int:
        return self.db.exec(select(func.count()).select_from(Transaction).where(Transaction.user == self.uid)).one()

    def count_since(self, since: datetime, leaving_out: tuple[str, ...] = ()) -> int:
        """Transactions created since a moment, not counting those made by the given origins (a recurring rule)."""
        statement = select(func.count()).select_from(Transaction).where(
            Transaction.user == self.uid, Transaction.created >= since
        )
        for origin in leaving_out:
            statement = statement.where(or_(Transaction.created_via.is_(None), Transaction.created_via != origin))
        return self.db.exec(statement).one()

    def account_ids_with_postings(self) -> set[UUID]:
        return set(self.db.exec(select(Posting.account).where(Posting.user == self.uid).distinct()).all())

    def postings_for_account(self, aid: UUID) -> list[Posting]:
        statement = select(Posting).where(
            Posting.account == aid,
            Posting.user == self.uid,
        )
        postings = self.db.exec(statement).all()
        return postings

    def posting_facts(self, aids: list[UUID]):
        """What an account's running balance needs from its postings (transaction, side, amount, date, created): no
        payees, notes or other accounts, so a long history costs little to read."""
        if not aids:
            return []
        statement = (
            select(Posting.transaction, Posting.side, Posting.amount, Transaction.date, Transaction.created)
            .join(Transaction, Transaction.tid == Posting.transaction)
            .where(Posting.account.in_(aids), Posting.user == self.uid, Transaction.user == self.uid)
        )
        return self.db.exec(statement).all()

    def postings_for_accounts(
        self,
        aids: list[UUID],
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[Posting]:
        if not aids:
            return []
        statement = select(Posting).where(
            Posting.account.in_(aids),
            Posting.user == self.uid,
        )
        if date_from is not None or date_to is not None:
            statement = statement.join(
                Transaction, Transaction.tid == Posting.transaction
            )
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

        fields = data.model_dump(exclude_unset=True, exclude={"postings"})
        for key, value in fields.items():
            setattr(transaction, key, value)
        if origin is not None:
            transaction.updated_via = origin

        if data.postings is not None:
            self._replace_postings(transaction, data.postings)

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
        taken: list[Posting | None] = [None] * len(postings)
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
        for data, old in zip(postings, taken):
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
        for posting in self.postings(tid):
            self.db.delete(posting)
        self.db.delete(transaction)
        self.db.flush()
        return transaction

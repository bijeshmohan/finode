from datetime import date
from decimal import Decimal
from uuid import UUID

from ..config import settings
from ..clock import local_midnight_utc
from .lock import LockedPeriodError as _LockedPeriodError, refuse_locked
from ..limits import ensure_room
from ..currencies import Currency, find as find_currency
from ..models.transaction import Transaction, Posting, PostingSide
from ..repositories import AccountRepository, ProfileRepository, TransactionRepository
from .account import GROUP_POSTING_ROOT_NAMES, AccountService
from ..schemas.transaction import (
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
    PostingRead,
    HistoryPosting,
    HistoryRead,
)


class InvalidPostingError(ValueError):
    ...


class LockedPeriodError(InvalidPostingError, _LockedPeriodError):
    """The date is inside the locked period (a 400 for the API, like any other invalid entry)."""


class InvalidPostingAccountError(InvalidPostingError):
    ...


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
        self._currency: Currency | None = None

    def currency(self) -> Currency:
        if self._currency is None:
            self._currency = find_currency(self.pr.currency())
            if self._currency is None:
                raise RuntimeError("the profile names a currency finode does not know")
        return self._currency

    def _resolve(self, data: TransactionCreate | TransactionUpdate, keep_closed: set[UUID] = frozenset()) -> None:
        """Check the postings: the accounts can be posted to, the amounts fit the currency and the entry balances."""
        postings = data.postings
        if postings is None:
            return

        if settings.max_postings_per_transaction and len(postings) > settings.max_postings_per_transaction:
            raise InvalidPostingError(
                f"a transaction can have at most {settings.max_postings_per_transaction} postings: split it into several!"
            )
        currency = self.currency()
        accounts_by_id = None
        for posting in postings:
            account = self.ar.read(posting.account)
            if not account:
                raise ValueError(f"account with aid '{posting.account}' not found!")
            if account.parent_id is None:
                raise InvalidPostingAccountError(f"cannot post to root account '{account.name}'!")
            if account.closed_on is not None and account.aid not in keep_closed:
                raise InvalidPostingAccountError(f"account '{account.name}' is closed: reopen it to use it!")
            if self.ar.has_children(account.aid):
                if accounts_by_id is None:
                    accounts_by_id = {a.aid: a for a in self.ar.list()}
                if AccountService.root_name(account, accounts_by_id) not in GROUP_POSTING_ROOT_NAMES:
                    raise InvalidPostingAccountError(
                        f"cannot post to account '{account.name}' because it has sub-accounts!"
                    )
            if decimal_places(posting.amount) > currency.decimals:
                raise InvalidPostingError(
                    f"{currency.code} amounts can have at most {currency.decimals} "
                    f"decimal place{'' if currency.decimals == 1 else 's'}!"
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
            created=posting.created,
            updated=posting.updated,
        )

    def _to_read(self, transaction: Transaction, postings: list[Posting] | None = None) -> TransactionRead:
        return TransactionRead(
            tid=transaction.tid,
            date=transaction.date,
            payee=transaction.payee,
            comment=transaction.comment,
            created_via=transaction.created_via,
            updated_via=transaction.updated_via,
            recurring_id=transaction.recurring_id,
            postings=[
                self._posting_to_read(posting)
                for posting in (postings if postings is not None else self.tr.postings(transaction.tid))
            ],
            created=transaction.created,
            updated=transaction.updated,
        )

    def _history_read(self, row, paths: dict[UUID, str]) -> HistoryRead:
        snap = row.snapshot
        return HistoryRead(
            hid=row.hid,
            transaction=row.transaction_id,
            action=row.action,
            at=row.at,
            via=row.via,
            date=date.fromisoformat(snap["date"]),
            payee=snap.get("payee"),
            comment=snap.get("comment"),
            postings=[
                HistoryPosting(
                    account=paths.get(UUID(p["account"]), p["account"]),
                    side=p["side"],
                    amount=Decimal(p["amount"]),
                )
                for p in snap["postings"]
            ],
        )

    def _account_paths(self) -> dict[UUID, str]:
        accounts = {a.aid: a for a in self.ar.list()}
        paths: dict[UUID, str] = {}
        for aid, account in accounts.items():
            chain, seen = [], set()
            while account is not None and account.aid not in seen:
                seen.add(account.aid)
                chain.append(account.name)
                account = accounts.get(account.parent_id) if account.parent_id else None
            paths[aid] = ":".join(reversed(chain))
        return paths

    def history(self, tid: UUID) -> list[HistoryRead]:
        """What happened to a transaction, oldest first; works for a deleted one too."""
        paths = self._account_paths()
        return [self._history_read(row, paths) for row in self.tr.history(tid)]

    def deleted(self) -> list[HistoryRead]:
        """Transactions that were deleted, as they were when deleted, newest first."""
        paths = self._account_paths()
        return [self._history_read(row, paths) for row in self.tr.deleted()]

    def validate(self, data: TransactionCreate) -> None:
        """Raise what create would raise, without saving anything."""
        self._resolve(data)

    def _check_limits(self) -> None:
        ensure_room(self.tr.count(), settings.max_transactions, "transactions")
        if settings.max_transactions_per_day and self.origin not in ("recurring", "import"):
            midnight = local_midnight_utc()
            made = self.tr.count_since(midnight, leaving_out=("recurring", "import"))
            ensure_room(made, settings.max_transactions_per_day, "new transactions a day")

    def _refuse_locked(self, *days: date | None) -> None:
        try:
            refuse_locked(self.tr.db, self.tr.uid, *days)
        except _LockedPeriodError as e:
            raise LockedPeriodError(str(e)) from None

    def create(self, data: TransactionCreate, recurring: tuple[UUID, date] | None = None) -> TransactionRead:
        self._refuse_locked(data.date)
        self._check_limits()
        self._resolve(data)
        transaction = self.tr.create(data, self.origin, recurring)
        self.tr.db.commit()
        self.tr.db.refresh(transaction)
        return self._to_read(transaction)

    def read(self, tid: UUID) -> TransactionRead | None:
        transaction = self.tr.read(tid)
        if not transaction:
            return None
        return self._to_read(transaction)

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

    def list(
        self,
        account: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
        offset: int = 0,
        text: str | None = None,
        kind: str | None = None,
    ) -> list[TransactionRead]:
        account_ids = self._account_subtree(account) if account else None
        if kind not in (None, "", "expense", "income", "transfer"):
            raise ValueError("the kind must be expense, income or transfer!")
        kind_accounts = None
        if kind:
            roots = {a.name: a.aid for a in self.ar.list() if a.parent_id is None}
            kind_accounts = tuple(self._account_subtree(roots[name]) if name in roots else [] for name in ("Expenses", "Income"))
        transactions = self.tr.list(
            account_ids, date_from, date_to, limit, offset, (text or "").strip() or None, kind or None, kind_accounts
        )
        postings = self.tr.postings_for_transactions([t.tid for t in transactions])  # one query, not one per row
        return [self._to_read(transaction, postings.get(transaction.tid, [])) for transaction in transactions]

    def update(
        self,
        tid: UUID,
        data: TransactionUpdate,
    ) -> TransactionRead | None:
        existing = self.tr.read(tid)
        if not existing:
            raise ValueError(f"transaction with tid '{tid}' not found!")
        self._refuse_locked(existing.date, getattr(data, "date", None) if "date" in data.model_fields_set else None)
        # Postings an entry already has on an account that was closed since stay allowed, so it can still be edited.
        kept = {p.account for p in self.tr.postings(tid)}
        self._resolve(data, kept)
        transaction = self.tr.update(tid, data, self.origin)
        if not transaction:
            raise RuntimeError(f"failed to update transaction with tid '{tid}'!")
        self.tr.db.commit()
        self.tr.db.refresh(transaction)
        return self._to_read(transaction)

    def delete(self, tid: UUID) -> TransactionRead | None:
        transaction = self.read(tid)
        if transaction is not None:
            self._refuse_locked(transaction.date)
        deleted = self.tr.delete(tid, self.origin)
        if not deleted:
            raise ValueError(f"transaction with tid '{tid}' not found!")
        self.tr.db.commit()
        return transaction

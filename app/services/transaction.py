from datetime import date
from decimal import Decimal
from uuid import UUID

from ..models.commodity import Commodity
from ..models.transaction import Transaction, Posting, PostingSide
from ..repositories import AccountRepository, CommodityRepository, TransactionRepository
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
        cr: CommodityRepository | None = None,
        origin: str | None = None,
    ):
        # Recorded on what this service creates or changes: "web", "api" or "mcp:<token name>".
        self.origin = origin
        self.tr = tr
        self.ar = ar
        self.cr = cr or CommodityRepository(tr.db, tr.uid)
        self._commodities: dict[UUID, Commodity] | None = None

    def _catalog(self) -> dict[UUID, Commodity]:
        if self._commodities is None:
            self._commodities = {c.cid: c for c in self.cr.list()}
        return self._commodities

    def _commodity_code(self, commodity_id: UUID) -> str:
        return self._catalog()[commodity_id].code

    def _currency(self, code: str | None, current: UUID | None) -> Commodity:
        """The currency a transaction balances in: the one named, else the one it has, else the default."""
        if code:
            commodity = self.cr.read_by_code(code.upper())
            if commodity is None:
                raise InvalidPostingError(f"unknown currency '{code}'!")
            return commodity
        if current is not None:
            return self._catalog()[current]
        return self.cr.default_currency()

    def _resolve(
        self,
        data: TransactionCreate | TransactionUpdate,
        current_currency: UUID | None = None,
    ) -> tuple[UUID | None, list[Decimal] | None]:
        """Check the postings and work out what each is worth in the transaction's currency.

        Returns the currency and one value per posting, or (None, None) when an update leaves the
        postings alone.
        """
        postings = data.postings
        if postings is None:
            if data.currency and self._currency(data.currency, None).cid != current_currency:
                raise InvalidPostingError("changing a transaction's currency means entering its postings again!")
            return None, None

        currency = self._currency(data.currency, current_currency)
        accounts_by_id = None
        values: list[Decimal] = []
        for posting in postings:
            account = self.ar.read(posting.account)
            if not account:
                raise ValueError(f"account with aid '{posting.account}' not found!")
            if account.parent_id is None:
                raise InvalidPostingAccountError(f"cannot post to root account '{account.name}'!")
            if self.ar.has_children(account.aid):
                if accounts_by_id is None:
                    accounts_by_id = {a.aid: a for a in self.ar.list()}
                if AccountService.root_name(account, accounts_by_id) not in GROUP_POSTING_ROOT_NAMES:
                    raise InvalidPostingAccountError(
                        f"cannot post to account '{account.name}' because it has sub-accounts!"
                    )
            values.append(self._value_of(posting, account, currency))

        debits = sum((v for p, v in zip(postings, values) if p.side == PostingSide.DEBIT), Decimal(0))
        credits = sum((v for p, v in zip(postings, values) if p.side == PostingSide.CREDIT), Decimal(0))
        if debits != credits:
            raise InvalidPostingError(
                f"debits and credits must balance in {currency.code} "
                f"(debits {debits:f}, credits {credits:f})!"
            )
        return currency.cid, values

    def _value_of(self, posting, account, currency: Commodity) -> Decimal:
        held = self._catalog()[account.commodity_id] if account.commodity_id else self.cr.default_currency()
        if decimal_places(posting.amount) > held.decimals:
            raise InvalidPostingError(
                f"{held.code} amounts can have at most {held.decimals} decimal place{'' if held.decimals == 1 else 's'}!"
            )
        if held.cid == currency.cid:
            if posting.value is not None and posting.value != posting.amount:
                raise InvalidPostingError(
                    f"'{account.name}' is in {currency.code} like the rest of the transaction, "
                    "so its value is its amount: leave the value out!"
                )
            return posting.amount
        if posting.value is None:
            raise InvalidPostingError(
                f"'{account.name}' holds {held.code} but the transaction is in {currency.code}: "
                f"say what {posting.amount:f} {held.code} is worth in {currency.code} (value)!"
            )
        if decimal_places(posting.value) > currency.decimals:
            raise InvalidPostingError(
                f"{currency.code} amounts can have at most {currency.decimals} decimal place"
                f"{'' if currency.decimals == 1 else 's'}!"
            )
        return posting.value

    def _posting_to_read(self, posting: Posting) -> PostingRead:
        return PostingRead(
            pid=posting.pid,
            transaction=posting.transaction,
            account=posting.account,
            side=posting.side,
            amount=posting.amount,
            value=posting.value,
            created=posting.created,
            updated=posting.updated,
        )

    def _to_read(self, transaction: Transaction) -> TransactionRead:
        return TransactionRead(
            tid=transaction.tid,
            currency=self._commodity_code(transaction.currency_id),
            date=transaction.date,
            payee=transaction.payee,
            comment=transaction.comment,
            created_via=transaction.created_via,
            updated_via=transaction.updated_via,
            recurring_id=transaction.recurring_id,
            postings=[self._posting_to_read(posting) for posting in self.tr.postings(transaction.tid)],
            created=transaction.created,
            updated=transaction.updated,
        )

    def _history_read(self, row, paths: dict[UUID, str]) -> HistoryRead:
        snap = row.snapshot
        currency = self._catalog().get(UUID(snap["currency_id"]))
        return HistoryRead(
            hid=row.hid,
            transaction=row.transaction_id,
            action=row.action,
            at=row.at,
            via=row.via,
            date=date.fromisoformat(snap["date"]),
            payee=snap.get("payee"),
            comment=snap.get("comment"),
            currency=currency.code if currency else snap["currency_id"],
            postings=[
                HistoryPosting(
                    account=paths.get(UUID(p["account"]), p["account"]),
                    side=p["side"],
                    amount=Decimal(p["amount"]),
                    value=Decimal(p["value"]),
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

    def create(self, data: TransactionCreate, recurring: tuple[UUID, date] | None = None) -> TransactionRead:
        currency_id, values = self._resolve(data)
        transaction = self.tr.create(data, currency_id, values, self.origin, recurring)
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
    ) -> list[TransactionRead]:
        account_ids = self._account_subtree(account) if account else None
        transactions = self.tr.list(account_ids, date_from, date_to, limit, offset)
        return [self._to_read(transaction) for transaction in transactions]

    def update(
        self,
        tid: UUID,
        data: TransactionUpdate,
    ) -> TransactionRead | None:
        existing = self.tr.read(tid)
        if not existing:
            raise ValueError(f"transaction with tid '{tid}' not found!")
        currency_id, values = self._resolve(data, existing.currency_id)
        transaction = self.tr.update(tid, data, currency_id, values, self.origin)
        if not transaction:
            raise RuntimeError(f"failed to update transaction with tid '{tid}'!")
        self.tr.db.commit()
        self.tr.db.refresh(transaction)
        return self._to_read(transaction)

    def delete(self, tid: UUID) -> TransactionRead | None:
        transaction = self.read(tid)
        deleted = self.tr.delete(tid, self.origin)
        if not deleted:
            raise ValueError(f"transaction with tid '{tid}' not found!")
        self.tr.db.commit()
        return transaction

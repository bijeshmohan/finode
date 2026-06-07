from uuid import UUID

from ..models.transaction import Transaction, Posting
from ..repositories import AccountRepository, TransactionRepository
from ..schemas.transaction import (
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
    PostingRead,
)


class TransactionService:
    def __init__(self, tr: TransactionRepository, ar: AccountRepository):
        self.tr = tr
        self.ar = ar

    def _validate_references(
        self,
        data: TransactionCreate | TransactionUpdate,
    ) -> None:
        postings = data.postings
        if postings is None:
            return
        for posting in postings:
            if not self.ar.read(posting.account):
                raise ValueError(f"account with aid '{posting.account}' not found!")

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

    def _to_read(self, transaction: Transaction) -> TransactionRead:
        return TransactionRead(
            tid=transaction.tid,
            date=transaction.date,
            payee=transaction.payee,
            comment=transaction.comment,
            postings=[self._posting_to_read(posting) for posting in self.tr.postings(transaction.tid)],
            created=transaction.created,
            updated=transaction.updated,
        )

    def create(self, data: TransactionCreate) -> TransactionRead:
        self._validate_references(data)
        transaction = self.tr.create(data)
        self.tr.db.commit()
        self.tr.db.refresh(transaction)
        return self._to_read(transaction)

    def read(self, tid: UUID) -> TransactionRead | None:
        transaction = self.tr.read(tid)
        if not transaction:
            return None
        return self._to_read(transaction)

    def list(self) -> list[TransactionRead]:
        return [self._to_read(transaction) for transaction in self.tr.list()]

    def update(
        self,
        tid: UUID,
        data: TransactionUpdate,
    ) -> TransactionRead | None:
        if not self.tr.read(tid):
            raise ValueError(f"transaction with tid '{tid}' not found!")
        self._validate_references(data)
        transaction = self.tr.update(tid, data)
        if not transaction:
            raise RuntimeError(f"failed to update transaction with tid '{tid}'!")
        self.tr.db.commit()
        self.tr.db.refresh(transaction)
        return self._to_read(transaction)

    def delete(self, tid: UUID) -> TransactionRead | None:
        transaction = self.read(tid)
        deleted = self.tr.delete(tid)
        if not deleted:
            raise ValueError(f"transaction with tid '{tid}' not found!")
        self.tr.db.commit()
        return transaction

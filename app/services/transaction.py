from uuid import UUID

from ..models.transaction import Transaction
from ..repositories import AccountRepository, TransactionRepository
from ..schemas.transaction import TransactionCreate, TransactionUpdate


class TransactionService:
    def __init__(self, tr: TransactionRepository, ar: AccountRepository):
        self.tr = tr
        self.ar = ar

    def _apply(self, transaction: Transaction) -> None:
        if transaction.source:
            source = self.ar.read(transaction.source)
            if source:
                source.balance -= transaction.amount
                _ = self.ar.update(source.aid, source)

        if transaction.destination:
            destination = self.ar.read(transaction.destination)
            if destination:
                destination.balance += transaction.amount
                _ = self.ar.update(destination.aid, destination)

    def _reverse(self, transaction: Transaction) -> None:
        if transaction.source:
            source = self.ar.read(transaction.source)
            if source:
                source.balance += transaction.amount
                _ = self.ar.update(source.aid, source)

        if transaction.destination:
            destination = self.ar.read(transaction.destination)
            if destination:
                destination.balance -= transaction.amount
                _ = self.ar.update(destination.aid, destination)

    def create(self, transaction: TransactionCreate) -> Transaction:
        txn = self.tr.create(transaction)
        self._apply(txn)
        return txn

    def read(self, tid: UUID) -> Transaction | None:
        return self.tr.read(tid)

    def list(self) -> list[Transaction]:
        return self.tr.list()

    def update(self, tid: UUID, data: TransactionUpdate) -> Transaction | None:
        txn = self.tr.read(tid)
        if not txn:
            raise ValueError(f"transaction with tid '{tid}' not found!")
        self._reverse(txn)

        updated = self.tr.update(tid, data)
        if not updated:
            raise RuntimeError(f"failed to update transaction with tid '{tid}'!")
        self._apply(updated)

        return updated

    def delete(self, tid: UUID) -> Transaction | None:
        deleted = self.tr.delete(tid)
        if not deleted:
            raise ValueError(f"transaction with tid '{tid}' not found!")
        self._reverse(deleted)
        return deleted

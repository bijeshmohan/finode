from uuid import UUID

from ..models.transaction import Transaction
from ..repositories import AccountRepository, CategoryRepository, TransactionRepository
from ..schemas.transaction import TransactionCreate, TransactionUpdate


class TransactionService:
    def __init__(
        self,
        tr: TransactionRepository,
        ar: AccountRepository,
        cr: CategoryRepository,
    ):
        self.tr = tr
        self.ar = ar
        self.cr = cr

    def _validate_references(self, transaction: TransactionCreate | TransactionUpdate) -> None:
        if transaction.source and not self.ar.read(transaction.source):
            raise ValueError(f"source account with aid '{transaction.source}' not found!")
        if transaction.destination and not self.ar.read(transaction.destination):
            raise ValueError(f"destination account with aid '{transaction.destination}' not found!")
        if transaction.category and not self.cr.read(transaction.category):
            raise ValueError(f"category with cid '{transaction.category}' not found!")

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
        self._validate_references(transaction)
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
        self._validate_references(data)
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

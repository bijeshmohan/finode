from datetime import date
from uuid import UUID

from ..models.transaction import Transaction, Posting
from ..repositories import AccountRepository, TransactionRepository
from .account import GROUP_POSTING_ROOT_NAMES, AccountService
from ..schemas.transaction import (
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
    PostingRead,
)


class InvalidPostingAccountError(ValueError):
    ...


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
        accounts_by_id = None
        for posting in postings:
            account = self.ar.read(posting.account)
            if not account:
                raise ValueError(f"account with aid '{posting.account}' not found!")
            if account.parent_id is None:
                raise InvalidPostingAccountError(f"cannot post to root account '{account.name}'!")
            if self.ar.has_children(account.aid):
                if accounts_by_id is None:
                    accounts_by_id = {a.aid: a for a in self.ar.list()}
                if AccountService.root_name(account, accounts_by_id) in GROUP_POSTING_ROOT_NAMES:
                    continue
                raise InvalidPostingAccountError(
                    f"cannot post to account '{account.name}' because it has sub-accounts!"
                )

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

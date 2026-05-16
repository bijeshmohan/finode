from datetime import date
from decimal import Decimal
from uuid import UUID

from ..models import Account
from ..repositories import AccountRepository, TransactionRepository
from ..schemas import AccountCreate, AccountUpdate, TransactionCreate


class AccountService:
    def __init__(self, ar: AccountRepository, tr: TransactionRepository):
        self.ar = ar
        self.tr = tr

    def _create_income(self, amount: Decimal, aid: UUID):
        txn = TransactionCreate(
            amount=amount,
            date=date.today(),
            destination=aid,
            note="Difference",
            details="Result of direct account balance update",
        )
        self.tr.create(txn)

    def _create_expense(self, amount: Decimal, aid: UUID):
        txn = TransactionCreate(
            amount=amount,
            date=date.today(),
            source=aid,
            note="Difference",
            details="Result of direct account balance update",
        )
        self.tr.create(txn)

    def create(self, account: AccountCreate) -> Account:
        return self.ar.create(account)

    def read(self, aid: UUID) -> Account | None:
        return self.ar.read(aid)

    def list(self) -> list[Account]:
        return self.ar.list()

    def update(self, aid: UUID, data: AccountUpdate) -> Account | None:
        account = self.ar.read(aid)
        if not account:
            raise ValueError(f"account with aid '{aid}' not found!")

        previous_balance = account.balance
        updated = self.ar.update(aid, data)
        if not updated:
            raise RuntimeError(f"failed to update account with aid '{aid}'!")

        diff = updated.balance - previous_balance
        if diff > 0:
            self._create_income(abs(diff), aid)
        elif diff < 0:
            self._create_expense(abs(diff), aid)
        else:
            ...  # no change in balance

        return updated

    def delete(self, aid: UUID) -> Account | None:
        txn = self.ar.delete(aid)
        if not txn:
            raise ValueError(f"account with aid '{aid}' not found!")
        return txn

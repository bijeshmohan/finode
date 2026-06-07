from datetime import date
from decimal import Decimal
from uuid import UUID

from ..models import Account
from ..models.account import AccountType
from ..models.transaction import PostingSide
from ..repositories import AccountRepository, TransactionRepository
from ..schemas import AccountCreate, AccountRead, AccountUpdate
from ..schemas.transaction import TransactionCreate, PostingCreate


OPENING_BALANCES_ACCOUNT_NAME = "Opening Balances"


class AccountInUseError(ValueError):
    ...


class AccountService:
    def __init__(self, ar: AccountRepository, tr: TransactionRepository):
        self.ar = ar
        self.tr = tr

    def _normal_side(self, account_type: AccountType) -> PostingSide:
        if account_type in (AccountType.ASSET, AccountType.EXPENSE):
            return PostingSide.DEBIT
        return PostingSide.CREDIT

    def _opposite_side(self, side: PostingSide) -> PostingSide:
        if side == PostingSide.DEBIT:
            return PostingSide.CREDIT
        return PostingSide.DEBIT

    def _balance_for(self, account: Account) -> Decimal:
        debit_total = Decimal("0.00")
        credit_total = Decimal("0.00")
        for posting in self.tr.postings_for_account(account.aid):
            if posting.side == PostingSide.DEBIT:
                debit_total += posting.amount
            else:
                credit_total += posting.amount

        if self._normal_side(account.type) == PostingSide.DEBIT:
            return debit_total - credit_total
        return credit_total - debit_total

    def _to_read(self, account: Account) -> AccountRead:
        return AccountRead(
            aid=account.aid,
            name=account.name,
            details=account.details,
            type=account.type,
            balance=self._balance_for(account),
            created=account.created,
            updated=account.updated,
        )

    def _opening_balances_account(self) -> Account:
        account = self.ar.read_by_name(
            OPENING_BALANCES_ACCOUNT_NAME,
            AccountType.EQUITY,
        )
        if account:
            return account
        return self.ar.create(
            AccountCreate(
                name=OPENING_BALANCES_ACCOUNT_NAME,
                details="System account for opening balance adjustments",
                type=AccountType.EQUITY,
            )
        )

    def _post_balance_adjustment(
        self,
        account: Account,
        amount: Decimal,
        payee: str,
        comment: str,
    ) -> None:
        if amount == 0:
            return

        opening_account = self._opening_balances_account()
        account_side = self._normal_side(account.type)
        opening_side = self._opposite_side(account_side)
        adjustment = abs(amount)
        if amount < 0:
            account_side, opening_side = opening_side, account_side

        self.tr.create(
            TransactionCreate(
                date=date.today(),
                payee=payee,
                comment=comment,
                postings=[
                    PostingCreate(
                        account=account.aid,
                        side=account_side,
                        amount=adjustment,
                    ),
                    PostingCreate(
                        account=opening_account.aid,
                        side=opening_side,
                        amount=adjustment,
                    ),
                ],
            )
        )

    def create(self, account: AccountCreate) -> AccountRead:
        created = self.ar.create(account)
        self._post_balance_adjustment(
            created,
            account.balance,
            "Opening balance",
            "Initial account balance",
        )
        return self._to_read(created)

    def read(self, aid: UUID) -> AccountRead | None:
        account = self.ar.read(aid)
        if not account:
            return None
        return self._to_read(account)

    def list(self, account_type: AccountType | None = None) -> list[AccountRead]:
        accounts = self.ar.list()
        if account_type is not None:
            accounts = [account for account in accounts if account.type == account_type]
        return [self._to_read(account) for account in accounts]

    def update(self, aid: UUID, data: AccountUpdate) -> AccountRead | None:
        account = self.ar.read(aid)
        if not account:
            raise ValueError(f"account with aid '{aid}' not found!")

        previous_balance = self._balance_for(account)
        updated = self.ar.update(aid, data)
        if not updated:
            raise RuntimeError(f"failed to update account with aid '{aid}'!")

        if "balance" in data.model_fields_set and data.balance is not None:
            current_balance = self._balance_for(updated)
            self._post_balance_adjustment(
                updated,
                data.balance - current_balance,
                "Balance adjustment",
                "Result of direct account balance update",
            )
        elif data.type is not None:
            self._post_balance_adjustment(
                updated,
                previous_balance - self._balance_for(updated),
                "Balance adjustment",
                "Result of account type update",
            )

        return self._to_read(updated)

    def delete(self, aid: UUID) -> AccountRead | None:
        account_read = self.read(aid)
        if self.tr.postings_for_account(aid):
            raise AccountInUseError(f"account with aid '{aid}' has postings!")
        account = self.ar.delete(aid)
        if not account:
            raise ValueError(f"account with aid '{aid}' not found!")
        return account_read

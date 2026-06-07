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
        if account_type in (AccountType.ASSETS, AccountType.EXPENSES):
            return PostingSide.DEBIT
        return PostingSide.CREDIT

    def _opposite_side(self, side: PostingSide) -> PostingSide:
        if side == PostingSide.DEBIT:
            return PostingSide.CREDIT
        return PostingSide.DEBIT

    def _get_descendants(
        self,
        parent_id: UUID,
        accounts_by_parent: dict[UUID, list[Account]],
    ) -> list[UUID]:
        descendants = []
        to_visit = [parent_id]
        while to_visit:
            current = to_visit.pop()
            children = accounts_by_parent.get(current, [])
            for child in children:
                descendants.append(child.aid)
                to_visit.append(child.aid)
        return descendants

    def _balance_for(
        self,
        account: Account,
        all_accounts: list[Account] | None = None,
    ) -> Decimal:
        if all_accounts is None:
            all_accounts = self.ar.list()

        accounts_by_parent = {}
        for acc in all_accounts:
            if acc.parent_id is not None:
                accounts_by_parent.setdefault(acc.parent_id, []).append(acc)

        descendant_ids = self._get_descendants(account.aid, accounts_by_parent)
        target_ids = [account.aid] + descendant_ids

        debit_total = Decimal("0.00")
        credit_total = Decimal("0.00")
        for posting in self.tr.postings_for_accounts(target_ids):
            if posting.side == PostingSide.DEBIT:
                debit_total += posting.amount
            else:
                credit_total += posting.amount

        if self._normal_side(account.type) == PostingSide.DEBIT:
            return debit_total - credit_total
        return credit_total - debit_total

    def _to_read(
        self,
        account: Account,
        all_accounts: list[Account] | None = None,
    ) -> AccountRead:
        return AccountRead(
            aid=account.aid,
            name=account.name,
            details=account.details,
            type=account.type,
            parent_id=account.parent_id,
            balance=self._balance_for(account, all_accounts),
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

    def _detect_cycle(self, account_id: UUID, proposed_parent_id: UUID | None) -> bool:
        if proposed_parent_id is None:
            return False
        current_id = proposed_parent_id
        while current_id is not None:
            if current_id == account_id:
                return True
            parent = self.ar.read(current_id)
            if not parent:
                break
            current_id = parent.parent_id
        return False

    def create(self, account: AccountCreate) -> AccountRead:
        if account.parent_id is not None:
            parent = self.ar.read(account.parent_id)
            if not parent:
                raise ValueError("parent account not found!")
            if account.type is None:
                account.type = parent.type
            elif parent.type != account.type:
                raise ValueError("parent account type must match child account type!")
        else:
            if account.type is None:
                raise ValueError("type is required for top-level accounts!")

        created = self.ar.create(account)
        self._post_balance_adjustment(
            created,
            account.balance,
            "Opening balance",
            "Initial account balance",
        )
        self.ar.db.commit()
        self.ar.db.refresh(created)
        return self._to_read(created)

    def read(self, aid: UUID) -> AccountRead | None:
        account = self.ar.read(aid)
        if not account:
            return None
        return self._to_read(account)

    def list(self, account_type: AccountType | None = None) -> list[AccountRead]:
        all_accounts = self.ar.list()
        filtered = all_accounts
        if account_type is not None:
            filtered = [a for a in all_accounts if a.type == account_type]
        return [self._to_read(account, all_accounts) for account in filtered]

    def update(self, aid: UUID, data: AccountUpdate) -> AccountRead | None:
        account = self.ar.read(aid)
        if not account:
            raise ValueError(f"account with aid '{aid}' not found!")

        # 0. Check if type is explicitly set to None (invalid payload)
        if "type" in data.model_fields_set and data.type is None:
            raise ValueError("Account type cannot be null")

        # 1. Validation for parent_id updates
        if "parent_id" in data.model_fields_set:
            parent_id = data.parent_id
            if parent_id is not None:
                if parent_id == aid:
                    raise ValueError("an account cannot be its own parent!")
                parent = self.ar.read(parent_id)
                if not parent:
                    raise ValueError("parent account not found!")
                
                target_type = data.type if data.type is not None else account.type
                if parent.type != target_type:
                    raise ValueError("parent account type must match child account type!")
                
                if self._detect_cycle(aid, parent_id):
                    raise ValueError("cyclic parent relationship detected!")

        # 2. Validation for type updates
        if data.type is not None and data.type != account.type:
            if self.ar.has_children(aid):
                raise ValueError("cannot change type of account with sub-accounts!")
            if "parent_id" not in data.model_fields_set and account.parent_id is not None:
                parent = self.ar.read(account.parent_id)
                if parent and parent.type != data.type:
                    raise ValueError("parent account type must match child account type!")

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

        self.ar.db.commit()
        self.ar.db.refresh(updated)
        return self._to_read(updated)

    def delete(self, aid: UUID) -> AccountRead | None:
        account_read = self.read(aid)
        if self.ar.has_children(aid):
            raise AccountInUseError("account has sub-accounts")
        if self.tr.postings_for_account(aid):
            raise AccountInUseError("account has postings")
        account = self.ar.delete(aid)
        if not account:
            raise ValueError(f"account with aid '{aid}' not found!")
        self.ar.db.commit()
        return account_read


from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from ..models import Account
from ..models.transaction import PostingSide
from ..repositories import AccountRepository, TransactionRepository
from ..schemas import AccountCreate, AccountRead, AccountUpdate, RegisterEntry
from ..schemas.transaction import TransactionCreate, PostingCreate


OPENING_BALANCES_ACCOUNT_NAME = "Opening Balances"
ROOT_ACCOUNT_NAMES = ("Assets", "Expenses", "Equity", "Income", "Liabilities")
DEBIT_ROOT_NAMES = frozenset({"Assets", "Expenses"})
# Income and expense accounts are categories, so a group may hold postings of its own.
# Assets and liabilities are real holdings and stay leaf-only.
GROUP_POSTING_ROOT_NAMES = frozenset({"Income", "Expenses"})


class AccountInUseError(ValueError):
    ...


class SystemAccountError(ValueError):
    ...


class RootAccountError(SystemAccountError):
    ...


class AccountService:
    def __init__(self, ar: AccountRepository, tr: TransactionRepository):
        self.ar = ar
        self.tr = tr

    @staticmethod
    def _is_root(account: Account) -> bool:
        return account.parent_id is None and account.name in ROOT_ACCOUNT_NAMES

    @staticmethod
    def is_opening_balances(account: Account, all_accounts: list[Account]) -> bool:
        if account.name != OPENING_BALANCES_ACCOUNT_NAME or account.parent_id is None:
            return False
        parent = next((a for a in all_accounts if a.aid == account.parent_id), None)
        return parent is not None and parent.name == "Equity" and parent.parent_id is None

    def _validate_parent(self, parent: Account, all_accounts: list[Account]) -> None:
        if self.is_opening_balances(parent, all_accounts):
            raise SystemAccountError(
                f"cannot add sub-accounts to system account '{parent.name}'!"
            )
        accounts_by_id = {a.aid: a for a in all_accounts}
        if self._get_root_name(parent, accounts_by_id) in GROUP_POSTING_ROOT_NAMES:
            return
        if self.tr.postings_for_account(parent.aid):
            raise ValueError(
                f"cannot add sub-accounts to '{parent.name}' because it has postings!"
            )

    def ensure_roots(self) -> list[Account]:
        return self._ensure_roots()

    def _ensure_roots(self) -> list[Account]:
        """Return all accounts, lazily provisioning the user's system roots.

        Only the first request of a new user writes. A unique partial index on
        root names makes concurrent provisioning safe: the loser rolls back and
        re-reads the roots created by the winner.
        """
        all_accounts = self.ar.list()
        existing = {a.name for a in all_accounts if a.parent_id is None}
        missing = [name for name in ROOT_ACCOUNT_NAMES if name not in existing]
        if not missing:
            return all_accounts

        for name in missing:
            self.ar.db.add(
                Account(
                    name=name,
                    details=f"System root account for {name}",
                    parent_id=None,
                    user=self.ar.uid,
                )
            )
        try:
            self.ar.db.commit()
        except IntegrityError:
            self.ar.db.rollback()
        return self.ar.list()

    def _get_root_name(self, account: Account, accounts_by_id: dict[UUID, Account]) -> str:
        return self.root_name(account, accounts_by_id)

    @staticmethod
    def root_name(account: Account, accounts_by_id: dict[UUID, Account]) -> str:
        current = account
        visited = set()
        while current.parent_id is not None:
            if current.aid in visited:
                break
            visited.add(current.aid)
            parent = accounts_by_id.get(current.parent_id)
            if not parent:
                break
            current = parent
        return current.name

    def _normal_side(self, account: Account, accounts_by_id: dict[UUID, Account]) -> PostingSide:
        root_name = self._get_root_name(account, accounts_by_id)
        if root_name in DEBIT_ROOT_NAMES:
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

    def subtree_ids(
        self,
        account_id: UUID,
        all_accounts: list[Account] | None = None,
    ) -> list[UUID]:
        if all_accounts is None:
            all_accounts = self._ensure_roots()
        accounts_by_parent: dict[UUID, list[Account]] = {}
        for acc in all_accounts:
            if acc.parent_id is not None:
                accounts_by_parent.setdefault(acc.parent_id, []).append(acc)
        return [account_id] + self._get_descendants(account_id, accounts_by_parent)

    def _balance_for(
        self,
        account: Account,
        all_accounts: list[Account] | None = None,
    ) -> Decimal:
        if all_accounts is None:
            all_accounts = self._ensure_roots()

        accounts_by_id = {acc.aid: acc for acc in all_accounts}
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

        normal_side = self._normal_side(account, accounts_by_id)
        if normal_side == PostingSide.DEBIT:
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
            parent_id=account.parent_id,
            balance=self._balance_for(account, all_accounts),
            created=account.created,
            updated=account.updated,
        )

    def _opening_balances_account(self) -> Account:
        all_accounts = self._ensure_roots()
        equity_root = next(a for a in all_accounts if a.name == "Equity" and a.parent_id is None)
        account = self.ar.read_by_name(OPENING_BALANCES_ACCOUNT_NAME, equity_root.aid)
        if account:
            return account
        return self.ar.create(
            AccountCreate(
                name=OPENING_BALANCES_ACCOUNT_NAME,
                details="System account for opening balance adjustments",
                parent_id=equity_root.aid,
            )
        )

    def _post_balance_adjustment(
        self,
        account: Account,
        amount: Decimal,
        payee: str,
        comment: str,
        all_accounts: list[Account],
    ) -> None:
        if amount == 0:
            return

        opening_account = self._opening_balances_account()
        accounts_by_id = {acc.aid: acc for acc in all_accounts}
        accounts_by_id[opening_account.aid] = opening_account

        account_side = self._normal_side(account, accounts_by_id)
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
        all_accounts = self._ensure_roots()

        if account.parent_id is None:
            raise ValueError("parent_id is required for all user-created accounts!")

        parent = next((a for a in all_accounts if a.aid == account.parent_id), None)
        if not parent:
            raise ValueError("parent account not found!")

        self._validate_parent(parent, all_accounts)
        if (
            self.is_opening_balances(
                Account(name=account.name, parent_id=account.parent_id, user=self.ar.uid),
                all_accounts,
            )
            and self.ar.read_by_name(account.name, account.parent_id)
        ):
            raise ValueError(f"system account '{account.name}' already exists!")

        created = self.ar.create(account)
        all_accounts_with_created = all_accounts + [created]

        self._post_balance_adjustment(
            created,
            account.balance,
            "Opening balance",
            "Initial account balance",
            all_accounts_with_created,
        )
        self.ar.db.commit()
        self.ar.db.refresh(created)
        return self._to_read(created, all_accounts_with_created)

    def read(self, aid: UUID) -> AccountRead | None:
        all_accounts = self._ensure_roots()
        account = next((a for a in all_accounts if a.aid == aid), None)
        if not account:
            return None
        return self._to_read(account, all_accounts)

    def list(self, root_name: str | None = None) -> list[AccountRead]:
        all_accounts = self._ensure_roots()
        accounts_by_id = {acc.aid: acc for acc in all_accounts}

        filtered = all_accounts
        if root_name is not None:
            filtered = [
                a for a in all_accounts
                if self._get_root_name(a, accounts_by_id) == root_name
            ]
        return [self._to_read(account, all_accounts) for account in filtered]

    def register(self, aid: UUID) -> list[RegisterEntry] | None:
        """Return the account's activity oldest first with a running balance.

        Postings on sub-accounts count towards the account, matching how its
        balance is derived. Each entry's change is signed by the account's
        normal side, so it adds up to the account balance.
        """
        all_accounts = self._ensure_roots()
        account = next((a for a in all_accounts if a.aid == aid), None)
        if not account:
            return None

        accounts_by_id = {acc.aid: acc for acc in all_accounts}
        target_ids = self.subtree_ids(aid, all_accounts)
        normal_side = self._normal_side(account, accounts_by_id)

        changes: dict[UUID, Decimal] = {}
        for posting in self.tr.postings_for_accounts(target_ids):
            signed = posting.amount if posting.side == normal_side else -posting.amount
            changes[posting.transaction] = changes.get(posting.transaction, Decimal("0.00")) + signed

        transactions = [self.tr.read(tid) for tid in changes]
        transactions = [t for t in transactions if t is not None]
        transactions.sort(key=lambda t: (t.date, t.created))

        entries = []
        balance = Decimal("0.00")
        for transaction in transactions:
            balance += changes[transaction.tid]
            counter_accounts = []
            for posting in self.tr.postings(transaction.tid):
                if posting.account in target_ids:
                    continue
                name = accounts_by_id[posting.account].name
                if name not in counter_accounts:
                    counter_accounts.append(name)
            entries.append(
                RegisterEntry(
                    tid=transaction.tid,
                    date=transaction.date,
                    payee=transaction.payee,
                    comment=transaction.comment,
                    counter_accounts=counter_accounts,
                    change=changes[transaction.tid],
                    balance=balance,
                )
            )
        return entries

    def update(self, aid: UUID, data: AccountUpdate) -> AccountRead | None:
        all_accounts = self._ensure_roots()
        account = next((a for a in all_accounts if a.aid == aid), None)
        if not account:
            raise ValueError(f"account with aid '{aid}' not found!")

        is_system_root = self._is_root(account)
        is_opening = self.is_opening_balances(account, all_accounts)

        if is_opening:
            if "name" in data.model_fields_set and data.name != account.name:
                raise SystemAccountError(f"cannot change name of system account '{account.name}'!")
            if "parent_id" in data.model_fields_set and data.parent_id != account.parent_id:
                raise SystemAccountError(f"cannot move system account '{account.name}'!")
            if "balance" in data.model_fields_set and data.balance is not None:
                raise SystemAccountError(f"cannot set balance of system account '{account.name}'!")

        if is_system_root:
            if "parent_id" in data.model_fields_set and data.parent_id is not None:
                raise RootAccountError("cannot change parent of a root account!")
            if "name" in data.model_fields_set and data.name != account.name:
                raise RootAccountError("cannot change name of a system root account!")

        if "parent_id" in data.model_fields_set:
            parent_id = data.parent_id
            if parent_id is not None:
                if parent_id == aid:
                    raise ValueError("an account cannot be its own parent!")
                parent = next((a for a in all_accounts if a.aid == parent_id), None)
                if not parent:
                    raise ValueError("parent account not found!")

                if parent_id != account.parent_id:
                    self._validate_parent(parent, all_accounts)

                if self._detect_cycle(aid, parent_id):
                    raise ValueError("cyclic parent relationship detected!")

                accounts_by_id = {a.aid: a for a in all_accounts}
                if self._get_root_name(parent, accounts_by_id) != self._get_root_name(
                    account, accounts_by_id
                ):
                    raise ValueError("cannot move account under a different root account!")
            else:
                if not is_system_root:
                    raise ValueError("parent_id is required for all user-created accounts!")

        if not is_opening and ("name" in data.model_fields_set or "parent_id" in data.model_fields_set):
            candidate = Account(
                name=data.name if "name" in data.model_fields_set and data.name else account.name,
                parent_id=data.parent_id if "parent_id" in data.model_fields_set else account.parent_id,
                user=self.ar.uid,
            )
            if self.is_opening_balances(candidate, all_accounts) and self.ar.read_by_name(
                candidate.name, candidate.parent_id
            ):
                raise ValueError(f"system account '{candidate.name}' already exists!")

        if "balance" in data.model_fields_set and data.balance is not None:
            if is_system_root:
                raise RootAccountError("cannot set balance of a root account!")
            if self.ar.has_children(aid):
                raise ValueError("cannot set balance of an account with sub-accounts!")

        previous_balance = self._balance_for(account, all_accounts)
        updated = self.ar.update(aid, data)
        if not updated:
            raise RuntimeError(f"failed to update account with aid '{aid}'!")

        all_accounts = [a if a.aid != aid else updated for a in all_accounts]

        if "balance" in data.model_fields_set and data.balance is not None:
            current_balance = self._balance_for(updated, all_accounts)
            self._post_balance_adjustment(
                updated,
                data.balance - current_balance,
                "Balance adjustment",
                "Result of direct account balance update",
                all_accounts,
            )

        self.ar.db.commit()
        self.ar.db.refresh(updated)
        return self._to_read(updated, all_accounts)

    def delete(self, aid: UUID) -> AccountRead | None:
        all_accounts = self._ensure_roots()
        account = next((a for a in all_accounts if a.aid == aid), None)
        if not account:
            raise ValueError(f"account with aid '{aid}' not found!")

        is_system_root = self._is_root(account)
        if is_system_root:
            raise RootAccountError("cannot delete system root accounts!")

        if self.is_opening_balances(account, all_accounts):
            raise SystemAccountError(f"cannot delete system account '{account.name}'!")

        if self.ar.has_children(aid):
            raise AccountInUseError("account has sub-accounts")
        if self.tr.postings_for_account(aid):
            raise AccountInUseError("account has postings")

        account_read = self._to_read(account, all_accounts)
        deleted = self.ar.delete(aid)
        if not deleted:
            raise ValueError(f"account with aid '{aid}' not found!")
        self.ar.db.commit()
        return account_read

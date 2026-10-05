from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from ..models import Account, Commodity
from ..models.transaction import PostingSide
from ..repositories import (
    AccountRepository,
    CommodityRepository,
    PriceRepository,
    ProfileRepository,
    TransactionRepository,
)
from ..schemas import AccountCreate, AccountRead, AccountUpdate, RegisterEntry
from ..schemas.account import HoldingRead
from ..schemas.transaction import TransactionCreate, PostingCreate
from .depth import depth_limit
from .prices import PriceService


OPENING_BALANCES_ACCOUNT_NAME = "Opening Balances"
ROOT_ACCOUNT_NAMES = ("Assets", "Expenses", "Equity", "Income", "Liabilities")
DEBIT_ROOT_NAMES = frozenset({"Assets", "Expenses"})
# Income and expense accounts are categories, so a group may hold postings of its own.
# Assets and liabilities are real holdings and stay leaf-only.
GROUP_POSTING_ROOT_NAMES = frozenset({"Income", "Expenses"})


class AccountInUseError(ValueError):
    ...


class AccountDepthError(ValueError):
    ...


class SystemAccountError(ValueError):
    ...


class RootAccountError(SystemAccountError):
    ...


class AccountService:
    def __init__(
        self,
        ar: AccountRepository,
        tr: TransactionRepository,
        pr: ProfileRepository,
        cr: CommodityRepository | None = None,
        prices: PriceService | None = None,
    ):
        self.ar = ar
        self.tr = tr
        self.pr = pr
        self.cr = cr or CommodityRepository(ar.db, ar.uid)
        self.prices = prices or PriceService(PriceRepository(ar.db, ar.uid), tr)
        self._catalog: dict[UUID, Commodity] | None = None
        self._default: Commodity | None = None

    def reset_defaults(self) -> None:
        """Forget what was looked up before a setting changed."""
        self._catalog = None
        self._default = None

    def catalog(self) -> dict[UUID, Commodity]:
        if self._catalog is None:
            self._catalog = {c.cid: c for c in self.cr.list()}
        return self._catalog

    def default_currency(self) -> Commodity:
        if self._default is None:
            self._default = self.cr.default_currency()
        return self._default

    def _holds(self, account: Account) -> Commodity:
        """What an account holds; root accounts are totalled in the default currency."""
        if account.commodity_id is None:
            return self.default_currency()
        return self.catalog()[account.commodity_id]

    def _commodity_code(self, commodity_id: UUID | None) -> str | None:
        if commodity_id is None:
            return self.default_currency().code
        commodity = self.catalog().get(commodity_id)
        return commodity.code if commodity else None

    def _new_account_commodity(self, parent: Account, code: str | None = None) -> UUID:
        """A new account holds what was asked for, else what its parent holds, else the default currency."""
        if code:
            commodity = self.cr.read_by_code(code.upper())
            if commodity is None:
                raise ValueError(f"unknown commodity '{code}'!")
            return commodity.cid
        return parent.commodity_id or self.default_currency().cid

    @staticmethod
    def _check_places(commodity: Commodity, amount: Decimal) -> None:
        exponent = amount.normalize().as_tuple().exponent
        places = max(0, -exponent) if isinstance(exponent, int) else 0
        if places > commodity.decimals:
            raise ValueError(
                f"{commodity.code} amounts can have at most {commodity.decimals} "
                f"decimal place{'' if commodity.decimals == 1 else 's'}!"
            )

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

    @staticmethod
    def _depth(account: Account, accounts_by_id: dict[UUID, Account]) -> int:
        """Levels below the top-level account (a top-level account is 0)."""
        depth = 0
        seen = {account.aid}
        while account.parent_id is not None and account.parent_id in accounts_by_id:
            account = accounts_by_id[account.parent_id]
            if account.aid in seen:
                break
            seen.add(account.aid)
            depth += 1
        return depth

    def account_depths(self) -> list[tuple[str, int, str]]:
        """(top-level account name, depth, path) for every non-top-level account."""
        all_accounts = self._ensure_roots()
        by_id = {a.aid: a for a in all_accounts}
        result = []
        for account in all_accounts:
            if account.parent_id is None:
                continue
            names, current, seen = [], account, set()
            while current.aid not in seen:
                seen.add(current.aid)
                names.append(current.name)
                if current.parent_id is None or current.parent_id not in by_id:
                    break
                current = by_id[current.parent_id]
            result.append((current.name, len(names) - 1, " › ".join(reversed(names))))
        return result

    def _check_depth(self, parent: Account, levels_below_parent: int, all_accounts: list[Account]) -> None:
        """Refuse a new or moved subtree that would go deeper than the user's limit."""
        by_id = {a.aid: a for a in all_accounts}
        root = self._get_root_name(parent, by_id)
        resulting = self._depth(parent, by_id) + levels_below_parent
        limit = depth_limit(self.pr.read(), root)
        if resulting > limit:
            raise AccountDepthError(
                f"{root} accounts can be at most {limit} level{'' if limit == 1 else 's'} deep, "
                f"and this would be {resulting}. You can raise the limit in your profile."
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

    def _height(self, aid: UUID, all_accounts: list[Account]) -> int:
        """Levels of sub-accounts below an account (0 for a leaf)."""
        children: dict[UUID, list[UUID]] = {}
        for a in all_accounts:
            if a.parent_id is not None:
                children.setdefault(a.parent_id, []).append(a.aid)
        height, level, seen = 0, [aid], {aid}
        while True:
            level = [c for p in level for c in children.get(p, []) if c not in seen]
            if not level:
                return height
            seen.update(level)
            height += 1

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

    def _valued_balance(
        self,
        account: Account,
        all_accounts: list[Account] | None = None,
    ) -> tuple[Decimal, bool]:
        """The account's balance in what it holds, and whether part of it could not be valued.

        Sub-accounts that hold something else are valued at the latest price. A group of
        accounts without a price linking them is reported as partly unpriced, never as zero.
        """
        if all_accounts is None:
            all_accounts = self._ensure_roots()

        accounts_by_id = {acc.aid: acc for acc in all_accounts}
        accounts_by_parent = {}
        for acc in all_accounts:
            if acc.parent_id is not None:
                accounts_by_parent.setdefault(acc.parent_id, []).append(acc)

        descendant_ids = self._get_descendants(account.aid, accounts_by_parent)
        target_ids = [account.aid] + descendant_ids

        normal_side = self._normal_side(account, accounts_by_id)
        target = self._holds(account)
        totals: dict[UUID, Decimal] = {}
        for posting in self.tr.postings_for_accounts(target_ids):
            held = accounts_by_id[posting.account].commodity_id or target.cid
            signed = posting.amount if posting.side == normal_side else -posting.amount
            totals[held] = totals.get(held, Decimal("0.00")) + signed

        balance = Decimal("0.00")
        unpriced = False
        for held, total in totals.items():
            if held == target.cid or total == 0:
                balance += total
                continue
            converted = self.prices.book().convert(total, held, target.cid, date.today(), target.decimals)
            if converted is None:
                unpriced = True
            else:
                balance += converted
        return balance, unpriced

    def _balance_for(
        self,
        account: Account,
        all_accounts: list[Account] | None = None,
    ) -> Decimal:
        return self._valued_balance(account, all_accounts)[0]

    def _to_read(
        self,
        account: Account,
        all_accounts: list[Account] | None = None,
    ) -> AccountRead:
        balance, unpriced = self._valued_balance(account, all_accounts)
        return AccountRead(
            aid=account.aid,
            name=account.name,
            details=account.details,
            parent_id=account.parent_id,
            commodity=self._commodity_code(account.commodity_id),
            balance=balance,
            unpriced=unpriced,
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
            ),
            commodity_id=self.default_currency().cid,
        )

    def _post_balance_adjustment(
        self,
        account: Account,
        amount: Decimal,
        payee: str,
        comment: str,
        all_accounts: list[Account],
        worth: Decimal | None = None,
    ) -> None:
        """Post `amount` of what the account holds against Opening Balances.

        When the account holds something other than the opening-balances account's currency,
        the adjustment is valued in that currency: `worth` if the user gave it, else the latest price.
        """
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

        held = self._holds(account)
        self._check_places(held, adjustment)
        currency = self._holds(opening_account)
        postings = [PostingCreate(account=account.aid, side=account_side, amount=adjustment)]
        values: list[Decimal] | None = None
        if held.cid == currency.cid:
            postings.append(PostingCreate(account=opening_account.aid, side=opening_side, amount=adjustment))
        else:
            value = abs(worth) if worth is not None else self.prices.book().convert(
                adjustment, held.cid, currency.cid, date.today()
            )
            if value is None:
                raise ValueError(
                    f"no {held.code} price is known yet: say what {adjustment:f} {held.code} is worth in {currency.code}!"
                )
            value = value.quantize(Decimal(1).scaleb(-currency.decimals), rounding=ROUND_HALF_UP)
            if value <= 0:
                raise ValueError(f"that amount of {held.code} is worth less than the smallest unit of {currency.code}!")
            postings[0].value = value
            postings.append(PostingCreate(account=opening_account.aid, side=opening_side, amount=value))
            values = [value, value]

        self.tr.create(
            TransactionCreate(date=date.today(), payee=payee, comment=comment, postings=postings),
            currency.cid,
            values,
        )
        self.prices.invalidate()

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
        self._check_depth(parent, 1, all_accounts)
        if (
            self.is_opening_balances(
                Account(name=account.name, parent_id=account.parent_id, user=self.ar.uid),
                all_accounts,
            )
            and self.ar.read_by_name(account.name, account.parent_id)
        ):
            raise ValueError(f"system account '{account.name}' already exists!")

        commodity_id = self._new_account_commodity(parent, account.commodity)
        created = self.ar.create(account, commodity_id=commodity_id)
        all_accounts_with_created = all_accounts + [created]

        try:
            self._post_balance_adjustment(
                created,
                account.balance,
                "Opening balance",
                "Initial account balance",
                all_accounts_with_created,
                account.balance_value,
            )
        except ValueError:
            self.ar.db.rollback()
            raise
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
        target = self._holds(account)

        changes: dict[UUID, Decimal] = {}
        unpriced_in: set[UUID] = set()
        dates: dict[UUID, date] = {}
        for posting in self.tr.postings_for_accounts(target_ids):
            signed = posting.amount if posting.side == normal_side else -posting.amount
            held = accounts_by_id[posting.account].commodity_id or target.cid
            if held != target.cid:
                # Sub-accounts holding something else count at the rate of the day.
                if posting.transaction not in dates:
                    dates[posting.transaction] = self.tr.read(posting.transaction).date
                converted = self.prices.book().convert(
                    signed, held, target.cid, dates[posting.transaction], target.decimals
                )
                if converted is None:
                    unpriced_in.add(posting.transaction)
                    continue
                signed = converted
            changes[posting.transaction] = changes.get(posting.transaction, Decimal("0.00")) + signed
        for tid in unpriced_in:
            changes.setdefault(tid, Decimal("0.00"))

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
                    unpriced=transaction.tid in unpriced_in,
                )
            )
        return entries

    def opening_currency(self) -> Commodity:
        """What balances are valued in when an account holding something else is opened: the currency of
        the Opening Balances account, which is the default currency from when it was first needed."""
        all_accounts = self._ensure_roots()
        equity = next(a for a in all_accounts if a.name == "Equity" and a.parent_id is None)
        opening = self.ar.read_by_name(OPENING_BALANCES_ACCOUNT_NAME, equity.aid)
        return self._holds(opening) if opening else self.default_currency()

    def commodity_of(self, aid: UUID) -> Commodity | None:
        """What an account holds (None for an unknown account)."""
        account = self.ar.read(aid)
        return self._holds(account) if account else None

    def has_postings(self, aid: UUID) -> bool:
        return bool(self.tr.postings_for_account(aid))

    def commodity_choices(self) -> list[Commodity]:
        """What an account can hold: the built-in currencies and the user's own assets."""
        return sorted(self.catalog().values(), key=lambda c: (c.user is not None, c.kind != "currency", c.code))

    def holding(self, aid: UUID) -> HoldingRead | None:
        """What an account holding something other than the default currency is worth.

        `invested` is what the postings to the account were worth when they were made, in the
        default currency; the difference to today's value is the gain (or loss).
        """
        all_accounts = self._ensure_roots()
        account = next((a for a in all_accounts if a.aid == aid), None)
        default = self.default_currency()
        if account is None or account.commodity_id in (None, default.cid) or any(
            a.parent_id == aid for a in all_accounts
        ):
            return None
        held = self._holds(account)
        accounts_by_id = {acc.aid: acc for acc in all_accounts}
        normal_side = self._normal_side(account, accounts_by_id)
        quantity = self._balance_for(account, all_accounts)
        book = self.prices.book()

        invested = Decimal("0.00")
        invested_known = True
        for posting in self.tr.postings_for_account(aid):
            transaction = self.tr.read(posting.transaction)
            signed = posting.value if posting.side == normal_side else -posting.value
            if transaction.currency_id != default.cid:
                signed = book.convert(signed, transaction.currency_id, default.cid, transaction.date, default.decimals)
                if signed is None:
                    invested_known = False
                    continue
            invested += signed

        value = book.convert(quantity, held.cid, default.cid, date.today(), default.decimals) if quantity else Decimal("0.00")
        rate = book.rate(held.cid, default.cid, date.today())
        return HoldingRead(
            commodity=held.code,
            currency=default.code,
            quantity=quantity,
            value=value,
            invested=invested if invested_known else None,
            gain=value - invested if value is not None and invested_known else None,
            rate=rate.value if rate else None,
            rate_as_of=rate.as_of if rate else None,
        )

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
                    self._check_depth(parent, 1 + self._height(aid, all_accounts), all_accounts)

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

        commodity_id = None
        if data.commodity:
            commodity = self.cr.read_by_code(data.commodity.upper())
            if commodity is None:
                raise ValueError(f"unknown commodity '{data.commodity}'!")
            if commodity.cid != account.commodity_id:
                if is_system_root or is_opening:
                    raise SystemAccountError(f"cannot change what '{account.name}' holds!")
                if self.tr.postings_for_account(aid):
                    raise ValueError(
                        f"cannot change what '{account.name}' holds because it has postings!"
                    )
                commodity_id = commodity.cid

        updated = self.ar.update(aid, data, commodity_id)
        if not updated:
            raise RuntimeError(f"failed to update account with aid '{aid}'!")

        all_accounts = [a if a.aid != aid else updated for a in all_accounts]

        if "balance" in data.model_fields_set and data.balance is not None:
            current_balance = self._balance_for(updated, all_accounts)
            try:
                self._post_balance_adjustment(
                    updated,
                    data.balance - current_balance,
                    "Balance adjustment",
                    "Result of direct account balance update",
                    all_accounts,
                    data.balance_value,
                )
            except ValueError:
                self.ar.db.rollback()
                raise

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

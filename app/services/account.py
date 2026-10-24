"""Accounts: the tree and its rules (two levels, no posting to roots or groups), balances derived from postings, closing, deleting, restoring, ordering and the account register."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from ..clock import local_today
from ..config import settings
from ..currencies import Currency
from ..currencies import find as find_currency
from ..limits import ensure_room
from ..models import Account
from ..models.transaction import Posting, PostingSide
from ..repositories import AccountRepository, ProfileRepository, TransactionRepository
from ..repositories.budget import BudgetRepository
from ..repositories.recurring import RecurringRepository
from ..schemas import AccountCreate, AccountRead, AccountUpdate, RegisterEntry
from ..schemas.transaction import PostingCreate, TransactionCreate

# Levels below a top-level account: Expenses › Food is 1 and Expenses › Food › Groceries is 2, the deepest there is.
MAX_ACCOUNT_DEPTH = 2

# How many entries an account's page shows before "Load more" (a day is never split, so a chunk can run a little over).
REGISTER_PAGE = 30
OPENING_BALANCES_ACCOUNT_NAME = "Opening Balances"
ROOT_ACCOUNT_NAMES = ("Assets", "Expenses", "Equity", "Income", "Liabilities")
DEBIT_ROOT_NAMES = frozenset({"Assets", "Expenses"})
# Income and expense accounts are categories, so a group may hold postings of its own.
# Assets and liabilities are real holdings and stay leaf-only.
GROUP_POSTING_ROOT_NAMES = frozenset({"Income", "Expenses"})

# The built-in groups every new person starts with under Assets and Liabilities: (root, name, key, what an account made
# under it starts as: "budget" or "outside" the budget). They cannot be renamed, moved, closed or deleted; what is made
# under them gets its budget behaviour from here, so a new person does not have to decide it. Rules read the key, never
# the name.
FIXED_PARENTS = (
    ("Assets", "Bank Accounts", "assets.bank", "budget"),
    ("Assets", "Cash", "assets.cash", "budget"),
    ("Assets", "Investments", "assets.investments", "outside"),
    ("Liabilities", "Credit Cards", "liabilities.cards", "budget"),
    ("Liabilities", "Loans", "liabilities.loans", "outside"),
)
FIXED_DEFAULTS = {key: start for _, _, key, start in FIXED_PARENTS}
FIXED_ORDER = {key: place for place, (_, _, key, _) in enumerate(FIXED_PARENTS)}
# New people get the groups; tests switch this off (most of them build their own accounts) and a few switch it on.
NEW_PROFILE_FIXED_PARENTS = True


@dataclass
class RegisterPage:
    """One chunk of an account's activity (see `AccountService.register_page`)."""

    entries: list  # newest first, up to today
    upcoming: list  # dated after today, soonest first
    total: int  # how many entries up to today there are in all
    next_offset: int
    has_more: bool
    has_any: bool  # whether the account has any entry at all


class AccountInUseError(ValueError): ...


class AccountDepthError(ValueError): ...


class SystemAccountError(ValueError): ...


class RootAccountError(SystemAccountError): ...


class FixedParentError(SystemAccountError): ...


class AccountService:
    def __init__(self, ar: AccountRepository, tr: TransactionRepository, pr: ProfileRepository):
        self.ar = ar
        self.tr = tr
        self.pr = pr
        self._currency: Currency | None = None

    def reset_defaults(self) -> None:
        """Forget what was looked up before a setting changed."""
        self._currency = None

    def currency(self) -> Currency:
        """The currency the whole ledger is kept in."""
        if self._currency is None:
            self._currency = find_currency(self.pr.currency())
            if self._currency is None:
                raise RuntimeError("the profile names a currency finode does not know")
        return self._currency

    def check_places(self, amount: Decimal) -> None:
        """An amount may have no more decimals than the currency has (rupees 2, yen 0)."""
        currency = self.currency()
        exponent = amount.normalize().as_tuple().exponent
        places = max(0, -exponent) if isinstance(exponent, int) else 0
        if places > currency.decimals:
            raise ValueError(
                f"{currency.code} amounts can have at most {currency.decimals} "
                f"decimal place{'' if currency.decimals == 1 else 's'}!"
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
            raise SystemAccountError(f"cannot add sub-accounts to system account '{parent.name}'!")
        accounts_by_id = {a.aid: a for a in all_accounts}
        if self._get_root_name(parent, accounts_by_id) in GROUP_POSTING_ROOT_NAMES:
            return
        if self.tr.postings_for_account(parent.aid):
            raise ValueError(f"cannot add sub-accounts to '{parent.name}' because it has postings!")

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

    def _check_depth(self, parent: Account, levels_below_parent: int, all_accounts: list[Account]) -> None:
        """Refuse a new or moved subtree that would go deeper than two levels below the top-level account."""
        resulting = self._depth(parent, {a.aid: a for a in all_accounts}) + levels_below_parent
        if resulting > MAX_ACCOUNT_DEPTH:
            raise AccountDepthError(
                "accounts can be at most two levels deep (a category and a subcategory, like Expenses › Food › Groceries)!"
            )

    @staticmethod
    def _refuse_fixed(account: Account, what: str) -> None:
        if account.system_key is not None:
            raise FixedParentError(f"'{account.name}' is built in and can't be {what}!")

    def empty_fixed_parents(self) -> list[Account]:
        """The built-in groups nothing has been made under yet (what a restore or an import may replace with its own)."""
        all_accounts = self._ensure_roots()
        used = {a.parent_id for a in all_accounts}
        return [a for a in all_accounts if a.system_key is not None and a.aid not in used]

    def release_fixed_parents(self, aids: list[UUID]) -> None:
        """Remove empty built-in groups so a restore or an import can bring its own structure (the caller commits)."""
        empty = {a.aid for a in self.empty_fixed_parents()}
        for aid in aids:
            if aid in empty:
                self.ar.delete(aid)

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

        new_roots: dict[str, Account] = {}
        for name in missing:
            new_roots[name] = Account(
                name=name,
                details=f"System root account for {name}",
                parent_id=None,
                user=self.ar.uid,
            )
            self.ar.db.add(new_roots[name])
        if len(missing) == len(ROOT_ACCOUNT_NAMES) and NEW_PROFILE_FIXED_PARENTS:
            # A brand-new person: the built-in groups come with the roots (same transaction, so a lost race makes none twice).
            for root, name, key, _ in FIXED_PARENTS:
                self.ar.db.add(Account(name=name, parent_id=new_roots[root].aid, user=self.ar.uid, system_key=key))
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
        return [account_id, *self._get_descendants(account_id, accounts_by_parent)]

    def _postings_by_account(self, all_accounts: list[Account], as_of: date | None) -> dict[UUID, list[Posting]]:
        """Every posting up to `as_of`, grouped by account, in one query: what a list of balances is computed from."""
        grouped: dict[UUID, list[Posting]] = {}
        for posting in self.tr.postings_for_accounts([a.aid for a in all_accounts], date_to=as_of or local_today()):
            grouped.setdefault(posting.account, []).append(posting)
        return grouped

    def _balance_for(
        self,
        account: Account,
        all_accounts: list[Account] | None = None,
        as_of: date | None = None,
        postings: dict[UUID, list[Posting]] | None = None,
    ) -> Decimal:
        """The account's balance: postings dated up to `as_of` (today by default, so entries dated in the future
        do not count yet) on the account and everything inside it."""
        if all_accounts is None:
            all_accounts = self._ensure_roots()
        as_of = as_of or local_today()

        accounts_by_id = {acc.aid: acc for acc in all_accounts}
        accounts_by_parent: dict[UUID, list[Account]] = {}
        for acc in all_accounts:
            if acc.parent_id is not None:
                accounts_by_parent.setdefault(acc.parent_id, []).append(acc)

        target_ids = [account.aid, *self._get_descendants(account.aid, accounts_by_parent)]
        normal_side = self._normal_side(account, accounts_by_id)
        rows = (
            self.tr.postings_for_accounts(target_ids, date_to=as_of)
            if postings is None
            else (p for aid in target_ids for p in postings.get(aid, ()))
        )
        balance = Decimal("0.00")
        for posting in rows:
            balance += posting.amount if posting.side == normal_side else -posting.amount
        return balance

    def _to_read(
        self,
        account: Account,
        all_accounts: list[Account] | None = None,
        as_of: date | None = None,
        postings: dict[UUID, list[Posting]] | None = None,
    ) -> AccountRead:
        balance = self._balance_for(account, all_accounts, as_of, postings)
        return AccountRead(
            aid=account.aid,
            name=account.name,
            details=account.details,
            parent_id=account.parent_id,
            balance=balance,
            on_budget=account.on_budget,
            payment_category_id=account.payment_category_id,
            closed_on=account.closed_on,
            system_key=account.system_key,
            created=account.created,
            updated=account.updated,
        )

    def opening_balances_account(self) -> Account:
        return self._opening_balances_account()

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
        )

    def _post_balance_adjustment(
        self,
        account: Account,
        amount: Decimal,
        payee: str,
        comment: str,
        all_accounts: list[Account],
    ) -> None:
        """Post `amount` on the account against Opening Balances."""
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

        self.check_places(adjustment)
        self.tr.create(
            TransactionCreate(
                date=local_today(),
                payee=payee,
                comment=comment,
                postings=[
                    PostingCreate(account=account.aid, side=account_side, amount=adjustment),
                    PostingCreate(account=opening_account.aid, side=opening_side, amount=adjustment),
                ],
            ),
        )

    # ---- closing ---------------------------------------------------------------------------------

    def _subtree(self, aid: UUID, all_accounts: list[Account]) -> list[Account]:
        children: dict[UUID, list[Account]] = {}
        for a in all_accounts:
            if a.parent_id is not None:
                children.setdefault(a.parent_id, []).append(a)
        found, queue = [], [next(a for a in all_accounts if a.aid == aid)]
        while queue:
            current = queue.pop()
            found.append(current)
            queue.extend(children.get(current.aid, []))
        return found

    def close(self, aid: UUID, today: date | None = None) -> AccountRead:
        """Close an account, and everything inside it: nothing more can be posted to it and it leaves the
        pickers and the accounts list, but its history stays. Refused while anything inside still holds a
        balance (now or in a future-dated entry) or a recurring transaction still uses it."""
        today = today or local_today()
        all_accounts = self._ensure_roots()
        account = next((a for a in all_accounts if a.aid == aid), None)
        if account is None:
            raise ValueError("account not found!")
        if self._is_root(account):
            raise RootAccountError("cannot close system root accounts!")
        if self.is_opening_balances(account, all_accounts):
            raise SystemAccountError(f"cannot close system account '{account.name}'!")
        self._refuse_fixed(account, "closed")
        subtree = self._subtree(aid, all_accounts)
        by_id = {a.aid: a for a in all_accounts}
        if self._get_root_name(account, by_id) in GROUP_POSTING_ROOT_NAMES:
            subtree_money = []  # a category's "balance" is what was spent or earned in it, not money to move out first
        else:
            subtree_money = subtree
        for member in subtree_money:
            for when in (today, date(2999, 12, 31)):
                balance = self._to_read(member, all_accounts, when).balance
                if balance != 0:
                    raise ValueError(
                        f"'{member.name}' still holds {balance:f}: move or spend it first, then close "
                        f"{'it' if member.aid == aid else account.name}!"
                    )
        rules = RecurringRepository.active_rules_using(self.ar.db, self.ar.uid, {m.aid for m in subtree})
        if rules:
            label = rules[0].payee or "a recurring transaction"
            raise AccountInUseError(f"'{label}' still records into it: stop that recurring transaction first!")
        for member in subtree:
            self.ar.clear_payment_category(member.aid)
        self.ar.set_closed([m.aid for m in subtree if m.closed_on is None], today)
        self.ar.db.commit()
        return self._to_read(self.ar.read(aid), self._ensure_roots())

    @staticmethod
    def order_key(account: Account) -> tuple:
        """How siblings are listed: the built-in groups first, in their fixed order, then the rest by name."""
        return (FIXED_ORDER.get(account.system_key or "", len(FIXED_ORDER)), account.name.lower())

    def reopen(self, aid: UUID) -> AccountRead:
        """Reopen an account with everything inside it, and the groups above it (an open account sits in open groups)."""
        all_accounts = self._ensure_roots()
        by_id = {a.aid: a for a in all_accounts}
        if aid not in by_id:
            raise ValueError("account not found!")
        ids = [m.aid for m in self._subtree(aid, all_accounts)]
        current = by_id[aid]
        while current.parent_id is not None:
            current = by_id[current.parent_id]
            ids.append(current.aid)
        self.ar.set_closed([i for i in ids if by_id[i].closed_on is not None], None)
        self.ar.db.commit()
        return self._to_read(self.ar.read(aid), self._ensure_roots())

    def _check_budgetable(self, parent: Account | None, accounts_by_id: dict) -> None:
        """Only an asset or liability account can be part of the budget."""
        if parent is None or self._get_root_name(parent, accounts_by_id) not in ("Assets", "Liabilities"):
            raise ValueError("only asset and liability accounts can be part of the budget!")

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

    @staticmethod
    def _check_name_free(
        name: str, parent_id: UUID | None, all_accounts: list[Account], exclude: UUID | None = None
    ) -> None:
        """Two accounts in the same place may not read the same (capitals aside): paths such as Expenses:Food name an
        account in the journal files and for the assistants, so they must tell accounts apart."""
        wanted = name.casefold()
        for other in all_accounts:
            if other.parent_id == parent_id and other.aid != exclude and other.name.casefold() == wanted:
                parent = next((a.name for a in all_accounts if a.aid == parent_id), None)
                raise ValueError(
                    f"{'there' if parent is None else repr(parent)} already has an account called '{other.name}'!"
                )

    def create(self, account: AccountCreate) -> AccountRead:
        all_accounts = self._ensure_roots()

        if account.parent_id is None:
            raise ValueError("parent_id is required for all user-created accounts!")

        parent = next((a for a in all_accounts if a.aid == account.parent_id), None)
        if not parent:
            raise ValueError("parent account not found!")

        self._validate_parent(parent, all_accounts)
        ensure_room(len(all_accounts), settings.max_accounts, "accounts")
        if parent.closed_on is not None:
            raise ValueError(f"'{parent.name}' is closed: reopen it to add accounts to it!")
        self._check_depth(parent, 1, all_accounts)
        if self.is_opening_balances(
            Account(name=account.name, parent_id=account.parent_id, user=self.ar.uid),
            all_accounts,
        ) and self.ar.read_by_name(account.name, account.parent_id):
            raise ValueError(f"system account '{account.name}' already exists!")

        self._check_name_free(account.name, account.parent_id, all_accounts)
        accounts_by_id = {a.aid: a for a in all_accounts}
        start = FIXED_DEFAULTS.get(parent.system_key or "")
        if start and account.on_budget is None and account.payment_category_id is None:
            # Made under a built-in group without saying how: it starts as the group says (a bank in the budget, a loan outside it).
            account = account.model_copy(update={"on_budget": start == "budget"})
        in_budget = account.on_budget
        if in_budget is None:  # money in an asset account is budgeted unless said otherwise
            in_budget = self._get_root_name(parent, accounts_by_id) == "Assets"
        elif in_budget:
            self._check_budgetable(parent, accounts_by_id)
        if account.payment_category_id is not None:
            target = accounts_by_id.get(account.payment_category_id)
            if target is None or target.parent_id is None or self._get_root_name(target, accounts_by_id) != "Expenses":
                raise ValueError("payments can only be budgeted under an expense category!")
            if self._get_root_name(parent, accounts_by_id) not in ("Assets", "Liabilities"):
                raise ValueError("only asset and liability accounts can have a payment category!")
            if in_budget:
                raise ValueError(
                    "an account that is part of the budget doesn't need one: its money is already budgeted!"
                )
        created = self.ar.create(account, on_budget=in_budget)
        all_accounts_with_created = [*all_accounts, created]

        try:
            self._post_balance_adjustment(
                created,
                account.balance,
                "Opening balance",
                "Initial account balance",
                all_accounts_with_created,
            )
        except ValueError:
            self.ar.db.rollback()
            raise
        self.ar.db.commit()
        self.ar.db.refresh(created)
        return self._to_read(created, all_accounts_with_created)

    def read(self, aid: UUID, as_of: date | None = None) -> AccountRead | None:
        all_accounts = self._ensure_roots()
        account = next((a for a in all_accounts if a.aid == aid), None)
        if not account:
            return None
        return self._to_read(account, all_accounts, as_of)

    def list(self, root_name: str | None = None, as_of: date | None = None) -> list[AccountRead]:
        all_accounts = self._ensure_roots()
        accounts_by_id = {acc.aid: acc for acc in all_accounts}

        filtered = all_accounts
        if root_name is not None:
            filtered = [a for a in all_accounts if self._get_root_name(a, accounts_by_id) == root_name]
        postings = self._postings_by_account(all_accounts, as_of)  # one query for every balance
        return [self._to_read(account, all_accounts, as_of, postings) for account in filtered]

    def payments_into_loans(
        self, all_accounts: list[Account], date_from: date | None = None, date_to: date | None = None
    ) -> list[tuple[UUID, Posting]]:
        """What was paid into accounts outside the budget (a loan) that name a payment category: (category, posting),
        debits only and only in transactions that touch a budget account, which is what the Budget counts as
        spending in that category too."""
        linked = {a.aid: a.payment_category_id for a in all_accounts if a.payment_category_id and not a.on_budget}
        if not linked:
            return []
        into = [
            p for p in self.tr.postings_for_accounts(list(linked), date_from, date_to) if p.side == PostingSide.DEBIT
        ]
        if not into:
            return []
        budget_accounts = {a.aid for a in all_accounts if a.on_budget}
        postings_of = self.tr.postings_for_transactions(list({p.transaction for p in into}))
        touching = {tid for tid, rows in postings_of.items() if any(r.account in budget_accounts for r in rows)}
        return [(linked[p.account], p) for p in into if p.transaction in touching]

    def register(self, aid: UUID, own_only: bool = False) -> list[RegisterEntry] | None:
        """Return the account's activity oldest first with a running balance.

        Postings on sub-accounts count towards the account, matching how its
        balance is derived, unless `own_only` asks for what was posted to the account itself. Each entry's change is signed by the account's
        normal side, so it adds up to the account balance.
        """
        all_accounts = self._ensure_roots()
        account = next((a for a in all_accounts if a.aid == aid), None)
        if not account:
            return None

        accounts_by_id = {acc.aid: acc for acc in all_accounts}
        target_ids = {aid} if own_only else self.subtree_ids(aid, all_accounts)
        normal_side = self._normal_side(account, accounts_by_id)

        changes: dict[UUID, Decimal] = {}
        rows = self.tr.postings_for_accounts(target_ids)
        # What was paid into a loan that is budgeted under this category (or one inside it) counts here too.
        paid = [p for category, p in self.payments_into_loans(all_accounts) if category in target_ids]
        loaded = self.tr.read_many(
            list({p.transaction for p in [*rows, *paid]})
        )  # one query for every transaction it needs
        for posting in rows:
            signed = posting.amount if posting.side == normal_side else -posting.amount
            changes[posting.transaction] = changes.get(posting.transaction, Decimal("0.00")) + signed
        for posting in paid:
            changes[posting.transaction] = changes.get(posting.transaction, Decimal("0.00")) + posting.amount

        transactions = [loaded[tid] for tid in changes if tid in loaded]
        transactions.sort(key=lambda t: (t.date, t.created))
        postings_of = self.tr.postings_for_transactions(list(changes))

        entries = []
        balance = Decimal("0.00")
        for transaction in transactions:
            balance += changes[transaction.tid]
            counter_accounts = []
            for posting in postings_of.get(transaction.tid, []):
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

    def register_page(self, aid: UUID, today: date, offset: int = 0, limit: int = REGISTER_PAGE) -> RegisterPage | None:
        """An account's activity for its page without reading all of it: the newest `limit` entries up to today (then
        whatever finishes the last day, so a day is never split between two chunks), starting `offset` entries in, plus
        everything dated after today. Only what is shown has its payee and other accounts read; the running balance
        comes from the postings alone. Entries are the same as `register` gives."""
        all_accounts = self._ensure_roots()
        account = next((a for a in all_accounts if a.aid == aid), None)
        if not account:
            return None
        accounts_by_id = {acc.aid: acc for acc in all_accounts}
        target_ids = self.subtree_ids(aid, all_accounts)
        normal_side = self._normal_side(account, accounts_by_id)
        changes: dict[UUID, Decimal] = {}
        when: dict[UUID, tuple] = {}
        for transaction, side, amount, day, created in self.tr.posting_facts(target_ids):
            signed = amount if side == normal_side else -amount
            changes[transaction] = changes.get(transaction, Decimal("0.00")) + signed
            when[transaction] = (day, created)
        ordered = sorted(changes, key=lambda tid: when[tid])
        balances: dict[UUID, Decimal] = {}
        running = Decimal("0.00")
        for tid in ordered:
            running += changes[tid]
            balances[tid] = running
        history = [tid for tid in reversed(ordered) if when[tid][0] <= today]
        ahead = [tid for tid in ordered if when[tid][0] > today]
        chunk = history[offset : offset + limit]
        while (
            chunk and offset + len(chunk) < len(history) and when[history[offset + len(chunk)]][0] == when[chunk[-1]][0]
        ):
            chunk.append(history[offset + len(chunk)])
        wanted = [*chunk, *ahead]
        loaded = self.tr.read_many(wanted)
        postings_of = self.tr.postings_for_transactions(wanted)

        def entry(tid: UUID) -> RegisterEntry:
            transaction = loaded[tid]
            counter: list[str] = []
            for posting in postings_of.get(tid, []):
                if posting.account in target_ids:
                    continue
                name = accounts_by_id[posting.account].name
                if name not in counter:
                    counter.append(name)
            return RegisterEntry(
                tid=tid,
                date=transaction.date,
                payee=transaction.payee,
                comment=transaction.comment,
                counter_accounts=counter,
                change=changes[tid],
                balance=balances[tid],
            )

        return RegisterPage(
            entries=[entry(t) for t in chunk if t in loaded],
            upcoming=[entry(t) for t in ahead if t in loaded],
            total=len(history),
            next_offset=offset + len(chunk),
            has_more=offset + len(chunk) < len(history),
            has_any=bool(changes),
        )

    def update(self, aid: UUID, data: AccountUpdate) -> AccountRead | None:
        all_accounts = self._ensure_roots()
        account = next((a for a in all_accounts if a.aid == aid), None)
        if not account:
            raise ValueError(f"account with aid '{aid}' not found!")

        is_system_root = self._is_root(account)
        is_opening = self.is_opening_balances(account, all_accounts)
        if data.model_fields_set:
            self._refuse_fixed(account, "changed")

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

                if self._detect_cycle(aid, parent_id):
                    raise ValueError("cyclic parent relationship detected!")

                if parent_id != account.parent_id:
                    self._validate_parent(parent, all_accounts)
                    self._check_depth(parent, 1 + self._height(aid, all_accounts), all_accounts)

                accounts_by_id = {a.aid: a for a in all_accounts}
                if self._get_root_name(parent, accounts_by_id) != self._get_root_name(account, accounts_by_id):
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
            self._check_name_free(candidate.name, candidate.parent_id, all_accounts, exclude=aid)

        if "balance" in data.model_fields_set and data.balance is not None:
            if is_system_root:
                raise RootAccountError("cannot set balance of a root account!")
            if self.ar.has_children(aid):
                raise ValueError("cannot set balance of an account with sub-accounts!")

        on_budget = None
        if data.on_budget is not None:
            accounts_by_id = {a.aid: a for a in all_accounts}
            if data.on_budget:
                if is_system_root or account.parent_id is None:
                    raise ValueError("only asset and liability accounts can be part of the budget!")
                if self.ar.has_children(aid):
                    raise ValueError("an account with sub-accounts cannot be part of the budget: use its sub-accounts!")
                new_parent = next((a for a in all_accounts if a.aid == (data.parent_id or account.parent_id)), None)
                self._check_budgetable(new_parent, accounts_by_id)
            on_budget = data.on_budget

        if account.closed_on is not None and "balance" in data.model_fields_set and data.balance is not None:
            raise ValueError(f"'{account.name}' is closed: reopen it to change its balance!")
        if data.parent_id and data.parent_id != account.parent_id:
            new_home = next((a for a in all_accounts if a.aid == data.parent_id), None)
            if new_home is not None and new_home.closed_on is not None:
                raise ValueError(f"'{new_home.name}' is closed: reopen it to move accounts into it!")

        payment_category: UUID | type(...) | None = ...
        if "payment_category_id" in data.model_fields_set:
            payment_category = data.payment_category_id
            if payment_category is not None:
                accounts_by_id = {a.aid: a for a in all_accounts}
                target = accounts_by_id.get(payment_category)
                if (
                    target is None
                    or target.parent_id is None
                    or self._get_root_name(target, accounts_by_id) != "Expenses"
                ):
                    raise ValueError("payments can only be budgeted under an expense category!")
                if (
                    is_system_root
                    or account.parent_id is None
                    or self._get_root_name(account, accounts_by_id) not in ("Assets", "Liabilities")
                ):
                    raise ValueError("only asset and liability accounts can have a payment category!")
                if self.ar.has_children(aid):
                    raise ValueError("an account with sub-accounts cannot have one: use its sub-accounts!")
                if on_budget if on_budget is not None else account.on_budget:
                    raise ValueError(
                        "an account that is part of the budget doesn't need one: its money is already budgeted!"
                    )
        elif on_budget and account.payment_category_id is not None:
            payment_category = None  # now part of the budget itself

        updated = self.ar.update(aid, data, on_budget, payment_category)
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
                )
            except ValueError:
                self.ar.db.rollback()
                raise

        self.ar.db.commit()
        self.ar.db.refresh(updated)
        return self._to_read(updated, all_accounts)

    def _path(self, account: Account, by_id: dict[UUID, Account]) -> str:
        names, seen = [], set()
        while account is not None and account.aid not in seen:
            seen.add(account.aid)
            names.append(account.name)
            account = by_id.get(account.parent_id) if account.parent_id else None
        return ":".join(reversed(names))

    def _deletion_snapshot(self, account: Account, all_accounts: list[Account], budget: BudgetRepository) -> dict:
        """What is needed to bring an unused account back (see models/account_deletion.py)."""
        by_id = {a.aid: a for a in all_accounts}
        return {
            "name": account.name,
            "details": account.details,
            "parent_id": str(account.parent_id) if account.parent_id else None,
            "path": self._path(account, by_id),
            "root": self._get_root_name(account, by_id),
            "on_budget": account.on_budget,
            "payment_category_id": str(account.payment_category_id) if account.payment_category_id else None,
            "plan": [
                {"month": row.month.isoformat(), "amount": str(row.amount)}
                for row in budget.list()
                if row.account_id == account.aid
            ],
            "linked": [str(a.aid) for a in all_accounts if a.payment_category_id == account.aid],
        }

    def restorable(self, limit: int = 50) -> list[dict]:
        """Accounts and categories deleted for good and not back, newest first (one per account, the latest deletion)."""
        by_id = {a.aid: a for a in self._ensure_roots()}
        latest: dict[UUID, object] = {}
        for row in self.ar.deletions():
            latest.setdefault(row.account_id, row)
        return [
            {
                "did": row.did,
                "account_id": row.account_id,
                "at": row.at,
                **{k: row.snapshot.get(k) for k in ("name", "path", "root")},
            }
            for aid, row in latest.items()
            if aid not in by_id
        ][:limit]

    def closed(self) -> list[dict]:
        """The accounts that were closed (a category that was deleted but had a history is closed): the outermost of
        each closed branch, newest first."""
        all_accounts = self._ensure_roots()
        by_id = {a.aid: a for a in all_accounts}
        top = [
            a
            for a in all_accounts
            if a.closed_on is not None
            and not self._is_root(a)
            and not (a.parent_id in by_id and by_id[a.parent_id].closed_on is not None)
        ]
        top.sort(key=lambda a: (a.closed_on, a.name), reverse=True)
        return [
            {
                "aid": a.aid,
                "name": a.name,
                "path": self._path(a, by_id),
                "root": self._get_root_name(a, by_id),
                "closed_on": a.closed_on,
            }
            for a in top
        ]

    def restore_deleted(self, did: UUID) -> AccountRead:
        """Bring back an account or category that was deleted for good: with its old id, note, budget flag, place,
        planned amounts and target, and the payment links that pointed at it."""
        row = self.ar.deletion(did)
        if row is None:
            raise LookupError("deleted account not found!")
        all_accounts = self._ensure_roots()
        by_id = {a.aid: a for a in all_accounts}
        if row.account_id in by_id:
            raise ValueError("this account is already back!")
        if next(r for r in self.ar.deletions() if r.account_id == row.account_id).did != row.did:
            raise ValueError("this account was deleted again later; restore the latest deletion!")
        snap = row.snapshot
        parent = by_id.get(UUID(snap["parent_id"])) if snap.get("parent_id") else None
        if parent is None:
            raise ValueError("the account it was in no longer exists, so it cannot be restored!")
        if parent.closed_on is not None:
            raise ValueError(f"'{parent.name}' is closed: reopen it first!")
        self._validate_parent(parent, all_accounts)
        ensure_room(len(all_accounts), settings.max_accounts, "accounts")
        self._check_depth(parent, 1, all_accounts)
        if any(a.parent_id == parent.aid and a.name == snap["name"] for a in all_accounts):
            raise ValueError(f"'{parent.name}' already has an account called '{snap['name']}'!")
        payment = UUID(snap["payment_category_id"]) if snap.get("payment_category_id") else None
        restored = self.ar.restore(
            row.account_id,
            {
                "name": snap["name"],
                "details": snap.get("details"),
                "parent_id": parent.aid,
                "on_budget": bool(snap.get("on_budget")),
                "payment_category_id": payment if payment in by_id else None,
            },
        )
        budget = BudgetRepository(self.ar.db, self.ar.uid)
        for item in snap.get("plan", []):
            budget.set(date.fromisoformat(item["month"]), restored.aid, Decimal(item["amount"]))
        for linked in snap.get("linked", []):
            other = by_id.get(UUID(linked))
            if other is not None and other.payment_category_id is None:
                other.payment_category_id = restored.aid
                self.ar.db.add(other)
        self.ar.db.commit()
        self.ar.db.refresh(restored)
        return self._to_read(restored, self._ensure_roots())

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
        self._refuse_fixed(account, "deleted")

        if self.ar.has_children(aid):
            raise AccountInUseError("account has sub-accounts")
        if self.tr.postings_for_account(aid):
            raise AccountInUseError("account has postings")
        if RecurringRepository.uses_account(self.ar.db, aid):
            raise AccountInUseError("account is used by a recurring transaction")

        account_read = self._to_read(account, all_accounts)
        budget = BudgetRepository(self.ar.db, self.ar.uid)
        self.ar.record_deletion(aid, self._deletion_snapshot(account, all_accounts, budget))
        budget.delete_for_account(aid)  # only a plan: it goes with the category
        self.ar.clear_payment_category(aid)
        deleted = self.ar.delete(aid)
        if not deleted:
            raise ValueError(f"account with aid '{aid}' not found!")
        self.ar.db.commit()
        return account_read

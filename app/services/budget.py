import calendar
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from ..models.account import Account
from ..models.transaction import PostingSide
from ..repositories import BudgetRepository, TransactionRepository
from ..schemas.budget import BudgetLine, BudgetRead
from .account import AccountService
from .transaction import decimal_places


ZERO = Decimal("0.00")


class BudgetError(ValueError):
    ...


def month_start(day: date | None) -> date:
    return (day or date.today()).replace(day=1)


def month_end(month: date) -> date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


class BudgetService:
    """Every unit of money gets a job (envelope budgeting) on top of the ledger.

    The only thing stored is the plan: how much of each month the user assigned to each category (an
    Expenses account). Everything else is derived, so editing the ledger can never leave it stale:

    - *cash* is what the budget's accounts hold: the asset and liability accounts the user flagged
      (`accounts.on_budget`), debits minus credits, a credit card counting as negative.
    - *activity* of a category in a month is what was posted to it in transactions that touch a
      budget account (spending from an account outside the budget is not the budget's business).
    - *available* is everything assigned to the category up to the month minus its activity up to
      then, so what is left (or overspent) carries into the next month.
    - *ready to assign* is cash minus the sum of all categories' available money. Income arriving
      raises it; assigning, or spending beyond what was assigned, lowers it.

    The figures are in the default currency and count entries up to the last day of the month.
    """

    def __init__(self, accounts: AccountService, tr: TransactionRepository, br: BudgetRepository):
        self.accounts = accounts
        self.tr = tr
        self.br = br

    # ---- reading ---------------------------------------------------------------------------------

    def _categories(self, accounts: list[Account]) -> dict[UUID, Account]:
        by_id = {a.aid: a for a in accounts}
        return {
            a.aid: a
            for a in accounts
            if a.parent_id is not None and AccountService.root_name(a, by_id) == "Expenses"
        }

    def _path(self, account: Account, by_id: dict[UUID, Account]) -> list[str]:
        names, seen = [], set()
        while account is not None and account.parent_id is not None and account.aid not in seen:
            seen.add(account.aid)
            names.append(account.name)
            account = by_id.get(account.parent_id)
        return list(reversed(names))

    def view(self, month: date | None = None) -> BudgetRead:
        return self._compute(month)[0]

    def _compute(self, month: date | None) -> tuple[BudgetRead, dict[UUID, tuple[Decimal, Decimal, Decimal]]]:
        month = month_start(month)
        through = month_end(month)
        default = self.accounts.default_currency()
        accounts = self.accounts.ar.list()
        by_id = {a.aid: a for a in accounts}
        parents = {a.parent_id for a in accounts if a.parent_id is not None}
        categories = self._categories(accounts)

        in_budget: set[UUID] = set()
        budget_accounts: list[str] = []
        ignored: list[str] = []
        for a in accounts:
            if not a.on_budget:
                continue
            label = ":".join(self._path_with_root(a, by_id))
            if a.commodity_id == default.cid and a.aid not in parents:
                in_budget.add(a.aid)
                budget_accounts.append(label)
            else:
                ignored.append(label)
        budget_accounts.sort()
        ignored.sort()

        transactions = {t.tid: t for t in self.tr.list(date_to=through)}
        touching: set[UUID] = set()
        postings = [p for p in self.tr.all_postings() if p.transaction in transactions]
        for p in postings:
            if p.account in in_budget:
                touching.add(p.transaction)

        cash = ZERO
        # What happened to each category in each month: [assigned, spent].
        by_category: dict[UUID, dict[date, list[Decimal]]] = {}
        unpriced = False
        book = self.accounts.prices.book()
        for p in postings:
            if p.account in in_budget:
                cash += p.amount if p.side == PostingSide.DEBIT else -p.amount
            if p.account in categories and p.transaction in touching:
                transaction = transactions[p.transaction]
                value = p.value if p.side == PostingSide.DEBIT else -p.value
                if transaction.currency_id != default.cid:
                    value = book.convert(value, transaction.currency_id, default.cid, transaction.date, default.decimals)
                    if value is None:
                        unpriced = True
                        continue
                figures = by_category.setdefault(p.account, {}).setdefault(month_start(transaction.date), [ZERO, ZERO])
                figures[1] += value
        for row in self.br.list(up_to=month):
            if row.account_id in categories:
                by_category.setdefault(row.account_id, {}).setdefault(row.month, [ZERO, ZERO])[0] += row.amount

        previous = month_start(month - timedelta(days=1))
        own: dict[UUID, tuple[Decimal, Decimal, Decimal, Decimal]] = {}
        for aid in categories:
            own[aid] = self._roll(by_category.get(aid, {}), month, previous)
        total_assigned = sum((v[0] for v in own.values()), ZERO)
        total_activity = sum((v[1] for v in own.values()), ZERO)
        total_available = sum((v[2] for v in own.values()), ZERO)
        total_overspent = sum((v[3] for v in own.values()), ZERO)

        lines = self._lines(categories, by_id, parents, own)
        read = BudgetRead(
            month=month,
            currency=default.code,
            ready_to_assign=cash - total_available,
            cash=cash,
            assigned=total_assigned,
            activity=total_activity,
            available=total_available,
            overspent_last_month=total_overspent,
            unpriced=unpriced,
            budget_accounts=budget_accounts,
            ignored_accounts=ignored,
            lines=lines,
        )
        return read, own

    @staticmethod
    def _roll(
        months: dict[date, list[Decimal]], month: date, previous: date
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """A category's figures for `month`: (assigned, spent, available, overspent last month).

        What is left carries into the next month, but an overspent category starts the next month at
        zero: the money it overspent has already left the budget's accounts, so it is taken out of
        what is ready to assign instead (cash overspending, as YNAB treats it). Within the month it
        happens in, the category just shows negative.
        """
        left = ZERO
        last: date | None = None
        for when in sorted(m for m in months if m < month):
            assigned, spent = months[when]
            left = max(ZERO, left) + assigned - spent
            last = when
        end_of_previous = left if last == previous else max(ZERO, left)
        assigned, spent = months.get(month, (ZERO, ZERO))
        return (
            assigned,
            spent,
            max(ZERO, end_of_previous) + assigned - spent,
            -end_of_previous if end_of_previous < 0 else ZERO,
        )

    def _path_with_root(self, account: Account, by_id: dict[UUID, Account]) -> list[str]:
        names = self._path(account, by_id)
        root = account
        while root.parent_id is not None and root.parent_id in by_id:
            root = by_id[root.parent_id]
        return [root.name, *names]

    def _lines(self, categories, by_id, parents, own) -> list[BudgetLine]:
        """The categories as a tree in display order: a group row (sums) before its sub-categories;
        a group that was itself posted to or assigned money also gets an '(other)' row of its own."""
        children: dict[UUID | None, list[Account]] = {}
        for a in categories.values():
            children.setdefault(a.parent_id, []).append(a)
        for kids in children.values():
            kids.sort(key=lambda a: a.name.lower())
        expenses_root = next((a for a in by_id.values() if a.parent_id is None and a.name == "Expenses"), None)
        zero = (ZERO, ZERO, ZERO, ZERO)

        def total(account: Account) -> tuple[Decimal, Decimal, Decimal, Decimal]:
            parts = [own.get(account.aid, zero)] + [total(c) for c in children.get(account.aid, [])]
            return tuple(sum((p[i] for p in parts), ZERO) for i in range(4))  # type: ignore[return-value]

        lines: list[BudgetLine] = []

        def walk(account: Account, depth: int) -> None:
            path = ":".join(self._path(account, by_id))
            kids = children.get(account.aid, [])
            if not kids:
                a, s, v, o = own[account.aid]
                lines.append(BudgetLine(aid=account.aid, name=account.name, path=path, depth=depth,
                                        assigned=a, activity=s, available=v, overspent_last_month=o))
                return
            a, s, v, o = total(account)
            lines.append(BudgetLine(aid=account.aid, name=account.name, path=path, depth=depth, group=True,
                                    assigned=a, activity=s, available=v, overspent_last_month=o))
            if any(own[account.aid]):
                a, s, v, o = own[account.aid]
                lines.append(BudgetLine(aid=account.aid, name=f"{account.name} (other)", path=path, depth=depth + 1,
                                        assigned=a, activity=s, available=v, overspent_last_month=o))
            for kid in kids:
                walk(kid, depth + 1)

        if expenses_root is not None:
            for top in children.get(expenses_root.aid, []):
                walk(top, 1)
        return lines

    # ---- changing the plan -----------------------------------------------------------------------

    def _category(self, aid: UUID) -> Account:
        account = self.accounts.ar.read(aid)
        if account is None:
            raise BudgetError("category not found!")
        if aid not in self._categories(self.accounts.ar.list()):
            raise BudgetError(f"'{account.name}' is not an expense account: only expense accounts can be budgeted!")
        return account

    def _check_amount(self, amount: Decimal) -> None:
        default = self.accounts.default_currency()
        if decimal_places(amount) > default.decimals:
            raise BudgetError(f"{default.code} amounts can have at most {default.decimals} decimal places!")

    def assigned(self, month: date, aid: UUID) -> Decimal:
        row = self.br.read(month, aid)
        return row.amount if row else ZERO

    def assign(self, month: date | None, aid: UUID, amount: Decimal) -> BudgetRead:
        """Set what a category gets in a month (0 removes it)."""
        month = month_start(month)
        self._category(aid)
        self._check_amount(amount)
        self.br.set(month, aid, amount)
        self.br.db.commit()
        return self.view(month)

    def move(self, month: date | None, from_aid: UUID, to_aid: UUID, amount: Decimal) -> BudgetRead:
        """Take money from one category's available and give it to another, in a month."""
        month = month_start(month)
        if from_aid == to_aid:
            raise BudgetError("choose two different categories!")
        source, target = self._category(from_aid), self._category(to_aid)
        self._check_amount(amount)
        if amount <= 0:
            raise BudgetError("the amount must be positive!")
        available = self._compute(month)[1][from_aid][2]
        if available <= 0:
            raise BudgetError(f"'{source.name}' has nothing available to move!")
        if amount > available:
            raise BudgetError(f"only {available:f} is available in '{source.name}'!")
        self.br.set(month, from_aid, self.assigned(month, from_aid) - amount)
        self.br.set(month, to_aid, self.assigned(month, to_aid) + amount)
        self.br.db.commit()
        return self.view(month)

import calendar
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from uuid import UUID

from ..models.account import Account
from ..models.budget import BudgetTarget
from ..models.transaction import PostingSide
from ..repositories import BudgetRepository, TransactionRepository
from ..schemas.budget import TARGET_KINDS, BudgetLeftOut, BudgetLine, BudgetRead, BudgetTargetRead
from ..schemas.account import AccountUpdate
from .account import AccountService
from .transaction import decimal_places


ZERO = Decimal("0.00")


class BudgetError(ValueError):
    ...


def month_start(day: date | None) -> date:
    return (day or date.today()).replace(day=1)


def months_between(first: date, last: date) -> int:
    return (last.year - first.year) * 12 + last.month - first.month


def funding(target: BudgetTarget, assigned: Decimal, carried: Decimal, month: date, decimals: int) -> tuple[Decimal, Decimal]:
    """(needed, underfunded) for a category in a month, from its target.

    `carried` is what the category brought into the month. monthly needs the amount assigned each month;
    refill needs what keeps the amount available; by_date saves the missing money evenly over the months
    left, the whole of it once the date's month has come.
    """
    if target.kind == "monthly":
        needed = target.amount
    elif target.kind == "refill":
        needed = max(ZERO, target.amount - carried)
    else:
        remaining = max(ZERO, target.amount - carried)
        left = max(1, months_between(month, month_start(target.target_date)) + 1) if target.target_date else 1
        step = Decimal(1).scaleb(-decimals)
        needed = min(remaining, (remaining / left).quantize(step, rounding=ROUND_CEILING))
    return needed + ZERO, max(ZERO, needed - assigned) + ZERO


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
        # Accounts outside the budget (loans) whose payments are budgeted under a category.
        payments = {
            a.aid: a.payment_category_id
            for a in accounts
            if a.payment_category_id in categories and not a.on_budget
        }

        in_budget: set[UUID] = set()
        candidates: dict[UUID, Account] = {}  # could be in the budget but are not: assets/liabilities holding the currency
        budget_accounts: list[str] = []
        ignored: list[str] = []
        for a in accounts:
            if not a.on_budget:
                if (
                    a.aid not in payments
                    and a.parent_id is not None
                    and a.aid not in parents
                    and a.commodity_id == default.cid
                    and AccountService.root_name(a, by_id) in ("Assets", "Liabilities")
                ):
                    candidates[a.aid] = a
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

        book = self.accounts.prices.book()
        # Spending this month in transactions that touch no budget account: [value, accounts that paid].
        outside: dict[UUID, list] = {}
        for p in postings:
            if p.transaction in touching:
                continue
            transaction = transactions[p.transaction]
            if p.account in categories and month_start(transaction.date) == month:
                value = p.value if p.side == PostingSide.DEBIT else -p.value
                if transaction.currency_id != default.cid:
                    value = book.convert(value, transaction.currency_id, default.cid, transaction.date, default.decimals) or ZERO
                outside.setdefault(p.transaction, [ZERO, set()])[0] += value
        for p in postings:
            if p.transaction in outside and p.account in candidates:
                outside[p.transaction][1].add(p.account)

        allocations = self.br.list(up_to=month)
        # Budgeting starts with the first month anything was assigned: earlier spending already left the
        # accounts that cash is counted from, and must not show up as overspending.
        start = min((row.month for row in allocations), default=month)

        cash = ZERO
        # What happened to each category in each month: [assigned, spent].
        by_category: dict[UUID, dict[date, list[Decimal]]] = {}
        unpriced = False
        for p in postings:
            if p.account in in_budget:
                cash += p.amount if p.side == PostingSide.DEBIT else -p.amount
            # Spending is what is posted to a category, and what is paid into an account that has one.
            target = p.account if p.account in categories else (payments.get(p.account) if p.side == PostingSide.DEBIT else None)
            if target is not None and p.transaction in touching:
                transaction = transactions[p.transaction]
                if month_start(transaction.date) < start:
                    continue
                value = p.value if p.side == PostingSide.DEBIT else -p.value
                if transaction.currency_id != default.cid:
                    value = book.convert(value, transaction.currency_id, default.cid, transaction.date, default.decimals)
                    if value is None:
                        unpriced = True
                        continue
                figures = by_category.setdefault(target, {}).setdefault(month_start(transaction.date), [ZERO, ZERO])
                figures[1] += value
        for row in allocations:
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

        left: dict[UUID, list] = {}
        for value, payers in outside.values():
            for aid in payers:
                entry = left.setdefault(aid, [0, ZERO])
                entry[0] += 1
                entry[1] += value
        left_out_accounts = sorted(
            (
                BudgetLeftOut(aid=aid, path=":".join(self._path_with_root(candidates[aid], by_id)), entries=n, spent=v)
                for aid, (n, v) in left.items()
            ),
            key=lambda x: -x.spent,
        )
        left_out_total = sum((v[0] for v in outside.values() if v[1]), ZERO)

        targets = self.br.targets()
        needs: dict[UUID, tuple[Decimal, Decimal]] = {}
        for aid, target in targets.items():
            if aid in own:
                assigned, spent, available, _ = own[aid]
                needs[aid] = funding(target, assigned, available - assigned + spent, month, default.decimals)
        total_underfunded = sum((v[1] for v in needs.values()), ZERO)

        lines = self._lines(categories, by_id, parents, own, targets, needs)
        read = BudgetRead(
            month=month,
            currency=default.code,
            ready_to_assign=cash - total_available,
            cash=cash,
            assigned=total_assigned,
            activity=total_activity,
            available=total_available,
            overspent_last_month=total_overspent,
            underfunded=total_underfunded,
            left_out=left_out_total,
            left_out_accounts=left_out_accounts,
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

    def _lines(self, categories, by_id, parents, own, targets, needs) -> list[BudgetLine]:
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

        def visible(account: Account) -> bool:
            """A closed category disappears from the budget once nothing is left in it for the month."""
            return (
                account.closed_on is None
                or any(own.get(account.aid, zero))
                or any(visible(c) for c in children.get(account.aid, []))
            )

        def missing(account: Account) -> Decimal:
            return needs.get(account.aid, (ZERO, ZERO))[1] + sum((missing(c) for c in children.get(account.aid, [])), ZERO)

        def line(account: Account, name: str, depth: int, figures, group: bool = False, underfunded=None) -> BudgetLine:
            a, s, v, o = figures
            target = targets.get(account.aid) if not group else None
            return BudgetLine(
                aid=account.aid, name=name, path=":".join(self._path(account, by_id)), depth=depth, group=group,
                assigned=a, activity=s, available=v, overspent_last_month=o,
                target=BudgetTargetRead(kind=target.kind, amount=target.amount, target_date=target.target_date) if target else None,
                needed=needs.get(account.aid, (ZERO, ZERO))[0] if target else ZERO,
                underfunded=needs.get(account.aid, (ZERO, ZERO))[1] if underfunded is None else underfunded,
            )

        lines: list[BudgetLine] = []

        def walk(account: Account, depth: int) -> None:
            kids = [k for k in children.get(account.aid, []) if visible(k)]
            if not kids:
                lines.append(line(account, account.name, depth, own[account.aid]))
                return
            lines.append(line(account, account.name, depth, total(account), group=True, underfunded=missing(account)))
            if any(own[account.aid]) or account.aid in targets:
                lines.append(line(account, f"{account.name} (other)", depth + 1, own[account.aid]))
            for kid in kids:
                walk(kid, depth + 1)

        if expenses_root is not None:
            for top in children.get(expenses_root.aid, []):
                if visible(top):
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

    def include_account(self, aid: UUID) -> None:
        """Make an account part of the budget (its money and its spending count from now on)."""
        try:
            if self.accounts.update(aid, AccountUpdate(on_budget=True)) is None:
                raise BudgetError("account not found!")
        except ValueError as e:
            raise BudgetError(str(e))

    def set_target(self, aid: UUID, kind: str, amount: Decimal, target_date: date | None = None) -> BudgetRead:
        """Say what a category should be funded with (replaces its target)."""
        account = self._category(aid)
        if kind not in TARGET_KINDS:
            raise BudgetError(f"the target must be one of: {', '.join(TARGET_KINDS)}!")
        if amount <= 0:
            raise BudgetError("the target amount must be positive!")
        self._check_amount(amount)
        if kind == "by_date":
            if target_date is None:
                raise BudgetError("a target by a date needs the date!")
            if month_start(target_date) < month_start(None):
                raise BudgetError("the date is in the past: choose this month or later!")
        else:
            target_date = None
        self.br.set_target(account.aid, kind, amount, target_date)
        self.br.db.commit()
        return self.view(None)

    def clear_target(self, aid: UUID) -> BudgetRead:
        self._category(aid)
        self.br.clear_target(aid)
        self.br.db.commit()
        return self.view(None)

    def fund(self, month: date | None) -> BudgetRead:
        """Assign what the targets still need, in display order, until there is nothing left to assign."""
        month = month_start(month)
        data = self.view(month)
        if data.underfunded <= 0:
            raise BudgetError("nothing is underfunded!")
        if data.ready_to_assign <= 0:
            raise BudgetError("there is nothing ready to assign: add income or lower another category first!")
        left = data.ready_to_assign
        for line in data.lines:
            if line.group or line.underfunded <= 0 or left <= 0:
                continue
            add = min(line.underfunded, left)
            self.br.set(month, line.aid, self.assigned(month, line.aid) + add)
            left -= add
        self.br.db.commit()
        return self.view(month)

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

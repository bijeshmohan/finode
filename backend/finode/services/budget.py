"""Envelope budgeting on top of the ledger: assigned, activity, available and Ready to assign, moving and copying money. Only the plan is stored; the rest is derived (see docs/architecture/budget.md)."""

import calendar
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from ..clock import FIRST_DAY, LAST_DAY, local_today
from ..models.account import Account
from ..models.category import BudgetCategory
from ..models.transaction import PostingSide
from ..repositories import BudgetRepository, CategoryRepository, TransactionRepository
from ..schemas.account import AccountUpdate
from ..schemas.budget import BudgetCard, BudgetLeftOut, BudgetLine, BudgetRead, BudgetUncategorised
from .account import AccountService
from .transaction import decimal_places

ZERO = Decimal("0.00")


class BudgetError(ValueError): ...


def first_of_month(day: date) -> date:
    """The first day of a day's month, for dates already stored or checked (no range check)."""
    return day.replace(day=1)


def month_start(day: date | None) -> date:
    """The first day of the month a day is in (this month when empty). Months outside the calendar finode works in
    (clock.FIRST_DAY to LAST_DAY) are refused, so no sum or step to the next or previous month can run off its ends."""
    day = day or local_today()
    if not FIRST_DAY <= day <= LAST_DAY:
        raise BudgetError(f"{day:%b %Y} is outside the months finode works with!")
    return day.replace(day=1)


def month_end(month: date) -> date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


class BudgetService:
    """Every unit of money gets a job (envelope budgeting) on top of the ledger.

    The only thing stored is the plan: how much of each month the user assigned to each spending category
    (`budget_categories`). Everything else is derived, so editing the ledger can never leave it stale:

    - *cash* is what the budget's accounts hold: the asset and liability accounts the user flagged
      (`accounts.on_budget`), debits minus credits, a credit card counting as negative.
    - *activity* of a category in a month is what was posted to it in transactions that touch a
      budget account (spending from an account outside the budget is not the budget's business).
    - *available* is everything assigned to the category up to the month minus its activity up to
      then, so what is left (or overspent) carries into the next month.
    - *ready to assign* is cash minus the sum of all categories' available money. Income arriving
      raises it; assigning, or spending beyond what was assigned, lowers it.

    The figures are in the user's currency and count entries up to the last day of the month.
    """

    def __init__(self, accounts: AccountService, tr: TransactionRepository, br: BudgetRepository):
        self.accounts = accounts
        self.tr = tr
        self.br = br
        self.cr = CategoryRepository(br.db, br.uid)

    # ---- reading ---------------------------------------------------------------------------------

    def _categories(self) -> dict[UUID, BudgetCategory]:
        """The spending categories (earning ones are not budgeted), closed ones too."""
        return {c.id: c for c in self.cr.list() if c.kind == "spending"}

    @staticmethod
    def _category_path(category: BudgetCategory, by_id: dict[UUID, BudgetCategory]) -> list[str]:
        names: list[str] = []
        seen: set[UUID] = set()
        current: BudgetCategory | None = category
        while current is not None and current.id not in seen:
            seen.add(current.id)
            names.append(current.name)
            current = by_id.get(current.parent_id) if current.parent_id else None
        return list(reversed(names))

    def _path(self, account: Account, by_id: dict[UUID, Account]) -> list[str]:
        names: list[str] = []
        seen: set[UUID] = set()
        current: Account | None = account
        while current is not None and current.parent_id is not None and current.id not in seen:
            seen.add(current.id)
            names.append(current.name)
            current = by_id.get(current.parent_id)
        return list(reversed(names))

    def spending_categories(self, include_closed: bool = False) -> list[BudgetCategory]:
        """The categories a payment can be given, A to Z by path."""
        every = self._categories()
        found = [c for c in every.values() if include_closed or c.closed_on is None]
        return sorted(found, key=lambda c: [part.casefold() for part in self._category_path(c, every)])

    def category_path(self, category: BudgetCategory) -> list[str]:
        return self._category_path(category, self._categories())

    def view(self, month: date | None = None) -> BudgetRead:
        return self._compute(month)[0]

    def started(self) -> bool:
        """Whether an amount was ever assigned to a category, in any month."""
        return bool(self.br.list())

    def _compute(self, month: date | None) -> tuple[BudgetRead, dict[UUID, tuple[Decimal, Decimal, Decimal, Decimal]]]:
        month = month_start(month)
        through = month_end(month)
        today = local_today()
        if month == first_of_month(today):
            through = min(through, today)  # what is dated later this month is not here yet: the budget is as of today
        currency = self.accounts.currency()
        accounts = self.accounts.ar.list()
        by_id = {a.id: a for a in accounts}
        parents = {a.parent_id for a in accounts if a.parent_id is not None}
        categories = self._categories()

        owed = self.accounts.ar.contact_account_ids()  # "Due from" and "Due to": money owed, not a place money is kept
        in_budget: set[UUID] = set()
        candidates: dict[UUID, Account] = {}  # could be in the budget but are not: assets/liabilities that could be
        budget_accounts: list[str] = []
        ignored: list[str] = []
        for a in accounts:
            if not a.on_budget:
                home = by_id.get(a.parent_id) if a.parent_id else None
                if (
                    home is not None
                    and a.id not in parents
                    and a.new_accounts_in_budget is None
                    and a.id not in owed
                    and AccountService.root_name(a, by_id) in ("Assets", "Liabilities")
                    # A group whose accounts start outside the budget (loans, investments) is outside by design: no nudge to add them.
                    and home.new_accounts_in_budget is not False
                ):
                    candidates[a.id] = a
                continue
            label = ":".join(self._path_with_root(a, by_id))
            if a.id not in parents:
                in_budget.add(a.id)
                budget_accounts.append(label)
            else:
                ignored.append(label)
        budget_accounts.sort()
        ignored.sort()

        touching: set[UUID] = set()
        postings = self.tr.posting_rows(through)
        for p in postings:
            if p.account_id in in_budget:
                touching.add(p.transaction_id)

        # Payments this month into accounts outside the budget (a loan, a fund) that no category took.
        unlabelled = [
            p
            for p in postings
            if p.transaction_id in touching
            and p.side == PostingSide.DEBIT
            and p.category_id is None
            and p.account_id not in in_budget
            and p.account_id not in owed
            and first_of_month(p.date) == month
            and p.account_id in by_id
            and AccountService.root_name(by_id[p.account_id], by_id) in ("Assets", "Liabilities")
        ]
        uncategorised: list[BudgetUncategorised] = []
        if unlabelled:
            entries = self.tr.read_many(list({p.transaction_id for p in unlabelled}))
            for p in sorted(unlabelled, key=lambda p: (p.date, str(p.transaction_id)), reverse=True):
                entry = entries.get(p.transaction_id)
                uncategorised.append(
                    BudgetUncategorised(
                        transaction_id=p.transaction_id,
                        date=p.date,
                        payee=entry.payee if entry else None,
                        account=":".join(self._path_with_root(by_id[p.account_id], by_id)),
                        amount=p.amount,
                    )
                )

        # Spending this month in transactions that touch no budget account: [value, accounts that paid].
        outside: dict[UUID, list] = {}
        for p in postings:
            if p.transaction_id in touching:
                continue
            if p.category_id in categories and first_of_month(p.date) == month:
                value = p.amount if p.side == PostingSide.DEBIT else -p.amount
                outside.setdefault(p.transaction_id, [ZERO, set()])[0] += value
        for p in postings:  # the account that paid, not the loan or fund that took the money
            if p.transaction_id in outside and p.side == PostingSide.CREDIT and p.account_id in candidates:
                outside[p.transaction_id][1].add(p.account_id)

        every_row = self.br.list()
        allocations = [row for row in every_row if row.month <= month]
        # Money assigned to later months is out of what can be assigned now.
        later = sum((row.amount for row in every_row if row.month > month and row.category_id in categories), ZERO)
        previous = first_of_month(month - timedelta(days=1))
        assigned_here = {row.category_id for row in allocations if row.month == month}
        # Once anything is assigned this month the month is started, so there is nothing to offer a copy of.
        started = bool(assigned_here)
        copyable = sum(
            (
                row.amount
                for row in allocations
                if row.month == previous
                and row.category_id in categories
                and row.category_id not in assigned_here
                and categories[row.category_id].closed_on is None
            ),
            ZERO,
        )
        if started:
            copyable = ZERO
        # Budgeting starts with the first month anything was assigned: earlier spending already left the
        # accounts that cash is counted from, and must not show up as overspending.
        start = min((row.month for row in allocations), default=month)

        liabilities = {
            account_id
            for account_id in in_budget
            if AccountService.root_name(by_id[account_id], by_id) == "Liabilities"
        }
        # Per card: [balance (debits - credits) to the month's end, charged this month, paid this month].
        card_books: dict[UUID, list[Decimal]] = {account_id: [ZERO, ZERO, ZERO] for account_id in liabilities}

        cash = ZERO
        # What happened to each category in each month: [assigned, spent].
        by_category: dict[UUID, dict[date, list[Decimal]]] = {}
        for p in postings:
            if p.account_id in in_budget:
                cash += p.amount if p.side == PostingSide.DEBIT else -p.amount
                if p.account_id in liabilities:
                    book_ = card_books[p.account_id]
                    book_[0] += p.amount if p.side == PostingSide.DEBIT else -p.amount
                    if first_of_month(p.date) == month:
                        book_[2 if p.side == PostingSide.DEBIT else 1] += p.amount
            # Spending is what a line says it was for, when its own account is not part of the budget.
            target = p.category_id if p.category_id in categories and p.account_id not in in_budget else None
            if target is not None and p.transaction_id in touching:
                if first_of_month(p.date) < start:
                    continue
                value = p.amount if p.side == PostingSide.DEBIT else -p.amount
                figures = by_category.setdefault(target, {}).setdefault(first_of_month(p.date), [ZERO, ZERO])
                figures[1] += value
        for row in allocations:
            if row.category_id in categories:
                by_category.setdefault(row.category_id, {}).setdefault(row.month, [ZERO, ZERO])[0] += row.amount

        own: dict[UUID, tuple[Decimal, Decimal, Decimal, Decimal]] = {
            category_id: self._roll(by_category.get(category_id, {}), month, previous) for category_id in categories
        }
        total_assigned = sum((v[0] for v in own.values()), ZERO)
        total_activity = sum((v[1] for v in own.values()), ZERO)
        total_available = sum((v[2] for v in own.values()), ZERO)
        total_overspent = sum((v[3] for v in own.values()), ZERO)
        left: dict[UUID, list] = {}
        for value, payers in outside.values():
            for account_id in payers:
                entry = left.setdefault(account_id, [0, ZERO])
                entry[0] += 1
                entry[1] += value
        left_out_accounts = sorted(
            (
                BudgetLeftOut(
                    account_id=account_id,
                    path=":".join(self._path_with_root(candidates[account_id], by_id)),
                    entries=n,
                    spent=v,
                )
                for account_id, (n, v) in left.items()
            ),
            key=lambda x: -x.spent,
        )
        left_out_total = sum((v[0] for v in outside.values() if v[1]), ZERO)

        cards = sorted(
            (
                BudgetCard(
                    account_id=account_id,
                    path=":".join(self._path_with_root(by_id[account_id], by_id)),
                    owed=max(ZERO, -balance),
                    charged=charged,
                    paid=paid,
                )
                for account_id, (balance, charged, paid) in card_books.items()
            ),
            key=lambda c: c.path,
        )
        reserved = sum((c.owed for c in cards), ZERO)

        lines = self._lines(categories, own)
        read = BudgetRead(
            month=month,
            currency=currency.code,
            ready_to_assign=cash - total_available - later,
            assigned_to_later_months=later,
            copyable=copyable,
            cash=cash,
            assigned=total_assigned,
            activity=total_activity,
            available=total_available,
            overspent_last_month=total_overspent,
            money_in_accounts=cash + reserved,
            reserved_for_cards=reserved,
            cards=cards,
            uncategorised=uncategorised,
            left_out=left_out_total,
            left_out_accounts=left_out_accounts,
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

    def _lines(
        self, categories: dict[UUID, BudgetCategory], own: dict[UUID, tuple[Decimal, Decimal, Decimal, Decimal]]
    ) -> list[BudgetLine]:
        """The categories as a tree in display order: a group row (sums) before its subcategories;
        a group that was itself posted to or assigned money also gets an '(other)' row of its own."""
        children: dict[UUID | None, list[BudgetCategory]] = {}
        for c in categories.values():
            children.setdefault(c.parent_id if c.parent_id in categories else None, []).append(c)
        for kids in children.values():
            kids.sort(key=lambda c: c.name.lower())
        zero = (ZERO, ZERO, ZERO, ZERO)

        def total(category: BudgetCategory) -> tuple[Decimal, Decimal, Decimal, Decimal]:
            parts = [own.get(category.id, zero)] + [total(c) for c in children.get(category.id, [])]
            return (
                sum((p[0] for p in parts), ZERO),
                sum((p[1] for p in parts), ZERO),
                sum((p[2] for p in parts), ZERO),
                sum((p[3] for p in parts), ZERO),
            )

        def visible(category: BudgetCategory) -> bool:
            """A closed category disappears from the budget once nothing is left in it for the month."""
            return (
                category.closed_on is None
                or any(own.get(category.id, zero))
                or any(visible(c) for c in children.get(category.id, []))
            )

        def line(
            category: BudgetCategory,
            name: str,
            depth: int,
            figures: tuple[Decimal, Decimal, Decimal, Decimal],
            group: bool = False,
        ) -> BudgetLine:
            a, s, v, o = figures
            return BudgetLine(
                category_id=category.id,
                name=name,
                path=":".join(self._category_path(category, categories)),
                depth=depth,
                group=group,
                assigned=a,
                activity=s,
                available=v,
                overspent_last_month=o,
            )

        lines: list[BudgetLine] = []

        def walk(category: BudgetCategory, depth: int) -> None:
            kids = [k for k in children.get(category.id, []) if visible(k)]
            if not kids:
                lines.append(line(category, category.name, depth, own[category.id]))
                return
            lines.append(line(category, category.name, depth, total(category), group=True))
            if any(own[category.id]):
                lines.append(line(category, f"{category.name} (other)", depth + 1, own[category.id]))
            for kid in kids:
                walk(kid, depth + 1)

        for top in children.get(None, []):
            if visible(top):
                walk(top, 1)
        return lines

    # ---- changing the plan -----------------------------------------------------------------------

    def _category(self, category_id: UUID) -> BudgetCategory:
        category = self._categories().get(category_id)
        if category is not None:
            return category
        found = self.cr.read(category_id)
        if found is None:
            raise BudgetError("category not found!")
        raise BudgetError(f"'{found.name}' is not a spending category: only spending categories can be budgeted!")

    def _check_amount(self, amount: Decimal) -> None:
        currency = self.accounts.currency()
        if decimal_places(amount) > currency.decimals:
            raise BudgetError(f"{currency.code} amounts can have at most {currency.decimals} decimal places!")

    def include_account(self, account_id: UUID) -> None:
        """Make an account part of the budget (its money and its spending count from now on)."""
        try:
            if self.accounts.update(account_id, AccountUpdate(on_budget=True)) is None:
                raise BudgetError("account not found!")
        except ValueError as e:
            raise BudgetError(str(e)) from None

    def assigned(self, month: date, category_id: UUID) -> Decimal:
        row = self.br.read(month, category_id)
        return row.amount if row else ZERO

    def assign(self, month: date | None, category_id: UUID, amount: Decimal) -> BudgetRead:
        """Set what a category gets in a month (0 removes it)."""
        month = month_start(month)
        self._category(category_id)
        if amount < 0:
            # A month's amount may be negative to take back what an earlier month left in the category (that is what
            # Move money writes too), but never more than the category has left: past that it would show as overspent
            # with nothing spent and make Ready to assign larger than the money there is.
            available = self._compute(month)[1][category_id][2]
            taken = self.assigned(month, category_id) - amount
            if taken > available:
                name = self._category(category_id).name
                raise BudgetError(
                    f"only {max(available, ZERO):f} is available in '{name}' to take out: assign at least "
                    f"{self.assigned(month, category_id) - max(available, ZERO):f}!"
                )
        self._check_amount(amount)
        self.br.set(month, category_id, amount)
        self.br.db.commit()
        return self.view(month)

    def group_minimum(self, month: date | None, category_id: UUID, data: BudgetRead | None = None) -> Decimal:
        """The least a group can be given in a month: what its subcategories were given add up to."""
        data = data or self.view(month)
        group = next((ln for ln in data.lines if ln.category_id == category_id and ln.group), None)
        if group is None:
            raise BudgetError("only a category with subcategories has a budget of its own!")
        prefix = f"{group.path}:"
        return sum(
            (
                ln.assigned
                for ln in data.lines
                if ln.path.startswith(prefix) and not ln.group and not ln.name.endswith("(other)")
            ),
            ZERO,
        )

    def assign_group(self, month: date | None, category_id: UUID, total: Decimal) -> BudgetRead:
        """Set a group's budget for a month. It starts at what its subcategories add up to and may be more (the rest is
        the group's own money, which the budget keeps on the group's own account); never less."""
        month = month_start(month)
        minimum = self.group_minimum(month, category_id)
        if total < minimum:
            raise BudgetError(f"minimum {minimum:f}")
        return self.assign(month, category_id, total - minimum)

    def copy_previous(self, month: date | None) -> BudgetRead:
        """Assign this month what each category got last month, for the categories with nothing assigned yet."""
        month = month_start(month)
        previous = first_of_month(month - timedelta(days=1))
        categories = self._categories()
        rows = self.br.list(up_to=month)
        have = {row.category_id for row in rows if row.month == month}
        wanted = [
            row
            for row in rows
            if row.month == previous
            and row.category_id in categories
            and row.category_id not in have
            and categories[row.category_id].closed_on is None
        ]
        if not wanted:
            raise BudgetError(
                "last month has nothing assigned to copy!"
                if not any(row.month == previous for row in rows)
                else "everything last month had is already assigned this month!"
            )
        self.br.add_many((month, row.category_id, row.amount) for row in wanted)
        self.br.db.commit()
        return self.view(month)

    def move(self, month: date | None, from_id: UUID, to_id: UUID, amount: Decimal) -> BudgetRead:
        """Take money from one category's available and give it to another, in a month."""
        month = month_start(month)
        if from_id == to_id:
            raise BudgetError("choose two different categories!")
        source = self._category(from_id)
        self._category(to_id)  # must exist and be a category
        self._check_amount(amount)
        if amount <= 0:
            raise BudgetError("the amount must be positive!")
        available = self._compute(month)[1][from_id][2]
        if available <= 0:
            raise BudgetError(f"'{source.name}' has nothing available to move!")
        if amount > available:
            raise BudgetError(f"only {available:f} is available in '{source.name}'!")
        self.br.set(month, from_id, self.assigned(month, from_id) - amount)
        self.br.set(month, to_id, self.assigned(month, to_id) + amount)
        self.br.db.commit()
        return self.view(month)

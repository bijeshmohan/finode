"""Envelope budgeting on top of the ledger: assigned, activity, available and Ready to assign, goals, moving and copying money. Only the plan and goals are stored; the rest is derived (see docs/architecture/budget.md)."""

import calendar
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from uuid import UUID

from ..models.account import Account
from ..models.budget import Goal
from ..models.transaction import PostingSide
from ..repositories import BudgetRepository, TransactionRepository
from ..schemas.budget import BudgetCard, BudgetLeftOut, BudgetLine, BudgetRead, GoalLine
from ..schemas.account import AccountUpdate
from .account import AccountService
from .transaction import decimal_places
from ..clock import FIRST_DAY, LAST_DAY, local_today


ZERO = Decimal("0.00")


class BudgetError(ValueError):
    ...


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


def months_between(first: date, last: date) -> int:
    return (last.year - first.year) * 12 + last.month - first.month


def funding(amount: Decimal, due: date, carried: Decimal, assigned: Decimal, month: date, decimals: int) -> tuple[Decimal, Decimal]:
    """(needed, underfunded) for a goal in a month: the missing money (`amount` less what is saved, `carried`) spread
    evenly over the months left, this one included, the whole of it once the due month has come."""
    remaining = max(ZERO, amount - carried)
    left = max(1, months_between(month, due) + 1)
    step = Decimal(1).scaleb(-decimals)
    needed = min(remaining, (remaining / left).quantize(step, rounding=ROUND_CEILING))
    return needed + ZERO, max(ZERO, needed - assigned) + ZERO


def is_overdue(due: date, month: date, underfunded: Decimal) -> bool:
    """A goal whose month is behind us and that is still short."""
    return underfunded > 0 and due < month


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

    The figures are in the user's currency and count entries up to the last day of the month.
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
        currency = self.accounts.currency()
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
        candidates: dict[UUID, Account] = {}  # could be in the budget but are not: assets/liabilities that could be
        budget_accounts: list[str] = []
        ignored: list[str] = []
        for a in accounts:
            if not a.on_budget:
                if (
                    a.aid not in payments
                    and a.parent_id is not None
                    and a.aid not in parents
                    and AccountService.root_name(a, by_id) in ("Assets", "Liabilities")
                ):
                    candidates[a.aid] = a
                continue
            label = ":".join(self._path_with_root(a, by_id))
            if a.aid not in parents:
                in_budget.add(a.aid)
                budget_accounts.append(label)
            else:
                ignored.append(label)
        budget_accounts.sort()
        ignored.sort()

        touching: set[UUID] = set()
        postings = self.tr.posting_rows(through)
        for p in postings:
            if p.account in in_budget:
                touching.add(p.transaction)

        # Spending this month in transactions that touch no budget account: [value, accounts that paid].
        outside: dict[UUID, list] = {}
        for p in postings:
            if p.transaction in touching:
                continue
            if p.account in categories and first_of_month(p.date) == month:
                value = p.amount if p.side == PostingSide.DEBIT else -p.amount
                outside.setdefault(p.transaction, [ZERO, set()])[0] += value
        for p in postings:
            if p.transaction in outside and p.account in candidates:
                outside[p.transaction][1].add(p.account)

        goal_names = {g.gid: g for g in self.br.goals()}
        every_row = self.br.list()
        allocations = [row for row in every_row if row.month <= month]
        # Money assigned to later months is out of what can be assigned now.
        every_goal_row = [r for r in self.br.goal_allocations() if r.goal_id in goal_names]
        later = sum((row.amount for row in every_row if row.month > month and row.account_id in categories), ZERO)
        later += sum((row.amount for row in every_goal_row if row.month > month), ZERO)
        previous_month = first_of_month(month - timedelta(days=1))
        assigned_here = {row.account_id for row in allocations if row.month == month}
        copyable = sum(
            (
                row.amount
                for row in allocations
                if row.month == previous_month and row.account_id in categories and row.account_id not in assigned_here
                and categories[row.account_id].closed_on is None
            ),
            ZERO,
        )
        goal_here = {row.goal_id for row in every_goal_row if row.month == month}
        copyable += sum(
            (row.amount for row in every_goal_row if row.month == previous_month and row.amount > 0 and row.goal_id not in goal_here),
            ZERO,
        )
        # Budgeting starts with the first month anything was assigned: earlier spending already left the
        # accounts that cash is counted from, and must not show up as overspending.
        start = min([row.month for row in allocations] + [row.month for row in every_goal_row if row.month <= month], default=month)

        liabilities = {
            aid for aid in in_budget if AccountService.root_name(by_id[aid], by_id) == "Liabilities"
        }
        # Per card: [balance (debits - credits) to the month's end, charged this month, paid this month].
        card_books: dict[UUID, list[Decimal]] = {aid: [ZERO, ZERO, ZERO] for aid in liabilities}

        cash = ZERO
        # What happened to each category in each month: [assigned, spent].
        by_category: dict[UUID, dict[date, list[Decimal]]] = {}
        for p in postings:
            if p.account in in_budget:
                cash += p.amount if p.side == PostingSide.DEBIT else -p.amount
                if p.account in liabilities:
                    book_ = card_books[p.account]
                    book_[0] += p.amount if p.side == PostingSide.DEBIT else -p.amount
                    if first_of_month(p.date) == month:
                        book_[2 if p.side == PostingSide.DEBIT else 1] += p.amount
            # Spending is what is posted to a category, and what is paid into an account that has one.
            target = p.account if p.account in categories else (payments.get(p.account) if p.side == PostingSide.DEBIT else None)
            if target is not None and p.transaction in touching:
                if first_of_month(p.date) < start:
                    continue
                value = p.amount if p.side == PostingSide.DEBIT else -p.amount
                figures = by_category.setdefault(target, {}).setdefault(first_of_month(p.date), [ZERO, ZERO])
                figures[1] += value
        for row in allocations:
            if row.account_id in categories:
                by_category.setdefault(row.account_id, {}).setdefault(row.month, [ZERO, ZERO])[0] += row.amount

        previous = first_of_month(month - timedelta(days=1))
        own: dict[UUID, tuple[Decimal, Decimal, Decimal, Decimal]] = {}
        for aid in categories:
            own[aid] = self._roll(by_category.get(aid, {}), month, previous)
        total_assigned = sum((v[0] for v in own.values()), ZERO)
        total_activity = sum((v[1] for v in own.values()), ZERO)
        total_available = sum((v[2] for v in own.values()), ZERO)
        total_overspent = sum((v[3] for v in own.values()), ZERO)
        # Goals are money set aside for something, not money to spend: they are out of Left to spend, and what is saved in
        # them still counts against ready_to_assign.
        goals = self._goal_lines(list(goal_names.values()), every_goal_row, month, currency.decimals)
        goal_assigned = sum((g.assigned for g in goals), ZERO)
        goal_available = sum((g.available for g in goals), ZERO)

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

        cards = sorted(
            (
                BudgetCard(
                    aid=aid, path=":".join(self._path_with_root(by_id[aid], by_id)),
                    owed=max(ZERO, -balance), charged=charged, paid=paid,
                )
                for aid, (balance, charged, paid) in card_books.items()
            ),
            key=lambda c: c.path,
        )
        reserved = sum((c.owed for c in cards), ZERO)

        lines = self._lines(categories, by_id, parents, own)
        read = BudgetRead(
            month=month,
            currency=currency.code,
            ready_to_assign=cash - total_available - goal_available - later,
            assigned_to_later_months=later,
            copyable=copyable,
            cash=cash,
            assigned=total_assigned,
            activity=total_activity,
            available=total_available,
            overspent_last_month=total_overspent,
            goals=goals,
            goal_assigned=goal_assigned,
            goal_available=goal_available,
            goal_underfunded=sum((g.underfunded for g in goals), ZERO),
            money_in_accounts=cash + reserved,
            reserved_for_cards=reserved,
            cards=cards,
            left_out=left_out_total,
            left_out_accounts=left_out_accounts,
            budget_accounts=budget_accounts,
            ignored_accounts=ignored,
            lines=lines,
        )
        return read, own

    def _goal_lines(self, goals: list[Goal], rows, month: date, decimals: int) -> list[GoalLine]:
        """The goals, the soonest due first, with what is saved up to the month's end and what the month asks of each."""
        lines = []
        for goal in goals:
            mine = [r for r in rows if r.goal_id == goal.gid and r.month <= month]
            assigned = sum((r.amount for r in mine if r.month == month), ZERO)
            saved = sum((r.amount for r in mine), ZERO)
            needed, missing = funding(goal.amount, goal.target_date, saved - assigned, assigned, month, decimals)
            lines.append(
                GoalLine(
                    gid=goal.gid, name=goal.name, amount=goal.amount, target_date=goal.target_date,
                    assigned=assigned, available=saved, needed=needed, underfunded=missing,
                    overdue=is_overdue(goal.target_date, month, missing),
                )
            )
        return sorted(lines, key=lambda g: (g.target_date, g.name.lower()))

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
        """The categories as a tree in display order: a group row (sums) before its subcategories;
        a group that was itself posted to or assigned money also gets an '(other)' row of its own."""
        children: dict[UUID | None, list[Account]] = {}
        for a in categories.values():
            children.setdefault(a.parent_id, []).append(a)
        for kids in children.values():
            kids.sort(key=AccountService.order_key)
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

        def line(account: Account, name: str, depth: int, figures, group: bool = False) -> BudgetLine:
            a, s, v, o = figures
            return BudgetLine(
                aid=account.aid, name=name, path=":".join(self._path(account, by_id)), depth=depth, group=group,
                assigned=a, activity=s, available=v, overspent_last_month=o,
            )

        lines: list[BudgetLine] = []

        def walk(account: Account, depth: int) -> None:
            kids = [k for k in children.get(account.aid, []) if visible(k)]
            if not kids:
                lines.append(line(account, account.name, depth, own[account.aid]))
                return
            lines.append(line(account, account.name, depth, total(account), group=True))
            if any(own[account.aid]):
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
        currency = self.accounts.currency()
        if decimal_places(amount) > currency.decimals:
            raise BudgetError(f"{currency.code} amounts can have at most {currency.decimals} decimal places!")

    def include_account(self, aid: UUID) -> None:
        """Make an account part of the budget (its money and its spending count from now on)."""
        try:
            if self.accounts.update(aid, AccountUpdate(on_budget=True)) is None:
                raise BudgetError("account not found!")
        except ValueError as e:
            raise BudgetError(str(e))

    def goal_share(self, amount: Decimal, by: date) -> tuple[Decimal, int]:
        """What a goal of `amount` needed by the month `by` asks of each month if it starts now: (the share, the months it
        is spread over, this one included). The same rule as the plan uses, so what the form promises is what it will ask."""
        if amount <= 0:
            raise BudgetError("the goal amount must be positive!")
        self._check_amount(amount)
        month, due = month_start(None), month_start(by)
        if due <= month:
            raise BudgetError("choose a month after this one!")
        share, _ = funding(amount, due, ZERO, ZERO, month, self.accounts.currency().decimals)
        return share, months_between(month, due) + 1

    def _goal_name(self, name: str, own: UUID | None = None) -> str:
        name = " ".join((name or "").split())
        if not name:
            raise BudgetError("say what the goal is for!")
        if len(name) > 80:
            raise BudgetError("a goal's name can be at most 80 characters!")
        if any(g.name.lower() == name.lower() and g.gid != own for g in self.br.goals()):
            raise BudgetError(f"you already have a goal called '{name}'!")
        return name

    def create_goal(self, name: str, amount: Decimal, by: date, assign_now: bool) -> BudgetRead:
        """A goal is money to save by a month: made in one step, and this month's share set aside when asked."""
        share, _ = self.goal_share(amount, by)
        name = self._goal_name(name)
        month = month_start(None)
        goal = self.br.add_goal(name, amount, month_start(by))
        if assign_now:
            self.br.set_goal(month, goal.gid, share)
        self.br.db.commit()
        return self.view(month)

    def _goal(self, gid: UUID) -> Goal:
        goal = self.br.goal(gid)
        if goal is None:
            raise BudgetError("goal not found!")
        return goal

    def update_goal(self, gid: UUID, name: str, amount: Decimal, by: date) -> BudgetRead:
        """Change a goal's name, amount or month."""
        goal = self._goal(gid)
        self.goal_share(amount, by)
        goal.name = self._goal_name(name, own=gid)
        goal.amount = amount
        goal.target_date = month_start(by)
        self.br.save_goal(goal)
        self.br.db.commit()
        return self.view(None)

    def delete_goal(self, gid: UUID) -> None:
        """Remove a goal for good: what was saved in it goes back to Ready to assign."""
        self._goal(gid)
        self.br.delete_goal(gid)
        self.br.db.commit()

    def _check_saved(self, goal: Goal, month: date, new_amount: Decimal) -> None:
        """A goal never holds less than nothing: with `new_amount` as the month's figure, what is saved must stay at or above
        zero at the end of every month."""
        rows = {r.month: r.amount for r in self.br.goal_allocations() if r.goal_id == goal.gid}
        rows[month] = new_amount
        saved = ZERO
        for when in sorted(rows):
            saved += rows[when]
            if saved < 0:
                before = saved - rows[when]
                raise BudgetError(
                    f"only {max(before, ZERO):f} is saved in '{goal.name}' to take out by the end of {when:%B %Y}!"
                )

    def assign_goal(self, month: date | None, gid: UUID, amount: Decimal) -> BudgetRead:
        """Set what is set aside for a goal in a month (zero removes it; negative takes back what was saved before)."""
        month = month_start(month)
        goal = self._goal(gid)
        self._check_amount(amount)
        self._check_saved(goal, month, amount)
        self.br.set_goal(month, gid, amount)
        self.br.db.commit()
        return self.view(month)

    def use_goal(self, month: date | None, gid: UUID, aid: UUID, amount: Decimal) -> BudgetRead:
        """Hand money a goal saved to a category, in a month: the goal's money becomes that category's available money.
        Spending is recorded on the category as always; this is how the goal pays for it."""
        month = month_start(month)
        goal = self._goal(gid)
        self._category(aid)
        self._check_amount(amount)
        if amount <= 0:
            raise BudgetError("the amount must be positive!")
        saved = sum((r.amount for r in self.br.goal_allocations() if r.goal_id == gid and r.month <= month_end(month)), ZERO)
        if amount > saved:
            raise BudgetError(f"only {max(saved, ZERO):f} is saved in '{goal.name}'!")
        taken = self.br.goal_assigned(month, gid) - amount
        self._check_saved(goal, month, taken)
        self.br.set_goal(month, gid, taken)
        self.br.set(month, aid, self.assigned(month, aid) + amount)
        self.br.db.commit()
        return self.view(month)

    def assigned(self, month: date, aid: UUID) -> Decimal:
        row = self.br.read(month, aid)
        return row.amount if row else ZERO

    def assign(self, month: date | None, aid: UUID, amount: Decimal) -> BudgetRead:
        """Set what a category gets in a month (0 removes it)."""
        month = month_start(month)
        self._category(aid)
        if amount < 0:
            # A month's amount may be negative to take back what an earlier month left in the category (that is what
            # Move money writes too), but never more than the category has left: past that it would show as overspent
            # with nothing spent and make Ready to assign larger than the money there is.
            available = self._compute(month)[1][aid][2]
            taken = self.assigned(month, aid) - amount
            if taken > available:
                name = self.accounts.ar.read(aid).name
                raise BudgetError(
                    f"only {max(available, ZERO):f} is available in '{name}' to take out: assign at least "
                    f"{self.assigned(month, aid) - max(available, ZERO):f}!"
                )
        self._check_amount(amount)
        self.br.set(month, aid, amount)
        self.br.db.commit()
        return self.view(month)

    def group_minimum(self, month: date | None, aid: UUID, data: BudgetRead | None = None) -> Decimal:
        """The least a group can be given in a month: what its subcategories were given add up to."""
        data = data or self.view(month)
        group = next((l for l in data.lines if l.aid == aid and l.group), None)
        if group is None:
            raise BudgetError("only a category with subcategories has a budget of its own!")
        prefix = f"{group.path}:"
        return sum(
            (l.assigned for l in data.lines if l.path.startswith(prefix) and not l.group and not l.name.endswith("(other)")),
            ZERO,
        )

    def assign_group(self, month: date | None, aid: UUID, total: Decimal) -> BudgetRead:
        """Set a group's budget for a month. It starts at what its subcategories add up to and may be more (the rest is
        the group's own money, which the budget keeps on the group's own account); never less."""
        month = month_start(month)
        minimum = self.group_minimum(month, aid)
        if total < minimum:
            raise BudgetError(f"minimum {minimum:f}")
        return self.assign(month, aid, total - minimum)

    def copy_previous(self, month: date | None) -> BudgetRead:
        """Assign this month what each category got last month, for the categories with nothing assigned yet."""
        month = month_start(month)
        previous = first_of_month(month - timedelta(days=1))
        categories = self._categories(self.accounts.ar.list())
        rows = self.br.list(up_to=month)
        have = {row.account_id for row in rows if row.month == month}
        wanted = [
            row for row in rows
            if row.month == previous and row.account_id in categories and row.account_id not in have
            and categories[row.account_id].closed_on is None
        ]
        goal_rows = [r for r in self.br.goal_allocations(up_to=month) if r.goal_id in {g.gid for g in self.br.goals()}]
        goal_have = {r.goal_id for r in goal_rows if r.month == month}
        goal_wanted = [r for r in goal_rows if r.month == previous and r.amount > 0 and r.goal_id not in goal_have]
        if not wanted and not goal_wanted:
            raise BudgetError(
                "last month has nothing assigned to copy!"
                if not any(row.month == previous for row in [*rows, *goal_rows])
                else "everything last month had is already assigned this month!"
            )
        for row in wanted:
            self.br.set(month, row.account_id, row.amount)
        for row in goal_wanted:
            self.br.set_goal(month, row.goal_id, row.amount)
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

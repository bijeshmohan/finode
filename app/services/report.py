import calendar
from datetime import date
from decimal import Decimal

from ..models.transaction import PostingSide
from ..repositories import TransactionRepository
from ..schemas.report import (
    BreakdownLine,
    BreakdownRead,
    MonthLine,
    MonthReportRead,
    MonthTotals,
    SummaryRead,
    TrialBalanceLine,
    TrialBalanceRead,
)
from .account import AccountService
from ..clock import local_today


def _shift(month: date, by: int) -> date:
    index = month.year * 12 + month.month - 1 + by
    return date(index // 12, index % 12 + 1, 1)


class ReportService:
    def __init__(self, accounts: AccountService, tr: TransactionRepository):
        self.accounts = accounts
        self.tr = tr

    def summary(
        self,
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> SummaryRead:
        """Net worth as of now plus income and expenses for a period.

        The period defaults to the current month so far.
        """
        today = local_today()
        period_start = period_start or today.replace(day=1)
        period_end = period_end or today
        if period_start > period_end:
            raise ValueError("period start must not be after period end!")

        accounts = self.accounts.list()
        roots = {a.name: a for a in accounts if a.parent_id is None}
        assets = roots["Assets"].balance
        liabilities = roots["Liabilities"].balance

        income = self._period_total("Income", PostingSide.CREDIT, roots, period_start, period_end)
        expenses = self._period_total("Expenses", PostingSide.DEBIT, roots, period_start, period_end)

        return SummaryRead(
            currency=self.accounts.currency().code,
            period_start=period_start,
            period_end=period_end,
            assets=assets,
            liabilities=liabilities,
            net_worth=assets - liabilities,
            income=income,
            expenses=expenses,
            net_income=income - expenses,
        )

    def _period_total(self, root_name, normal_side, roots, period_start, period_end) -> Decimal:
        subtree = self.accounts.subtree_ids(roots[root_name].aid)
        total = Decimal("0.00")
        for posting in self.tr.postings_for_accounts(subtree, period_start, period_end):
            total += posting.amount if posting.side == normal_side else -posting.amount
        return total

    TREND_MONTHS = 6

    def month_report(self, month: date | None = None) -> MonthReportRead:
        """A month's income and spending, per top-level account and against the month before, with the
        last six months' totals. The current month counts up to today."""
        today = local_today()
        month = (month or today).replace(day=1)
        if month > today.replace(day=1):
            raise ValueError("that month has not started yet!")
        first = _shift(month, -(self.TREND_MONTHS - 1))
        last_day = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
        end = min(last_day, today)
        previous = _shift(month, -1)

        currency = self.accounts.currency()
        accounts = {a.aid: a for a in self.accounts.list()}
        by_month: dict[str, dict[date, Decimal]] = {"Income": {}, "Expenses": {}}
        by_group: dict[str, dict[date, dict[str, Decimal]]] = {"Income": {}, "Expenses": {}}
        for root_name, normal_side in (("Income", PostingSide.CREDIT), ("Expenses", PostingSide.DEBIT)):
            root = next(a for a in accounts.values() if a.parent_id is None and a.name == root_name)
            transactions = {t.tid: t for t in self.tr.list(date_from=first, date_to=end)}
            for posting in self.tr.postings_for_accounts(self.accounts.subtree_ids(root.aid), first, end):
                value = posting.amount if posting.side == normal_side else -posting.amount
                transaction = transactions[posting.transaction]
                when = transaction.date.replace(day=1)
                by_month[root_name][when] = by_month[root_name].get(when, Decimal("0.00")) + value
                if when in (month, previous):
                    top = posting.account
                    while accounts[top].parent_id is not None and accounts[accounts[top].parent_id].parent_id is not None:
                        top = accounts[top].parent_id
                    groups = by_group[root_name].setdefault(when, {})
                    groups[accounts[top].name] = groups.get(accounts[top].name, Decimal("0.00")) + value

        zero = Decimal("0.00")
        income, expenses = by_month["Income"].get(month, zero), by_month["Expenses"].get(month, zero)

        def lines(root_name: str, total: Decimal) -> list[MonthLine]:
            now, before = by_group[root_name].get(month, {}), by_group[root_name].get(previous, {})
            out = [
                MonthLine(
                    account=name,
                    amount=amount,
                    previous=before.get(name, zero),
                    share=(amount / total * 100).quantize(Decimal("0.1")) if total > 0 else Decimal("0.0"),
                )
                for name, amount in now.items()
                if amount != 0
            ]
            return sorted(out, key=lambda line: (-line.amount, line.account))

        trend = []
        for i in range(self.TREND_MONTHS):
            m = _shift(first, i)
            i_, e_ = by_month["Income"].get(m, zero), by_month["Expenses"].get(m, zero)
            trend.append(MonthTotals(month=m, income=i_, expenses=e_, net=i_ - e_))
        return MonthReportRead(
            month=month,
            period_end=end,
            currency=currency.code,
            income=income,
            expenses=expenses,
            net=income - expenses,
            savings_rate=((income - expenses) / income * 100).quantize(Decimal("0.1")) if income > 0 else None,
            previous_income=by_month["Income"].get(previous, zero),
            previous_expenses=by_month["Expenses"].get(previous, zero),
            spending=lines("Expenses", expenses),
            earnings=lines("Income", income),
            trend=trend,
        )

    def account_totals(self, root_name: str, period_start: date, period_end: date) -> dict:
        """What each account under Income or Expenses took in a period (what was posted to the account itself:
        a group's own postings, not its sub-accounts')."""
        if root_name not in ("Income", "Expenses"):
            raise ValueError("a breakdown is of Income or Expenses!")
        accounts = {a.aid: a for a in self.accounts.list()}
        root = next(a for a in accounts.values() if a.parent_id is None and a.name == root_name)
        normal_side = PostingSide.CREDIT if root_name == "Income" else PostingSide.DEBIT
        totals: dict = {}
        for posting in self.tr.postings_for_accounts(self.accounts.subtree_ids(root.aid), period_start, period_end):
            value = posting.amount if posting.side == normal_side else -posting.amount
            totals[posting.account] = totals.get(posting.account, Decimal("0.00")) + value
        return totals

    def breakdown(
        self,
        root_name: str,
        period_start: date | None = None,
        period_end: date | None = None,
        depth: int = 1,
    ) -> BreakdownRead:
        """Income or expenses for a period per account, `depth` levels below the top-level account.

        Postings to deeper accounts count towards their ancestor at `depth`.
        """
        if root_name not in ("Income", "Expenses"):
            raise ValueError("a breakdown is of Income or Expenses!")
        if depth < 1:
            raise ValueError("depth must be at least 1!")
        today = local_today()
        period_start = period_start or today.replace(day=1)
        period_end = period_end or today
        if period_start > period_end:
            raise ValueError("period start must not be after period end!")

        accounts = {a.aid: a for a in self.accounts.list()}

        def group_of(aid) -> str:
            chain = []
            current = accounts[aid]
            while current.parent_id is not None:
                chain.append(current.name)
                current = accounts[current.parent_id]
            chain.reverse()
            return " › ".join(chain[:depth])

        own = self.account_totals(root_name, period_start, period_end)
        totals: dict[str, Decimal] = {}
        for aid, value in own.items():
            key = group_of(aid)
            totals[key] = totals.get(key, Decimal("0.00")) + value

        lines = [BreakdownLine(account=k, amount=v) for k, v in totals.items() if v != 0]
        lines.sort(key=lambda line: (-line.amount, line.account))
        return BreakdownRead(
            root=root_name,
            currency=self.accounts.currency().code,
            period_start=period_start,
            period_end=period_end,
            total=sum((line.amount for line in lines), Decimal("0.00")),
            lines=lines,
        )

    def trial_balance(self, as_of: date | None = None) -> TrialBalanceRead:
        """Every account's debits and credits up to a day, and a check that the books are sound.

        The check looks at each transaction on its own, so a problem is named rather than hidden in a total.
        """
        as_of = as_of or local_today()
        accounts = {a.aid: a for a in self.accounts.ar.list()}
        paths: dict = {}

        def path_of(aid) -> str:
            if aid not in paths:
                account = accounts.get(aid)
                chain, seen = [], set()
                while account is not None and account.aid not in seen:
                    seen.add(account.aid)
                    chain.append(account.name)
                    account = accounts.get(account.parent_id) if account.parent_id else None
                paths[aid] = ":".join(reversed(chain)) if chain else str(aid)
            return paths[aid]

        transactions = {t.tid: t for t in self.tr.list(date_to=as_of)}
        by_transaction: dict = {}
        for posting in self.tr.all_postings():
            if posting.transaction in transactions:
                by_transaction.setdefault(posting.transaction, []).append(posting)

        problems: list[str] = []
        lines: dict = {}
        total_debit = total_credit = Decimal("0.00")
        for tid, transaction in transactions.items():
            postings = by_transaction.get(tid, [])
            label = f"transaction {tid} ({transaction.date})"
            if len(postings) < 2:
                problems.append(f"{label} has {len(postings)} posting{'' if len(postings) == 1 else 's'}, at least two are needed")
            debit = credit = Decimal(0)
            for posting in postings:
                account = accounts.get(posting.account)
                if account is None:
                    problems.append(f"{label} posts to an account that does not exist or is not yours")
                    continue
                if account.parent_id is None:
                    problems.append(f"{label} posts to the root account '{account.name}'")
                if posting.amount <= 0:
                    problems.append(f"{label} has a posting that is not positive")
                line = lines.setdefault(account.aid, [Decimal(0), Decimal(0)])
                if posting.side == PostingSide.DEBIT:
                    debit += posting.amount
                    line[0] += posting.amount
                else:
                    credit += posting.amount
                    line[1] += posting.amount
            if debit != credit:
                problems.append(f"{label} does not balance (debits {debit:f}, credits {credit:f})")
            total_debit += debit
            total_credit += credit

        result_lines = [
            TrialBalanceLine(account=path_of(aid), debit=debit, credit=credit) for aid, (debit, credit) in lines.items()
        ]
        result_lines.sort(key=lambda line: line.account)
        return TrialBalanceRead(
            as_of=as_of,
            balanced=not problems and total_debit == total_credit,
            currency=self.accounts.currency().code,
            lines=result_lines,
            debit=total_debit,
            credit=total_credit,
            problems=problems,
        )

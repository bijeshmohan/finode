"""Read-only reports computed from postings: summary, per-account breakdown, account totals and the trial balance that re-checks the books."""

from datetime import date
from decimal import Decimal

from ..models.transaction import PostingSide
from ..repositories import TransactionRepository
from ..schemas.report import (
    BreakdownLine,
    BreakdownRead,
    SummaryRead,
    TrialBalanceLine,
    TrialBalanceRead,
)
from .account import AccountService
from ..clock import local_today


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

        income, expenses = self._period_totals(roots, period_start, period_end)
        # Paying into a loan budgeted under a category spends that category: as on the Budget and the Categories page.
        expenses += sum(
            (p.amount for _, p in self.accounts.payments_into_loans(accounts, period_start, period_end)), Decimal("0.00")
        )

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

    def _period_totals(self, roots, period_start, period_end) -> tuple[Decimal, Decimal]:
        """(income, expenses) for a period from one query: what came in on the Income accounts and went out on the Expenses ones."""
        income_ids = set(self.accounts.subtree_ids(roots["Income"].aid))
        expense_ids = set(self.accounts.subtree_ids(roots["Expenses"].aid))
        income = expenses = Decimal("0.00")
        for posting in self.tr.postings_for_accounts(list(income_ids | expense_ids), period_start, period_end):
            if posting.account in income_ids:
                income += posting.amount if posting.side == PostingSide.CREDIT else -posting.amount
            else:
                expenses += posting.amount if posting.side == PostingSide.DEBIT else -posting.amount
        return income, expenses

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
        if root_name == "Expenses":
            # Paying into a loan budgeted under a category spends that category (as on the Budget).
            for category, posting in self.accounts.payments_into_loans(list(accounts.values()), period_start, period_end):
                totals[category] = totals.get(category, Decimal("0.00")) + posting.amount
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

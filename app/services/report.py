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
    TrialBalanceTotal,
)
from .account import AccountService


class ReportService:
    def __init__(self, accounts: AccountService, tr: TransactionRepository):
        self.accounts = accounts
        self.tr = tr
        self._unpriced = False

    def summary(
        self,
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> SummaryRead:
        """Net worth as of now plus income and expenses for a period.

        The period defaults to the current month so far.
        """
        today = date.today()
        period_start = period_start or today.replace(day=1)
        period_end = period_end or today
        if period_start > period_end:
            raise ValueError("period start must not be after period end!")

        accounts = self.accounts.list()
        roots = {a.name: a for a in accounts if a.parent_id is None}
        assets = roots["Assets"].balance
        liabilities = roots["Liabilities"].balance

        self._unpriced = roots["Assets"].unpriced or roots["Liabilities"].unpriced
        income = self._period_total("Income", PostingSide.CREDIT, roots, period_start, period_end)
        expenses = self._period_total("Expenses", PostingSide.DEBIT, roots, period_start, period_end)

        return SummaryRead(
            currency=self.accounts.default_currency().code,
            unpriced=self._unpriced,
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
        """Postings count at their value in the transaction's currency, converted to the default
        currency at the rate of the day. A posting no price can convert flags the summary as unpriced."""
        subtree = self.accounts.subtree_ids(roots[root_name].aid)
        default = self.accounts.default_currency()
        transactions = {t.tid: t for t in self.tr.list(date_from=period_start, date_to=period_end)}
        total = Decimal("0.00")
        for posting in self.tr.postings_for_accounts(subtree, period_start, period_end):
            value = posting.value if posting.side == normal_side else -posting.value
            transaction = transactions[posting.transaction]
            if transaction.currency_id != default.cid:
                value = self.accounts.prices.book().convert(
                    value, transaction.currency_id, default.cid, transaction.date, default.decimals
                )
                if value is None:
                    self._unpriced = True
                    continue
            total += value
        return total

    def breakdown(
        self,
        root_name: str,
        period_start: date | None = None,
        period_end: date | None = None,
        depth: int = 1,
    ) -> BreakdownRead:
        """Income or expenses for a period per account, `depth` levels below the top-level account.

        Amounts are in the default currency, converted like the summary's; postings to deeper
        accounts count towards their ancestor at `depth`.
        """
        if root_name not in ("Income", "Expenses"):
            raise ValueError("a breakdown is of Income or Expenses!")
        if depth < 1:
            raise ValueError("depth must be at least 1!")
        today = date.today()
        period_start = period_start or today.replace(day=1)
        period_end = period_end or today
        if period_start > period_end:
            raise ValueError("period start must not be after period end!")

        accounts = {a.aid: a for a in self.accounts.list()}
        root = next(a for a in accounts.values() if a.parent_id is None and a.name == root_name)
        normal_side = PostingSide.CREDIT if root_name == "Income" else PostingSide.DEBIT

        def group_of(aid) -> str:
            chain = []
            current = accounts[aid]
            while current.parent_id is not None:
                chain.append(current.name)
                current = accounts[current.parent_id]
            chain.reverse()
            return " › ".join(chain[:depth])

        default = self.accounts.default_currency()
        transactions = {t.tid: t for t in self.tr.list(date_from=period_start, date_to=period_end)}
        totals: dict[str, Decimal] = {}
        unpriced = False
        subtree = self.accounts.subtree_ids(root.aid)
        for posting in self.tr.postings_for_accounts(subtree, period_start, period_end):
            value = posting.value if posting.side == normal_side else -posting.value
            transaction = transactions[posting.transaction]
            if transaction.currency_id != default.cid:
                value = self.accounts.prices.book().convert(
                    value, transaction.currency_id, default.cid, transaction.date, default.decimals
                )
                if value is None:
                    unpriced = True
                    continue
            key = group_of(posting.account)
            totals[key] = totals.get(key, Decimal("0.00")) + value

        lines = [BreakdownLine(account=k, amount=v) for k, v in totals.items() if v != 0]
        lines.sort(key=lambda line: (-line.amount, line.account))
        return BreakdownRead(
            root=root_name,
            currency=default.code,
            unpriced=unpriced,
            period_start=period_start,
            period_end=period_end,
            total=sum((line.amount for line in lines), Decimal("0.00")),
            lines=lines,
        )

    def trial_balance(self, as_of: date | None = None) -> TrialBalanceRead:
        """Every account's debits and credits up to a day, and a check that the books are sound.

        The totals are per transaction currency, in each posting's `value`, because that is what
        debits and credits balance on. The check also looks at each transaction on its own, so a
        problem is named rather than hidden in a total.
        """
        as_of = as_of or date.today()
        accounts = {a.aid: a for a in self.accounts.ar.list()}
        catalog = self.accounts.catalog()
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
        totals: dict = {}
        for tid, transaction in transactions.items():
            postings = by_transaction.get(tid, [])
            currency = catalog[transaction.currency_id].code
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
                if posting.amount <= 0 or posting.value <= 0:
                    problems.append(f"{label} has a posting that is not positive")
                held = catalog[account.commodity_id].code if account.commodity_id else currency
                if account.commodity_id == transaction.currency_id and posting.value != posting.amount:
                    problems.append(f"{label}: '{path_of(account.aid)}' is in {currency} but its value differs from its amount")
                line = lines.setdefault(account.aid, [held, Decimal(0), Decimal(0)])
                if posting.side == PostingSide.DEBIT:
                    debit += posting.value
                    line[1] += posting.amount
                else:
                    credit += posting.value
                    line[2] += posting.amount
            if debit != credit:
                problems.append(f"{label} does not balance in {currency} (debits {debit:f}, credits {credit:f})")
            total = totals.setdefault(currency, [Decimal(0), Decimal(0)])
            total[0] += debit
            total[1] += credit

        result_lines = [
            TrialBalanceLine(account=path_of(aid), commodity=held, debit=debit, credit=credit)
            for aid, (held, debit, credit) in lines.items()
        ]
        result_lines.sort(key=lambda line: line.account)
        result_totals = [TrialBalanceTotal(currency=c, debit=d, credit=k) for c, (d, k) in sorted(totals.items())]
        return TrialBalanceRead(
            as_of=as_of,
            balanced=not problems and all(t.debit == t.credit for t in result_totals),
            lines=result_lines,
            totals=result_totals,
            problems=problems,
        )

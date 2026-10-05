from datetime import date
from decimal import Decimal

from ..models.transaction import PostingSide
from ..repositories import TransactionRepository
from ..schemas.report import SummaryRead
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

from datetime import date as Date
from decimal import Decimal

from pydantic import BaseModel, Field


class SummaryRead(BaseModel):
    # The currency every amount below is in.
    currency: str
    period_start: Date
    period_end: Date
    assets: Decimal
    liabilities: Decimal
    net_worth: Decimal
    income: Decimal
    expenses: Decimal
    net_income: Decimal


class BreakdownLine(BaseModel):
    # Account path below the top-level account, e.g. "Food › Groceries".
    account: str
    amount: Decimal


class BreakdownRead(BaseModel):
    # "Income" or "Expenses".
    root: str
    currency: str
    period_start: Date
    period_end: Date
    total: Decimal
    # Largest first.
    lines: list[BreakdownLine]


class TrialBalanceLine(BaseModel):
    # Account path, e.g. "Assets:Bank:HDFC".
    account: str
    debit: Decimal
    credit: Decimal


class TrialBalanceRead(BaseModel):
    as_of: Date
    # True when the totals agree and no problem was found.
    balanced: bool
    currency: str
    lines: list[TrialBalanceLine]
    debit: Decimal
    credit: Decimal
    # Plain-language findings, e.g. a transaction whose debits and credits differ. Empty when the books are sound.
    problems: list[str]


class MonthLine(BaseModel):
    # Account path below the top-level account, e.g. "Food", and what it came to in the month.
    account: str
    amount: Decimal
    # The same account the month before (zero when nothing was recorded), to see what moved.
    previous: Decimal
    # Its share of the month's total, in percent.
    share: Decimal = Field(decimal_places=1, max_digits=6)


class MonthTotals(BaseModel):
    month: Date
    income: Decimal
    expenses: Decimal
    net: Decimal


class MonthReportRead(BaseModel):
    """One month in a page: what came in, what went out, where, and the last few months for comparison."""

    # First day of the month; the current month counts up to today only.
    month: Date
    period_end: Date
    currency: str
    income: Decimal
    expenses: Decimal
    net: Decimal
    # net as a percentage of income; none when nothing came in.
    savings_rate: Decimal | None = Field(default=None, decimal_places=1, max_digits=6)
    previous_income: Decimal
    previous_expenses: Decimal
    # Largest first, per top-level account below Expenses / Income.
    spending: list[MonthLine]
    earnings: list[MonthLine]
    # The six months ending with this one, oldest first.
    trend: list[MonthTotals]

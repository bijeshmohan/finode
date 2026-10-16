from datetime import date as Date
from decimal import Decimal

from pydantic import BaseModel, Field


class SummaryRead(BaseModel):
    # The currency every amount below is in.
    currency: str
    period_start: Date
    period_end: Date
    assets: Decimal = Field(decimal_places=8, max_digits=24)
    liabilities: Decimal = Field(decimal_places=8, max_digits=24)
    net_worth: Decimal = Field(decimal_places=8, max_digits=24)
    income: Decimal = Field(decimal_places=8, max_digits=24)
    expenses: Decimal = Field(decimal_places=8, max_digits=24)
    net_income: Decimal = Field(decimal_places=8, max_digits=24)


class BreakdownLine(BaseModel):
    # Account path below the top-level account, e.g. "Food › Groceries".
    account: str
    amount: Decimal = Field(decimal_places=8, max_digits=24)


class BreakdownRead(BaseModel):
    # "Income" or "Expenses".
    root: str
    currency: str
    period_start: Date
    period_end: Date
    total: Decimal = Field(decimal_places=8, max_digits=24)
    # Largest first.
    lines: list[BreakdownLine]


class TrialBalanceLine(BaseModel):
    # Account path, e.g. "Assets:Bank:HDFC".
    account: str
    debit: Decimal = Field(decimal_places=8, max_digits=24)
    credit: Decimal = Field(decimal_places=8, max_digits=24)


class TrialBalanceRead(BaseModel):
    as_of: Date
    # True when the totals agree and no problem was found.
    balanced: bool
    currency: str
    lines: list[TrialBalanceLine]
    debit: Decimal = Field(decimal_places=8, max_digits=24)
    credit: Decimal = Field(decimal_places=8, max_digits=24)
    # Plain-language findings, e.g. a transaction whose debits and credits differ. Empty when the books are sound.
    problems: list[str]


class MonthLine(BaseModel):
    # Account path below the top-level account, e.g. "Food", and what it came to in the month.
    account: str
    amount: Decimal = Field(decimal_places=8, max_digits=24)
    # The same account the month before (zero when nothing was recorded), to see what moved.
    previous: Decimal = Field(decimal_places=8, max_digits=24)
    # Its share of the month's total, in percent.
    share: Decimal = Field(decimal_places=1, max_digits=6)


class MonthTotals(BaseModel):
    month: Date
    income: Decimal = Field(decimal_places=8, max_digits=24)
    expenses: Decimal = Field(decimal_places=8, max_digits=24)
    net: Decimal = Field(decimal_places=8, max_digits=24)


class MonthReportRead(BaseModel):
    """One month in a page: what came in, what went out, where, and the last few months for comparison."""

    # First day of the month; the current month counts up to today only.
    month: Date
    period_end: Date
    currency: str
    income: Decimal = Field(decimal_places=8, max_digits=24)
    expenses: Decimal = Field(decimal_places=8, max_digits=24)
    net: Decimal = Field(decimal_places=8, max_digits=24)
    # net as a percentage of income; none when nothing came in.
    savings_rate: Decimal | None = Field(default=None, decimal_places=1, max_digits=6)
    previous_income: Decimal = Field(decimal_places=8, max_digits=24)
    previous_expenses: Decimal = Field(decimal_places=8, max_digits=24)
    # Largest first, per top-level account below Expenses / Income.
    spending: list[MonthLine]
    earnings: list[MonthLine]
    # The six months ending with this one, oldest first.
    trend: list[MonthTotals]

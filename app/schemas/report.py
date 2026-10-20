from datetime import date as Date
from decimal import Decimal

from pydantic import BaseModel


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

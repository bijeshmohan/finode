"""What the reports return: the summary, the breakdown and the trial balance."""

from datetime import date as Date
from decimal import Decimal

from pydantic import BaseModel


class SummaryRead(BaseModel):
    # The currency every amount below is in.
    currency: str
    period_start: Date
    period_end: Date
    # Money in the Bank Account, Cash and Prepaid Wallet accounts less what is owed on the Credit Cards, now.
    cash_on_hand: Decimal
    income: Decimal
    # What the books call expenses: money that went out on the Expenses accounts (paying into a loan is not one).
    expenses: Decimal
    # What the budget calls spending: everything labelled with a spending category, a payment into a loan included.
    spent: Decimal
    net_income: Decimal


class BreakdownLine(BaseModel):
    # The category's name, e.g. "Groceries".
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

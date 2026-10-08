from datetime import date as Date
from decimal import Decimal

from pydantic import BaseModel, Field


class SummaryRead(BaseModel):
    # The default currency every amount below is in.
    currency: str
    # True when something could not be valued because no price links it to the currency.
    unpriced: bool = False
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
    unpriced: bool = False
    period_start: Date
    period_end: Date
    total: Decimal = Field(decimal_places=8, max_digits=24)
    # Largest first.
    lines: list[BreakdownLine]


class TrialBalanceLine(BaseModel):
    # Account path, e.g. "Assets:Bank:HDFC", and the commodity its amounts are in.
    account: str
    commodity: str
    debit: Decimal = Field(decimal_places=8, max_digits=24)
    credit: Decimal = Field(decimal_places=8, max_digits=24)


class TrialBalanceTotal(BaseModel):
    # Every posting is worth something in its transaction's currency; debits and credits must match there.
    currency: str
    debit: Decimal = Field(decimal_places=8, max_digits=24)
    credit: Decimal = Field(decimal_places=8, max_digits=24)


class TrialBalanceRead(BaseModel):
    as_of: Date
    # True when the totals agree in every currency and no problem was found.
    balanced: bool
    lines: list[TrialBalanceLine]
    totals: list[TrialBalanceTotal]
    # Plain-language findings, e.g. a transaction whose debits and credits differ. Empty when the books are sound.
    problems: list[str]

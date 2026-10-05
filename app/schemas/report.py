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

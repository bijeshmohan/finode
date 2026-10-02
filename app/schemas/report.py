from datetime import date as Date
from decimal import Decimal

from pydantic import BaseModel, Field


class SummaryRead(BaseModel):
    period_start: Date
    period_end: Date
    assets: Decimal = Field(decimal_places=2, max_digits=12)
    liabilities: Decimal = Field(decimal_places=2, max_digits=12)
    net_worth: Decimal = Field(decimal_places=2, max_digits=12)
    income: Decimal = Field(decimal_places=2, max_digits=12)
    expenses: Decimal = Field(decimal_places=2, max_digits=12)
    net_income: Decimal = Field(decimal_places=2, max_digits=12)

"""A calendar day finode accepts (see clock.FIRST_DAY and LAST_DAY)."""

from datetime import date
from typing import Annotated

from pydantic import AfterValidator

from ..clock import FIRST_DAY, LAST_DAY


def _within_span(day: date) -> date:
    if not FIRST_DAY <= day <= LAST_DAY:
        raise ValueError(f"the date must be between {FIRST_DAY:%d %b %Y} and {LAST_DAY:%d %b %Y}!")
    return day


Day = Annotated[date, AfterValidator(_within_span)]

"""How amounts are written, in one case file (tests/format_cases.json) the app's tests read too (frontend/src/lib):
the few sentences the server words itself (finode/formatting.py) write a number as the app does. The file's date and
amount-with-currency cases are the app's alone (lib/dates.ts, lib/money.ts)."""

import json
from decimal import Decimal

import pytest

from finode import formatting
from tests.paths import BACKEND

CASES = json.loads((BACKEND / "tests" / "format_cases.json").read_text())


@pytest.mark.parametrize(("value", "grouping", "expected"), CASES["money"])
def test_money(value: str, grouping: str, expected: str):
    assert formatting.money(Decimal(value), style=grouping) == expected

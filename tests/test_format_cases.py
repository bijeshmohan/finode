"""How amounts and days are written, in one case file (tests/format_cases.json) that the React app's tests read too
(frontend/src/lib): the two UIs cannot write a number or a date differently."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app import templating

CASES = json.loads((Path(__file__).parent / "format_cases.json").read_text())


@pytest.mark.parametrize(("value", "grouping", "expected"), CASES["money"])
def test_money(value: str, grouping: str, expected: str):
    assert templating.money(Decimal(value), style=grouping) == expected


@pytest.mark.parametrize(("text", "code", "expected"), CASES["amount"])
def test_amount(text: str, code: str | None, expected: str):
    assert templating.amount(text, code) == expected


@pytest.mark.parametrize("kind", ["friendly_date", "short_date", "date_chip"])
def test_dates(kind: str, monkeypatch: pytest.MonkeyPatch):
    write = getattr(templating, kind)
    for day, today, expected in CASES[kind]:
        monkeypatch.setattr(templating, "local_today", lambda today=today: date.fromisoformat(today))
        assert write(date.fromisoformat(day)) == expected, (kind, day, today)

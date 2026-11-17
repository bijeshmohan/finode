"""An account's page reads only its newest entries; "Load more" fetches the next chunk without splitting a day."""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import event

from app.clock import local_today
from app.services.account import REGISTER_PAGE

from .books import post_account
from .svc import plain, services


@pytest.fixture
def busy(client, root_accounts):
    """A bank account with many entries over many days (three on some days), and what it was spent on."""
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "10000"}).json()["id"]
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()["id"]
    made = []
    for i in range(80):
        day = local_today() - timedelta(days=1 + i // 3)  # three entries a day
        r = client.post(
            "/api/transactions/",
            json={
                "date": str(day),
                "payee": f"Shop {i:02d}",
                "postings": [
                    {"category_id": food, "side": "debit", "amount": "10"},
                    {"account_id": bank, "side": "credit", "amount": "10"},
                ],
            },
        )
        assert r.status_code == 201
        made.append((r.json()["id"], str(day), f"Shop {i:02d}"))
    return bank, food, made


def page(client, bank, offset=0):
    answer = client.get(f"/api/views/accounts/{bank}", params={"offset": offset} if offset else {})
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_the_page_shows_only_the_newest_entries_and_more_to_load(client, busy):
    bank, _, _made = busy
    first = page(client, bank)
    shown = {r["title"] for r in first["entries"]}
    assert REGISTER_PAGE <= len(shown) <= REGISTER_PAGE + 2, "a chunk, finished to the end of its day"
    assert "Shop 00" in shown and "Shop 79" not in shown, "the newest are there, the oldest are not"
    assert first["has_more"] is True and first["next_offset"]


def test_a_day_is_never_split_between_chunks(client, busy):
    bank, _, made = busy
    first = {r["title"] for r in page(client, bank)["entries"]}
    by_day = {}
    for _, day, name in made:
        by_day.setdefault(day, []).append(name)
    for day, names in by_day.items():
        present = [n in first for n in names]
        assert all(present) or not any(present), f"{day} is split: {present}"


def test_the_running_balance_is_the_same_as_the_full_register(client, busy, session):
    bank, _, _ = busy
    full = {e["payee"]: e for e in plain(services(session).accounts.register(UUID(bank)))}
    rows = [r for r in page(client, bank)["entries"] if r["title"] in full]
    assert len(rows) >= REGISTER_PAGE
    for row in rows:
        assert Decimal(row["balance"]) == Decimal(str(full[row["title"]]["balance"])), row["title"]


def test_entries_dated_ahead_still_all_show_in_their_card(client, busy):
    bank, food, _ = busy
    for i in range(3):
        client.post(
            "/api/transactions/",
            json={
                "date": str(local_today() + timedelta(days=5 + i)),
                "payee": f"Later {i}",
                "postings": [
                    {"category_id": food, "side": "debit", "amount": "5"},
                    {"account_id": bank, "side": "credit", "amount": "5"},
                ],
            },
        )
    assert sorted(u["title"] for u in page(client, bank)["upcoming"]) == ["Later 0", "Later 1", "Later 2"]


def test_a_small_account_has_nothing_more_to_load(client, root_accounts):
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "10"}).json()["id"]
    assert page(client, bank)["has_more"] is False


def test_the_database_is_not_read_in_full_for_the_page(client, busy, session):
    """The page asks for the payee and other accounts of a chunk, not of every entry it ever had."""
    bank, _, _ = busy
    seen = []
    engine = session.get_bind()
    watch = lambda conn, cursor, statement, params, context, many: seen.append((statement, params))
    event.listen(engine, "before_cursor_execute", watch)
    try:
        page(client, bank)
    finally:
        event.remove(engine, "before_cursor_execute", watch)
    wide = [
        s
        for s, params in seen
        if "transactions.payee" in s and "IN (" in s.upper() and len(params) > REGISTER_PAGE + 20
    ]
    assert not wide, "transactions were read for more entries than the page shows"

"""An account's page reads only its newest entries; "Show earlier" fetches the next chunk without splitting a day."""

from datetime import timedelta

import pytest
from sqlalchemy import event

from app.clock import local_today
from app.services.account import REGISTER_PAGE


@pytest.fixture
def busy(client, root_accounts):
    """A bank account with many entries over many days (three on some days), and what it was spent on."""
    bank = client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "10000"}).json()["aid"]
    food = client.post("/api/accounts/", json={"name": "Food", "parent_id": root_accounts["Expenses"]}).json()["aid"]
    made = []
    for i in range(80):
        day = local_today() - timedelta(days=1 + i // 3)  # three entries a day
        r = client.post("/api/transactions/", json={"date": str(day), "payee": f"Shop {i:02d}", "postings": [
            {"account": food, "side": "debit", "amount": "10"}, {"account": bank, "side": "credit", "amount": "10"}]})
        assert r.status_code == 201
        made.append((r.json()["tid"], str(day), f"Shop {i:02d}"))
    return bank, food, made


def test_the_page_shows_only_the_newest_entries_and_a_button(client, busy):
    bank, _, made = busy
    page = client.get(f"/accounts/{bank}").text
    shown = [name for _, _, name in made if name in page]
    assert REGISTER_PAGE <= len(shown) <= REGISTER_PAGE + 2, "a chunk, finished to the end of its day"
    assert "Shop 00" in page and "Shop 79" not in page, "the newest are there, the oldest are not"
    assert "Show earlier transactions" in page and f"/accounts/{bank}/more?offset=" in page


def test_a_day_is_never_split_between_chunks(client, busy):
    bank, _, made = busy
    first = client.get(f"/accounts/{bank}").text.split("<h2>Transactions</h2>", 1)[1]
    names_by_day = {}
    for _, day, name in made:
        names_by_day.setdefault(day, []).append(name)
    for day, names in names_by_day.items():
        present = [n in first for n in names]
        assert all(present) or not any(present), f"{day} is split: {present}"


def test_show_earlier_walks_back_to_the_start_without_repeats(client, busy):
    bank, _, made = busy
    seen = [n for _, _, n in made if n in client.get(f"/accounts/{bank}").text]
    page = client.get(f"/accounts/{bank}").text
    import re

    while "Show earlier transactions" in page:
        offset = int(re.search(r"/more\?offset=(\d+)", page).group(1))
        page = client.get(f"/accounts/{bank}/more?offset={offset}").text
        chunk = [n for _, _, n in made if n in page]
        assert chunk and not set(chunk) & set(seen), "no entry shows twice"
        seen += chunk
    assert sorted(seen) == sorted(n for _, _, n in made), "every entry came, once"


def test_the_running_balance_is_the_same_as_the_full_register(client, busy):
    from app.templating import money

    bank, _, made = busy
    full = {e["payee"]: e for e in client.get(f"/api/accounts/{bank}/register").json()}
    page = client.get(f"/accounts/{bank}").text
    checked = 0
    for _, _, name in made:
        if name not in page:
            continue
        row = page.split(name, 1)[1].split("</a>", 1)[0]
        assert f"<small>{money(full[name]['balance'])}</small>" in row, (name, full[name]["balance"])
        checked += 1
    assert checked >= REGISTER_PAGE


def test_entries_dated_ahead_still_all_show_in_their_card(client, busy):
    bank, food, _ = busy
    for i in range(3):
        client.post("/api/transactions/", json={"date": str(local_today() + timedelta(days=5 + i)), "payee": f"Later {i}", "postings": [
            {"account": food, "side": "debit", "amount": "5"}, {"account": bank, "side": "credit", "amount": "5"}]})
    page = client.get(f"/accounts/{bank}").text
    assert "3 upcoming" in page and all(f"Later {i}" in page for i in range(3))


def test_a_small_account_has_no_button(client, root_accounts):
    bank = client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "10"}).json()["aid"]
    assert "Show earlier" not in client.get(f"/accounts/{bank}").text


def test_the_database_is_not_read_in_full_for_the_page(client, busy, session):
    """The page asks for the payee and other accounts of a chunk, not of every entry it ever had."""
    bank, _, _ = busy
    seen = []
    engine = session.get_bind()
    watch = lambda conn, cursor, statement, params, context, many: seen.append((statement, params))
    event.listen(engine, "before_cursor_execute", watch)
    try:
        assert client.get(f"/accounts/{bank}").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", watch)
    wide = [s for s, params in seen if "transactions.payee" in s and "IN (" in s.upper() and len(params) > REGISTER_PAGE + 20]
    assert not wide, "transactions were read for more entries than the page shows"

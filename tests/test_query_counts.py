"""Pages must not ask the database once per account or once per row.

Every query costs a network round trip to the hosted database (about 16 ms), so a page that asks per account took
seconds. These tests count the statements a page runs and check the count does not grow with the size of the books.
"""

import json
from uuid import UUID

import pytest
from sqlalchemy import event

from app.auth import CurrentUser, require_authenticated_user
from app.main import app

PAGES = [
    "/transactions/new",
    "/transactions",
    "/api/views/transactions",
    "/",
    "/api/views/home",
    "/accounts",
    "/budget",
    "/categories",
    "/categories?tab=income",
]
# What each page asks today, with one to spare. The session remembers repeated reads (repositories/cache.py), which
# brought these down from 10 to 21 each; a page that climbs back has probably started loading something twice.
# /transactions and / read a chunk of the month, count what is left and, when a day runs over the chunk, finish the day (up to 3 more).
CEILING = {
    "/transactions/new": 4,  # + the categories
    "/transactions": 12,  # + the categories (their names for the rows) + the tags of the rows shown (one query, whatever the number of rows)
    "/api/views/transactions": 12,  # the Transactions page's own reads, for the finode app
    "/": 15,
    "/api/views/home": 15,  # Home's own reads, for the finode app  # + the categories (their own table) and what the month spent by category
    "/accounts": 5,  # + the day of each account's last entry, + the postings of the cards that have bill days (one query each, whatever the number)
    "/budget": 6,  # + the categories
    "/categories": 4,
    "/categories?tab=income": 4,
}

from .books import category, post_account  # noqa: E402
from .conftest import TEST_USER_ID  # noqa: E402


@pytest.fixture
def count_queries(session):
    engine = session.get_bind()
    counter = {"n": 0}

    def bump(*args, **kwargs):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", bump)

    def counted(get):
        counter["n"] = 0
        response = get()
        assert response.status_code == 200
        return counter["n"]

    yield counted
    event.remove(engine, "before_cursor_execute", bump)


def grow(client, root_accounts, accounts: int, transactions: int, start: int = 0):
    assets, expenses = [], []
    for i in range(start, start + accounts):
        parent = root_accounts["Assets" if i % 2 else "Expenses"]
        (assets if i % 2 else expenses).append(post_account(client, {"name": f"Acct{i}", "parent_id": parent}).json())
    for i in range(transactions):
        response = client.post(
            "/api/transactions/",
            json={
                "postings": [
                    {"category_id": expenses[i % len(expenses)]["id"], "side": "debit", "amount": "5"},
                    {"account_id": assets[i % len(assets)]["id"], "side": "credit", "amount": "5"},
                ]
            },
        )
        assert response.status_code == 201, response.text


def test_the_number_of_queries_does_not_grow_with_the_books(client, root_accounts, count_queries):
    grow(client, root_accounts, accounts=10, transactions=10)
    small = {p: count_queries(lambda p=p: client.get(p)) for p in PAGES}
    grow(client, root_accounts, accounts=40, transactions=40, start=10)
    large = {p: count_queries(lambda p=p: client.get(p)) for p in PAGES}
    for page in PAGES:
        assert large[page] <= small[page] + 2, (
            f"{page} asks the database more often as the books grow: {small[page]} -> {large[page]}"
        )
        assert large[page] <= CEILING[page], f"{page} makes {large[page]} queries"


def test_an_accounts_own_page_and_its_filtered_list_do_not_grow_either(client, root_accounts, count_queries):
    grow(client, root_accounts, accounts=6, transactions=6)
    busiest = client.get("/api/accounts/").json()[0]["id"]
    first = {
        "page": count_queries(lambda: client.get(f"/accounts/{busiest}")),
        "list": count_queries(lambda: client.get(f"/transactions?account={busiest}")),
    }
    grow(client, root_accounts, accounts=6, transactions=60, start=6)
    second = {
        "page": count_queries(lambda: client.get(f"/accounts/{busiest}")),
        "list": count_queries(lambda: client.get(f"/transactions?account={busiest}")),
    }
    assert second["page"] <= first["page"] + 2 and second["list"] <= first["list"] + 2, (first, second)


def test_saving_a_split_does_not_ask_more_as_it_gets_longer(client, root_accounts, count_queries):
    """Checking each posting's account used to cost two queries per row."""
    grow(client, root_accounts, accounts=14, transactions=0)
    accounts = client.get("/api/accounts/").json()
    assets = [a["id"] for a in accounts if a["parent_id"] == root_accounts["Assets"]]
    expenses = [c["id"] for c in client.get("/api/categories/").json()]

    def save(rows: int):
        data = {
            "account": [assets[0], *expenses[:rows]],
            "side": ["credit"] + ["debit"] * rows,
            "amount": [str(rows)] + ["1"] * rows,
            "payee": "split",
        }
        return count_queries(lambda: client.post("/transactions/split", data=data))

    short, long = save(2), save(7)
    assert long <= short + 1, (short, long)


def test_the_people_pages_do_not_ask_per_person_or_per_row(client, root_accounts, count_queries):
    grow(client, root_accounts, accounts=4, transactions=4)
    bank = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Acct1")

    def add_people(count: int, start: int) -> str:
        first = ""
        for i in range(start, start + count):
            who = client.post("/api/contacts/", json={"name": f"Person {i}"}).json()
            first = first or who["id"]
            client.post(
                f"/api/contacts/{who['id']}/transfers",
                json={"direction": "sent", "purpose": "loan", "amount": "5", "account_id": bank["id"]},
            )
        return first

    first = add_people(3, 0)
    pages = ["/people", f"/people/{first}", "/api/contacts/", f"/api/contacts/{first}/summary"]
    small = {p: count_queries(lambda p=p: client.get(p)) for p in pages}
    add_people(25, 3)
    large = {p: count_queries(lambda p=p: client.get(p)) for p in pages}
    for page in pages:
        assert large[page] <= small[page] + 1, f"{page} asks more as the people grow: {small[page]} -> {large[page]}"
        assert large[page] <= 25, f"{page} makes {large[page]} queries"


def test_one_persons_pages_do_not_ask_more_as_their_history_grows(client, root_accounts, count_queries):
    """Loans, shared bills and settlements with one person: their page and lists used to ask once per entry."""
    bank = post_account(client, {"name": "HDFC", "parent_id": root_accounts["Assets"], "balance": "1000000"}).json()
    dining = category(client, "Dining")
    alice = client.post("/api/contacts/", json={"name": "Alice"}).json()["id"]
    bob = client.post("/api/contacts/", json={"name": "Bob"}).json()["id"]

    def history(rounds: int) -> None:
        for _ in range(rounds):
            made = [
                client.post(
                    f"/api/contacts/{alice}/transfers",
                    json={"direction": "sent", "purpose": "loan", "amount": "100", "account_id": bank["id"]},
                ),
                client.post(
                    "/api/shared-expenses/",
                    params={"confirm": True},
                    json={
                        "description": "Dinner",
                        "total_amount": "90",
                        "category_id": dining["id"],
                        "participants": [{"is_self": True}, {"contact_id": alice}, {"contact_id": bob}],
                        "payments": [{"account_id": bank["id"], "amount": "90"}],
                    },
                ),
                client.post(
                    f"/api/contacts/{alice}/settlements",
                    json={"direction": "received", "amount": "60", "account_id": bank["id"]},
                ),
            ]
            assert [r.status_code for r in made] == [201, 201, 201], [r.text for r in made]

    pages = [
        f"/people/{alice}",
        f"/api/contacts/{alice}/summary",
        f"/api/contacts/{alice}/activity",
        f"/api/contacts/{alice}/obligations",
        f"/api/contacts/{alice}/transfers",
        f"/api/contacts/{alice}/settlements",
        "/api/shared-expenses/",
    ]
    history(2)
    small = {p: count_queries(lambda p=p: client.get(p)) for p in pages}
    history(8)
    large = {p: count_queries(lambda p=p: client.get(p)) for p in pages}
    for page in pages:
        assert large[page] <= small[page] + 1, f"{page} asks more as the history grows: {small[page]} -> {large[page]}"
        assert large[page] <= 25, f"{page} makes {large[page]} queries"


def test_paying_back_several_bills_at_once_does_not_read_once_per_bill(client, root_accounts, session):
    """One payment that clears your share of many bills a friend paid: what each bill was for is read together."""
    bank = post_account(client, {"name": "HDFC", "parent_id": root_accounts["Assets"], "balance": "1000000"}).json()
    dining = category(client, "Dining")
    reads = []

    def note(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)

    def pay_back(person: str, bills: int) -> int:
        who = client.post("/api/contacts/", json={"name": person}).json()["id"]
        for _ in range(bills):
            made = client.post(
                "/api/shared-expenses/",
                params={"confirm": True},
                json={
                    "description": "Dinner",
                    "total_amount": "60",
                    "category_id": dining["id"],
                    "participants": [{"is_self": True}, {"contact_id": who}],
                    "contributions": [{"contact_id": who, "amount": "60"}],
                },
            )
            assert made.status_code == 201, made.text
        reads.clear()
        event.listen(session.get_bind(), "before_cursor_execute", note)
        paid = client.post(
            f"/api/contacts/{who}/settlements",
            json={"direction": "sent", "amount": str(30 * bills), "account_id": bank["id"]},
        )
        event.remove(session.get_bind(), "before_cursor_execute", note)
        assert paid.status_code == 201, paid.text
        return len(reads)

    few, many = pay_back("Alice", 2), pay_back("Bob", 10)
    assert many <= few + 1, f"a payment reads more as it clears more bills: {few} -> {many}"
    line = next(l for l in client.get("/api/budget/").json()["lines"] if l["name"] == "Dining")
    assert float(line["activity"]) == 360, "every share paid back reached the budget"


def test_closing_a_group_does_not_read_once_per_account_inside_it(client, root_accounts, session):
    """Closing checks that nothing inside still holds money, now or later: the balances are read together."""
    reads = []

    def note(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)

    def close(group: str, members: int) -> int:
        parent = post_account(client, {"name": group, "parent_id": root_accounts["Assets"]}).json()
        for i in range(members):
            made = post_account(client, {"name": f"{group} {i}", "parent_id": parent["id"]})
            assert made.status_code == 201, made.text
        reads.clear()
        event.listen(session.get_bind(), "before_cursor_execute", note)
        closed = client.post(f"/api/accounts/{parent['id']}/close")
        event.remove(session.get_bind(), "before_cursor_execute", note)
        assert closed.status_code == 200, closed.text
        return len(reads)

    few, many = close("Old banks", 2), close("Old wallets", 9)
    assert many <= few, f"closing reads more as the group holds more accounts: {few} -> {many}"


def _statements(session, call) -> int:
    """How many statements of any kind a call makes; the call must succeed."""
    statements = []

    def note(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(session.get_bind(), "before_cursor_execute", note)
    try:
        response = call()
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", note)
    assert response.status_code < 300, response.text
    return len(statements)


def _selects(session, client, method: str, url: str, **kwargs) -> int:
    """How many SELECTs one request makes; the request must succeed."""
    reads = []

    def note(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)

    event.listen(session.get_bind(), "before_cursor_execute", note)
    try:
        response = client.request(method, url, **kwargs)
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", note)
    assert response.status_code < 300, response.text
    return len(reads)


def test_closing_a_category_group_does_not_read_once_per_category_inside_it(client, root_accounts, session):
    """Closing checks that no running recurring transaction records into the group: asked once for all of it."""

    def close(group: str, members: int) -> int:
        parent = category(client, group)
        for i in range(members):
            category(client, f"{group} {i}", parent=parent)
        return _selects(session, client, "POST", f"/api/categories/{parent['id']}/close")

    few, many = close("Old trips", 2), close("Old hobbies", 9)
    assert many <= few, f"closing reads more as the group holds more categories: {few} -> {many}"


def test_merging_accounts_does_not_read_once_per_recurring_transaction(client, root_accounts, session):
    """A merge checks no rule would end up with one account on both sides: the rules' rows are read together."""
    food = category(client, "Food")
    keep = post_account(client, {"name": "Keep", "parent_id": root_accounts["Assets"]}).json()

    def merge(name: str, rules: int) -> int:
        source = post_account(client, {"name": name, "parent_id": root_accounts["Assets"]}).json()
        for i in range(rules):
            made = client.post(
                "/api/recurring/",
                json={
                    "postings": [
                        {
                            "account_id": root_accounts["Expenses"],
                            "category_id": food["id"],
                            "side": "debit",
                            "amount": "10",
                        },
                        {"account_id": source["id"], "side": "credit", "amount": "10"},
                    ],
                    "frequency": "monthly",
                    "start_date": "2999-01-01",
                    "payee": f"{name} {i}",
                },
            )
            assert made.status_code == 201, made.text
        return _selects(session, client, "POST", f"/api/accounts/{source['id']}/merge", json={"into": keep["id"]})

    few, many = merge("Spare", 1), merge("Older", 8)
    assert many <= few, f"a merge reads more as there are more recurring transactions: {few} -> {many}"
    assert len(client.get("/api/recurring/").json()) == 9, "every rule came along"


def test_the_to_do_does_not_read_once_per_card(client, root_accounts, session):
    """The bell is asked on every page: every card's bill comes from one read of their lines."""

    def card(name: str) -> None:
        made = post_account(
            client, {"name": name, "parent_id": root_accounts["Liabilities"], "statement_day": 5, "due_day": 20}
        )
        assert made.status_code == 201, made.text

    card("Visa")
    few = _selects(session, client, "GET", "/api/todo/")
    for name in ("Amex", "Rupay", "Diners", "Master"):
        card(name)
    many = _selects(session, client, "GET", "/api/todo/")
    assert many <= few, f"the to-do reads more as there are more cards: {few} -> {many}"


def test_making_or_changing_an_account_does_not_read_once_per_account(client, root_accounts, session):
    """A commit makes every loaded account stale: the answer is built from one fresh list, not a read of each."""

    def measure(label: str) -> dict[str, int]:
        made = post_account(client, {"name": f"Spare {label}", "parent_id": root_accounts["Assets"]})
        assert made.status_code == 201, made.text
        return {
            "making an account": _selects(
                session, client, "POST", "/api/accounts/", json={"name": label, "parent_id": root_accounts["Assets"]}
            ),
            "making a group": _selects(
                session,
                client,
                "POST",
                "/api/accounts/groups",
                json={"name": f"Shelf {label}", "root": "Assets", "new_accounts_in_budget": True},
            ),
            "changing an account": _selects(
                session, client, "PATCH", f"/api/accounts/{made.json()['id']}", json={"name": f"Renamed {label}"}
            ),
        }

    few = measure("first")
    for i in range(12):
        assert post_account(client, {"name": f"Bank {i}", "parent_id": root_accounts["Assets"]}).status_code == 201
    many = measure("second")
    for what, reads in many.items():
        assert reads <= few[what], f"{what} reads more as there are more accounts: {few[what]} -> {reads}"


def test_recording_an_entry_does_not_read_once_per_tag(client, root_accounts, session):
    """The tags an entry names are looked up together: six tags ask no more than one."""
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"]}).json()
    food = category(client, "Food")

    def record(tags: list[str]) -> int:
        body = {
            "date": "2026-03-01",
            "payee": "Shop",
            "tags": tags,
            "postings": [
                {"category_id": food["id"], "side": "debit", "amount": "10"},
                {"account_id": bank["id"], "side": "credit", "amount": "10"},
            ],
        }
        return _selects(session, client, "POST", "/api/transactions/", json=body)

    record(["warm-up"])  # the built-in Uncategorised and the like are made once
    one = record(["trip"])
    six = record(["goa", "work", "gift", "claim", "home", "repair"])
    assert six <= one, f"recording reads more with more tags: {one} -> {six}"


# Recording an entry is what the app is used for most, and each read is a round trip of about 16 ms. Lower this when
# it gets cheaper; raise it only with a reason.
RECORD_CEILING = 7


def test_recording_a_plain_entry_stays_under_its_ceiling(client, root_accounts, session):
    """An entry with no tags reads nothing about tags, and its lines' accounts come from the list already in hand."""
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"]}).json()
    food = category(client, "Food")
    body = {
        "date": "2026-03-01",
        "payee": "Shop",
        "postings": [
            {"category_id": food["id"], "side": "debit", "amount": "10"},
            {"account_id": bank["id"], "side": "credit", "amount": "10"},
        ],
    }
    assert client.post("/api/transactions/", json=body).status_code == 201
    reads = _selects(session, client, "POST", "/api/transactions/", json=body)
    assert reads <= RECORD_CEILING, f"recording a plain entry took {reads} reads (ceiling {RECORD_CEILING})"


def test_a_batch_does_not_ask_once_per_entry(client, root_accounts, session):
    """A batch is one request for up to fifty entries: its checks, its writes and its answer are asked for together,
    whether it is only checked, saved, or sent again."""
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"]}).json()
    food = category(client, "Food")

    def batch(name: str, size: int, dry_run: bool = False) -> int:
        sent = [
            {
                "date": "2026-03-01",
                "payee": "Shop",
                "source": "bank",
                "external_id": f"{name}-{i}",
                "tags": ["weekly-shop", f"{name}-{i % 3}"],
                "postings": [
                    {"category_id": food["id"], "side": "debit", "amount": "10"},
                    {"account_id": bank["id"], "side": "credit", "amount": "10"},
                ],
            }
            for i in range(size)
        ]
        url = "/api/transactions/batch" + ("?dry_run=true" if dry_run else "")
        return _statements(session, lambda: client.post(url, json={"transactions": sent}))

    for what, few, many in (
        ("checking", batch("a", 2, dry_run=True), batch("b", 12, dry_run=True)),
        ("saving", batch("c", 2), batch("d", 12)),
        ("sending again", batch("c", 2), batch("d", 12)),
    ):
        assert many <= few, f"{what} a batch asks more as it holds more entries: {few} -> {many}"
    assert client.get("/api/reports/trial-balance").json()["balanced"] is True


def _as(user_id: UUID | None) -> None:
    """Sign the test client in as someone else (None: back to the usual person)."""
    if user_id is None:
        app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(
            id=TEST_USER_ID, email="test@example.com", claims={}
        )
    else:
        app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(
            id=user_id, email="other@example.com", claims={}
        )


def _journal(entries: int) -> str:
    """A journal of that many entries, each tagged, over two accounts and a category that do not exist yet."""
    return "".join(
        f"2026-09-{1 + i % 28:02d} Shop {i}\n"
        f"    ; tags: weekly-shop, trip-{i % 3}\n"
        f"    Expenses:Food   {10 + i}.00\n"
        f"    Assets:Bank\n"
        for i in range(entries)
    )


def test_an_import_and_a_restore_do_not_ask_once_per_entry(client, session):
    """A journal or a backup can hold years of entries: they are written together, so a long file costs the same few
    round trips as a short one. (Three per entry, as it was, made a few thousand entries take minutes.)"""
    people = [UUID(f"00000000-0000-4000-8000-0000000000c{n}") for n in range(4)]
    counts, backups = [], []
    try:
        for person, entries in zip(people[:2], (3, 30), strict=True):
            _as(person)
            journal = _journal(entries).encode()
            counts.append(
                _statements(session, lambda journal=journal: client.post("/api/import", files={"file": ("a", journal)}))
            )
            assert client.get("/api/reports/trial-balance").json()["balanced"] is True
            categories = client.get("/api/categories/").json()
            food = next(c for c in categories if c["name"] == "Food")
            for month in ("2026-08-01", "2026-09-01", "2026-10-01")[: 1 if entries == 3 else 3]:
                assert client.put(
                    f"/api/budget/categories/{food['id']}", json={"amount": "5", "month": month}
                ).is_success
            entries_made = client.get("/api/transactions/", params={"limit": 100}).json()
            first, second = entries_made[0]["id"], entries_made[1]["id"]
            assert client.patch(f"/api/transactions/{first}", json={"related_id": second}).is_success
            backups.append(client.get("/api/backup").json())
        few, many = counts
        assert many <= few, f"an import asks more as the journal holds more entries: {few} -> {many}"

        counts = []
        for person, backup in zip(people[2:], backups, strict=True):
            _as(person)
            sent = json.dumps(backup)
            counts.append(
                _statements(
                    session,
                    lambda sent=sent: client.post("/api/restore", files={"file": ("b.json", sent, "application/json")}),
                )
            )
            assert client.get("/api/reports/trial-balance").json()["balanced"] is True
            restored = client.get("/api/backup").json()
            assert len(restored["transactions"]) == len(backup["transactions"])
            assert len(restored["allocations"]) == len(backup["allocations"])
            assert sum(t["related_id"] is not None for t in restored["transactions"]) == 1
            assert sorted(t["tags"] for t in restored["transactions"]) == sorted(
                t["tags"] for t in backup["transactions"]
            )
        few, many = counts
        assert many <= few, f"a restore asks more as the backup holds more entries and budget rows: {few} -> {many}"
    finally:
        _as(None)


def test_copying_last_month_does_not_ask_once_per_category(client, root_accounts, session):
    """Copy last month writes a row for each category that has none yet: they are known to be missing, so nothing is
    read first and they are written together."""

    def copy(month: str, previous: str, names: list[str]) -> int:
        for name in names:
            made = category(client, name)
            body = {"amount": "100", "month": previous}
            assert client.put(f"/api/budget/categories/{made['id']}", json=body).is_success
        return _statements(session, lambda: client.post("/api/budget/copy", json={"month": month}))

    few = copy("2026-02-01", "2026-01-01", ["Food", "Rent"])
    many = copy("2026-05-01", "2026-04-01", [f"Category {i}" for i in range(10)])
    assert many <= few, f"copying asks more as there are more categories: {few} -> {many}"
    copied = client.get("/api/budget/", params={"month": "2026-05-01"}).json()
    assert sum(line["assigned"] == "100.00" for line in copied["lines"]) == 10


def test_a_backup_does_not_read_once_per_shared_bill(client, root_accounts, session):
    """The backup lists every shared bill with its shares and who paid: all the shares come in one read and all the
    payments in another."""
    bank = client.post("/api/accounts/", json={"name": "HDFC", "parent_id": root_accounts["Assets"]}).json()
    dining = category(client, "Dining")
    friend = client.post("/api/contacts/", json={"name": "Alice"}).json()

    def share(description: str) -> None:
        body = {
            "description": description,
            "total_amount": "300.00",
            "category_id": dining["id"],
            "split_method": "equal",
            "participants": [{"is_self": True}, {"contact_id": friend["id"]}],
            "payments": [{"account_id": bank["id"], "amount": "300.00"}],
        }
        assert client.post("/api/shared-expenses/", params={"confirm": True}, json=body).status_code == 201

    share("Dinner")
    few = _selects(session, client, "GET", "/api/backup")
    for i in range(6):
        share(f"Lunch {i}")
    many = _selects(session, client, "GET", "/api/backup")
    assert many <= few, f"a backup reads more as there are more shared bills: {few} -> {many}"
    bills = client.get("/api/backup").json()["shared_expenses"]
    assert len(bills) == 7 and all(len(b["shares"]) == 2 and len(b["contributions"]) == 1 for b in bills)

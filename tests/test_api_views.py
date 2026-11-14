"""The view endpoints (/api/views): what one screen of the React app shows, in one call, built from the same rows as the
web pages (services/transaction_rows.py)."""

from datetime import timedelta
from uuid import UUID

from app.clock import local_today
from app.services.transaction_rows import AccountIndex, to_row

from .books import into, leg
from .svc import services
from .test_api_parity import books  # noqa: F401  (the fixture)
from .test_isolation import B_USER, signed_in_as

TODAY = local_today()
MONTH = TODAY.strftime("%Y-%m")


def spend(client, books, amount="10", on=TODAY, payee="Shop", to="food", **extra):
    response = client.post(
        "/api/transactions/",
        json={
            "date": on.isoformat(),
            "payee": payee,
            "postings": [leg(books[to], "debit", amount), leg(books["bank"], "credit", amount)],
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def view(client, **params):
    response = client.get("/api/views/transactions", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def payees_of(answer):
    return [r["title"] for r in answer["rows"]]


def test_a_page_of_the_month_and_the_next_one_meet_without_a_gap(client, books):
    days = [TODAY - timedelta(days=i % max(TODAY.day, 1)) for i in range(30)]
    made = {spend(client, books, payee=f"P{i}", on=day)["id"] for i, day in enumerate(days)}
    first = view(client, month=MONTH)
    assert len(first["rows"]) == 25 and first["total"] >= 30
    rest = view(client, month=MONTH, offset=len(first["rows"]))
    ids = [r["id"] for r in first["rows"] + rest["rows"]]
    assert len(ids) == len(set(ids)), "no entry twice"
    assert made <= set(ids), "no entry dropped at the seam"
    assert len(ids) == first["total"]


def test_rows_say_what_the_list_says(client, session, books):
    made = spend(client, books, amount="597", payee="Swiggy", comment="dinner")
    row = next(r for r in view(client, month=MONTH)["rows"] if r["id"] == made["id"])
    svc = services(session)
    index = AccountIndex.build(svc.accounts.list(), svc.categories.list(include_closed=True))
    expected = to_row(svc.transactions.read(UUID(made["id"])), index)
    assert (row["title"], row["sub"], row["kind"], row["amount"]) == (
        expected.title,
        expected.sub,
        expected.kind,
        "597.00",
    )
    assert row["is_system"] is False and row["recurring"] is False and row["by_assistant"] is None


def test_upcoming_is_apart_from_the_list(client, books):
    if TODAY.day == 28 and (TODAY + timedelta(days=1)).month != TODAY.month:  # pragma: no cover
        return
    ahead = spend(client, books, payee="Rent soon", on=TODAY + timedelta(days=1))
    now = view(client, month=MONTH)
    if (TODAY + timedelta(days=1)).month == TODAY.month:
        assert [u["title"] for u in now["upcoming"]] == ["Rent soon"]
        assert now["upcoming_total"] == "10.00"
    assert ahead["id"] not in [r["id"] for r in now["rows"]]
    last_month = (TODAY.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    assert view(client, month=last_month)["upcoming"] == []


def test_the_month_never_runs_ahead(client, books):
    answer = view(client, month="2999-01")
    assert answer["month"] == MONTH and answer["is_current"] is True


def test_a_filter_sums_what_matches(client, books):
    spend(client, books, amount="30")
    spend(client, books, amount="20", payee="Other")
    spend(client, books, amount="900", to="rent")
    answer = view(client, month=MONTH, category=books["food"]["id"])
    assert answer["summary"] == {"count": 2, "total": "50.00", "word": "spent"}
    assert [(a["key"], a["name"]) for a in answer["applied"]] == [("category", "Food")]
    assert view(client, month=MONTH)["summary"] is None, "no filter, no summary"


def test_filters_that_are_not_yours_find_nothing(client, books):
    with signed_in_as(B_USER):
        roots = {a["name"]: a["id"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None}
        theirs = client.post("/api/accounts/", json={"name": "Hidden Vault", "parent_id": roots["Assets"]}).json()
    spend(client, books)
    answer = client.get("/api/views/transactions", params={"month": MONTH, "account": theirs["id"]})
    assert answer.status_code == 200, answer.text
    assert "Hidden Vault" not in answer.text and answer.json()["rows"] == []
    broken = view(client, month=MONTH, account="nope")
    assert broken["error"].startswith("Invalid filter") and broken["rows"] == []


def test_the_filter_choices(client, books):
    spend(client, books, payee="Swiggy")
    choices = client.get("/api/views/transaction-filters").json()
    names = [a["name"] for a in choices["accounts"]]
    assert "Bank" in names and "Expenses" not in names and "Income" not in names
    assert "Food" in [c["name"] for c in choices["categories"]]
    assert "Swiggy" in choices["merchants"]


def test_details_of_a_split_and_a_related_entry(client, books):
    split = client.post(
        "/api/transactions/",
        json={
            "payee": "DMart",
            "postings": [
                leg(books["food"], "debit", "70"),
                leg(books["rent"], "debit", "30"),
                leg(books["bank"], "credit", "100"),
            ],
        },
    ).json()
    refund = spend(client, books, amount="5", payee="DMart refund", related_id=split["id"])
    details = client.get(f"/api/views/transactions/{split['id']}").json()
    assert (details["from_label"], details["to_label"]) == ("Paid from", "Spent on")
    assert [(line["name"], line["amount"]) for line in details["to_lines"]] == [("Food", "70.00"), ("Rent", "30.00")]
    assert [r["id"] for r in details["related"]] == [refund["id"]]
    assert client.get(f"/api/views/transactions/{refund['id']}").json()["related_to"]["id"] == split["id"]


def test_details_of_someone_elses_entry_are_not_found(client, books):
    made = spend(client, books)
    assert client.get(f"/api/views/transactions/{made['id']}").status_code == 200
    with signed_in_as(B_USER):
        assert client.get(f"/api/views/transactions/{made['id']}").status_code == 404
    assert client.get("/api/views/transactions/00000000-0000-4000-8000-0000000000aa").status_code == 404


def test_recurring_falls_due_before_the_list(client, books):
    yesterday = TODAY - timedelta(days=1)
    rule = client.post(
        "/api/recurring/",
        json={
            "from_account_id": books["bank"]["id"],
            **into(client, books["food"]),
            "amount": "7",
            "frequency": "monthly",
            "start_date": yesterday.isoformat(),
            "payee": "Gym",
        },
    )
    assert rule.status_code == 201, rule.text
    month = yesterday.strftime("%Y-%m")
    assert "Gym" in payees_of(view(client, month=month))

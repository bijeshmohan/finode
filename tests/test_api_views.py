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


def a_day_across_the_page_end(client, books) -> set[str]:
    """January 2026, newest first: the 31st down to the 9th one entry each (23 rows), the 8th six entries (rows 24 to
    29, across a page of 25), the 7th down to the 1st one each. 36 entries."""
    from datetime import date

    made = set()
    days = (
        [date(2026, 1, d) for d in range(31, 8, -1)]
        + [date(2026, 1, 8)] * 6
        + [date(2026, 1, d) for d in range(7, 0, -1)]
    )
    for i, day in enumerate(days):
        made.add(spend(client, books, payee=f"P{i:02d}", on=day)["id"])
    return made


def test_a_page_of_the_month_and_the_next_one_meet_without_a_gap(client, books):
    made = a_day_across_the_page_end(client, books)
    first = view(client, month="2026-01")
    assert len(first["rows"]) == 29 and first["total"] == 36, "the 8th is finished on the first page"
    assert {r["date"] for r in first["rows"][23:]} == {"2026-01-08"}
    rest = view(client, month="2026-01", offset=len(first["rows"]))
    assert len(rest["rows"]) == 7 and rest["rows"][0]["date"] == "2026-01-07"
    ids = [r["id"] for r in first["rows"] + rest["rows"]]
    assert len(ids) == len(set(ids)), "no entry twice"
    assert set(ids) == made, "no entry dropped at the seam"


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


# ---- Home ----------------------------------------------------------------------------------------------------------


def home(client, **params):
    response = client.get("/api/views/home", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_home_with_nothing_recorded(client, root_accounts):
    seen = home(client)
    assert seen["has_recorded"] is False
    assert [(s["key"], s["done"]) for s in seen["steps"]] == [("account", False), ("spend", False), ("budget", False)]
    assert (
        seen["steps"][1]["title"] == "Record your first spend" and seen["steps"][1]["hint"] == "Takes about ten seconds"
    )
    assert (seen["steps_done"], seen["steps_total"]) == (0, 3)


def test_home_glance_when_overspent(client, books):
    client.put(f"/api/budget/categories/{books['food']['id']}", json={"month": f"{MONTH}-01", "amount": "100"})
    spend(client, books, amount="150.5")
    glance = home(client)["glance"]
    assert glance["has_budget"] is True
    assert (glance["left"], glance["spent"], glance["assigned"], glance["percent"]) == (
        "-50.50",
        "150.50",
        "100.00",
        100,
    )
    assert glance["pace"] is not None


def test_home_knows_when_something_was_recorded(client, books):
    spend(client, books, payee="Lunch")
    seen = home(client)
    assert seen["has_recorded"] is True and "rows" not in seen, "the entries are the list's"


def test_home_past_month_has_no_pace(client, books):
    last_month = (TODAY.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    seen = home(client, month=last_month)
    assert seen["month"] == last_month and seen["is_current"] is False and seen["glance"]["pace"] is None


def test_a_day_with_more_than_one_spend_says_what_it_came_to(client, books):
    spend(client, books, amount="30")
    spend(client, books, amount="20.5", payee="Other")
    yesterday = TODAY - timedelta(days=1)
    if yesterday.month == TODAY.month:
        spend(client, books, amount="99", on=yesterday)
    days = {d["date"]: d["spent"] for d in view(client, month=MONTH)["days"]}
    assert days.get(TODAY.isoformat()) == "50.50"
    assert yesterday.isoformat() not in days, "one entry would just repeat its row"


# ---- the Add screen's form ------------------------------------------------------------------------------------------


def form_view(client, **params):
    response = client.get("/api/views/entry-form", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_blank_form(client, books):
    seen = form_view(client)
    assert (seen["editing"], seen["kind"], seen["date"], seen["simple"]) == (False, "expense", TODAY.isoformat(), True)
    assert [r["choice"] for r in seen["from_rows"]] == [None] and [r["choice"] for r in seen["to_rows"]] == [None]
    titles = [g["title"] for g in seen["groups"]]
    assert "Assets" in titles and "Expenses" in titles and "Income" in titles
    bank = next(o for g in seen["groups"] for o in g["options"] if o["id"] == books["bank"]["id"])
    assert bank["balance"] == "5000.00" and bank["budget"] is True


def test_a_form_from_an_account_and_from_categories(client, books):
    assert form_view(client, account=books["bank"]["id"])["from_rows"][0]["choice"] == books["bank"]["id"]
    assert form_view(client, category=books["food"]["id"])["to_rows"][0]["choice"] == books["food"]["id"]
    earning = form_view(client, category=books["salary"]["id"])
    assert earning["kind"] == "income" and earning["from_rows"][0]["choice"] == books["salary"]["id"]


def test_repeat_and_related(client, books):
    made = spend(client, books, amount="597", payee="Swiggy", comment="dinner", tags=["food"])
    again = form_view(client, repeat=made["id"])
    assert (again["editing"], again["payee"], again["comment"], again["tags"], again["total"]) == (
        False,
        "Swiggy",
        "dinner",
        ["food"],
        "597.00",
    )
    assert again["to_rows"][0]["choice"] == books["food"]["id"] and again["date"] == TODAY.isoformat()
    linked = form_view(client, related=made["id"])
    assert linked["related"]["id"] == made["id"] and linked["payee"] == ""
    assert (
        client.get("/api/views/entry-form", params={"repeat": "00000000-0000-4000-8000-0000000000aa"}).status_code
        == 404
    )


def test_editing_a_simple_and_a_split_entry(client, books):
    simple = form_view(client, transaction_id=spend(client, books, amount="30")["id"])
    assert simple["editing"] is True and simple["simple"] is True and simple["total"] == "30.00"
    split = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(books["food"], "debit", "20"),
                leg(books["rent"], "debit", "10"),
                leg(books["bank"], "credit", "30"),
            ]
        },
    ).json()
    assert form_view(client, transaction_id=split["id"])["simple"] is False


def test_a_loan_opens_with_the_person_on_its_row(client, books):
    ada = client.post("/api/contacts/", json={"name": "Ada"}).json()
    lent = client.post(
        "/api/entries",
        json={
            "kind": "transfer",
            "rows": [
                {"choice": books["bank"]["id"], "side": "credit", "amount": "200"},
                {"choice": ada["id"], "side": "debit", "amount": "200"},
            ],
        },
    ).json()
    seen = form_view(client, transaction_id=lent["transaction_id"])
    assert seen["to_rows"][0]["choice"] == ada["id"] and seen["person_page"] is None
    assert "People" in [g["title"] for g in seen["groups"]]


def test_pay_a_card(client, books, root_accounts):
    card = client.post("/api/accounts/", json={"name": "Visa", "parent_id": root_accounts["Liabilities"]}).json()
    seen = form_view(client, pay=card["id"], amount="1,500")
    assert (seen["kind"], seen["total"], seen["to_rows"][0]["choice"]) == ("transfer", "1500", card["id"])


def test_related_entries(client, books):
    spend(client, books, payee="Swiggy")
    spend(client, books, payee="DMart")
    found = client.get("/api/views/related-entries", params={"q": "swig"}).json()
    assert [r["title"] for r in found] == ["Swiggy"]
    every = client.get("/api/views/related-entries").json()
    excluded = client.get("/api/views/related-entries", params={"exclude": every[0]["id"]}).json()
    assert every[0]["id"] not in [r["id"] for r in excluded]
    assert "Opening balance" not in [r["title"] for r in every]

"""A recurring rule saved from the Add screen's rows (POST /api/recurring/form, PUT /api/recurring/{id}/form) and the
form's view (GET /api/views/recurring-form): the server turns the rows into a plain rule or a split
(services/recurring_form.py)."""

from .test_isolation import B_USER, signed_in_as
from .test_recurring import accounts, split_accounts, transactions  # noqa: F401  # fixtures


def form(rows, **extra):
    return {
        "payee": "Landlord",
        "comment": "",
        "tags": [],
        "rows": rows,
        "frequency": "monthly",
        "every": 1,
        "start_date": "2999-01-01",
        "end_date": None,
        **extra,
    }


def row(choice, side, amount, **extra):
    return {"choice": choice, "side": side, "amount": amount, **extra}


def plain(a, amount="1500"):
    return [row(a["bank"], "credit", amount), row(a["rent"], "debit", amount)]


def saved(client, body, recurring_id=None):
    response = (
        client.put(f"/api/recurring/{recurring_id}/form", json=body)
        if recurring_id
        else client.post("/api/recurring/form", json=body)
    )
    assert response.status_code == (200 if recurring_id else 201), response.text
    return response.json()


def test_a_plain_rule_from_rows_stays_plain(client, accounts):
    made = saved(client, form(plain(accounts)))
    assert (made["from_account_id"], made["to_account_id"], made["amount"]) == (
        accounts["bank"],
        accounts["expenses"],
        "1500.00",
    )
    assert made["category_id"] == accounts["rent"] and made["postings"] == []
    assert made["payee"] == "Landlord" and made["next_date"] == "2999-01-01"


def test_two_lines_on_a_side_make_a_split(client, split_accounts):
    a = split_accounts
    rows = [row(a["bank"], "credit", "1200"), row(a["rent"], "debit", "1000"), row(a["Water"], "debit", "200")]
    made = saved(client, form(rows))
    assert made["from_account_id"] is None and len(made["postings"]) == 3
    assert {(p["side"], p["amount"], p["category_id"]) for p in made["postings"]} == {
        ("credit", "1200.00", None),
        ("debit", "1000.00", a["rent"]),
        ("debit", "200.00", a["Water"]),
    }


def test_a_category_row_posts_on_expenses_with_its_category(client, split_accounts):
    a = split_accounts
    rows = [row(a["bank"], "credit", "300"), row(a["rent"], "debit", "100"), row(a["Savings"], "debit", "200")]
    made = saved(client, form(rows))
    rent = next(p for p in made["postings"] if p["category_id"] == a["rent"])
    assert rent["account_id"] == a["expenses"]
    savings = next(p for p in made["postings"] if p["account_id"] == a["Savings"])
    assert savings["category_id"] is None


def test_editing_without_changes_keeps_the_rule(client, accounts):
    made = saved(client, form(plain(accounts), tags=["home"], comment="flat"))
    seen = client.get("/api/views/recurring-form", params={"recurring_id": made["id"]}).json()
    rows = [
        {"choice": r["choice"], "side": side, "amount": r["amount"] or seen["total"], "category_id": r["category_id"]}
        for side, key in (("credit", "from_rows"), ("debit", "to_rows"))
        for r in seen[key]
    ]
    body = form(
        rows,
        payee=seen["payee"],
        comment=seen["comment"],
        tags=seen["tags"],
        frequency=seen["frequency"],
        every=seen["every"],
        start_date=seen["start_date"],
        end_date=seen["end_date"],
    )
    again = saved(client, body, made["id"])
    keep = ("from_account_id", "to_account_id", "amount", "category_id", "postings", "payee", "comment", "tags")
    assert {k: again[k] for k in keep} == {k: made[k] for k in keep}


def test_a_past_start_is_recorded_at_once(client, accounts, session):
    saved(client, form(plain(accounts), start_date="2026-01-01", end_date="2026-02-15"))
    assert len(transactions(session)) == 2


def test_a_person_or_a_strangers_account_is_refused_and_nothing_is_saved(client, accounts):
    person = client.post("/api/contacts/", json={"name": "Asha"}).json()
    nobodys = "00000000-0000-4000-8000-0000000000aa"
    for choice in (person["id"], nobodys):
        rows = [row(choice, "credit", "5"), row(accounts["rent"], "debit", "5")]
        refused = client.post("/api/recurring/form", json=form(rows))
        assert refused.status_code in (400, 404), refused.text
    assert client.get("/api/recurring/").json() == []


def test_a_posting_day_on_a_row_is_refused(client, accounts):
    rows = [row(accounts["bank"], "credit", "5", posted_on="2999-01-03"), row(accounts["rent"], "debit", "5")]
    refused = client.post("/api/recurring/form", json=form(rows))
    assert refused.status_code == 400 and "posting day" in refused.json()["detail"]
    assert client.get("/api/recurring/").json() == []


def test_too_few_rows_say_so(client, accounts):
    refused = client.post("/api/recurring/form", json=form([row(accounts["bank"], "credit", "5")]))
    assert refused.status_code == 400
    assert refused.json()["detail"] == "choose where the money comes from and where it goes!"


def test_the_form_view_new_and_editing(client, accounts):
    new = client.get("/api/views/recurring-form").json()
    assert (new["editing"], new["kind"], new["every"], new["frequency"], new["end_date"]) == (
        False,
        "expense",
        1,
        "monthly",
        None,
    )
    assert new["start_date"] and new["total"] is None
    assert [f["value"] for f in new["frequencies"]] == ["daily", "weekly", "monthly", "yearly"]
    assert [f["name"] for f in new["frequencies"]] == ["day", "week", "month", "year"]
    assert "People" not in [g["title"] for g in new["groups"]]
    assert new["account_parents"] and new["category_parents"] is not None
    made = saved(client, form(plain(accounts), tags=["home"]))
    seen = client.get("/api/views/recurring-form", params={"recurring_id": made["id"]}).json()
    assert (seen["editing"], seen["kind"], seen["total"], seen["payee"], seen["tags"]) == (
        True,
        "expense",
        "1500.00",
        "Landlord",
        ["home"],
    )
    assert [r["choice"] for r in seen["from_rows"]] == [accounts["bank"]]
    assert [r["choice"] for r in seen["to_rows"]] == [accounts["rent"]]
    assert (seen["status"], seen["schedule"], seen["active"], seen["next_date"]) == (
        "active",
        "Every month",
        True,
        "2999-01-01",
    )
    assert seen["last_date"] is None and seen["skipped_date"] is None and seen["last_error"] is None
    with signed_in_as(B_USER):
        assert client.get("/api/views/recurring-form", params={"recurring_id": made["id"]}).status_code == 404
        assert client.put(f"/api/recurring/{made['id']}/form", json=form(plain(accounts))).status_code == 404

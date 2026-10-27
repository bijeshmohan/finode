"""Recurring rules carry tags: every entry a rule records gets them, and renaming, merging or deleting a tag follows."""

from datetime import date

from sqlmodel import select

from app.models.recurring import RecurringTransaction
from app.models.transaction import Transaction

from .test_recurring import accounts, rule  # noqa: F401  (the fixture and the helper)


def recorded(client):
    return [t for t in client.get("/api/transactions/").json() if t["created_via"] == "recurring"]


def test_a_rule_with_tags_records_entries_with_those_tags(client, accounts):
    made = rule(client, accounts, start_date="2026-01-01", tags=["#Rent", "home", "rent"])
    assert made["tags"] == ["rent", "home"], "each in its one form, once"
    entries = recorded(client)
    assert entries and all(sorted(t["tags"]) == ["home", "rent"] for t in entries)
    assert {t["tag"] for t in client.get("/api/tags/").json()} == {"home", "rent"}


def test_a_rule_without_tags_has_none(client, accounts):
    assert rule(client, accounts, start_date="2999-01-01")["tags"] == []


def test_changing_a_rules_tags_applies_to_the_next_entries_only(client, accounts):
    start = str(date.today().replace(day=1))
    made = rule(client, accounts, start_date=start, frequency="monthly", tags=["rent"])
    before = recorded(client)
    body = {k: made[k] for k in ("from_account", "to_account", "amount", "frequency", "every", "start_date", "payee")}
    changed = client.put(f"/api/recurring/{made['rid']}", json=body | {"tags": ["housing"]})
    assert changed.status_code == 200 and changed.json()["tags"] == ["housing"]
    assert [t["tags"] for t in recorded(client)] == [t["tags"] for t in before], "what was recorded keeps its tags"


def test_too_many_tags_or_a_bad_one_are_refused(client, accounts):
    body = {
        "from_account": accounts["bank"],
        "to_account": accounts["rent"],
        "amount": "10",
        "start_date": "2999-01-01",
    }
    assert client.post("/api/recurring/", json=body | {"tags": [f"t{i}" for i in range(11)]}).status_code == 422
    assert client.post("/api/recurring/", json=body | {"tags": ["has space"]}).status_code == 422


def test_renaming_merging_and_deleting_a_tag_follow_into_the_rules(client, accounts, session):
    rule(client, accounts, start_date="2026-01-01", tags=["rent", "home"], payee="A")
    rule(client, accounts, start_date="2026-01-01", tags=["rent"], payee="B")
    tags = lambda: {r.payee: r.tags for r in session.exec(select(RecurringTransaction)).all()}
    assert tags() == {"A": ["rent", "home"], "B": ["rent"]}
    assert client.patch("/api/tags/rent", json={"name": "housing"}).status_code == 200
    session.expire_all()
    assert tags() == {"A": ["housing", "home"], "B": ["housing"]}
    assert (
        client.patch("/api/tags/housing", json={"name": "home"}).status_code == 200
    )  # into an existing tag: they merge
    session.expire_all()
    assert tags() == {"A": ["home"], "B": ["home"]}
    assert client.delete("/api/tags/home").status_code in (200, 204)
    session.expire_all()
    assert tags() == {"A": [], "B": []}
    assert all(t["tags"] == [] for t in client.get("/api/transactions/").json())
    assert session.exec(select(Transaction)).all()


def test_the_new_form_saves_tags_and_the_edit_form_shows_them(client, accounts):
    posted = client.post(
        "/recurring",
        data={
            "kind": "expense",
            "total": "1,500",
            "account": [accounts["bank"], accounts["rent"]],
            "side": ["credit", "debit"],
            "amount": ["1500", "1500"],
            "payee": "Landlord",
            "comment": "Rent",
            "every": "2",
            "frequency": "monthly",
            "start": "2999-01-01",
            "tags": ["rent", "Home"],
        },
    )
    assert posted.status_code == 200, posted.text
    [made] = client.get("/api/recurring/").json()
    assert made["tags"] == ["rent", "home"] and made["every"] == 2 and made["comment"] == "Rent"
    page = client.get(f"/recurring/{made['rid']}/edit").text
    assert 'name="tags" value="rent"' in page and 'name="tags" value="home"' in page
    assert "#rent" in page and 'value="Landlord"' in page and "Every" in page
    assert client.get("/recurring/new").text.count('class="hash-btn"') == 1


def test_a_bad_tag_on_the_form_says_why(client, accounts):
    posted = client.post(
        "/recurring",
        data={
            "account": [accounts["bank"], accounts["rent"]],
            "side": ["credit", "debit"],
            "amount": ["10", "10"],
            "start": "2999-01-01",
            "tags": ["not a tag"],
        },
    )
    assert posted.status_code == 400 and "tag" in posted.text.lower()

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
    body = {
        k: made[k] for k in ("from_account_id", "to_account_id", "amount", "frequency", "every", "start_date", "payee")
    }
    changed = client.put(f"/api/recurring/{made['id']}", json=body | {"tags": ["housing"]})
    assert changed.status_code == 200 and changed.json()["tags"] == ["housing"]
    assert [t["tags"] for t in recorded(client)] == [t["tags"] for t in before], "what was recorded keeps its tags"


def test_too_many_tags_or_a_bad_one_are_refused(client, accounts):
    body = {
        "from_account_id": accounts["bank"],
        "to_account_id": accounts["rent"],
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


def test_the_form_saves_tags_and_the_edit_form_shows_them(client, accounts):
    from .test_api_recurring_form import form, plain, saved

    made = saved(client, form(plain(accounts), comment="Rent", every=2, tags=["rent", "Home"]))
    [listed] = client.get("/api/recurring/").json()
    assert listed["tags"] == ["rent", "home"] and listed["every"] == 2 and listed["comment"] == "Rent"
    seen = client.get("/api/views/recurring-form", params={"recurring_id": made["id"]}).json()
    assert seen["tags"] == ["rent", "home"] and seen["payee"] == "Landlord" and seen["every"] == 2


def test_a_bad_tag_on_the_form_says_why(client, accounts):
    from .test_api_recurring_form import form, plain

    refused = client.post("/api/recurring/form", json=form(plain(accounts), tags=["not a tag"]))
    assert refused.status_code in (400, 422) and "tag" in refused.text.lower()
    assert client.get("/api/recurring/").json() == [], "nothing is saved"

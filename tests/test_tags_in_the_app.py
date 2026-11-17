"""Tags as the app uses them (ported from the old pages' tests, step 10): saved on the Add and Edit screens through
/api/entries, shown on the details sheet, found by the Transactions view's tag filter, and listed most used first."""

from datetime import date

import pytest

from .books import leg, post_account

TODAY = date.today()
MONTH = TODAY.strftime("%Y-%m")


@pytest.fixture
def books(client, root_accounts):
    def make(name, root, **extra):
        return post_account(client, {"name": name, "parent_id": root_accounts[root], **extra}).json()

    return {
        "bank": make("Bank", "Assets", balance="100000"),
        "travel": make("Travel", "Expenses"),
        "food": make("Food", "Expenses"),
        "salary": make("Salary", "Income"),
    }


def spend(client, books, amount, note=None, payee=None, to="travel", on=None, tags=None):
    body = {
        "date": str(on or TODAY),
        "payee": payee,
        "comment": note,
        "tags": tags or [],
        "postings": [
            leg(books[to], "debit", amount),
            leg(books["bank"], "credit", amount),
        ],
    }
    made = client.post("/api/transactions/", json=body)
    assert made.status_code == 201, made.text
    return made.json()


def earn(client, books, amount, tags):
    made = client.post(
        "/api/transactions/",
        json={
            "date": str(TODAY),
            "tags": tags,
            "postings": [
                leg(books["bank"], "debit", amount),
                leg(books["salary"], "credit", amount),
            ],
        },
    )
    assert made.status_code == 201, made.text
    return made.json()


def titles(found: dict) -> list[str]:
    return [r["title"] for r in found["rows"]]


def listed(client, **params) -> dict:
    answer = client.get("/api/views/transactions", params=params)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_the_sheet_has_the_tags_apart_from_the_whole_note(client, books):
    made = spend(client, books, "840", note="Airport drop", payee="Cab", tags=["goa-trip", "reimbursable"])
    sheet = client.get(f"/api/views/transactions/{made['id']}").json()
    assert sheet["tags"] == ["goa-trip", "reimbursable"] and sheet["comment"] == "Airport drop"
    only = spend(client, books, "5", payee="Tag only", tags=["goa-trip"])
    assert client.get(f"/api/views/transactions/{only['id']}").json()["comment"] is None, "no empty note"


def test_a_hash_in_a_note_is_only_text_on_a_row(client, books):
    spend(client, books, "10", note="Issue #1 and #goa-trip are words", payee="Words")
    row = next(r for r in listed(client)["rows"] if r["title"] == "Words")
    made = client.get(f"/api/views/transactions/{row['id']}").json()
    assert made["comment"] == "Issue #1 and #goa-trip are words" and made["tags"] == []


def test_the_tag_filter_lists_only_those_entries_and_says_what_they_come_to(client, books):
    spend(client, books, "840", payee="Taj", tags=["goa-trip"])
    spend(client, books, "160", payee="Cab", tags=["Goa-Trip"])
    spend(client, books, "999", payee="Other", tags=["goa-tripping"])
    spend(client, books, "50", payee="Plain")
    found = listed(client, tag="goa-trip")
    assert sorted(titles(found)) == ["Cab", "Taj"], "capitals do not matter and a longer tag is another tag"
    assert (found["summary"]["count"], found["summary"]["total"], found["summary"]["word"]) == (2, "1000.00", "spent")
    assert [(a["key"], a["name"]) for a in found["applied"]] == [("tag", "#goa-trip")]
    for spelling in ("#GOA-trip", " #goa-TRIP "):
        assert sorted(titles(listed(client, tag=spelling))) == ["Cab", "Taj"], spelling
    assert titles(listed(client, tag="nothing-here")) == []


def test_the_tag_filter_combines_with_the_others(client, books):
    for i in range(6):
        spend(client, books, "1", payee=f"P{i}", to="food" if i % 2 else "travel", tags=["bulk"])
    assert len(titles(listed(client, tag="bulk"))) == 6
    assert len(titles(listed(client, tag="bulk", category=books["food"]["id"]))) == 3


def test_the_tags_are_listed_most_used_first_whatever_their_capitals(client, books):
    spend(client, books, "1", payee="1", tags=["b"])
    spend(client, books, "1", payee="2", tags=["a", "B"])
    spend(client, books, "1", payee="3", tags=["A", "b", "c"])
    assert [(t["tag"], t["uses"]) for t in client.get("/api/tags/").json()] == [("b", 3), ("a", 2), ("c", 1)]


def entry(books, **extra):
    return {
        "kind": "expense",
        "rows": [
            {"choice": books["bank"]["id"], "side": "credit", "amount": "50"},
            {"choice": books["travel"]["id"], "side": "debit", "amount": "50"},
        ],
        **extra,
    }


def test_saving_an_entry_keeps_its_tags_and_an_edit_changes_or_clears_them(client, books):
    made = client.post(
        "/api/entries", json=entry(books, comment="Taxi from the airport", tags=["Goa-Trip", "reimbursable"])
    )
    assert made.status_code == 201, made.text
    transaction_id = made.json()["transaction_id"]
    saved = client.get(f"/api/transactions/{transaction_id}").json()
    assert saved["tags"] == ["goa-trip", "reimbursable"] and saved["comment"] == "Taxi from the airport"
    form = client.get("/api/views/entry-form", params={"transaction_id": transaction_id}).json()
    assert form["tags"] == ["goa-trip", "reimbursable"], "the edit screen shows them"
    assert client.put(f"/api/entries/{transaction_id}", json=entry(books, tags=["reimbursable"])).status_code == 200
    assert client.get(f"/api/transactions/{transaction_id}").json()["tags"] == ["reimbursable"]
    assert client.put(f"/api/entries/{transaction_id}", json=entry(books)).status_code == 200
    assert client.get(f"/api/transactions/{transaction_id}").json()["tags"] == []


def test_a_bad_tag_says_why_and_nothing_is_saved(client, books):
    before = len(client.get("/api/transactions/").json())
    refused = client.post("/api/entries", json=entry(books, tags=["not valid"]))
    assert refused.status_code in (400, 422) and "tag" in refused.text
    assert len(client.get("/api/transactions/").json()) == before

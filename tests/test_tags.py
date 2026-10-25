"""Tags are #hashtags in a transaction's note: found in the notes, nothing stored."""

import pytest

from app.tags import clean_tag, tags_in

from .conftest import TEST_USER_ID
from .mcputil import make_token, mcp_client, payload, running_app
from .test_transaction_references import body


@pytest.mark.parametrize(
    ("note", "tags"),
    [
        ("Dinner with Ravi #Reimbursable #goa-trip", ["reimbursable", "goa-trip"]),
        ("#first at the start", ["first"]),
        ("twice #goa #GOA", ["goa"]),
        ("punctuation #goa, #trip. #x!", ["goa", "trip", "x"]),
        ("#1 and #123 are numbers, not tags", []),
        ("no#glue and a#b and C# here", []),
        ("trailing dash #goa- or #a_", ["goa", "a"]),
        ("#" + "a" * 30 + " ok but #" + "b" * 31 + " too long", ["a" * 30]),
        ("", []),
        (None, []),
        ("##double and #-dash", []),
    ],
)
def test_tags_in_a_note(note, tags):
    assert tags_in(note) == tags


def test_clean_tag():
    assert clean_tag(" #Goa-Trip ") == "goa-trip" and clean_tag("goa") == "goa"


def make(client, account, expense, note, on="2026-10-10", amount="10"):
    made = client.post("/api/transactions/", json=body(expense, account, amount, on=on, comment=note))
    assert made.status_code == 201, made.text
    return made.json()


def test_an_entry_reads_back_its_tags_and_can_be_found_by_them(client, account, expense_account):
    one = make(client, account, expense_account, "Taxi #reimbursable #work", on="2026-10-01")
    make(client, account, expense_account, "Lunch #reimbursable", on="2026-10-02")
    make(client, account, expense_account, "Plain note", on="2026-10-03")
    make(client, account, expense_account, "Trip #goa-trip", on="2026-10-04")
    assert one["tags"] == ["reimbursable", "work"]
    found = client.get("/api/transactions/", params={"tag": "#Reimbursable"}).json()
    assert [t["comment"] for t in found] == ["Lunch #reimbursable", "Taxi #reimbursable #work"]
    assert [t["comment"] for t in client.get("/api/transactions/", params={"tag": "goa"}).json()] == []
    assert len(client.get("/api/transactions/", params={"tag": "goa-trip"}).json()) == 1


def test_a_tag_search_pages_after_the_match(client, account, expense_account):
    for n in range(5):
        make(client, account, expense_account, f"n{n} #t", on=f"2026-10-0{n + 1}")
        make(client, account, expense_account, f"other {n}", on=f"2026-10-0{n + 1}")
    page = client.get("/api/transactions/", params={"tag": "t", "limit": 2, "offset": 2}).json()
    assert [t["comment"] for t in page] == ["n2 #t", "n1 #t"]


def test_the_tags_in_use(client, account, expense_account):
    make(client, account, expense_account, "a #work #lunch", on="2026-10-01")
    make(client, account, expense_account, "b #work", on="2026-10-05")
    make(client, account, expense_account, "c #Work", on="2026-10-03")
    tags = client.get("/api/transactions/tags").json()
    assert tags == [
        {"tag": "work", "uses": 3, "last_used": "2026-10-05"},
        {"tag": "lunch", "uses": 1, "last_used": "2026-10-01"},
    ]


@pytest.mark.anyio
async def test_assistants_use_tags_through_the_note(session, client, account, expense_account):
    made = make(client, account, expense_account, "Taxi")
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        await c.call_tool("update_transaction", {"transaction_id": made["tid"], "note": "Taxi #reimbursable"})
        assert payload(await c.call_tool("list_tags", {}))["tags"][0]["tag"] == "reimbursable"
        found = payload(await c.call_tool("search_transactions", {"tag": "reimbursable"}))
        assert found["count"] == 1 and found["transactions"][0]["tags"] == ["reimbursable"]
        assert payload(await c.call_tool("search_transactions", {"tag": "nope"}))["count"] == 0
